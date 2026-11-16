"""Plugin-only process entry, sibling imports and source/frozen routing; offline."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import plugin_worker


class WorkerEntryChecks(unittest.TestCase):
    def test_worker_does_not_construct_host_or_load_plugin_entry(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder/'plugin.py').write_text('raise RuntimeError("Plugin entry must not execute")\n')
            (folder/'helper.py').write_text('VALUE = 17\n')
            (folder/'worker.py').write_text(
                'from .helper import VALUE\nimport json,os,sys\n'
                'def run():\n'
                ' data=json.loads(sys.stdin.readline())\n'
                ' print(json.dumps(dict(pid=os.getpid(),value=VALUE,data=data,'
                'host_imported="ddm.app" in sys.modules,config_imported="ddm.config" in sys.modules)),flush=True)\n'
                ' return 0\n')
            program, arguments = plugin_worker.worker_command(folder/'plugin.py', 'worker')
            child = subprocess.run([program, *arguments], input='{"request":1}\n', text=True,
                                   capture_output=True, timeout=15, cwd=ROOT)
            self.assertEqual(child.returncode, 0, child.stderr)
            result = json.loads(child.stdout)
            self.assertNotEqual(result['pid'], os.getpid())
            self.assertEqual(result['value'], 17)
            self.assertEqual(result['data'], {'request': 1})
            self.assertFalse(result['host_imported'])
            self.assertFalse(result['config_imported'])
            with patch.object(sys, 'frozen', True, create=True):
                frozen, arguments = plugin_worker.worker_command(folder/'plugin.py', 'worker')
                self.assertEqual(frozen, sys.executable)
                self.assertEqual(arguments, ['--plugin-worker', str(folder.resolve()), 'worker'])

    def test_reject_missing_or_traversal_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder/'plugin.py').write_text('')
            for name in ('../other', 'a.b', 'a/b', ''):
                with self.assertRaises(ValueError):
                    plugin_worker.worker_command(folder/'plugin.py', name)
            with self.assertRaises(FileNotFoundError):
                plugin_worker.worker_command(folder/'plugin.py', 'missing')

    def test_incomplete_cli_does_not_start_host(self):
        child = subprocess.run([sys.executable, str(ROOT/'main.py'), '--plugin-worker'],
                               capture_output=True, text=True, timeout=10)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn('Usage: --plugin-worker', child.stderr)


if __name__ == '__main__':
    unittest.main()
