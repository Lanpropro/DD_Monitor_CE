"""Load the isolated Match Sync source for the opt-in comparison process."""
from pathlib import Path


def install_plugin_source(manager_type, entry):
    entry = Path(entry)
    if not entry.is_file():
        raise FileNotFoundError(entry)
    load_module = manager_type._load_module

    def load(manager, name, path):
        return load_module(manager, name, str(entry) if name == 'match_sync' else path)

    manager_type._load_module = load
