"""Opt-in disposable Docker/nginx smoke; no real credentials or database."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


@unittest.skipUnless(os.getenv('WPL_RUN_DOCKER_TESTS') == '1', 'Requires explicit local Docker opt-in.')
class LocalDeploymentTests(unittest.TestCase):
    def test_isolated_backend_proxy_and_gui_denial(self):
        root = Path(__file__).resolve().parents[1]
        tag = uuid4().hex
        names = ['wpl-toolkit-backend-' + tag, 'wpl-toolkit-web-' + tag]
        # Reserve distinct unused loopback ports without touching the live app.
        with socket.socket() as first, socket.socket() as second:
            first.bind(('127.0.0.1', 0))
            second.bind(('127.0.0.1', 0))
            backend_port, web_port = first.getsockname()[1], second.getsockname()[1]

        def docker(*args):
            return subprocess.check_output(['docker', *args], text=True, stderr=subprocess.PIPE).strip()

        def get(path, *, post=False):
            request = Request('http://127.0.0.1:' + str(web_port) + path,
                              data=b'{}' if post else None,
                              headers={'Content-Type': 'application/json'})
            try:
                with urlopen(request, timeout=5) as response:
                    return response.status, response.read()
            except HTTPError as error:
                with error:
                    return error.code, error.read()

        created = []
        with tempfile.TemporaryDirectory(prefix='wpl-toolkit-smoke-') as directory:
            config = Path(directory) / 'nginx.conf.template'
            template = (root / 'deploy/nginx.conf.template').read_text()
            config.write_text(template.replace('127.0.0.1:8000', '127.0.0.1:' + str(backend_port)))
            try:
                created.append(names[0])
                docker('run', '-d', '--name', names[0], '--label', 'wpl.toolkit.test=' + tag,
                       '--network', 'host', '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
                       '--env', 'WPL_PUBLIC_URL=http://127.0.0.1:' + str(web_port),
                       '--env', 'WPL_DATABASE_PATH=/tmp/fixture.db',
                       '--env', 'WPL_SECRET_KEY=' + 'synthetic-' * 8,
                       '--mount', 'type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock',
                       'wpl-backend:dev', '/bin/sh', '-c',
                       'python -m alembic upgrade head && exec python -m uvicorn backend.app.main:app --host 127.0.0.1 --port ' + str(backend_port))
                created.append(names[1])
                docker('run', '-d', '--name', names[1], '--label', 'wpl.toolkit.test=' + tag,
                       '--network', 'host', '--env', 'WPL_LISTEN_ADDRESS=127.0.0.1',
                       '--env', 'WPL_HTTP_PORT=' + str(web_port),
                       '--mount', 'type=bind,src=' + str(config) + ',dst=/etc/nginx/templates/default.conf.template,readonly',
                       'wpl-web:dev')
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        if get('/api/health')[0] == 200:
                            break
                    except (URLError, TimeoutError, ConnectionError):
                        pass
                    time.sleep(0.5)
                else:
                    self.fail('Disposable backend/proxy did not become ready.')
                code, body = get('/')
                self.assertEqual(code, 200)
                self.assertIn(b'<html', body.lower())
                self.assertEqual(get('/api/labs', post=True)[0], 401)
                self.assertEqual(get('/gui/' + str(uuid4()) + '/vnc.html')[0], 403)
                self.assertEqual(json.loads(get('/api/health')[1]), {'status': 'ok'})
                print('Disposable Docker startup/migrations, web/API proxy, anonymous lab denial and signed-GUI boundary passed.')
            finally:
                for name in reversed(created):
                    inspect = subprocess.run(['docker', 'inspect', '--format', '{{json .Config.Labels}}', name], capture_output=True, text=True)
                    if inspect.returncode:
                        continue
                    self.assertEqual(json.loads(inspect.stdout).get('wpl.toolkit.test'), tag)
                    docker('rm', '-f', name)
                print('Disposable toolkit containers and temporary fixture filesystem removed.')


if __name__ == '__main__':
    unittest.main()
