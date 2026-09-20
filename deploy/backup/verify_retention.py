"""Runs the real retention script only against disposable test files."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


def shell_path(path):
    value = Path(path).resolve().as_posix()
    return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.directory = Path(self.tmp.name)
        self.shell = os.environ.get('TEST_SH') or shutil.which('sh')
        self.script = Path(__file__).with_name('retention.sh')

    def tearDown(self):
        self.tmp.cleanup()

    def run_retention(self, days='14', interval='300'):
        env = dict(os.environ, BACKUP_DIR=shell_path(self.directory),
                   BACKUP_RETENTION_DAYS=days, BACKUP_RETENTION_CHECK_SECONDS=interval)
        return subprocess.run([self.shell, '-c',
                               'PATH=/usr/bin:/bin:$PATH; export PATH; exec sh "$1" once',
                               'verify-retention', shell_path(self.script)],
                              env=env, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=10)

    def test_expiry_without_any_successful_backup(self):
        # No .last-success or database: cleanup must not require a new dump.
        old_names = ['sumeungil-old.dump', 'sumeungil-old.dump.sha256',
                     '.sumeungil-failed.dump.partial']
        for name in old_names + ['unrelated.txt']:
            p = self.directory / name
            p.write_text('fixture')
            os.utime(p, (time.time() - 15*86400,) * 2)
        recent = self.directory / 'sumeungil-recent.dump'
        recent.write_text('fixture')
        nested = self.directory / 'nested'
        nested.mkdir()
        (nested / 'sumeungil-old.dump').write_text('fixture')
        result = self.run_retention()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in old_names:
            self.assertFalse((self.directory / name).exists())
        self.assertTrue(recent.exists())
        self.assertTrue((self.directory / 'unrelated.txt').exists())
        self.assertTrue((nested / 'sumeungil-old.dump').exists())
        self.assertTrue((self.directory / '.last-retention-success').exists())

    def test_rejects_invalid_configuration_without_deletion(self):
        p = self.directory / 'sumeungil-old.dump'
        p.write_text('fixture')
        os.utime(p, (time.time() - 15*86400,) * 2)
        for days, interval in [('0','300'), ('-1','300'), ('bad','300'),
                               ('14','0'), ('14','3601'), ('14','bad')]:
            with self.subTest(days=days, interval=interval):
                self.assertNotEqual(self.run_retention(days, interval).returncode, 0)
                self.assertTrue(p.exists())


if __name__ == '__main__':
    unittest.main()
