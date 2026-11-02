"""Compile and exercise the independent Windows collector on temporary fixtures only."""
import hashlib
import json
import os
import random
import runpy
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
        cls.compile(cls.driver, [ROOT / 'tools/diagnostics/Collector.cs', ROOT / 'tools/diagnostics/NativeDependencies.cs', ROOT / 'tools/diagnostics/Program.cs', ROOT / 'dev/diagnostics_tests.cs'])

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

    def test_independent_user_data_folder_is_used_for_config_plugins_and_logs(self):
        location_file = runpy.run_path(str(ROOT / 'ddm/data_paths.py'))['location_file']
        data = self.case / '用户数据'
        (data / 'utils').mkdir(parents=True)
        (data / 'utils/config.json').write_text('{"settings":{"default_volume":37}}', encoding='utf-8')
        self.put('utils/config.json', '{"settings":{"default_volume":12}}')
        (data / 'logs').mkdir()
        (data / 'logs/ddm-2026-10-29.log').write_text('external data log', encoding='utf-8')
        plugin = data / 'plugins_user/test_plugin'
        plugin.mkdir(parents=True)
        (plugin / 'plugin.json').write_text('{"version":"9.9"}', encoding='utf-8')
        home = self.case / 'user-home'
        location = location_file(self.app, home)
        location.parent.mkdir(parents=True)
        location.write_text(json.dumps({'root': str(data)}), encoding='utf-8')
        result = subprocess.run([str(self.driver), '--data-location', str(self.app), str(self.output), str(home)],
                                capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(next(self.output.glob('*.zip'))) as archive:
            self.assertEqual(json.loads(archive.read('config/current.json'))['settings']['default_volume'], 37)
            self.assertIn(b'external data log', archive.read('logs/ddm-2026-10-29.log'))
            self.assertIn(b'9.9', archive.read('plugins.json'))

    def test_rotated_and_crash_logs_are_included_with_platform_summary(self):
        self.put('logs/ddm-crash.log', 'fixture native crash')
        self.put('logs/ddm-2026-10-29.log.1', '[平台诊断] 阶段=source_request fixture rotated')
        self.put('logs/ddm.log', 'fixture PR61 compatible')
        self.put('logs/unrelated.log.1', 'PRIVATE_UNRELATED')
        entries = self.collect()
        self.assertIn('fixture native crash', entries['logs/ddm-crash.log'])
        self.assertIn('fixture rotated', entries['logs/ddm-2026-10-29.log.1'])
        self.assertIn('fixture PR61 compatible', entries['logs/ddm.log'])
        self.assertIn('source_request', entries['platform-diagnostics.json'])
        self.assertNotIn('PRIVATE_UNRELATED', str(entries))

    def test_recording_logs_are_bounded_redacted_and_keep_expiry_evidence(self):
        folder = self.case / 'recordings'
        parts = folder / '.ddm-parts'
        parts.mkdir(parents=True)
        self.put('utils/config.json', json.dumps({'settings': {'recording_dir': str(folder)}}))
        for index in range(7):
            path = parts / f'private-streamer_{index}.log'
            path.write_text('X' * (2 * 1024 * 1024 + 10) +
                '\nHTTP error 403 Forbidden\nhttps://cdn.test/live.flv?expires=1793320572&sign=PRIVATE_SIGN\n'
                'Cookie: PRIVATE_COOKIE\n', encoding='utf-8')
            os.utime(path, (index + 1000, index + 1000))
        (parts / 'video.mkv').write_text('NEVER_READ_VIDEO', encoding='utf-8')
        entries = self.collect()
        logs = [v for k, v in entries.items() if k.startswith('recording/')]
        self.assertEqual(len(logs), 5)
        self.assertTrue(all(len(v.encode('utf-8')) <= 2 * 1024 * 1024 for v in logs))
        combined = str(entries)
        for secret in ('PRIVATE_SIGN', 'PRIVATE_COOKIE', 'NEVER_READ_VIDEO', 'private-streamer'):
            self.assertNotIn(secret, combined)
        report = json.loads(entries['recording-diagnostics.json'])
        self.assertEqual(report['status'], 'observed')
        self.assertTrue(all(v['http_403'] for v in report['files']))
        self.assertEqual(report['files'][0]['expires_unix_seconds'], ['1793320572'])

    def test_missing_recording_directory_does_not_break_diagnostics(self):
        self.put('utils/config.json', json.dumps({'settings': {'recording_dir': str(self.case / 'missing')}}))
        entries = self.collect()
        self.assertEqual(json.loads(entries['recording-diagnostics.json'])['status'], 'missing')

    def test_linked_recording_log_directory_is_not_followed(self):
        folder = self.case / 'recordings'
        folder.mkdir()
        outside = self.case / 'unrelated'
        outside.mkdir()
        (outside / 'private.log').write_text('NEVER_FOLLOW_RECORDING_LINK', encoding='utf-8')
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(folder / '.ddm-parts'), str(outside)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.put('utils/config.json', json.dumps({'settings': {'recording_dir': str(folder)}}))
        entries = self.collect()
        self.assertNotIn('NEVER_FOLLOW_RECORDING_LINK', str(entries))
        self.assertEqual(json.loads(entries['recording-diagnostics.json'])['status'], 'unavailable')

    def test_platform_diagnostics_summarize_redacted_existing_logs(self):
        self.put('logs/ddm-2026-10-26.log', '\n'.join([
            '[插件 domestic_live] [Issue13-test3] 阶段=page_response HTTP=200 类型=text/html',
            '[插件 domestic_live] [Issue13-test3] 阶段=player_error 类别=HTTP_403',
            '[画质档位] huya:199300: 原画(10000)',
            '[取流失败] 连接失败',
            '[取流失败] token=PRIVATE_DIAGNOSTIC_TOKEN https://cdn.test/live?secret=PRIVATE_URL',
            'unrelated line']))
        entries = self.collect()
        report = json.loads(entries['platform-diagnostics.json'])
        self.assertEqual(report['status'], 'observed')
        self.assertEqual(report['counts'], {'page_response': 1, 'player_error': 1,
                                           'source_ready': 1, 'failure_summary': 1})
        self.assertEqual(len(report['events']), 4)
        self.assertEqual(report['events'][0]['line'], 1)
        self.assertNotIn('PRIVATE_DIAGNOSTIC_TOKEN', entries['platform-diagnostics.json'])
        self.assertNotIn('PRIVATE_URL', entries['platform-diagnostics.json'])
        self.assertIn('platform-diagnostics.json', entries['诊断摘要.txt'])

    def test_huya_transport_and_cdn_recovery_are_included(self):
        self.put('logs/ddm-2026-10-27.log', '\n'.join([
            '[平台诊断] 阶段=playback_session 房间=huya:123 会话=fixture 路径=hls_relay CDN=cdn.test',
            '[平台诊断] 阶段=hls_request 房间=huya:123 会话=fixture resource=media status=403 local=False',
            '[平台诊断] 阶段=hls_request 房间=huya:123 会话=fixture status=503 local=True error=refresh_required',
            '[插件 domestic_live] [平台诊断] 阶段=source_rejected 房间=huya:123 CDN=cdn.test',
            '[插件 domestic_live] [平台诊断] 阶段=source_selected 房间=huya:123 CDN=next.test']))
        report = json.loads(self.collect()['platform-diagnostics.json'])
        self.assertEqual(report['counts'], {'playback_session': 1, 'hls_request': 2,
                                           'source_rejected': 1, 'source_selected': 1})
        self.assertIn('local=True', report['events'][2]['text'])

    def test_platform_diagnostics_missing_logs_do_not_claim_success(self):
        entries = self.collect()
        report = json.loads(entries['platform-diagnostics.json'])
        self.assertEqual(report['status'], 'not_recorded')
        self.assertEqual(report['events'], [])

    def test_platform_summary_keeps_latest_day_when_old_logs_fill_limit(self):
        self.put('logs/ddm-2026-10-25.log', '\n'.join(
            '[画质档位] huya:1001: old-' + str(i) for i in range(1100)))
        self.put('logs/ddm-2026-10-26.log',
                 '[插件 domestic_live] [平台诊断] 阶段=player_error 类别=HTTP_403')
        entries = self.collect()
        report = json.loads(entries['platform-diagnostics.json'])
        self.assertEqual(len(report['events']), 1000)
        self.assertEqual(report['events'][-1]['log'], 'logs/ddm-2026-10-26.log')
        self.assertEqual(report['events'][-1]['stage'], 'player_error')
        self.assertEqual(report['counts']['source_ready'], 1100)

    def native_fixture(self, dependency='kernel32.dll', symbol='GetCurrentProcessId', x64=True):
        """Minimal inert PE DLL: no entry point, one import, no application code."""
        data = bytearray(0x800)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 0x80)
        data[0x80:0x84] = b'PE\0\0'
        optional_size = 240 if x64 else 224
        struct.pack_into('<HHIIIHH', data, 0x84, 0x8664 if x64 else 0x14c, 1, 0, 0, 0, optional_size, 0x2022)
        optional = 0x98
        struct.pack_into('<H', data, optional, 0x20b if x64 else 0x10b)
        struct.pack_into('<Q' if x64 else '<I', data, optional + (24 if x64 else 28), 0x180000000 if x64 else 0x10000000)
        struct.pack_into('<II', data, optional + 32, 0x1000, 0x200)
        struct.pack_into('<HH', data, optional + 40, 6, 0)
        struct.pack_into('<HH', data, optional + 48, 6, 0)
        struct.pack_into('<II', data, optional + 56, 0x2000, 0x200)
        struct.pack_into('<H', data, optional + 68, 3)
        directory = optional + (112 if x64 else 96)
        struct.pack_into('<I', data, directory - 4, 16)
        struct.pack_into('<II', data, directory + 8, 0x1000, 40)
        struct.pack_into('<II', data, directory + 40, 0x1400, 12)
        struct.pack_into('<IIHH', data, 0x600, 0x1000, 12, 0, 0)
        section = optional + optional_size
        data[section:section + 8] = b'.rdata\0\0'
        struct.pack_into('<IIII', data, section + 8, 0x600, 0x1000, 0x600, 0x200)
        struct.pack_into('<I', data, section + 36, 0xc0000040)
        struct.pack_into('<IIIII', data, 0x200, 0x1200, 0, 0, 0x1100, 0x1240)
        encoded = dependency.encode('ascii') + b'\0'
        data[0x300:0x300 + len(encoded)] = encoded
        struct.pack_into('<Q' if x64 else '<I', data, 0x400, 0x1300)
        struct.pack_into('<Q' if x64 else '<I', data, 0x440, 0x1300)
        encoded = symbol.encode('ascii') + b'\0'
        data[0x502:0x502 + len(encoded)] = encoded
        dll = self.app / '_internal/libmpv-2.dll'
        dll.parent.mkdir(exist_ok=True)
        dll.write_bytes(data)
        return dll

    def native_check(self, mode='--native-probe'):
        result = subprocess.run([str(self.driver), mode, str(self.app)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.decode('utf-8-sig'))

    def test_native_missing_library_and_invalid_pe_are_reported(self):
        self.assertEqual(self.native_check()['status'], 'not_present')
        self.put('_internal/libmpv-2.dll', 'not a DLL')
        self.assertEqual(self.native_check()['status'], 'invalid_pe')

    def test_native_missing_dependency_has_error_and_summary(self):
        dll = self.native_fixture(dependency='DDM_fixture_missing_913bed.dll')
        before = dll.read_bytes()
        entries = self.collect()
        report = json.loads(entries['native-dependencies.json'])
        self.assertEqual(report['status'], 'load_failed')
        self.assertEqual(report['win32_error'], 126)
        self.assertEqual(report['dependencies'][0]['status'], 'load_failed')
        self.assertIn('DDM_fixture_missing_913bed.dll', entries['诊断摘要.txt'])
        self.assertNotIn(str(self.app), entries['native-dependencies.json'])
        self.assertEqual(dll.read_bytes(), before)

    def test_native_missing_export_and_architecture_mismatch(self):
        self.native_fixture(symbol='DDM_fixture_missing_export_913bed')
        report = self.native_check()
        self.assertEqual(report['status'], 'load_failed')
        self.assertEqual(report['dependencies'][0]['missing_exports'], ['DDM_fixture_missing_export_913bed'])
        self.native_fixture(x64=False)
        self.assertEqual(self.native_check()['status'], 'architecture_mismatch')

    def test_native_success_and_timeout_still_allow_collection(self):
        self.native_fixture()
        report = self.native_check()
        self.assertEqual(report['status'], 'loaded')
        self.assertEqual(report['dependencies'][0]['status'], 'loaded')
        self.assertEqual(self.native_check('--native-timeout')['status'], 'timeout')
        entries = self.collect()
        self.assertEqual(json.loads(entries['native-dependencies.json'])['status'], 'loaded')

    def test_native_initialization_hang_is_terminated_in_child(self):
        dll = self.native_fixture()
        data = bytearray(dll.read_bytes())
        struct.pack_into('<I', data, 0x98 + 16, 0x1500)
        struct.pack_into('<I', data, 0x98 + 240 + 36, 0xe0000040)
        data[0x700:0x702] = b'\xeb\xfe'  # DllMain deliberately loops inside the child.
        dll.write_bytes(data)
        self.assertEqual(self.native_check('--native-short')['status'], 'timeout')
        self.assertEqual(dll.read_bytes(), bytes(data))

    def test_windowed_native_helper_outputs_json_without_console(self):
        self.native_fixture()
        executable = self.case / 'windowed.exe'
        self.compile(executable, [ROOT / 'tools/diagnostics/Collector.cs',
                                 ROOT / 'tools/diagnostics/NativeDependencies.cs',
                                 ROOT / 'tools/diagnostics/Program.cs'], gui=True)
        result = subprocess.run([str(executable), '--native-probe', str(self.app)], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout.decode('utf-8'))['status'], 'loaded')

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

    def test_larger_images_fit_new_limits_and_combined_limit_still_applies(self):
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
        width, height = 3000, 2000
        pixels = random.Random(42).randbytes(width * height * 3)
        rows = b''.join(b'\0' + pixels[row * width * 3:(row + 1) * width * 3] for row in range(height))
        png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
        self.assertGreater(len(png), 10 * 1024 * 1024)
        self.assertLess(len(png), 20 * 1024 * 1024)
        images = [self.case / f'noise-{index}.png' for index in range(3)]
        for image in images:
            image.write_bytes(png)
        entries = self.collect(images=images[:2])
        total = sum(len(data) for name, data in entries.items() if name.startswith('attachments/'))
        self.assertGreater(total, 25 * 1024 * 1024)
        self.assertLess(total, 50 * 1024 * 1024)
        self.collect(success=False, images=images)
        self.assertEqual(len(list(self.output.glob('*.zip'))), 1)

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
        image.write_bytes(b'X' * (20 * 1024 * 1024 + 1))
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

    def test_feedback_guidance_fits_minimum_window_size(self):
        result = subprocess.run([str(self.driver), '--layout', str(self.app)], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'layout passed', result.stdout)

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
        self.compile(executable, [ROOT / 'tools/diagnostics/Collector.cs', ROOT / 'tools/diagnostics/NativeDependencies.cs', ROOT / 'tools/diagnostics/Program.cs'], gui=True)
        image = executable.read_bytes()
        pe = int.from_bytes(image[0x3c:0x40], 'little')
        subsystem = int.from_bytes(image[pe + 24 + 68:pe + 24 + 70], 'little')
        self.assertEqual(subsystem, 2)  # IMAGE_SUBSYSTEM_WINDOWS_GUI
        self.assertNotIn(b'PySide6', image)

    def test_gui_optional_exit_preserves_generated_package(self):
        result = subprocess.run([str(self.driver), '--auto-exit', str(self.app), str(self.output)],
                                capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b'auto-exit passed', result.stdout)

    def test_standalone_and_installer_use_the_same_independent_executable(self):
        standalone, bundle = self.case / 'standalone', self.case / 'bundle'
        for output, arguments in ((standalone, []), (bundle, ['-NoZip'])):
            result = subprocess.run(['powershell', '-NoProfile', '-File', str(ROOT / 'dev/build_diagnostics.ps1'),
                                     '-OutDir', str(output), *arguments], capture_output=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with zipfile.ZipFile(standalone / 'DDMonitorDiagnostics-v1.2.zip') as archive:
            self.assertEqual(set(archive.namelist()), {'DDMonitorDiagnostics.exe', '诊断工具说明.md'})
            for name in archive.namelist():
                self.assertEqual(archive.read(name), (standalone / name).read_bytes())
        self.assertEqual(set(p.name for p in bundle.iterdir()), {'DDMonitorDiagnostics.exe', '诊断工具说明.md'})
        metadata = runpy.run_path(str(ROOT / 'dev/build_setup.py'))
        version = metadata['VERSION']
        files = {metadata['DISPLAY_NAME'] + '.exe': b'fake app', 'ffmpeg.exe': b'fake recorder',
                 '_internal/libmpv-2.dll': b'fake runtime',
                 'ddm-build.json': json.dumps({'version': version, 'update_protocol': 1, 'platform': 'windows-x64'}).encode()}
        for name, data in files.items():
            target = bundle / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        selected = metadata['payload_files'](bundle)
        self.assertIn('DDMonitorDiagnostics.exe', selected)
        self.assertIn('诊断工具说明.md', selected)
        self.assertFalse(any(name.endswith('.zip') for name in selected))


if __name__ == '__main__':
    unittest.main()
