import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server.config import Settings
from server.start import prepare_data_dir, server_command

spec = importlib.util.spec_from_file_location("check_publish", Path(__file__).resolve().parents[1] / "scripts/check_publish.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class DeploymentTests(unittest.TestCase):
    def test_platform_port_and_single_worker_are_used(self):
        command = server_command({"PORT": "9173"})
        self.assertEqual(command[command.index("--port") + 1], "9173")
        self.assertEqual(command[command.index("--workers") + 1], "1")
        for port in ("0", "65536", "not-a-port"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                server_command({"PORT": port})

    def test_root_volume_is_owned_before_privileges_are_dropped(self):
        with tempfile.TemporaryDirectory() as directory, patch("server.start.os.geteuid", return_value=0, create=True), \
                patch("server.start.os.chown", create=True) as chown, patch("server.start.os.setgroups", create=True) as groups, \
                patch("server.start.os.setgid", create=True) as gid, patch("server.start.os.setuid", create=True) as uid, \
                patch("server.start.os.umask"):
            events = []
            for name, mock in (("chown", chown), ("groups", groups), ("gid", gid), ("uid", uid)):
                mock.side_effect = lambda *args, label=name: events.append(label)
            prepare_data_dir({"OFFEROS_DATA_DIR": directory})
            self.assertEqual(events, ["chown", "groups", "gid", "uid"])
            chown.assert_called_once_with(Path(directory), 10001, 10001)
            uid.assert_called_once_with(10001)

    def test_production_rejects_default_admin_password(self):
        for password in ("admin123", "change-me-strong-password"):
            with patch.dict(os.environ, {"ENVIRONMENT": "production", "ADMIN_PASSWORD": password}), self.assertRaises(ValueError):
                Settings()
        with patch.dict(os.environ, {"ENVIRONMENT": "production", "ADMIN_PASSWORD": "test-only-long-password"}):
            os.environ.pop("DISABLE_DOCS", None)
            self.assertTrue(Settings().disable_docs)

    def test_private_paths_and_secret_values_fail_publication(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(publish, "ROOT", Path(directory)):
            root = Path(directory)
            (root / "leak.py").write_text('token = "sk-' + 'a' * 32 + '"')
            (root / ".env.example").write_text('DASHSCOPE_API_KEY=your_dashscope_api_key_here')
            findings = publish.audit_paths([".env", ".env.production", "data/resume.txt", "archive.db",
                                           "uploads/candidate.pdf", ".impeccable/review/capture.json", "private.pem", "leak.py"])
            self.assertEqual(len(findings), 8)
            self.assertNotIn('a' * 32, str(findings))
            self.assertEqual(publish.audit_paths([".env.example"]), [])


if __name__ == "__main__":
    unittest.main()
