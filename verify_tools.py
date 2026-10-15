"""Check quick-launch menu visibility, saved options and Windows launch targets."""
from pathlib import Path
import ctypes
from ctypes import wintypes
import os
import sys
import tempfile
from unittest.mock import call, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from desktop_pet import BehaviorSettingsDialog, DesktopPet


def run():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as temporary:
        settings = Path(temporary)/"settings.json"
        pet = DesktopPet(settings, start_timer=False)
        labels = ["메모장", "그림판", "계산기"]
        menu = QMenu()
        pet.populate_menu(menu)
        assert not pet.show_windows_tools
        assert not any(action.text() in labels for action in menu.actions())
        dialog = BehaviorSettingsDialog(pet)
        dialog.show_windows_tools.click()
        dialog.reject()
        assert not pet.show_windows_tools
        dialog = BehaviorSettingsDialog(pet)
        dialog.show_windows_tools.click()
        dialog.accept()
        assert pet.show_windows_tools
        restored = DesktopPet(settings, start_timer=False)
        assert restored.show_windows_tools
        restored.close()
        system = Path(os.environ.get("SystemRoot", r"C:\Windows"))/"System32"
        for character in ("zenith", "liberta"):
            pet.set_character(character)
            for menu in (QMenu(), pet.tray_menu):
                menu.clear()
                pet.populate_menu(menu)
                assert [action.text() for action in menu.actions()[:3]] == labels
                assert menu.actions()[3].isSeparator()
                with patch("desktop_pet.os.startfile") as launch:
                    for action in menu.actions()[:3]:
                        action.trigger()
                    assert launch.call_args_list == [call(str(system/"notepad.exe")),
                                                      call("ms-paint:"), call(str(system/"calc.exe"))]
        # Paint also supports a machine without its Store protocol registered.
        with patch("desktop_pet.os.startfile", side_effect=[OSError("No protocol"), None]) as launch:
            pet.launch_windows_tool("paint")
            assert launch.call_args_list == [call("ms-paint:"), call(str(system/"mspaint.exe"))]
        with patch("desktop_pet.os.startfile", side_effect=OSError("Unavailable")), \
                patch("desktop_pet.logging.exception"), patch.object(pet.tray, "showMessage") as notice:
            pet.launch_windows_tool("calculator")
            assert notice.call_count == 1 and "계산기" in notice.call_args.args[1]
        with patch("desktop_pet.os.startfile"), patch.object(pet,"restore_on_top") as restore:
            pet.launch_windows_tool("notepad")
            app.processEvents()
            assert restore.call_count >= 1
        dialog = BehaviorSettingsDialog(pet)
        dialog.show()
        app.processEvents()
        Path("artifacts").mkdir(exist_ok=True)
        dialog.grab().save("artifacts/windows-tools-settings.png")
        dialog.reject()
        menu = QMenu()
        pet.populate_menu(menu)
        menu.show()
        app.processEvents()
        menu.grab().save("artifacts/windows-tools-menu.png")
        menu.hide()
        dialog = BehaviorSettingsDialog(pet)
        dialog.show_windows_tools.click()
        dialog.reject()
        assert pet.show_windows_tools
        dialog = BehaviorSettingsDialog(pet)
        dialog.show_windows_tools.click()
        dialog.accept()
        menu = QMenu()
        pet.populate_menu(menu)
        assert not any(action.text() in labels for action in menu.actions())
        restored = DesktopPet(settings, start_timer=False)
        assert not restored.show_windows_tools
        restored.close()
        # A newly opened topmost app can overtake the pet. Reassert its place
        # without changing which window receives keyboard input.
        if sys.platform == "win32":
            pet.show()
            other = QWidget(None, Qt.WindowType.WindowStaysOnTopHint)
            other.resize(500, 300); other.move(pet.pos()); other.show(); other.raise_()
            app.processEvents()
            user = ctypes.WinDLL("user32")
            user.GetForegroundWindow.restype = wintypes.HWND
            foreground = int(user.GetForegroundWindow() or 0)
            pet.restore_on_top()
            handles = []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
            @callback_type
            def collect(handle, _):
                handles.append(int(handle))
                return True
            user.EnumWindows.argtypes = [callback_type,wintypes.LPARAM]
            user.EnumWindows(collect,0)
            assert handles.index(int(pet.winId())) < handles.index(int(other.winId()))
            assert int(user.GetForegroundWindow() or 0) == foreground
            other.close()
        pet.quit_pet()
    print("PASS: tools off/on, Save/Cancel, both character/tray menu ordering and saved state.")
    print("PASS: menu actions launch the correct Windows tools, Store/native Paint fallback,")
    print("      and unavailable-tool feedback (launches mocked to keep other apps closed).")
    print("PASS: the pet returns above a newer topmost window without taking keyboard focus.")


if __name__ == "__main__":
    run()
