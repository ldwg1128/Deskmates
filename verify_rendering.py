"""Compare live Windows backing-store pixels, not just offscreen sprite frames."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from desktop_pet import DesktopPet


def assert_current_frame(pet):
    actual = pet.backingStore().paintDevice()
    assert isinstance(actual, QImage), "This check requires the Windows raster backing store."
    expected = pet.pixmap.toImage()
    if expected.size() != actual.size():
        expected = expected.scaled(actual.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
    expected = expected.convertToFormat(actual.format())
    if bytes(actual.constBits()) != bytes(expected.constBits()):
        Path("artifacts").mkdir(exist_ok=True)
        actual.save("artifacts/render-buffer-actual.png")
        expected.save("artifacts/render-buffer-expected.png")
        raise AssertionError((pet.character_id, pet.body_height, pet.edge_direction,
                              pet.frame_key, "native buffer contains stale/missing pixels"))


def run():
    if sys.platform != "win32":
        raise SystemExit("Run this native layered-window regression on Windows.")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as folder:
        pet = DesktopPet(Path(folder)/"settings.json", start_timer=False)
        pet.show()
        count = 0
        for character in ("liberta", "zenith"):
            pet.set_character(character)
            for height in (160, 320, 400):
                pet.set_size(height, save=False)
                for direction in ("clockwise", "counterclockwise"):
                    pet.set_roaming("edge", direction, save=False)
                    for segment, length in enumerate(pet.edge_route.lengths):
                        for step in range(12):
                            pet.edge_progress = pet.edge_route.starts[segment]+length*(step+0.5)/12
                            pet.place_edge()
                            pet.enter_state("left" if pet.edge_sign > 0 else "right", 100)
                            pet.walk_distance = step*height/30
                            pet.update_frame()
                            app.processEvents()
                            assert_current_frame(pet)
                            count += 1
                    for gesture in ("idle", "wave", "bow", "jump", "feed_eat", "feed_happy"):
                        pet.enter_state(gesture)
                        app.processEvents()
                        assert_current_frame(pet)
                        if gesture == "feed_eat":
                            pet.state_time = 0.23
                            pet.update_frame()
                            app.processEvents()
                            assert_current_frame(pet)

        # Removing the native shape mask must preserve desktop click-through.
        background = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowStaysOnTopHint
                             | Qt.WindowType.WindowDoesNotAcceptFocus)
        area = app.primaryScreen().availableGeometry()
        background.setGeometry(area.adjusted(40, 40, -40, -40))
        background.show()
        pet.set_roaming("free", "clockwise", save=False)
        pet.set_size(160, save=False)
        pet.x = pet.anchor_x = area.center().x()
        pet.y = pet.anchor_y = area.center().y()+120
        pet.position_window()
        pet.enter_state("idle", 100)
        pet.raise_()
        QTest.qWait(200)
        assert_current_frame(pet)
        api = ctypes.windll.user32
        api.WindowFromPoint.argtypes = [wintypes.POINT]
        api.WindowFromPoint.restype = wintypes.HWND
        sprite = pet.pixmap.toImage()
        for transparent in (True, False):
            point = next((x, y) for y in range(sprite.height()) for x in range(sprite.width())
                         if (sprite.pixelColor(x, y).alpha() == 0 if transparent
                             else sprite.pixelColor(x, y).alpha() >= 128)
                         and background.geometry().contains(pet.pos().x()+x, pet.pos().y()+y))
            x, y = point
            hit = api.WindowFromPoint(wintypes.POINT(pet.pos().x()+x, pet.pos().y()+y))
            assert hit == int(background.winId() if transparent else pet.winId()), (transparent, hit)
        pet.hide()
        background.hide()
        pet.deleteLater()
        background.deleteLater()
    print(f"PASS: {count} live edge frames match the Windows backing store pixel-for-pixel;")
    print("      both characters, 160/320/400px, both directions, four corners and gesture transitions.")
    print("PASS: zero-alpha desktop hit-through and opaque character hit testing without a native mask.")


if __name__ == "__main__":
    run()
