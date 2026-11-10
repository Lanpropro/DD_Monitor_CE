"""Launch an installed plugin's own worker without constructing the host UI."""
import importlib
from pathlib import Path
import sys
from types import ModuleType


def _module_path(directory, module):
    if not module.isidentifier():
        raise ValueError('Worker module must be a single Python identifier')
    directory = Path(directory).resolve()
    path = directory / (module + '.py')
    if not (directory / 'plugin.py').is_file() or not path.is_file():
        raise FileNotFoundError('Plugin entry or worker module is missing')
    return directory, path


def worker_command(plugin_file, module):
    """Return (program, arguments); the plugin owns QProcess and its protocol."""
    directory, _ = _module_path(Path(plugin_file).resolve().parent, module)
    arguments = ['--plugin-worker', str(directory), module]
    if not getattr(sys, 'frozen', False):
        arguments.insert(0, str(Path(__file__).resolve().parents[1] / 'main.py'))
    return sys.executable, arguments


def run_worker(directory, module):
    directory, path = _module_path(directory, module)
    # Relative sibling imports work without executing plugin.py/on_load or
    # discovering other installed plugins. No settings/account files are read.
    package = ModuleType('ddm_plugin_worker')
    package.__path__ = [str(directory)]
    package.__package__ = package.__name__
    sys.modules[package.__name__] = package
    sys.argv = [str(path)]
    worker = importlib.import_module(package.__name__ + '.' + module)
    return int(worker.run() or 0)
