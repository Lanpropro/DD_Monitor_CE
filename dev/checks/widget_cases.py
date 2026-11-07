"""Run complete Qt-window cases in fresh application processes, retaining every result."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import unittest


def run_widget_cases(case, script, arguments=()):
    names = unittest.defaultTestLoader.getTestCaseNames(case)
    bootstrap = Path(__file__).with_name('bootstrap.py')
    env = dict(os.environ)
    env.setdefault('PYTHONFAULTHANDLER', '1')

    def run(name):
        command = [sys.executable, '-u', str(bootstrap), str(script),
                   case.__name__ + '.' + name, *arguments]
        try:
            result = subprocess.run(command, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                    errors='replace', timeout=60)
            return name, result.returncode, result.stdout
        except subprocess.TimeoutExpired as error:
            output = error.stdout or ''
            if isinstance(output, bytes):
                output = output.decode('utf-8', errors='replace')
            return name, 1, output + '\nTIMEOUT: ' + name + '\n'

    failed = []
    # Native cases share desktop focus; keep their original serial order.
    workers = 1 if '--native' in arguments else 2
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, code, output in pool.map(run, names):
            print(output, end='', flush=True)
            if code:
                failed.append(name)
                print('FAILED:', name, 'exit=', code, flush=True)
    return int(bool(failed))
