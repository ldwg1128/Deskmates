"""Exercise real feeding/refusal, timed stacks, hunger poses and persistence."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from appetite import Appetite, BREAD_LIMIT, DIGEST_SECONDS
from desktop_pet import DesktopPet, FEED_STATES


def check_model():
    appetite = Appetite.restore(None, 1000)
    assert appetite.stacks == 0 and appetite.label == "배고픔"
    for count in range(1, 6):
        assert appetite.eat(1000+count*2)
        assert appetite.stacks == count
        assert appetite.label == ("보통" if count <= 2 else "배부름" if count <= 4 else "너무 배부름")
    start = appetite.updated_at
    assert not appetite.eat(start+59)
    assert appetite.updated_at == start and appetite.stacks == 5
    assert not appetite.digest(start+DIGEST_SECONDS-0.01)
    assert appetite.digest(start+DIGEST_SECONDS) and appetite.stacks == 4
    assert appetite.digest(start+3*DIGEST_SECONDS+0.5) and appetite.stacks == 2
    assert appetite.digest(start+10*DIGEST_SECONDS) and appetite.stacks == 0
    restored = Appetite.restore({"stacks": 5, "updated_at": 1000}, 1121)
    assert restored.stacks == 3 and restored.updated_at == 1120
    restored.digest(900)  # Clock rollback must not add food or freeze decay.
    assert restored.stacks == 3 and restored.updated_at == 900
    for bad in (None, [], {"stacks": True}, {"stacks": "5"},
                {"stacks": -99}, {"stacks": 999, "updated_at": float("nan")},
                {"stacks": 5, "updated_at": 10**1000}):
        appetite = Appetite.restore(bad, 1000)
        assert 0 <= appetite.stacks <= 5 and appetite.updated_at <= 1000


def run():
    check_model()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    clock = [2_000_000_000.0]
    far = QPoint(-10000, -10000)
    preview = QImage(1180, 660, QImage.Format.Format_ARGB32)
    preview.fill(QColor("#e6edf4"))
    painter = QPainter(preview)
    with tempfile.TemporaryDirectory() as folder, patch("desktop_pet.time.time", side_effect=lambda: clock[0]):
        settings = Path(folder)/"settings.json"
        pet = DesktopPet(settings, start_timer=False)
        pet.show()
        app.processEvents()
        pet.next_hunger = float("inf")

        def offer():
            pet.hide_food()
            pet.feed_cooldown = 0
            pet.enter_state("idle", 10)
            near = pet.feeding_point(pet.body_height*0.7).toPoint()
            pet.advance(0.71, near)
            assert pet.bread_button.isVisible()
            QTest.mouseClick(pet.bread_button, Qt.MouseButton.LeftButton)
            assert pet.state == "feed_drop"

        def eat():
            offer()
            pet.advance(0.7, far)
            assert pet.state == "feed_eat"
            pet.advance(1.61, far)
            assert pet.state == "feed_happy"
            pet.advance(0.9, far)
            assert pet.state == "idle"

        for row, character in enumerate(("liberta", "zenith")):
            pet.set_character(character)
            pet.set_roaming("free", "clockwise", save=False)
            pet.reset_position()
            pet.appetites[character] = Appetite(0, clock[0])
            pet.next_hunger = 0
            pet.choose_action()
            assert pet.state == "hungry" and pet.speech.isVisible()
            painter.drawText(10, row*320+20, character+" · hungry / receive / shake left / shake right / return")
            painter.drawPixmap(10, row*320+35, pet.pixmap)
            pet.next_hunger = float("inf")

            # Cancelled food is never counted.
            offer()
            pet.begin_drag(pet.feeding_point(80).toPoint())
            assert pet.appetite.stacks == 0 and not pet.meal_pending
            pet.dragging = False
            pet.reset_position()
            for expected in range(1, BREAD_LIMIT+1):
                eat()
                assert pet.appetite.stacks == expected
                clock[0] += 4
            assert pet.speech.isVisible() and "못 먹겠어" in pet.speech.text()
            assert pet.speech.windowFlags() & Qt.WindowType.WindowTransparentForInput
            pet.speech.grab().save(str(output/f"{character}-full-message.png"))
            menu = QMenu()
            pet.populate_menu(menu)
            assert any("너무 배부름" in action.text() and "5/5" in action.text()
                       and not action.isEnabled() for action in menu.actions())
            digestion_start = pet.appetite.updated_at

            messages = []
            for repeat in range(3):
                offer()
                assert pet.feed_refusing and not pet.meal_pending
                pet.advance(0.6, far)
                if repeat == 0:
                    painter.drawPixmap(220, row*320+35, pet.pixmap)
                pet.advance(0.1, far)
                assert pet.state == "feed_refuse" and pet.speech.isVisible()
                messages.append(pet.speech.text())
                left = pet.pixmap.toImage()
                if repeat == 0:
                    painter.drawPixmap(440, row*320+35, pet.pixmap)
                pet.advance(0.24, far)
                assert pet.pixmap.toImage() != left  # Two distinct head turns.
                if repeat == 0:
                    painter.drawPixmap(660, row*320+35, pet.pixmap)
                pet.advance(1.1, far)
                if repeat == 0:
                    painter.drawPixmap(880, row*320+35, pet.pixmap)
                pet.advance(0.4, far)
                assert pet.state == "idle" and pet.appetite.stacks == 5
                assert pet.appetite.updated_at == digestion_start
            assert len(set(messages)) == 3

            # At one minute, exactly one stack is removed and eating is allowed.
            clock[0] = digestion_start+DIGEST_SECONDS-0.01
            pet.advance(0.1, far)
            assert pet.appetite.stacks == 5
            clock[0] += 0.01
            pet.advance(0.1, far)
            assert pet.appetite.stacks == 4
            eat()
            assert pet.appetite.stacks == 5
            pet.save_settings()
            restored = DesktopPet(settings, start_timer=False)
            assert restored.appetites[character].stacks == 5
            restored.hide()
            restored.deleteLater()

            # Refusal, text placement and hunger keep every wall orientation.
            for height in (64, 400):
                pet.set_size(height, save=False)
                for direction in ("clockwise", "counterclockwise"):
                    pet.set_roaming("edge", direction, save=False)
                    for segment in (0, 2, 4, 6):
                        pet.edge_progress = pet.edge_route.starts[segment]+pet.edge_route.lengths[segment]/2
                        pet.place_edge()
                        origin = pet.edge_progress
                        offer()
                        pet.advance(0.7, far)
                        assert pet.state == "feed_refuse"
                        assert pet.screen_area.contains(pet.speech.geometry())
                        for elapsed in (0.24, 0.24, 1.3):
                            pet.advance(elapsed, far)
                            assert pet.edge_progress == origin
                            body = QRegion(pet.pixmap.mask()).boundingRect().translated(pet.pos())
                            assert pet.screen_area.contains(body), (character, height, segment, body)
                        assert pet.state == ("left" if pet.edge_sign > 0 else "right")
                        pet.cancel_feeding()
                pet.set_roaming("free", "clockwise", save=False)
            pet.set_size(160, save=False)
            clock[0] += 5*DIGEST_SECONDS
            pet.advance(0.1, far)
            assert pet.appetite.stacks == 0
            pet.next_hunger = 0
            pet.choose_action()
            assert pet.state == "hungry"
            pet.feeding_enabled = False
            pet.enter_state("idle", 10)
            pet.next_hunger = 0
            pet.choose_action()
            assert pet.state != "hungry"
            pet.feeding_enabled = True

        # Character-specific stacks survive switching and offline digestion.
        pet.appetites["liberta"] = Appetite(5, clock[0])
        pet.appetites["zenith"] = Appetite(2, clock[0])
        pet.save_settings()
        pet.set_character("liberta")
        assert pet.appetite.stacks == 5
        pet.set_character("zenith")
        assert pet.appetite.stacks == 2
        clock[0] += 2*DIGEST_SECONDS+1
        restored = DesktopPet(settings, start_timer=False)
        assert restored.appetites["liberta"].stacks == 3
        assert restored.appetites["zenith"].stacks == 0
        restored.deleteLater()
        pet.say("테스트")
        pet.hide()
        assert not pet.speech.isVisible() and not pet.falling_bread.isVisible()
        pet.deleteLater()
    painter.end()
    preview.save(str(output/"appetite-preview.png"))
    print("PASS: 0/1-2/3-4/5 hunger states, five completed meals, no counting cancelled or refused food.")
    print("PASS: receive/head-shake/return with varied speech, one stack per minute, refill and offline decay.")
    print("PASS: per-character persistence, hungry gestures, all wall orientations/directions at 64/400px,")
    print("      speech placement, no pointer interception, and UI cleanup.")


if __name__ == "__main__":
    run()
