"""Run in the backend image with synthetic settings and no external access."""
from datetime import datetime, timedelta, timezone
from contextlib import closing
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4


class ConfigurationTests(unittest.TestCase):
    def evaluate(self, public, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ) | {
                "WPL_PUBLIC_URL": public,
                "WPL_DATABASE_PATH": directory + "/state.db",
            } | overrides
            for key in ("WPL_API_BASE_URL", "WPL_GUI_BASE_URL"):
                if key not in overrides:
                    environment.pop(key, None)
            return subprocess.run([
                sys.executable, "-c",
                "from backend.app import config as c; import json; "
                "print(json.dumps({'origin':c.PUBLIC_URL,'api':c.API_BASE_URL,"
                "'callback':c.GITHUB_CALLBACK_URL,'gui':c.GUI_BASE_URL,"
                "'secure':c.GUI_HTTPS,'idle':c.IDLE_MINUTES}))",
            ], env=environment, capture_output=True, text=True)

    def test_http_and_https_addresses_are_derived(self):
        for public, secure in (("http://localhost:8080", False), ("https://lab.example.invalid", True)):
            with self.subTest(public=public):
                result = self.evaluate(public, WPL_IDLE_MINUTES="45")
                self.assertEqual(result.returncode, 0, result.stderr)
                values = json.loads(result.stdout)
                self.assertEqual(values["callback"], public + "/api/github/callback")
                self.assertEqual(values["gui"], public)
                self.assertEqual(values["secure"], secure)
                self.assertEqual(values["idle"], 45)

    def test_invalid_addresses_and_limits_fail(self):
        for public, overrides in (
            ("https://example.invalid:99999", {}),
            ("https://example.invalid/path", {}),
            ("https://u:p@example.invalid", {}),
            ("http://localhost:8080", {"WPL_LAB_CPUS": "NaN"}),
            ("http://localhost:8080", {"WPL_LAB_PIDS_LIMIT": "0"}),
        ):
            with self.subTest(public=public, overrides=overrides):
                self.assertNotEqual(self.evaluate(public, **overrides).returncode, 0)

    def test_backend_and_migrations_use_selected_database(self):
        from alembic import command
        from alembic.config import Config
        from backend.app.config import DATABASE_PATH, DATABASE_URL
        from backend.app.db.database import engine
        self.assertEqual(engine.url, DATABASE_URL)
        self.assertEqual(Path(engine.url.database), DATABASE_PATH)
        command.upgrade(Config('/app/alembic.ini'), 'head')
        with closing(sqlite3.connect(DATABASE_PATH)) as db:
            self.assertEqual(db.execute('SELECT version_num FROM alembic_version').fetchone()[0], '7d8e63fb45c3')


class RouteTests(unittest.TestCase):
    def test_gui_urls_and_cookies_follow_configured_scheme(self):
        from fastapi import Response
        from backend.app import config
        from backend.app.routes.gui_proxy import issue_gui_url
        for origin, secure in (("http://localhost:8080", False), ("https://lab.example.invalid", True)):
            with patch.object(config, 'GUI_BASE_URL', origin), patch.object(config, 'GUI_HTTPS', secure), patch.dict(os.environ, {'WPL_SECRET_KEY': 's' * 48}):
                response = Response()
                lab = str(uuid4())
                url = issue_gui_url(response, lab, str(uuid4()))
                self.assertTrue(url.startswith(origin + '/gui/' + lab + '/'))
                self.assertIn('encrypt=' + str(secure).lower(), url)
                cookie = SimpleCookie()
                cookie.load(response.headers['set-cookie'])
                morsel = cookie['wpl_gui_' + lab]
                self.assertEqual(bool(morsel['secure']), secure)
                self.assertTrue(morsel['httponly'])
                self.assertEqual(morsel['samesite'], 'strict')

    def test_github_connect_uses_configured_callback(self):
        from backend.app import config
        from backend.app.routes import github
        with patch.object(github.lab_service, 'get_or_create_student', return_value=SimpleNamespace(id='synthetic')), patch.object(
            github.github_service, 'get_connection', return_value=None
        ), patch.object(github.github_service, 'get_authorization_url', return_value='https://github.example.invalid/authorize') as authorization:
            github.github_connect(SimpleNamespace(id='synthetic', email=None, name=None))
            authorization.assert_called_once_with(student_id='synthetic', redirect_uri=config.PUBLIC_URL + '/api/github/callback')

    def test_health_authentication_cors_and_gui_denial(self):
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config('/app/alembic.ini'), 'head')
        with patch('docker.from_env'):
            from backend.app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            self.assertEqual(client.get('/health').status_code, 200)
            self.assertEqual(client.post('/labs').status_code, 401)
            self.assertEqual(client.get('/gui/proxy-auth').status_code, 403)
            response = client.options('/labs', headers={
                'Origin': 'http://localhost:8080',
                'Access-Control-Request-Method': 'POST',
            })
            self.assertEqual(response.headers.get('access-control-allow-origin'), 'http://localhost:8080')
            response = client.options('/labs', headers={
                'Origin': 'https://foreign.example.invalid',
                'Access-Control-Request-Method': 'POST',
            })
            self.assertNotIn('access-control-allow-origin', response.headers)


class InactivityRegressionTests(unittest.TestCase):
    def exercise(self, fail_push):
        from backend.app.services.inactivity_service import InactivityService
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.db'
            lab, student = str(uuid4()), str(uuid4())
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE labs (id TEXT, student_id TEXT, container_id TEXT, status TEXT, last_activity_at TEXT, github_repository_id TEXT)')
                db.execute('INSERT INTO labs VALUES (?,?,?,?,?,?)', (
                    lab, student, 'synthetic-container', 'running',
                    (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), 'synthetic-repository',
                ))
                db.commit()
            docker = MagicMock()
            container = docker.containers.get.return_value
            container.exec_run.return_value.exit_code = 0
            service = InactivityService(docker, db_path=path)
            service.gui_last_activity = MagicMock(return_value=None)
            git = MagicMock()
            git.status.side_effect = [{'clean': False}, {'clean': True}]
            git._assert_repository.return_value = (None, SimpleNamespace(id=student), SimpleNamespace(full_name='synthetic/repository'))
            git._credential_command.side_effect = lambda command: command
            git._run.side_effect = ['main', RuntimeError('synthetic push failure')] if fail_push else ['main', '', 'saved-commit', 'saved-commit refs/heads/main']
            service.git_service = git
            result = service.cleanup_lab(lab, 'synthetic-container')
            git.commit.assert_called_once_with(lab, 'Auto-save due to lab inactivity')
            with closing(sqlite3.connect(path)) as db:
                row = db.execute('SELECT status FROM labs WHERE id=?', (lab,)).fetchone()
                event = db.execute('SELECT outcome,message FROM lab_timeout_events WHERE lab_id=?', (lab,)).fetchone()
            if fail_push:
                self.assertFalse(result)
                self.assertEqual(row, ('running',))
                self.assertEqual(event[0], 'save_failed')
                container.remove.assert_not_called()
                self.assertTrue(any('-CONT' in call.args[0] for call in container.exec_run.call_args_list))
            else:
                self.assertTrue(result)
                self.assertIsNone(row)
                self.assertEqual(event[0], 'saved')
                self.assertIn('automatically committed and pushed', event[1])
                container.remove.assert_called_once_with(force=True)

    def test_inactivity_saves_pushes_verifies_and_keeps_notice(self):
        self.exercise(False)

    def test_failed_inactivity_push_preserves_lab_and_resumes_programs(self):
        self.exercise(True)


if __name__ == '__main__':
    unittest.main()
