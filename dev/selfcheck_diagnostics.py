"""Compile and exercise the independent Windows collector on temporary fixtures only."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows .NET Framework diagnostic tool')
class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='ddm-diagnostic-tests-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.compiler = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
        cls.driver = cls.base / 'test.exe'
        cls.compile(cls.driver, [ROOT / 'tools/diagnostics/Collector.cs', ROOT / 'tools/diagnostics/Program.cs', ROOT / 'dev/diagnostics_tests.cs'])

    @classmethod
    def compile(cls, target, sources, gui=False):
        references = ['System.Management', 'System.Web.Extensions', 'System.IO.Compression',
                      'System.IO.Compression.FileSystem', 'System.Windows.Forms', 'System.Drawing']
        command = [str(cls.compiler), '/nologo', '/utf8output', '/platform:anycpu',
                   '/target:' + ('winexe' if gui else 'exe'), '/out:' + str(target)]
        command += ['/reference:' + name + '.dll' for name in references]
        if not gui:
            command += ['/main:DiagnosticsTests']
        command += list(map(str, sources))
        result = subprocess.run(command, capture_output=True, timeout=40)
        if result.returncode:
            raise AssertionError(result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace'))

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(dir=self.base, prefix='case-'))
        self.app = self.case / '软件 测试目录'
        self.output = self.case / '输出'
        self.app.mkdir()
        self.output.mkdir()
        (self.app / 'main.py').write_text('# fake application; must never be executed\nraise RuntimeError()', encoding='utf-8')

    def put(self, name, value):
        path = self.app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def collect(self, success=True, output=None, reproduction='尚未确认', images=()):
        result = subprocess.run([str(self.driver), str(self.app), str(output or self.output), reproduction, *map(str, images)],
                                capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr)
        if success:
            files = list(self.output.glob('*.zip'))
            self.assertEqual(len(files), 1)
            with zipfile.ZipFile(files[0]) as archive:
                return {name: archive.read(name) if name.startswith('attachments/') else archive.read(name).decode('utf-8')
                        for name in archive.namelist()}

    def image_fixture(self):
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
        path = self.case / 'private-image-name.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
                         + chunk(b'tEXt', b'Comment\0NEVER_KEEP_IMAGE_METADATA')
                         + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0' * 2) * 2)) + chunk(b'IEND', b''))
        return path

    def test_reproduction_and_reencoded_image_are_exported_without_original_metadata(self):
        image = self.image_fixture()
        original = image.read_bytes()
        entries = self.collect(reproduction='概率触发', images=[image])
        problem = json.loads(entries['problem.json'])
        self.assertEqual(problem['reproducibility'], '概率触发')
        self.assertEqual(problem['attachments'], ['attachments/image-01.png'])
        exported = entries['attachments/image-01.png']
        self.assertTrue(exported.startswith(b'\x89PNG'))
        self.assertNotIn(b'NEVER_KEEP_IMAGE_METADATA', exported)
        self.assertNotIn('private-image-name', entries['problem.json'])
        self.assertEqual(original, image.read_bytes())
        self.assertIn('概率触发', entries['诊断摘要.txt'])

    def test_thumbnail_file_drop_duplicate_removal_and_export(self):
        image = self.image_fixture()
        invalid = self.case / 'not-image.txt'
        invalid.write_text('not an image', encoding='utf-8')
        second = self.case / 'second.png'
        second.write_bytes(image.read_bytes())
        result = subprocess.run([str(self.driver), '--gallery', str(image), str(invalid), str(second),
                                 str(self.app), str(self.output)], capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(next(self.output.glob('*.zip'))) as archive:
            problem = json.loads(archive.read('problem.json'))
            self.assertEqual(problem['attachments'], ['attachments/image-01.png'])
            self.assertTrue(archive.read(problem['attachments'][0]).startswith(b'\x89PNG'))

    def test_invalid_or_excessive_images_do_not_produce_partial_archive(self):
        image = self.image_fixture()
        self.collect(success=False, images=[image] * 6)
        self.collect(success=False, images=[self.case / 'missing.png'])
        image.write_bytes(b'not an image')
        self.collect(success=False, images=[image])
        image.write_bytes(b'X' * (10 * 1024 * 1024 + 1))
        self.collect(success=False, images=[image])
        self.collect(success=False, reproduction='invalid')
        self.assertEqual(list(self.output.iterdir()), [])

    def test_discovery_validates_deduplicates_and_preserves_multiple_candidates(self):
        portable = self.case / 'portable'
        portable.mkdir()
        (portable / 'DD监控室CE-v0.5.exe').write_bytes(b'fixture')
        invalid = self.case / 'unrelated'
        invalid.mkdir()
        (invalid / 'unrelated.exe').write_bytes(b'fixture')
        result = subprocess.run([str(self.driver), '--discover', str(self.app), str(self.app / 'main.py'),
                                 str(portable), str(invalid), str(self.case / 'missing')], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        found = json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(found, [str(self.app), str(portable)])

    def test_nearby_results_finds_extracted_releases_without_scanning_unrelated_trees(self):
        tool = self.case / 'work/diagnostics-preview'
        tool.mkdir(parents=True)
        expected = []
        for relative in ('results/release-v0.5.2-final/DD监控室CE', 'result/DDMonitorCE'):
            app = self.case / relative
            app.mkdir(parents=True)
            (app / 'DD监控室CE.exe').write_bytes(b'fixture')
            expected.append(str(app))
        for relative in ('other/private/DDMonitorCE', 'results/cache/DDMonitorCE'):
            hidden = self.case / relative
            hidden.mkdir(parents=True)
            (hidden / 'DD监控室CE.exe').write_bytes(b'fixture')
        for initial in (str(tool), str(tool) + os.sep):
            result = subprocess.run([str(self.driver), '--nearby', initial], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(json.loads(result.stdout.decode('utf-8'))), set(expected))

    def test_shared_dark_scrollbar_scrolls_clamps_and_resets(self):
        result = subprocess.run([str(self.driver), '--scroll'], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'scroll passed', result.stdout)

    def test_collects_version_configuration_plugins_and_only_selected_logs(self):
        self.put('ddm-build.json', '\ufeff' + json.dumps({'version': '0.5.2', 'platform': 'windows-x64'}))
        self.put('RELEASE-v0.5.2.md', '# 0.5.2 更新\n敏感正文不收集')
        self.put('ddm-program-inventory.json', json.dumps({'version': '0.5.2', 'files': ['main.py', 'missing.dll', '../outside.txt']}))
        config = {'settings': {'decode_mode': 'auto', 'recording_dir': r'C:\Users\private-person\Videos'},
                  'rooms': [{'room_id': '123', 'name': '测试主播'}], 'plugins_enabled': ['test_plugin'],
                  'plugins': {'test_plugin': {'unusual_credential': 'private-plugin-987'}},
                  'nested': {'access_token': 'private-token-123', 'password': 'private-pass-456'}}
        self.put('utils/config.json', json.dumps(config, ensure_ascii=False))
        self.put('utils/config.json.bak', json.dumps({'settings': {'cookie': 'backup-secret-789'}}))
        self.put('utils/accounts/login.json', 'NEVER_READ_ACCOUNT')
        self.put('plugins_user/test_plugin/plugin.json', json.dumps({'id': 'test_plugin', 'version': '1.2.3', 'secret': 'NEVER_COPY_MANIFEST'}))
        self.put('logs/ddm-2026-10-26.log', 'Traceback\nQt render failed 0xC0000005\nCookie: hidden-cookie\n'
                 'note private-plugin-987 private-token-123 backup-secret-789\n'
                 'url https://example.com/live?sign=NEVER_KEEP_QUERY\nC:\\Users\\private-person\\app\\main.py\n')
        self.put('logs/chat.log', 'NEVER_READ_CHAT')
        self.put('plugins_user/_danmaku_log/123.log', 'NEVER_READ_DANMAKU')
        before = {str(p.relative_to(self.app)): hashlib.sha256(p.read_bytes()).digest()
                  for p in self.app.rglob('*') if p.is_file()}
        entries = self.collect()
        text = '\n'.join(entries.values())
        for private in ('private-plugin-987', 'private-token-123', 'private-pass-456', 'backup-secret-789',
                        'private-person', 'hidden-cookie', 'NEVER_', 'sign='):
            self.assertNotIn(private, text)
        data = json.loads(entries['config/current.json'])
        self.assertEqual(data['settings']['decode_mode'], 'auto')
        self.assertEqual(data['rooms'][0]['room_id'], '123')
        self.assertEqual(data['plugins_enabled'], ['test_plugin'])
        self.assertIn('0xC0000005', text)
        software = json.loads(entries['software.json'])
        self.assertEqual(software['ddm-build.json']['version'], '0.5.2')
        self.assertEqual(software['inventory_missing'], ['missing.dll'])
        main = next(row for row in software['files'] if row['file'] == 'main.py')
        self.assertEqual(main['sha256'], hashlib.sha256((self.app / 'main.py').read_bytes()).hexdigest())
        self.assertEqual(json.loads(entries['plugins.json']), [{'id': 'test_plugin', 'version': '1.2.3'}])
        after = {str(p.relative_to(self.app)): hashlib.sha256(p.read_bytes()).digest()
                 for p in self.app.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_corrupt_config_and_missing_logs_still_produce_package_without_raw_content(self):
        self.put('utils/config.json', '{broken: "NEVER_INCLUDE_INVALID_RAW"')
        self.put('ddm-build.json', '{broken metadata')
        entries = self.collect()
        self.assertEqual(json.loads(entries['config/current.json'])['status'], 'unreadable_or_invalid')
        self.assertNotIn('NEVER_INCLUDE_INVALID_RAW', '\n'.join(entries.values()))
        self.assertTrue(json.loads(entries['collection.json'])['warnings'])
        self.assertIn('system.json', entries)

    def test_oversized_config_and_log_limits(self):
        self.put('utils/config.json', 'X' * (8 * 1024 * 1024 + 1))
        for index in range(7):
            self.put(f'logs/ddm-2026-10-{index + 10:02}.log', 'X' * (2 * 1024 * 1024 + 10))
        entries = self.collect()
        logs = [text for name, text in entries.items() if name.startswith('logs/')]
        self.assertEqual(len(logs), 5)
        self.assertTrue(all(len(text) <= 2 * 1024 * 1024 for text in logs))
        self.assertIn('文件过大', entries['collection.json'])

    def test_linked_config_directory_is_skipped(self):
        outside = self.case / 'private'
        outside.mkdir()
        (outside / 'config.json').write_text('{"private":"NEVER_FOLLOW_LINK"}', encoding='utf-8')
        # Directory junctions do not require symlink privileges on Windows.
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(self.app / 'utils'), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        entries = self.collect()
        self.assertNotIn('NEVER_FOLLOW_LINK', '\n'.join(entries.values()))
        self.assertIn('跳过链接', entries['collection.json'])

    def test_invalid_software_directory_and_unwritable_destination(self):
        (self.app / 'main.py').unlink()
        self.collect(success=False)
        self.put('main.py', '# fixture')
        blocked = self.case / 'not-a-directory'
        blocked.write_text('preserve', encoding='utf-8')
        self.collect(success=False, output=blocked)
        self.assertEqual(blocked.read_text(encoding='utf-8'), 'preserve')
        self.assertEqual(list(self.output.iterdir()), [])

    def test_gui_compiles_without_qt_or_python_and_has_windows_subsystem(self):
        executable = self.base / 'DDMonitorDiagnostics.exe'
        self.compile(executable, [ROOT / 'tools/diagnostics/Collector.cs', ROOT / 'tools/diagnostics/Program.cs'], gui=True)
        image = executable.read_bytes()
        pe = int.from_bytes(image[0x3c:0x40], 'little')
        subsystem = int.from_bytes(image[pe + 24 + 68:pe + 24 + 70], 'little')
        self.assertEqual(subsystem, 2)  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        self.assertNotIn(b'PySide6', image)


if __name__ == '__main__':
    unittest.main()
