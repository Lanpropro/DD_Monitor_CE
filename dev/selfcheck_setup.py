"""Installer payload boundaries and generated file ownership; no install or network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev.build_setup import PERSONAL_FILES, payload_files, write_script
from ddm.update_install import MANIFEST
from ddm.version import DISPLAY_NAME, VERSION


def fixture(root):
    root.mkdir()
    files = {f'{DISPLAY_NAME}.exe': b'program', 'ffmpeg.exe': b'ffmpeg',
             '_internal/libmpv-2.dll': b'runtime', 'assets/logo.png': b'logo',
             'ddm-build.json': json.dumps({'version': VERSION, 'update_protocol': 1,
                                          'platform': 'windows-x64'}).encode()}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / 'plugins_user').mkdir()
    return files


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ddm-setup-boundary-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.payload = self.root / 'portable'
        self.files = fixture(self.payload)

    def test_initial_inventory_contains_only_release_program_files(self):
        script = write_script(self.payload, self.root / 'build', self.root / 'out')
        recorded = json.loads((script.parent / MANIFEST).read_text(encoding='utf-8'))
        self.assertEqual(set(recorded), set(self.files))
        self.assertNotIn(MANIFEST, recorded)

    def test_user_data_or_unknown_files_cannot_enter_setup(self):
        for name in ('utils/config.json', 'plugins_user/custom/plugin.py',
                     'cache/token', 'recordings/a.mp4', 'personal.txt',
                     '_internal/../secret.txt'):
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('keep', encoding='utf-8')
            with self.subTest(name=name), self.assertRaises(ValueError):
                payload_files(self.payload)
            path.unlink()
            # Remove only fixture-created empty parent directories.
            for parent in path.parents:
                if parent == self.payload or parent.name in ('_internal', 'plugins_user'):
                    break
                if not any(parent.iterdir()):
                    parent.rmdir()

    def test_portable_notes_are_not_installed(self):
        for name in (f'RELEASE-v{VERSION}.md', '运行说明.txt'):
            (self.payload / name).write_text('portable instructions', encoding='utf-8')
        self.assertEqual(set(payload_files(self.payload)), set(self.files))
        script = write_script(self.payload, self.root / 'build', self.root / 'out')
        source = script.read_text(encoding='utf-8-sig')
        self.assertNotIn('RELEASE-v', source)
        self.assertNotIn('运行说明.txt', source)
        self.assertIn('ddm-build.json', source)

    def test_branded_wizard_and_discoverable_uninstall(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        self.assertIn('WizardStyle=modern dark', source)
        self.assertIn('WizardBackColor=#202225', source)
        self.assertIn('DisableWelcomePage=no', source)
        self.assertIn('WizardImageFile=', source)
        self.assertIn('WizardSmallImageFile=', source)
        self.assertIn('DestName: "DDMonitorUninstall.exe"', source)
        self.assertNotIn(f'Name: "{{app}}\\卸载 {DISPLAY_NAME}"', source)
        self.assertIn(f'Name: "{{autoprograms}}\\DDMonitorCE\\卸载 {DISPLAY_NAME}"', source)
        self.assertIn('DirBrowseButton.OnClick := @BrowseInstallFolder', source)
        self.assertIn('--pick-folder', source)
        self.assertIn('LoadStringsFromFile(Output, Lines)', source)

    def test_payload_directory_links_are_rejected(self):
        with patch.object(Path, 'is_junction', lambda p: p.name == 'assets'):
            with self.assertRaisesRegex(ValueError, 'Linked payload'):
                payload_files(self.payload)

    def test_personal_cleanup_is_opt_in_and_uses_exact_known_paths(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        self.assertIn('RemovePersonalData := False;', source)
        self.assertIn('Choice.Checked := False;', source)
        self.assertIn('if UninstallSilent then Exit;', source)
        self.assertIn('RemovePersonalData := Choice.Checked', source)
        self.assertIn('(Step = usUninstall) and RemovePersonalData', source)
        self.assertIn('if not PersonalPathsSafe then CleanupFailed := True', source)
        self.assertIn('未登记来源的文件始终保留', source)
        self.assertIn('没有逐文件来源记录，因此保留', source)
        for name in PERSONAL_FILES:
            self.assertTrue(name.startswith('utils/'))
            self.assertNotIn('*', name)
            self.assertNotIn('..', name)
            self.assertIn("RemovePersonalFile('" + name.replace('/', '\\') + "');", source)
        self.assertIn('utils/config.json.bak', PERSONAL_FILES)
        self.assertIn('utils/accounts/youtube_oauth_client.bin', PERSONAL_FILES)
        self.assertNotIn('utils/accounts/custom.bin', PERSONAL_FILES)
        for directory in ('recordings/', 'plugins_user/', 'logs/', 'cache/', 'utils/skins/'):
            self.assertFalse(any(name.startswith(directory) for name in PERSONAL_FILES))

    def test_version_and_required_runtimes_are_verified(self):
        (self.payload / '_internal/libmpv-2.dll').unlink()
        with self.assertRaisesRegex(ValueError, 'runtime is missing'):
            payload_files(self.payload)
        (self.payload / 'ddm-build.json').write_text('{"version":"old"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            payload_files(self.payload)

    def test_uninstall_uses_only_file_records_and_rejects_linked_directories(self):
        script = write_script(self.payload, self.root / 'build', self.root / 'out')
        source = script.read_text(encoding='utf-8-sig')
        self.assertIn('OutputBaseFilename=DDMonitorSetup', source)
        self.assertIn('PrivilegesRequired=lowest', source)
        self.assertIn('function InitializeUninstall', source)
        self.assertIn('GetFileAttributesW@kernel32.dll', source)
        self.assertIn('if not SafePath(ExpandConstant(\'{app}\\_internal\')) then Exit;', source)
        self.assertIn('if HasFiles and not OwnInstall then', source)
        self.assertIn('Check: CanCreateShortcut', source)
        for unsafe in ('[UninstallDelete]', '[InstallDelete]', 'DelTree(', 'uninsneveruninstall',
                       'recursesubdirs', 'Source: "*', 'restartreplace'):
            self.assertNotIn(unsafe, source)
        entries = source.split('[Files]', 1)[1].split('[Icons]', 1)[0].strip().splitlines()
        self.assertEqual(len(entries), len(self.files) + 4)
        self.assertTrue(all('Flags: ignoreversion' in entry for entry in entries[:-1]))
        self.assertIn('Flags: dontcopy', entries[-1])


if __name__ == '__main__':
    unittest.main()
