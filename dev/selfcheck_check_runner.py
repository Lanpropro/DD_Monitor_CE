"""检查分类入口、失败退出码、隔离进程、超时和工具目录；不启动 Qt 或联网。"""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev import run_checks as runner
from dev.checks import bootstrap


class CheckRunnerTests(unittest.TestCase):
    def test_catalog_has_explicit_modes_and_a_dependency_free_default(self):
        suites = runner.load_suites()
        self.assertEqual(set(suites), {'repository', 'smoke', 'offline', 'native', 'live'})
        self.assertEqual(suites['repository']['scripts'], [
            'selfcheck_repository_files', 'selfcheck_project_workflow',
            'selfcheck_repository_map', 'selfcheck_check_runner',
            'selfcheck_readme', 'selfcheck_appearance_design',
            'selfcheck_customization_plan', 'selfcheck_website_plan'])
        for name in suites['repository']['scripts']:
            source = (runner.ROOT / 'dev' / (name + '.py')).read_text(encoding='utf-8')
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(not item.name.startswith('PySide6') for item in node.names))
                elif isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or '').startswith('PySide6'))

    def test_registered_checks_do_not_force_successful_process_exit(self):
        for suite in runner.load_suites().values():
            for script in suite['scripts']:
                tree = ast.parse((runner.ROOT / 'dev' / (script + '.py')).read_text(encoding='utf-8-sig'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotEqual(ast.unparse(node.func), 'os._exit', script)

    def test_smoke_covers_core_areas_with_offline_isolation(self):
        suite = runner.load_suites()['smoke']
        self.assertEqual(suite['mode'], 'offline')
        self.assertEqual(suite['scripts'], [
            'selfcheck_general_settings', 'selfcheck_drag_lifecycle',
            'selfcheck_player_lifetime',
            'selfcheck_main_notices', 'selfcheck_notification_center', 'selfcheck_layout_16',
            'selfcheck_bili_plugin_boundary', 'selfcheck_plugin_contract', 'selfcheck_frequent_sort'])
        workflow = (runner.ROOT / '.github/workflows/repository-checks.yml').read_text(encoding='utf-8')
        for text in ('name: Functional smoke', 'python -m pip install -r requirements.txt',
                     'libmpv-SOURCE.json', '$source.sha256', '$source.dll_sha256',
                     'python dev/run_checks.py --suite smoke --timeout 120'):
            self.assertIn(text, workflow)

    def test_shared_scripts_require_the_same_isolation_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            catalog = Path(temp) / 'suites.json'
            suites = {'a': {'mode': 'offline', 'scripts': ['selfcheck_bili_plugin_boundary']},
                      'b': {'mode': 'offline', 'scripts': ['selfcheck_bili_plugin_boundary']}}
            with patch.object(runner, 'CATALOG', catalog):
                catalog.write_text(json.dumps(suites), encoding='utf-8')
                self.assertEqual(len(runner.load_suites()), 2)
                suites['b']['mode'] = 'live'
                catalog.write_text(json.dumps(suites), encoding='utf-8')
                with self.assertRaises(ValueError):
                    runner.load_suites()
                suites['b'] = {'mode': 'offline', 'scripts': ['selfcheck_bili_plugin_boundary'] * 2}
                catalog.write_text(json.dumps(suites), encoding='utf-8')
                with self.assertRaises(ValueError):
                    runner.load_suites()

    def test_contribution_matrix_uses_registered_or_existing_checks(self):
        source = (runner.ROOT / 'CONTRIBUTING.md').read_text(encoding='utf-8')
        matrix = source.split('### 改动区域 → 必跑测试', 1)[1].split('## 本机资料与发布', 1)[0]
        registered = {script for suite in runner.load_suites().values() for script in suite['scripts']}
        for script in re.findall(r'--script\s+(\w+)', matrix):
            self.assertIn(script, registered)
        for script in re.findall(r'python dev/(\w+\.py)', matrix):
            self.assertTrue((runner.ROOT / 'dev' / script).is_file(), script)
        for area in ('设置', '通知', '布局', '弹幕', '插件', '录制', '播放器'):
            self.assertIn('| ' + area, matrix)

    def test_offline_network_guard_allows_only_loopback(self):
        denied = []
        for host in ('localhost', '127.0.0.1', '::1'):
            bootstrap.require_local_network('socket.getaddrinfo', (host,), denied)
            bootstrap.require_local_network('socket.connect', (None, (host, 80)), denied)
        self.assertFalse(denied)
        for event, arguments in (('socket.getaddrinfo', ('example.invalid',)),
                                  ('socket.gethostbyname', ('example.invalid',)),
                                  ('socket.gethostbyaddr', ('203.0.113.1',)),
                                  ('socket.getnameinfo', (('203.0.113.1', 80),)),
                                  ('socket.connect', (None, ('203.0.113.1', 80))),
                                  ('socket.sendto', (None, ('203.0.113.1', 80))),
                                  ('socket.sendmsg', (None, ('203.0.113.1', 80)))):
            with self.assertRaises(RuntimeError):
                bootstrap.require_local_network(event, arguments, denied)
        self.assertEqual(len(denied), 7)

    def test_caught_external_network_attempt_still_fails_offline_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dev').mkdir()
            (root / 'dev/fixture.py').write_text(
                "import socket\ntry:\n    socket.getaddrinfo('example.invalid', 80)\nexcept RuntimeError:\n    pass\n",
                encoding='utf-8')
            with patch.object(runner, 'ROOT', root):
                result = runner.run_script('fixture', 'offline', [], root, 10)
            self.assertNotEqual(result['exit_code'], 0)
            self.assertIn('external network access', Path(result['log']).read_text(encoding='utf-8'))

    def test_bootstrap_preserves_arguments_imports_and_failure_code(self):
        with tempfile.TemporaryDirectory(prefix='ddm check runner ') as temp:
            directory = Path(temp)
            (directory / 'sibling.py').write_text('VALUE = 17\n', encoding='utf-8')
            script = directory / 'check.py'
            script.write_text("import sibling, sys\nprint(sibling.VALUE, sys.argv[1])\nraise SystemExit(19)\n", encoding='utf-8')
            result = subprocess.run([sys.executable, str(runner.BOOTSTRAP), str(script), 'two words'],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 19, result.stderr)
            self.assertIn('17 two words', result.stdout)

    def test_script_gets_isolated_environment_and_logs_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'dev').mkdir()
            (root / 'dev/fixture.py').write_text(
                "import os,sys\nprint(os.environ['DDM_NO_SAVE'], os.environ['QT_QPA_PLATFORM'], sys.argv[1])\nraise SystemExit(7)\n",
                encoding='utf-8')
            with patch.object(runner, 'ROOT', root):
                result = runner.run_script('fixture', 'offline', ['payload'], root, 10)
            self.assertEqual(result['exit_code'], 7)
            self.assertIn('1 offscreen payload', Path(result['log']).read_text(encoding='utf-8'))

    def test_timeout_is_a_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
                runner.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 1)):
            result = runner.run_script('fixture', 'repository', [], Path(temp), 1)
        self.assertEqual(result['exit_code'], 'timeout')

    def test_default_continues_after_failure_and_writes_summary(self):
        suites = {'repository': {'mode': 'repository', 'scripts': ['first', 'second']}}
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, 'ROOT', Path(temp)), \
                patch.object(runner, 'load_suites', return_value=suites), \
                patch.object(runner, 'run_script', side_effect=[
                    {'script': 'first', 'exit_code': 3}, {'script': 'second', 'exit_code': 0}]) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main([]), 1)
            self.assertEqual(run.call_count, 2)
            summary = next(Path(temp).glob('work/checks/*/summary.json'))
            self.assertEqual([item['exit_code'] for item in json.loads(summary.read_text())], [3, 0])

    def test_invalid_or_implicit_live_selection_never_runs(self):
        for arguments in (['--suite', 'missing'], ['--script', 'missing'],
                          ['--suite', 'live'], ['--script', 'check_live_restore'],
                          ['--timeout', '0'], ['--suite', 'offline', '--', 'extra']):
            with self.subTest(arguments=arguments), patch.object(runner.sys, 'platform', 'win32'), \
                    patch.object(runner, 'run_script') as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    runner.main(arguments)
                self.assertEqual(raised.exception.code, 2)
                run.assert_not_called()

    def test_listing_never_starts_processes(self):
        with patch.object(runner, 'run_script') as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(['--list']), 0)
            self.assertIn('native:', output.getvalue())
            run.assert_not_called()

    def test_entrypoint_outputs_utf8_with_a_legacy_console_encoding(self):
        env = dict(os.environ, PYTHONIOENCODING='cp1252')
        result = subprocess.run([sys.executable, str(runner.ROOT / 'dev/run_checks.py'), '--list'],
                                env=env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('仓库规范', result.stdout.decode('utf-8'))

    def test_explicit_live_arguments_are_forwarded(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(runner, 'ROOT', Path(temp)), \
                patch.object(runner.sys, 'platform', 'win32'), \
                patch.object(runner, 'run_script', return_value={'exit_code': 0}) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            # Load catalog paths before replacing the repository root with a fixture.
            with patch.object(runner, 'load_suites', return_value={
                    'live': {'mode': 'live', 'scripts': ['check_live_restore']}}):
                self.assertEqual(runner.main(['--script', 'check_live_restore', '--', '6']), 0)
            self.assertEqual(run.call_args.args[:3], ('check_live_restore', 'live', ['6']))

    def test_cmd_delegates_and_propagates_exit_status(self):
        source = (runner.ROOT / 'dev/run-checks.cmd').read_text(encoding='utf-8-sig')
        self.assertIn('run_checks.py" %*', source)
        self.assertIn('exit /b %errorlevel%', source)
        self.assertNotIn('selfcheck_*.py', source)
        self.assertNotIn('pause', source)
        self.assertNotIn('libvlc.dll', source)
        self.assertIn('*.cmd text eol=crlf', (runner.ROOT / '.gitattributes').read_text())

    def test_every_tracked_check_has_a_topic_index(self):
        tracked = subprocess.check_output(['git', 'ls-files', 'dev'], cwd=runner.ROOT, text=True).splitlines()
        checks = {Path(path).name for path in tracked if Path(path).name.startswith(('selfcheck_', 'check_'))
                  and path.endswith('.py')}
        index = (runner.ROOT / 'dev/checks/README.md').read_text(encoding='utf-8')
        listed = re.findall(r'\]\(\.\./((?:selfcheck_|check_)[^/)]+\.py)\)', index)
        self.assertEqual(set(listed), checks)
        self.assertEqual(len(listed), len(set(listed)))
        rows = dict(re.findall(r'\[([^]]+)\]\(\.\./(?:selfcheck_|check_)[^/)]+\.py\) \| ([^\n]+)', index))
        for suite, settings in runner.load_suites().items():
            for script in settings['scripts']:
                self.assertIn(f'`{suite}`', rows[script])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows CMD wrapper')
    def test_real_cmd_handles_spaced_paths_and_failure_status(self):
        with tempfile.TemporaryDirectory(prefix='ddm runner spaces ') as temp:
            root = Path(temp)
            (root / 'dev/checks').mkdir(parents=True)
            for name in ('run-checks.cmd', 'run_checks.py'):
                shutil.copyfile(runner.ROOT / 'dev' / name, root / 'dev' / name)
            (root / 'dev/checks/suites.json').write_text(json.dumps({
                'repository': {'mode': 'repository', 'description': 'fixture', 'scripts': []}}), encoding='utf-8')
            env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'])
            for arguments, expected in ((['--list'], 0), (['--suite', 'missing'], 2)):
                result = subprocess.run(['cmd', '/d', '/c', 'dev\\run-checks.cmd', *arguments],
                                        cwd=root, env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
