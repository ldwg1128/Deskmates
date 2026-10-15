"""Integration checks for the supplied sprite, movement and actual menu actions."""
from pathlib import Path
import json
import tempfile

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMenu

from desktop_pet import BehaviorSettingsDialog, CHARACTERS, DesktopPet, gaze_index


def run_character(character_id):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as temporary:
        settings = Path(temporary) / "settings.json"
        settings.write_text(json.dumps({"character": character_id}), encoding="utf-8")
        pet = DesktopPet(settings, start_timer=False)
        pet.next_hunger = float("inf")
        pet.rng.seed(42)
        assert [gaze_index(*direction) for direction in [(0, -10), (10, 0), (0, 10), (-10, 0)]] == [0, 4, 8, 12]
        for height in [64, 80, 120, 160, 200, 240, 320, 400]:
            pet.set_size(height, save=False)
            for frames in pet.frames.values():
                for frame in frames:
                    assert not frame.isNull()
                    # One integer-pixel rounding tolerance, never stretch.
                    assert abs(frame.width() - frame.height() * pet.character.crop_width / 208) <= 1
                    assert not frame.mask().isNull()
            pet.show()
            app.processEvents()
            image = pet.grab().toImage()
            assert image.hasAlphaChannel()
            assert image.pixelColor(0, 0).alpha() == 0
        pet.set_size(160, save=False)
        # Exercise a monitor left of the primary screen, including boundaries.
        pet.screen_area = QRect(-1280, -120, 1280, 900)
        pet.anchor_x, pet.anchor_y = -300, 720
        pet.x, pet.y = pet.anchor_x, pet.anchor_y
        pet.position_window()
        if character_id == "liberta":
            # A horizontal profile must follow a horizontal path, with leg
            # cadence responding to actual travel rather than elapsed time.
            for _ in range(10):
                pet.start_walk()
                assert pet.target[1] == pet.y
            pet.next_gaze = float("inf")
            for speed in (28, 75):
                pet.x, pet.y = -300, 720
                pet.speed = speed
                pet.target = (-150, 720)
                pet.enter_state("right", 15)
                pet.advance(0.5, QPoint(-10000, -10000))
                assert abs(pet.x - (-300 + speed * 0.5)) < 1e-6
                assert pet.y == 720
                assert pet.frame_key == ("right", int(speed * 0.5 / 64 * 8))
            pet.target = (-500, 720)
            pet.enter_state("left", 15)
            old_x = pet.x
            pet.advance(0.5, QPoint(-10000, -10000))
            assert pet.x < old_x and pet.y == 720 and pet.frame_key[0] == "left"
            for height in (64, 160, 400):
                pet.set_size(height, save=False)
                for right, left in zip(pet.frames["right"], pet.frames["left"]):
                    assert left.toImage() == right.toImage().transformed(QTransform().scale(-1, 1))
                    assert not right.mask().isNull()
                    # Shoes, hair and arms retain transparent margins at every size.
                    rectangle = QRegion(right.mask()).boundingRect()
                    assert rectangle.left() > 0 and rectangle.top() > 0
                    assert rectangle.right() < right.width() - 1
                    assert rectangle.bottom() < right.height() - 1
            pet.set_size(160, save=False)
            pet.speed = 46
            pet.x, pet.y = pet.anchor_x, pet.anchor_y
            pet.next_gaze = 7
            pet.gaze_elapsed = 0
            pet.rng.seed(42)
            pet.enter_state("idle", 1.5)
            print("PASS: Liberta side profiles, horizontal left/right travel, speed-based leg cadence,")
            print("      mirrored directions and unclipped frames at 64px, 160px and 400px.")
        visited = set()
        positions = []
        for _ in range(3600):
            pet.advance(1 / 30, QPoint(-500, 400))
            visited.add(pet.state)
            positions.append(pet.x)
            left, right, top, bottom = pet.bounds()
            assert left <= pet.x <= right
            assert top <= pet.y <= bottom
            assert pet.screen_area.left() <= pet.pos().x()
            assert pet.pos().x() + pet.width() <= pet.screen_area.right() + 1
        assert max(positions) - min(positions) > 100
        assert {"left", "right", "gaze"} <= visited, visited
        # A long horizontal walk yields fewer random rest gestures. Verify
        # each one directly instead of relying on its selection in 120 s.
        for gesture in ("wave", "jump"):
            pet.enter_state(gesture)
            pet.advance(1 / 30, QPoint(-500, 400))
            assert pet.frame_key[0] == gesture
        head_y = round(pet.y - pet.frames["idle"][0].height() * 0.57)
        near_right = QPoint(round(pet.x + 50), head_y)
        pet.start_walk()
        before = (pet.x, pet.y)
        for _ in range(600):
            pet.advance(1 / 30, near_right)
            assert pet.state == "gaze" and pet.near_cursor
            assert (pet.x, pet.y) == before
        assert pet.frame_key == ("gaze", 4)
        near_up = QPoint(round(pet.x), head_y - 30)
        pet.advance(1 / 30, near_up)
        assert pet.frame_key == ("gaze", 0)
        far = QPoint(-10000, -10000)
        pet.advance(1 / 30, far)
        assert pet.state == "idle" and not pet.near_cursor
        for _ in range(150):
            pet.advance(1 / 30, far)
        assert (pet.x, pet.y) != before
        pet.set_paused(True)
        old = (pet.x, pet.y, pet.state_time)
        pet.advance(1, far)
        assert (pet.x, pet.y, pet.state_time) == old
        pet.advance(1 / 30, QPoint(round(pet.x), round(pet.y - 50)))
        assert pet.state == "gaze" and pet.near_cursor and pet.paused
        pet.advance(1 / 30, far)
        assert pet.state == "idle" and pet.paused
        pet.set_paused(False)
        menu = QMenu()
        pet.populate_menu(menu)
        sizes = next(action.menu() for action in menu.actions() if action.text() == "캐릭터 크기")
        next(action for action in sizes.actions() if "240px" in action.text()).trigger()
        assert pet.body_height == 240
        pet.set_click_through(True)
        pet.set_click_through(False)
        pet.set_radius(420)
        pet.set_speed(75)
        pet.start_walk()
        assert any(action.text() == "행동 설정…" for action in menu.actions())
        assert not any(action.text() in ("산책 범위", "걷는 속도", "잠시 멈추기")
                       for action in menu.actions())
        dialog = BehaviorSettingsDialog(pet)
        dialog.stationary.setChecked(True)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        assert pet.stationary and pet.state == "idle"
        position = (pet.x, pet.y)
        stationary_states = set()
        for _ in range(1800):
            pet.advance(1 / 30, far)
            stationary_states.add(pet.state)
            assert (pet.x, pet.y) == position
        assert not ({"left", "right"} & stationary_states)
        assert {"wave", "jump", "gaze"} <= stationary_states, stationary_states
        pet.advance(1 / 30, QPoint(round(pet.x), round(pet.y - 50)))
        assert pet.state == "gaze" and pet.stationary
        restored = DesktopPet(settings, start_timer=False)
        assert (restored.body_height, restored.radius, restored.speed) == (240, 420, 75)
        assert restored.stationary and restored.character_id == character_id
        restored.close()
        dialog = BehaviorSettingsDialog(pet)
        dialog.stationary.setChecked(False)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        assert not pet.stationary
        for _ in range(300):
            pet.advance(1 / 30, far)
        assert (pet.x, pet.y) != position
        pet.screen_area = QApplication.primaryScreen().availableGeometry()
        pet.x = pet.screen_area.center().x()
        pet.y = pet.screen_area.bottom() - 12
        pet.anchor_x, pet.anchor_y = pet.x, pet.y
        pet.enter_state("idle")
        pet.position_window()
        pet.show()
        app.processEvents()
        # A render of our own app for visual QA, without capturing other apps.
        Path("artifacts").mkdir(exist_ok=True)
        pet.grab().save(f"artifacts/{character_id}-preview.png")
        # Send real Qt mouse events through the widget, including while paused.
        pet.set_size(160, save=False)
        pet.set_paused(True)
        screen = QApplication.primaryScreen().availableGeometry()
        point = QPoint(screen.center().x(), screen.center().y())
        def mouse(kind, position, button, buttons):
            local = position - pet.pos()
            event = QMouseEvent(kind, QPointF(local), QPointF(position), button, buttons,
                                Qt.KeyboardModifier.NoModifier)
            QCoreApplication.sendEvent(pet, event)
        mouse(QEvent.Type.MouseButtonPress, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
        moved = point + QPoint(45, 30)
        mouse(QEvent.Type.MouseMove, moved, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
        assert pet.dragging
        samples = []
        for _ in range(20):
            pet.advance(1 / 30)
        assert abs(pet.drag_angle) > 0.1
        samples.append(pet.pixmap.copy())
        mouse(QEvent.Type.MouseButtonRelease, moved, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
        assert not pet.dragging and pet.state == "flip"
        assert len(pet.motion_frames) == 6
        duration = pet.fall_duration
        for fraction in (0.10, 0.30, 0.56, 0.78, 0.99):
            pet.advance(duration * fraction - pet.state_time)
            samples.append(pet.pixmap.copy())
            expected_com = (pet.fall_start[1] + pet.fall_velocity[1] * pet.state_time
                            + 0.5 * pet.fall_gravity * pet.state_time ** 2)
            assert abs(pet.y - pet.height() / 2 - expected_com) < 1e-6
        pet.advance(duration * 0.02)
        assert pet.state == "land"
        assert pet.y - 4 == pet.landing_floor
        pet.advance(0.10)
        samples.append(pet.pixmap.copy())
        pet.advance(0.20)
        samples.append(pet.pixmap.copy())
        pet.advance(0.19)
        assert pet.state == "idle" and pet.paused
        samples.append(pet.pixmap.copy())
        contact = QPixmap(pet.width() * len(samples), pet.height())
        contact.fill(Qt.GlobalColor.transparent)
        painter = QPainter(contact)
        for index, sample in enumerate(samples):
            painter.drawPixmap(index * pet.width(), 0, sample)
        painter.end()
        contact.save(f"artifacts/{character_id}-drag-landing-preview.png")
        # Check that rotation remains contained at both size extremes.
        for height in (64, 400):
            pet.set_size(height, save=False)
            pet.begin_drag(point)
            pet.advance(0.3)
            pet.drag_angle = 0
            pet.drag_velocity = (0, 0)
            pet.finish_drag()
            previous_com = pet.fall_start[1]
            visited_poses = set()
            interval = pet.fall_duration / 24
            for _ in range(23):
                pet.advance(interval)
                visited_poses.add(pet.motion_pose)
                com = pet.y - pet.height() / 2
                assert com >= previous_com
                previous_com = com
                image = pet.pixmap.toImage()
                assert all(image.pixelColor(x, y).alpha() < 32
                           for x, y in [(0, image.height() // 2), (image.width() - 1, image.height() // 2),
                                        (image.width() // 2, 0), (image.width() // 2, image.height() - 1)])
            assert visited_poses == {0, 1, 2, 3}, visited_poses
            pet.advance(interval * 2)
            assert pet.state == "land"
            pet.advance(0.5)
            assert pet.state == "idle"
        assert any(action.text() == "종료" for action in menu.actions())
        # Cancel leaves settings unchanged; Save writes all behavior controls together.
        dialog = BehaviorSettingsDialog(pet)
        assert dialog.advanced_panel.isHidden()
        assert not dialog.radius_preset.isEditable() and not dialog.speed_preset.isEditable()
        assert dialog.height_preset.currentData() == 400  # Existing custom size is retained.
        for combo, editor, value in ((dialog.height_preset, dialog.height_input, 160),
                                     (dialog.radius_preset, dialog.radius, 220),
                                     (dialog.speed_preset, dialog.speed, 46)):
            combo.setCurrentIndex(combo.findData(value))
            assert editor.value() == value and combo.currentData() == value
        dialog.advanced_toggle.click()
        assert not dialog.advanced_panel.isHidden()
        dialog.radius.setValue(180)
        dialog.speed.setValue(30)
        assert dialog.radius_preset.currentData() == 180
        assert dialog.speed_preset.currentData() == 30
        assert "사용자 지정" in dialog.radius_preset.currentText()
        dialog.advanced_toggle.click()
        assert dialog.advanced_panel.isHidden() and dialog.radius.value() == 180
        dialog.paused.setChecked(False)
        dialog.stationary.setChecked(True)
        dialog.reject()
        assert (pet.radius, pet.speed, pet.paused, pet.stationary, pet.click_through) == (420, 75, True, False, False)
        assert pet.body_height == 400
        dialog = BehaviorSettingsDialog(pet)
        dialog.height_preset.setCurrentIndex(dialog.height_preset.findData(200))
        dialog.radius.setValue(180)
        dialog.speed.setValue(30)
        dialog.paused.setChecked(False)
        dialog.stationary.setChecked(True)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        assert (pet.radius, pet.speed, pet.paused, pet.stationary, pet.click_through) == (180, 30, False, True, False)
        assert pet.body_height == 200
        pet.set_click_through(False)
        dialog = BehaviorSettingsDialog(pet)
        dialog.show()
        app.processEvents()
        dialog.grab().save("artifacts/behavior-settings-preview.png")
        assert dialog.radius_preset.currentData() == 180 and dialog.speed_preset.currentData() == 30
        dialog.advanced_toggle.click()
        app.processEvents()
        assert dialog.radius.isVisible() and dialog.speed.isVisible() and dialog.height_input.isVisible()
        dialog.grab().save("artifacts/behavior-settings-advanced-preview.png")
        dialog.reject()
        # Switch through the actual menu, including while a fall was in progress.
        pet.begin_drag(point)
        pet.finish_drag()
        assert pet.state == "flip"
        other_id = "liberta" if character_id == "zenith" else "zenith"
        characters = next(action.menu() for action in menu.actions() if action.text() == "캐릭터 전환")
        next(action for action in characters.actions() if action.text() == CHARACTERS[other_id].name).trigger()
        assert pet.character_id == other_id and pet.state == "idle" and not pet.dragging
        assert pet.frame_key == ("idle", 0) and pet.target is None
        assert (pet.radius, pet.speed, pet.stationary) == (180, 30, True)
        assert CHARACTERS[other_id].name in pet.tray.toolTip()
        restored = DesktopPet(settings, start_timer=False)
        assert restored.character_id == other_id and restored.stationary
        assert (restored.body_height, restored.radius, restored.speed) == (200, 180, 30)
        restored.close()
        pet.set_character(character_id)
        assert pet.character_id == character_id
        pet.tray_menu.clear()
        pet.populate_menu(pet.tray_menu)
        tray_characters = next(action.menu() for action in pet.tray_menu.actions()
                               if action.text() == "캐릭터 전환")
        assert next(action for action in tray_characters.actions()
                    if action.text() == pet.character.name).isChecked()
        pet.quit_pet()
        pet.hide()
        print("PASS: transparent rendering, all frame proportions at 8 sizes, 120s bounded movement,")
        print("      cursor directions, gestures, pause, size menu, click-through and saved settings.")
        print("PASS: mouse pickup/release, six poses including two in-betweens, constant-gravity descent,")
        print("      exact floor contact, paused landing, no upward drift or clipping at 64px / 400px.")
        print("PASS: 20s continuous nearby gaze, immediate direction updates, walking resumes on exit,")
        print("      proximity gaze during pause, and drag/landing retains priority.")
        print("PASS: stationary menu stops an active walk, 60s of gestures without movement,")
        print("      nearby gaze, setting restore and roaming resumes after unchecking.")
        print(f"PASS: {character_id}: shared behavior dialog Save/Cancel, menu character switching,")
        print("      tray identity, switch during falling, shared behavior and selected character restore.")
        print("PASS: preset dropdowns, collapsed advanced controls, custom-value synchronization,")
        print("      size selection, Cancel rollback and saved custom values restored.")


def run():
    # This suite asserts preserved legacy atlas geometry; manifest packs have their
    # own geometry/behavior checks (verify_character_pipeline.py, verify_seir.py).
    for character_id in (key for key,c in CHARACTERS.items() if c.data['renderer']=='legacy-v1'):
        run_character(character_id)


if __name__ == "__main__":
    run()
