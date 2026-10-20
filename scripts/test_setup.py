"""Wizard tests using temporary files and mocked Docker operations."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("wpl_setup", Path(__file__).with_name("setup.py"))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def settings():
    return {
        "WPL_PUBLIC_URL": "http://localhost:8080",
        "SUPABASE_URL": "https://test-project.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        "SUPABASE_SECRET_KEY": "sb_secret_test",
        "WPL_GITHUB_CLIENT_ID": "test-client",
        "WPL_GITHUB_CLIENT_SECRET": "test-client-secret",
        "WPL_SECRET_KEY": "s" * 48,
    }


class SetupTests(unittest.TestCase):
    def test_origin_rejects_paths_credentials_and_invalid_ports(self):
        for value in ("https://example.com/rest/v1/", "https://u:p@example.com",
                      "https://example.com:99999", "https://example.com?x=1",
                      "https://example.com:0", "https://example.com/a"):
            with self.subTest(value=value), self.assertRaises(setup.SetupError):
                setup.origin(value, "URL")

    def test_settings_reject_wrong_keys_and_wrong_ports(self):
        for update in ({"SUPABASE_PUBLISHABLE_KEY": "sb_secret_wrong"},
                       {"WPL_HTTP_PORT": "9000"},
                       {"WPL_API_BASE_URL": "http://localhost:8000"},
                       {"WPL_LAB_CPUS": "NaN"},
                       {"WPL_LAB_CPUS": "0.0000000001"},
                       {"WPL_LAB_MEMORY": "0g"},
                       {"WPL_SECRET_KEY": "short"}):
            with self.subTest(update=update), self.assertRaises(setup.SetupError):
                setup.validate(settings() | update)

    def test_https_uses_separate_internal_port(self):
        values = settings() | {"WPL_PUBLIC_URL": "https://lab.example.com", "WPL_HTTP_PORT": "8081"}
        self.assertEqual(setup.validate(values), ("https://lab.example.com", 8081))

    def test_compose_build_settings_must_match_backend(self):
        values = settings()
        config = {"services": {
            "backend": {"environment": values},
            "web": {"environment": {}, "build": {"args": {
                "VITE_API_URL": "http://wrong.example/api",
                "VITE_SUPABASE_URL": values["SUPABASE_URL"],
                "VITE_SUPABASE_PUBLISHABLE_KEY": values["SUPABASE_PUBLISHABLE_KEY"],
            }}},
        }}
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.touch()
            env_file.chmod(0o600)
            with patch.object(setup, "ENV_FILE", env_file), \
                    patch.object(setup, "capture", return_value=json.dumps(config)), \
                    self.assertRaisesRegex(setup.SetupError, "Frontend and backend settings disagree"):
                setup.read_configuration()

    def test_check_never_writes_or_builds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / ".env"
            original = b"PRIVATE_SETTINGS=preserved\n"
            env_file.write_bytes(original)
            with patch.object(setup, "ROOT", root), patch.object(setup, "ENV_FILE", env_file), \
                    patch.object(setup, "prerequisites"), patch.object(setup, "check_ports"), \
                    patch.object(setup, "read_configuration", return_value=(settings(), "http://localhost:8080", 8080)), \
                    patch.object(setup, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                setup.main(["--check"])
                run.assert_not_called()
            self.assertEqual(env_file.read_bytes(), original)
            self.assertFalse((root / "data").exists())

    def test_existing_setup_preserves_secrets_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env_file = root / ".env"
            env_file.write_bytes(b"WPL_SECRET_KEY=do-not-rotate\n")
            (root / "data").mkdir()
            database = root / "data" / "wpl.db"
            database.write_bytes(b"existing-database")
            with patch.object(setup, "ROOT", root), patch.object(setup, "ENV_FILE", env_file), \
                    patch.object(setup, "prerequisites"), patch.object(setup, "check_ports"), \
                    patch.object(setup, "read_configuration", return_value=(settings(), "http://localhost:8080", 8080)), \
                    patch.object(setup, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                setup.main([])
                self.assertEqual(run.call_count, 2)
            self.assertEqual(env_file.read_bytes(), b"WPL_SECRET_KEY=do-not-rotate\n")
            self.assertEqual(database.read_bytes(), b"existing-database")

    def test_cancelled_wizard_does_not_save_configuration(self):
        responses = ["http://localhost:8080", "https://test.supabase.co", "test-client"]
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            with patch.object(setup, "ENV_FILE", env_file), \
                    patch("builtins.input", side_effect=responses + ["no"]), \
                    patch.object(setup.getpass, "getpass", side_effect=["sb_publishable_test", "sb_secret_test", "client-secret"]), \
                    patch.object(setup, "check_ports"), contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(setup.SetupError):
                setup.fresh_configuration()
            self.assertFalse(env_file.exists())

    def test_fresh_wizard_saves_private_config_with_generated_key(self):
        responses = ["http://localhost:8080", "https://test.supabase.co", "test-client", "yes"]
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            with patch.object(setup, "ENV_FILE", env_file), \
                    patch("builtins.input", side_effect=responses), \
                    patch.object(setup.getpass, "getpass", side_effect=["sb_publishable_test", "sb_secret_test", "client-secret"]), \
                    patch.object(setup.secrets, "token_urlsafe", return_value="s" * 48), \
                    patch.object(setup, "check_ports"), contextlib.redirect_stdout(io.StringIO()):
                setup.fresh_configuration()
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            self.assertIn("WPL_SECRET_KEY='" + "s" * 48 + "'", env_file.read_text())

    def test_missing_config_with_existing_database_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "wpl.db").write_bytes(b"preserve")
            env_file = root / ".env"
            with patch.object(setup, "ROOT", root), patch.object(setup, "ENV_FILE", env_file), \
                    patch.object(setup, "prerequisites"), \
                    patch.object(setup, "fresh_configuration") as fresh, \
                    self.assertRaises(setup.SetupError):
                setup.main([])
            fresh.assert_not_called()
            self.assertFalse(env_file.exists())

    def test_adoption_checks_credentials_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            path.write_text("{}")
            old = {"services": {"backend": {"environment": settings()}, "web": {}}}
            new = {"services": {"backend": {"environment": settings()}}}
            before = path.read_bytes()
            with patch.object(setup, "capture", side_effect=[json.dumps(old), json.dumps(new)]):
                self.assertEqual(setup.adoption_configuration(path), path.resolve())
            self.assertEqual(path.read_bytes(), before)
            old["services"]["backend"]["environment"]["WPL_SECRET_KEY"] = "different"
            with patch.object(setup, "capture", side_effect=[json.dumps(old), json.dumps(new)]):
                with self.assertRaisesRegex(setup.SetupError, "credentials/origin differ"):
                    setup.adoption_configuration(path)

    def test_foreign_compose_owner_is_not_silently_adopted(self):
        labels = {"com.docker.compose.project.working_dir": "/other/checkout"}
        with patch.object(setup, "capture", side_effect=["container", json.dumps(labels) + "|true"]):
            with self.assertRaisesRegex(setup.SetupError, "Another checkout"):
                setup.managed_services()

    def test_adoption_rejects_wrong_database_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            labels = {
                "com.docker.compose.project.working_dir": directory,
                "com.docker.compose.project.config_files": str(path),
                "com.docker.compose.service": "backend",
            }
            with patch.object(setup, "adoption_configuration", return_value=path), patch.object(
                setup, "capture", side_effect=["container", json.dumps(labels) + "|true", "[]"],
            ):
                with self.assertRaisesRegex(setup.SetupError, "preserved database"):
                    setup.managed_services(path)

    def test_adoption_accepts_only_matching_owner_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            labels = {
                "com.docker.compose.project.working_dir": directory,
                "com.docker.compose.project.config_files": str(path),
                "com.docker.compose.service": "backend",
            }
            mounts = [{"Type": "bind", "Source": str(setup.ROOT / "data/wpl.db"), "Destination": "/app/wpl.db"}]
            with patch.object(setup, "adoption_configuration", return_value=path), patch.object(
                setup, "capture", side_effect=["container", json.dumps(labels) + "|true", json.dumps(mounts)],
            ):
                self.assertEqual(setup.managed_services(path), {"backend"})

    def test_adoption_refuses_active_lab_before_any_build(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            env = root / ".env"
            env.write_text("PRIVATE=preserved\n")
            with sqlite3.connect(root / "data/wpl.db") as db:
                db.execute("CREATE TABLE labs (id TEXT)")
                db.execute("INSERT INTO labs VALUES ('active')")
            db.close()
            with patch.object(setup, "ROOT", root), patch.object(setup, "ENV_FILE", env), patch.object(
                setup, "prerequisites"
            ), patch.object(setup, "check_ports"), patch.object(
                setup, "read_configuration", return_value=(settings(), "http://localhost:8080", 8080)
            ), patch.object(setup, "run") as run:
                with self.assertRaisesRegex(setup.SetupError, "Save and close"):
                    setup.main(["--adopt-existing", str(root / "external.json")])
                run.assert_not_called()

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI unavailable")
    def test_dotenv_special_characters_round_trip_through_compose(self):
        version = subprocess.run(["docker", "compose", "version"], capture_output=True)
        if version.returncode:
            self.skipTest("Compose unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = "literal$DOLLAR #hash quote' and backslash\\value"
            (root / ".env").write_text(setup.dotenv_text({"TEST_VALUE": value}))
            (root / "compose.yaml").write_text(
                "services:\n  test:\n    image: scratch\n    env_file: .env\n"
                '    build:\n      context: .\n      args:\n        TEST_VALUE: "${TEST_VALUE}"\n'
            )
            result = subprocess.run(
                ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(root / "compose.yaml"),
                 "config", "--format", "json"], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, "Synthetic Compose configuration failed")
            service = json.loads(result.stdout)["services"]["test"]
            # Config exports escape literal dollars to remain re-loadable.
            self.assertEqual(service["environment"]["TEST_VALUE"].replace("$$", "$"), value)
            self.assertEqual(service["build"]["args"]["TEST_VALUE"].replace("$$", "$"), value)


if __name__ == "__main__":
    unittest.main()
