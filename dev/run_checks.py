"""按已审查的套件运行检查；默认只运行无需第三方依赖的仓库检查。"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'dev/checks/suites.json'
BOOTSTRAP = ROOT / 'dev/checks/bootstrap.py'


def load_suites():
    suites = json.loads(CATALOG.read_text(encoding='utf-8'))
    seen = set()
    for name, suite in suites.items():
        if suite['mode'] not in ('repository', 'offline', 'native', 'live'):
            raise ValueError(f'Unknown check mode: {name}')
        for script in suite['scripts']:
            if Path(script).name != script or script in seen or not (ROOT / 'dev' / (script + '.py')).is_file():
                raise ValueError(f'Invalid or duplicate check: {script}')
            seen.add(script)
    return suites


def run_script(script, mode, arguments, directory, timeout):
    env = dict(os.environ, DDM_NO_SAVE='1', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
               DDM_CHECK_MODE=mode)
    env['QT_QPA_PLATFORM'] = 'windows' if mode in ('native', 'live') else 'offscreen'
    logfile = directory / (script + '.log')
    command = [sys.executable, '-u', str(BOOTSTRAP), str(ROOT / 'dev' / (script + '.py')), *arguments]
    with logfile.open('w', encoding='utf-8') as output:
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 'timeout'
    return {'script': script, 'exit_code': code, 'log': str(logfile)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--suite')
    selection.add_argument('--script', help='套件中某个脚本的文件名，不含 .py')
    parser.add_argument('--list', action='store_true', help='只显示分类，不运行检查')
    parser.add_argument('--timeout', type=float, default=300, help='每个脚本的超时秒数')
    parser.add_argument('arguments', nargs=argparse.REMAINDER, help='-- 后的参数传给单项脚本')
    args = parser.parse_args(argv)
    suites = load_suites()
    if args.list:
        for name, suite in suites.items():
            print(f"{name}: {suite['description']}")
            for script in suite['scripts']:
                print(f'  {script}')
        print('其他专项脚本见 dev/checks/README.md，未纳入批量套件。')
        return 0
    if args.timeout <= 0:
        parser.error('--timeout 必须大于 0')
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    if arguments and not args.script:
        parser.error('脚本参数只能与 --script 一起使用')
    if args.script:
        selected = next((suite for suite in suites.values() if args.script in suite['scripts']), None)
        if selected is None:
            parser.error('脚本未纳入套件，请先检查分类说明')
        scripts = [args.script]
    else:
        selected = suites.get(args.suite or 'repository')
        if selected is None:
            parser.error('未知套件；使用 --list 查看可用分类')
        scripts = selected['scripts']
    if selected['mode'] in ('native', 'live') and sys.platform != 'win32':
        parser.error('该套件需要 Windows 原生窗口')
    if selected['mode'] == 'live' and not args.script:
        parser.error('真实直播请使用 --script 并明确传入房间参数，见分类说明')
    if selected['mode'] == 'live' and not arguments:
        parser.error('真实直播检查必须显式提供房间参数')
    directory = ROOT / 'work/checks' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory.mkdir(parents=True)
    results = []
    for script in scripts:
        result = run_script(script, selected['mode'], arguments, directory, args.timeout)
        results.append(result)
        print(f"{'PASS' if result['exit_code'] == 0 else 'FAIL'} {script}: {result['exit_code']}", flush=True)
        (directory / 'summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    failed = sum(result['exit_code'] != 0 for result in results)
    print(f'通过 {len(results) - failed}/{len(results)}；日志：{directory}', flush=True)
    return int(failed > 0)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
