"""Shared folder selection actions for adding rooms and importing follows."""
from .folder_icons import create_folder_dialog


def _add_folder_option(dialog, menu, folder_id, name):
    action = menu.addAction(name)
    action.setData(folder_id)
    action.setCheckable(True)
    action.setChecked(not folder_id)
    action.triggered.connect(lambda _checked=False: dialog._select_folder(action))
    return action


def _create_folder_for_dialog(dialog, folder_creator):
    folder_id, name = create_folder_dialog(dialog, folder_creator, dialog.folder_names)
    if not folder_id:
        return
    dialog.folder_names.add(name)
    action = _add_folder_option(dialog, dialog.folder_button.menu(), folder_id, name)
    dialog._select_folder(action)
