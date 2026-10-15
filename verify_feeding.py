"""Exercise feeding through the actual button and shared settings dialog."""
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QBitmap, QColor, QImage, QPainter, QRegion, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop_pet import BehaviorSettingsDialog, DesktopPet, FEED_STATES


def check_alignment(pet):
    def solid_bounds(pixmap, top=0, height=None):
        image = pixmap.toImage().copy(0, top, pixmap.width(), height or pixmap.height())
        mask = QBitmap.fromImage(image.createAlphaMask(Qt.ImageConversionFlag.ThresholdDither))
        return QRegion(mask).boundingRect().translated(0, top)

    for height in (64, 160, 320, 400):
        pet.set_size(height, save=False)
        for mode in ("free", "edge"):
            pet.set_roaming(mode, "clockwise", save=False)
            for segment in ((0,) if mode == "free" else (0, 2, 4, 6)):
                if mode == "edge":
                    pet.edge_progress = pet.edge_route.starts[segment]+pet.edge_route.lengths[segment]/2
                    pet.place_edge()
                rotation = QTransform().rotate(-pet.edge_angle if mode == "edge" else 0)
                pet.enter_state("idle", 10)
                idle = pet.pixmap.transformed(rotation)
                floor = solid_bounds(idle).bottom()+1
                band = max(2, round(height*0.08))
                reference = solid_bounds(idle, floor-band, band+2)
                centers, floors = [], []
                for state, elapsed in (("feed_drop", 0.1), ("feed_drop", 0.6),
                                       ("feed_eat", 0.0), ("feed_eat", 0.23),
                                       ("feed_happy", 0.0), ("feed_refuse", 0.0),
                                       ("feed_refuse", 0.24), ("feed_refuse", 1.4),
                                       ("hungry", 0.0), ("hungry", 0.45),
                                       ("hungry", 0.9), ("hungry", 1.35), ("idle", 0.0)):
                    pet.enter_state(state, 10)
                    pet.state_time = elapsed
                    if state == "feed_drop":
                        pet.state_duration = 0.65
                    pet.update_frame()
                    shoes = solid_bounds(pet.pixmap.transformed(rotation), floor-band, band+2)
                    assert not shoes.isEmpty()
                    centers.append((shoes.left()+shoes.right()+1)/2)
                    floors.append(shoes.bottom())
                target = (reference.left()+reference.right()+1)/2
                # Quarter-turn rasterization can change a shoe silhouette's
                # thresholded bounds by a pixel on either side.
                assert max(centers)-min(centers) <= 2, (pet.character_id, height, mode, segment, centers)
                assert max(abs(center-target) for center in centers) <= 2
                assert max(floors)-min(floors) <= 1, (pet.character_id, height, floors)
                pet.cancel_feeding()
        pet.set_roaming("free", "clockwise", save=False)
        pet.reset_position()
    pet.set_size(160, save=False)


def run():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    preview = QImage(1000, 620, QImage.Format.Format_ARGB32)
    preview.fill(QColor("#e6edf4"))
    painter = QPainter(preview)
    far = QPoint(-10000, -10000)
    with tempfile.TemporaryDirectory() as folder:
        settings = Path(folder)/"settings.json"
        pet = DesktopPet(settings, start_timer=False)
        pet.next_hunger = float("inf")
        pet.show()
        app.processEvents()
        assert pet.feeding_enabled

        def offer():
            # These scenarios isolate feeding mechanics; stack limits and
            # timed digestion are exercised separately in verify_appetite.py.
            pet.appetites[pet.character_id].stacks = 0
            pet.hide_food()
            pet.feed_cooldown = 0
            pet.enter_state("idle", 10)
            pet.near_cursor = False
            near = pet.feeding_point(pet.body_height * 0.7).toPoint()
            pet.advance(0.3, near)
            assert not pet.bread_button.isVisible()
            pet.advance(0.41, near)
            assert pet.bread_button.isVisible()
            assert pet.screen_area.contains(pet.bread_button.geometry())
            return near

        def click_bread():
            QTest.mouseClick(pet.bread_button, Qt.MouseButton.LeftButton)
            assert pet.state == "feed_drop" and not pet.bread_button.isVisible()
            assert pet.falling_bread.windowFlags() & Qt.WindowType.WindowTransparentForInput
            pet.start_feeding()
            assert pet.state_time == 0  # A second trigger cannot queue food.

        for row, character in enumerate(("liberta", "zenith")):
            pet.set_character(character)
            check_alignment(pet)
            pet.set_roaming("free", "clockwise", save=False)
            pet.reset_position()
            near = offer()
            # Moving away removes the button without creating food.
            pet.advance(0.1, far)
            assert not pet.bread_button.isVisible() and pet.state not in FEED_STATES
            offer()
            painter.drawText(10, row*300+20, character)
            painter.drawPixmap(10, row*300+30, pet.bread_button.grab())
            click_bread()
            origin = (pet.x, pet.y, pet.anchor_x, pet.anchor_y)
            for col, elapsed in enumerate((0.25, 0.35, 0.1, 0.25, 1.4)):
                pet.advance(elapsed, far)
                painter.drawPixmap(60+col*185, row*300+25, pet.pixmap)
                assert origin == (pet.x, pet.y, pet.anchor_x, pet.anchor_y)
            assert pet.state == "feed_happy"
            pet.advance(0.9, far)
            assert pet.state == "idle" and not pet.falling_bread.isVisible()
            pet.advance(0.71, near)
            assert pet.near_cursor and not pet.bread_button.isVisible()  # Cooldown.

            for height in (64, 400):
                pet.set_size(height, save=False)
                pet.set_roaming("edge", "clockwise", save=False)
                for segment in (0, 2, 4, 6):
                    for fraction in (0.05, 0.95):
                        pet.edge_progress = pet.edge_route.starts[segment]+pet.edge_route.lengths[segment]*fraction
                        pet.place_edge()
                        offer()
                        click_bread()
                        before = pet.falling_bread.pos()
                        pet.advance(0.3, far)
                        after = pet.falling_bread.pos()
                        assert before != after
                        pet.advance(0.4, far)
                        assert pet.state == "feed_eat"
                        box = QRegion(pet.pixmap.mask()).boundingRect().translated(pet.pos())
                        assert pet.screen_area.contains(box), (character, height, segment, fraction, box)
                        pet.cancel_feeding()
                pet.set_roaming("free", "clockwise", save=False)
                pet.reset_position()
            pet.set_size(160, save=False)

            # Explicit feeding works when automatic movement is paused.
            pet.set_paused(True)
            offer()
            click_bread()
            for _ in range(40):
                pet.advance(0.1, far)
            assert pet.state == "idle" and pet.paused
            pet.set_paused(False)

            # All straight edges, both directions, negative monitor coordinates.
            pet.screen_area = QRect(-1280, -120, 1280, 900)
            for direction in ("clockwise", "counterclockwise"):
                pet.set_roaming("edge", direction, save=False)
                for segment in (0, 2, 4, 6):
                    pet.edge_progress = pet.edge_route.starts[segment]+pet.edge_route.lengths[segment]/2
                    pet.place_edge()
                    offer()
                    origin = (pet.edge_progress, pet.edge_phase, pet.x, pet.y, pet.edge_angle)
                    click_bread()
                    for _ in range(40):
                        pet.advance(0.1, far)
                        assert origin == (pet.edge_progress, pet.edge_phase, pet.x, pet.y, pet.edge_angle)
                        box = QRegion(pet.pixmap.mask()).boundingRect().translated(pet.pos())
                        assert pet.screen_area.contains(box), (character, direction, segment, box)
                        if pet.state not in FEED_STATES:
                            break
                    assert pet.state == ("left" if pet.edge_sign > 0 else "right")
                    old_progress = pet.edge_progress
                    pet.advance(0.1, far)
                    assert (pet.edge_progress-old_progress)*pet.edge_sign > 0

            # A corner jump completes before any offering is allowed.
            pet.edge_progress = pet.edge_route.starts[1]+pet.edge_route.lengths[1]/2
            pet.place_edge()
            pet.start_walk()
            pet.advance(0.1, pet.feeding_point(80).toPoint())
            assert pet.edge_jumping() and not pet.bread_button.isVisible()
            pet.set_roaming("free", "clockwise", save=False)
            pet.reset_position()

            # Input pass-through, drag, resizing and switching clear transient UI.
            offer()
            pet.set_click_through(True)
            assert not pet.bread_button.isVisible()
            near = pet.feeding_point(80).toPoint()
            pet.advance(1, near)
            assert not pet.bread_button.isVisible()
            pet.set_click_through(False)
            offer()
            click_bread()
            pet.begin_drag(near)
            assert pet.dragging and pet.state not in FEED_STATES and not pet.falling_bread.isVisible()
            pet.dragging = False
            pet.enter_state("idle", 1)
            pet.reset_position()
            offer()
            click_bread()
            pet.set_size(200, save=False)
            assert pet.state == "idle" and not pet.falling_bread.isVisible()
            pet.set_size(160, save=False)
            offer()
            click_bread()
            pet.set_character("zenith" if character == "liberta" else "liberta")
            assert pet.state == "idle" and not pet.falling_bread.isVisible()

        # Save/Cancel and old settings default are shared across both characters.
        dialog = BehaviorSettingsDialog(pet)
        dialog.feeding_enabled.setChecked(False)
        dialog.reject()
        assert pet.feeding_enabled
        dialog = BehaviorSettingsDialog(pet)
        dialog.feeding_enabled.setChecked(False)
        dialog.accept()
        offer_near = pet.feeding_point(80).toPoint()
        pet.advance(1, offer_near)
        assert not pet.feeding_enabled and not pet.bread_button.isVisible()
        assert not json.loads(settings.read_text(encoding="utf-8"))["feeding_enabled"]
        restored = DesktopPet(settings, start_timer=False)
        assert not restored.feeding_enabled
        restored.deleteLater()
        dialog = BehaviorSettingsDialog(pet)
        dialog.feeding_enabled.setChecked(True)
        dialog.accept()
        dialog = BehaviorSettingsDialog(pet)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(output/"feeding-settings.png"))
        dialog.reject()
        offer()
        click_bread()
        pet.hide()
        assert not pet.bread_button.isVisible() and not pet.falling_bread.isVisible()
        pet.advance(0.1, far)
        assert pet.state not in FEED_STATES and not pet.falling_bread.isVisible()
        pet.deleteLater()
    painter.end()
    preview.save(str(output/"feeding-preview.png"))
    print("PASS: hover delay, actual bread click, drop/eat/happy, cooldown, pause, settings Save/Cancel.")
    print("PASS: both characters, four edges, both directions, negative screens, resume and input pass-through.")
    print("PASS: jump/drag/resize/switch/hide cleanup; preview and settings saved under artifacts/.")
    print("PASS: feet stay aligned through look/catch/bite/chew/happy/idle at 64/160/320/400px,")
    print("      including all four wall orientations (at most two pixels of raster rounding).")


if __name__ == "__main__":
    run()
