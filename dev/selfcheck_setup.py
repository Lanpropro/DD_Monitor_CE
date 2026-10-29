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
             'DDMonitorDiagnostics.exe': b'diagnostics', '诊断工具说明.md': b'diagnostic guide',
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

    def test_build_commit_provenance_is_validated(self):
        path = self.payload / 'ddm-build.json'
        build = json.loads(path.read_text(encoding='utf-8'))
        build['source_commit'] = 'a' * 40
        path.write_text(json.dumps(build), encoding='utf-8')
        write_script(self.payload, self.root / 'valid', self.root / 'out')
        build['source_commit'] = 'not-a-commit'
        path.write_text(json.dumps(build), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Invalid source commit'):
            write_script(self.payload, self.root / 'invalid', self.root / 'out')

    def test_diagnostic_tool_and_guide_are_installed_and_recorded(self):
        script = write_script(self.payload, self.root / 'build', self.root / 'out')
        recorded = json.loads((script.parent / MANIFEST).read_text(encoding='utf-8'))
        for name in ('DDMonitorDiagnostics.exe', '诊断工具说明.md'):
            self.assertIn(name, recorded)
            self.assertIn(name, script.read_text(encoding='utf-8-sig'))
            original = (self.payload / name).read_bytes()
            (self.payload / name).unlink()
            with self.assertRaises(ValueError):
                payload_files(self.payload)
            (self.payload / name).write_bytes(original)

    def test_user_data_or_unknown_files_cannot_enter_setup(self):
        for name in ('utils/config.json', 'plugins_user/custom/plugin.py',
                     'cache/token', 'recordings/a.mp4', 'personal.txt',
                     '.ddm-install.json', '_internal/../secret.txt'):
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

    def test_current_release_notes_remain_available_to_the_app(self):
        for name in (f'RELEASE-v{VERSION}.md', '运行说明.txt'):
            (self.payload / name).write_text('portable instructions', encoding='utf-8')
        self.assertEqual(set(payload_files(self.payload)), set(self.files) | {f'RELEASE-v{VERSION}.md'})
        script = write_script(self.payload, self.root / 'build', self.root / 'out')
        source = script.read_text(encoding='utf-8-sig')
        self.assertIn(f'RELEASE-v{VERSION}.md', source)
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
        self.assertIn('同时清除个人信息（账号、设置及插件）', source)
        self.assertIn('个人信息目录：', source)
        self.assertIn("if not ResolvePersonalDataDir then PersonalDataDir := '';", source)
        self.assertIn('AddBackslash(PersonalDataDir) + RelativeName', source)
        self.assertIn("if PersonalDataDir = '' then Exit", source)
        self.assertNotIn('旧版安装目录中的个人信息', source)
        self.assertIn("RemoveInstalledPlugins('plugins_user');", source)
        self.assertIn('.ddm-plugin-files.txt', source)
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
        self.assertEqual(len(entries), len(self.files) + 5)
        self.assertTrue(all('Flags: ignoreversion' in entry for entry in entries[1:]))
        self.assertIn('Flags: dontcopy', entries[0])
        self.assertIn('solidbreak', entries[2])
        self.assertIn('DDMonitorInstallerHelper.exe', entries[0])
        self.assertIn('DDMonitorUninstall.exe', entries[1])

    def test_two_install_modes_keep_user_data_separate(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        self.assertIn('DefaultDirName={autopf}\\DDMonitorCE', source)
        self.assertIn('PrivilegesRequiredOverridesAllowed=dialog', source)
        self.assertIn('RegQueryStringValue(HKA,', source)
        self.assertIn('.ddm-install.json', source)
        self.assertNotIn('.ddm-install.json', json.loads((self.root / 'build' / MANIFEST).read_text(encoding='utf-8')))

    def test_directory_page_is_always_visible_including_repeat_installs(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        setup = source.split('[Setup]', 1)[1].split('[Languages]', 1)[0]
        self.assertEqual([line for line in setup.splitlines() if line.startswith('DisableDirPage=')],
                         ['DisableDirPage=no'])

    def test_repeat_installs_do_not_hide_privilege_mode_choice(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        setup = source.split('[Setup]', 1)[1].split('[Languages]', 1)[0]
        self.assertIn('PrivilegesRequiredOverridesAllowed=dialog', setup)
        self.assertEqual([line for line in setup.splitlines() if line.startswith('UsePreviousPrivileges=')],
                         ['UsePreviousPrivileges=no'])

    def test_picker_is_extracted_before_browse_and_dialog_is_not_scaled_twice(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        browse = source.split('procedure BrowseInstallFolder', 1)[1].split('procedure InitializeWizard', 1)[0]
        self.assertNotIn('ExtractTemporaryFile', browse)
        self.assertIn("ExtractTemporaryFile('DDMonitorInstallerHelper.exe')", source.split('procedure InitializeWizard', 1)[1])
        self.assertIn('CreateCustomForm(470, 245, True, True)', source)
        self.assertIn('Compression=lzma2/fast', source)
        self.assertIn('SetupLogging=no', source)

    def test_folder_picker_quotes_trailing_backslashes_and_keeps_uninstall_separate(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        self.assertIn("'--pick-folder ' + QuoteProcessPath(Initial)", source)
        self.assertIn('QuoteProcessPath(Output)', source)
        quoting = source.split('function QuoteProcessPath', 1)[1].split('procedure BrowseInstallFolder', 1)[0]
        self.assertIn("(Value[Index] = '\\')", quoting)
        self.assertIn("Result := Result + '\\';", quoting)
        helper = (Path(__file__).resolve().parent / 'installer/helper.cpp').read_text(encoding='utf-8')
        branch = helper.split('if (count >= 2 &&', 1)[1].split('} else result = LaunchUninstaller', 1)[0]
        self.assertIn('result = 2;', branch)
        self.assertIn('if (count == 5)', branch)
        self.assertNotIn('LaunchUninstaller', branch)

    def test_install_directory_permissions_are_checked_before_extracting_payload(self):
        source = write_script(self.payload, self.root / 'build', self.root / 'out').read_text(encoding='utf-8-sig')
        check = source.split('function InstallDirectoryError:', 1)[1].split('function NextButtonClick', 1)[0]
        self.assertIn('if not SafeProgramPaths then Exit', check)
        self.assertIn('while not DirExists(Directory)', check)
        self.assertIn("SaveStringToFile(FileName, 'DDMonitorCE write check', False)", check)
        self.assertIn('RemoveDir(Probe)', check)
        self.assertNotIn('ForceDirectories', check)
        self.assertIn('无法写入所选安装位置', check)
        self.assertIn('例如 E:\\DDMonitorCE', check)
        next_page = source.split('function NextButtonClick', 1)[1].split('function PersonalPathsSafe', 1)[0]
        self.assertIn('CurPageID <> wpSelectDir', next_page)
        self.assertIn('Error := InstallDirectoryError', next_page)
        prepare = source.split('function PrepareToInstall', 1)[1].split('function InitializeUninstall', 1)[0]
        self.assertIn('Result := InstallDirectoryError', prepare)
        self.assertLess(prepare.index('Result := InstallDirectoryError'), prepare.index('FindFirst('))


if __name__ == '__main__':
    unittest.main()
