"""Controlled native child-process crashes; not a reproduction of issue #222."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows native evidence')
class NativeDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ddm-native-tests-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        subprocess.run(['cmd', '/c', str(ROOT / 'dev/build_native_diagnostics.cmd'), str(cls.folder)], check=True, timeout=90)
        vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
        vs = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
        build = cls.folder / 'fixture.cmd'
        build.write_text(f'@echo off\ncall "{vs}\\VC\\Auxiliary\\Build\\vcvars64.bat" >nul\n'
            f'cl /nologo /MT /O2 "{ROOT / "dev/native_diagnostics_fixture.cpp"}" '
            f'/Fe"{cls.folder / "fixture.exe"}" /Fo"{cls.folder / "fixture.obj"}"\n', encoding='utf-8')
        subprocess.run(['cmd', '/c', str(build)], check=True, timeout=60)

    def invoke(self, mode):
        folder = self.folder / mode
        folder.mkdir()
        result = subprocess.run([str(self.folder / 'fixture.exe'), str(self.folder / 'DDMonitorNativeCapture.dll'),
            str(self.folder / 'DDMonitorCrashWatcher.exe'), str(folder), mode], timeout=20)
        return result.returncode, folder

    def test_default_text_stack_preserves_fatal_exit(self):
        code, folder = self.invoke('0')
        self.assertEqual(code & 0xffffffff, 0xc0000005)
        report = json.loads(next(folder.glob('*.json')).read_text())
        self.assertEqual(report['exception_code'], '0xc0000005')
        self.assertTrue(report['frames'])
        self.assertTrue(any('fixture' in row.get('module', '').lower() for row in report['frames']), report)
        self.assertFalse(report['dump_requested'])
        self.assertEqual(list(folder.glob('*.dmp')), [])

    def test_opt_in_dump_is_valid_and_atomic(self):
        code, folder = self.invoke('1')
        self.assertEqual(code & 0xffffffff, 0xc0000005)
        report = json.loads(next(folder.glob('*.json')).read_text())
        self.assertTrue(report['dump_saved'], report)
        dump = next(folder.glob('*.dmp'))
        with dump.open('rb') as stream:
            self.assertEqual(stream.read(4), b'MDMP')
        self.assertEqual(list(folder.glob('*.part')), [])

    def test_normal_exit_not_recorded_or_changed(self):
        code, folder = self.invoke('normal')
        self.assertEqual(code, 23)
        self.assertEqual(list(folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
