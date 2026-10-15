"""Check radio choices, mode-specific controls, presets and advanced settings."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialogButtonBox, QMenu

from desktop_pet import BehaviorSettingsDialog, DesktopPet


def run():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        settings = Path(folder)/"settings.json"
        # Existing custom values remain exact, without units in basic choices.
        settings.write_text(json.dumps({"height": 175, "radius": 180, "speed": 100}), encoding="utf-8")
        pet = DesktopPet(settings, start_timer=False)
        pet.next_hunger = float("inf")
        dialog = BehaviorSettingsDialog(pet)
        dialog.show()
        app.processEvents()

        def save_preview(name):
            QTest.qWait(160)  # Let the native radio/check indicator animation settle.
            dialog.grab().save(str(output/name))
        assert dialog.free_radio.isChecked() and not dialog.edge_radio.isChecked()
        assert dialog.radius_preset.isVisible() and dialog.recenter_button.isVisible()
        assert not dialog.edge_direction.isVisible() and not dialog.edge_hint.isVisible()
        assert dialog.advanced_toggle.text() == "고급"
        for control in (dialog.height_input, dialog.radius, dialog.speed, dialog.show_windows_tools):
            assert not control.isVisible()
            assert dialog.advanced_panel.isAncestorOf(control)
        for combo, value in ((dialog.height_preset, 175), (dialog.radius_preset, 180), (dialog.speed_preset, 100)):
            assert not combo.isEditable() and combo.currentData() == value
            assert combo.currentText() == "사용자 지정"
            assert all("px" not in combo.itemText(i) and not any(c.isdigit() for c in combo.itemText(i))
                       for i in range(combo.count()))
        assert [dialog.speed_preset.itemText(i) for i in range(3)] == ["느림", "보통", "빠름"]
        assert not any(control.text() == "마우스 통과" for control in dialog.findChildren(QCheckBox))
        save_preview("settings-free.png")

        QTest.mouseClick(dialog.edge_radio, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert dialog.edge_radio.isChecked() and not dialog.free_radio.isChecked()
        assert dialog.edge_direction.isVisible() and dialog.edge_hint.isVisible()
        assert not dialog.radius_preset.isVisible() and not dialog.recenter_button.isVisible()
        assert dialog.height_preset.isVisible() and dialog.speed_preset.isVisible()
        save_preview("settings-edge.png")

        # Advanced is the last content control before the Save/Cancel footer.
        assert dialog.advanced_toggle.y() > dialog.reset_button.geometry().bottom()
        QTest.mouseClick(dialog.advanced_toggle, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert dialog.height_input.isVisible() and dialog.speed.isVisible()
        assert dialog.show_windows_tools.isVisible() and not dialog.radius.isVisible()
        assert not dialog.advanced_form.labelForField(dialog.radius).isVisible()
        save_preview("settings-edge-advanced.png")
        QTest.mouseClick(dialog.free_radio, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert dialog.radius.isVisible() and dialog.advanced_form.labelForField(dialog.radius).isVisible()
        assert not dialog.edge_hint.isVisible()
        save_preview("settings-free-advanced.png")

        for combo, editor, value in ((dialog.height_preset, dialog.height_input, 160),
                                     (dialog.radius_preset, dialog.radius, 420),
                                     (dialog.speed_preset, dialog.speed, 75)):
            combo.setCurrentIndex(combo.findData(value))
            assert editor.value() == value
        dialog.radius.setValue(333)
        dialog.speed.setValue(63.5)
        assert dialog.radius_preset.currentData() == 333 and dialog.radius_preset.currentText() == "사용자 지정"
        assert dialog.speed_preset.currentData() == 63.5 and dialog.speed_preset.currentText() == "사용자 지정"
        dialog.show_windows_tools.setChecked(True)
        dialog.edge_radio.click()
        dialog.reject()
        assert (pet.body_height, pet.radius, pet.speed, pet.roam_mode, pet.show_windows_tools) == (175, 180, 100, "free", False)

        # Both character/tray menus put the toggle immediately above Quit and
        # allow recovery after input passes through the pet's native window.
        for character in ("liberta", "zenith"):
            pet.set_character(character)
            menu = QMenu()
            pet.populate_menu(menu)
            assert [action.text() for action in menu.actions()[-2:]] == ["마우스 통과", "종료"]
            toggle = menu.actions()[-2]
            assert toggle.isCheckable() and not toggle.isChecked()
            toggle.trigger()
            assert pet.click_through and pet.windowFlags() & Qt.WindowType.WindowTransparentForInput
            dialog = BehaviorSettingsDialog(pet)
            dialog.edge_radio.click()
            dialog.edge_direction.setCurrentIndex(dialog.edge_direction.findData("counterclockwise"))
            dialog.radius.setValue(333)
            dialog.speed.setValue(63.5)
            dialog.advanced_toggle.click()
            dialog.show_windows_tools.setChecked(True)
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            assert pet.click_through  # Dialog must not overwrite the menu setting.
            assert (pet.roam_mode, pet.edge_direction, pet.radius, pet.speed) == ("edge", "counterclockwise", 333, 63.5)
            assert pet.show_windows_tools
            pet.tray_menu.clear()
            pet.populate_menu(pet.tray_menu)
            assert [action.text() for action in pet.tray_menu.actions()[-2:]] == ["마우스 통과", "종료"]
            assert pet.tray_menu.actions()[-2].isChecked()
            pet.tray_menu.actions()[-2].trigger()
            assert not pet.click_through

        restored = DesktopPet(settings, start_timer=False)
        assert (restored.radius, restored.speed, restored.roam_mode, restored.edge_direction) == (333, 63.5, "edge", "counterclockwise")
        assert restored.show_windows_tools and not restored.click_through
        dialog = BehaviorSettingsDialog(restored)
        assert dialog.edge_radio.isChecked() and dialog.free_options.isHidden()
        assert dialog.advanced_panel.isHidden() and dialog.show_windows_tools.isChecked()
        dialog.free_radio.click()
        assert dialog.radius_preset.currentData() == 333
        dialog.accept()
        assert restored.roam_mode == "free" and restored.radius == 333
        pet.hide()
        restored.hide()
        pet.deleteLater()
        restored.deleteLater()
    print("PASS: exclusive walk radios, only relevant controls/labels, named presets without pixel units.")
    print("PASS: bottom Advanced, numeric/custom preservation, Windows tools, Save/Cancel and restore.")
    print("PASS: click-through directly above Quit in both character/tray menus; recovery and dialog independence.")
    print("Saved four native dialog previews under artifacts/settings-*.png.")


if __name__ == "__main__":
    run()
