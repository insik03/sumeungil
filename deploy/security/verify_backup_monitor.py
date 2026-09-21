import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).with_name("backup-monitor.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def test_fresh_stale_missing_stopped(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            self.assertEqual(len(m.assess(p, True, 100, 1000)), 2)
            for name in (".last-success", ".last-retention-success"):
                (p / name).write_text("950")
            self.assertEqual(m.assess(p, True, 100, 1000), [])
            self.assertIn("backup_container_not_running", m.assess(p, False, 100, 1000))
            self.assertIn("last-success_stale", m.assess(p, True, 100, 2000))
    def test_transitions_retry_and_reminder(self):
        self.assertFalse(m.should_send({}, "ok", 1000))
        self.assertTrue(m.should_send({}, "error", 1000))
        self.assertFalse(m.should_send({"status":"error", "sent_at":999}, "error", 1000))
        self.assertTrue(m.should_send({"status":"error", "sent_at":1}, "error", 4000))
        self.assertTrue(m.should_send({"status":"error", "sent_at":999}, "ok", 1000))
    def test_delivery_requires_ack(self):
        with patch.object(m.urllib.request, "urlopen") as send:
            send.return_value.__enter__.return_value.status = 200
            send.return_value.__enter__.return_value.read.return_value = b"ok"
            m.deliver("https://hooks.slack.com/services/synthetic", "test")
            send.return_value.__enter__.return_value.read.return_value = b"invalid_payload"
            with self.assertRaises(RuntimeError):
                m.deliver("https://hooks.slack.com/services/synthetic", "test")
        with self.assertRaises(RuntimeError):
            m.deliver("http://untrusted.invalid", "test")

if __name__ == "__main__":
    unittest.main()
