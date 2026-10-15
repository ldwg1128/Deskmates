"""Release-coordinate, snap-band and rejected-attachment regressions."""
from pathlib import Path
import tempfile

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from desktop_pet import DesktopPet
from window_surfaces import WindowSurface, WindowsSurfaces, select_ledge


class Surfaces:
    def __init__(self, surface): self.surface = surface
    def all(self): return [self.surface]
    def get(self, handle): return self.surface


def release(pet, point):
    pet.press_global = QPoint(700, 700)
    event = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(0, 0), QPointF(point),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    pet.mouseReleaseEvent(event)


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    area = QRect(0, 0, 1920, 1080)
    surface = WindowSurface(12, QRectF(220, 430, 900, 300))
    # The new band accepts nearby drops but not ordinary drops well away from it.
    for height, offset in ((64, 24), (160, 34), (400, 84)):
        for sign in (-1, 1):
            assert select_ledge([surface], QPointF(700, 430 + sign * offset), height, area) == (surface, 0)
        assert select_ledge([surface], QPointF(700, 550), height, area) is None
    cover = WindowSurface(13, QRectF(500, 200, 400, 500))
    assert select_ledge([cover, surface], QPointF(700, 430), 160, area) is None
    assert select_ledge([surface], QPointF(1120, 520), 160, area) == (surface, 1)

    with tempfile.TemporaryDirectory() as folder:
        pet = DesktopPet(Path(folder) / 'settings.json', start_timer=False)
        ctrl = pet.interactions
        ctrl.sleep_enabled = ctrl.rare_enabled = False
        for character in ('zenith', 'liberta', 'seir'):
            pet.set_character(character)
            for height, offset in ((64, 24), (160, 34), (400, 84)):
                pet.set_size(height, save=False)
                for mode in ('free', 'edge'):
                    pet.set_roaming(mode, 'counterclockwise', save=False)
                    for sign in (-1, 1):
                        ctrl.windows = Surfaces(surface)
                        # Last delivered move is outside the band; release is inside.
                        pet.begin_drag(QPoint(700, 700))
                        release(pet, QPoint(700, 430 + sign * offset))
                        assert ctrl.kind == 'window_sit', (character, height, mode, sign)
                        assert ctrl.point == QPointF(700, 430)
                        assert not pet.dragging and pet.drag_cursor is None
                        pet.advance(ctrl.duration, QPoint(-10000, -10000))
                        assert ctrl.kind == 'interaction_jump'
                        for _ in range(180):
                            pet.advance(.1, QPoint(-10000, -10000))
                            if ctrl.kind is None: break
                        assert ctrl.kind is None and pet.roam_mode == mode
                        assert pet.edge_direction == 'counterclockwise'
        # The reverse case must fall at the actual release, not attach at a stale move.
        pet.set_size(160, save=False)
        pet.set_roaming('free', 'clockwise', save=False)
        pet.begin_drag(QPoint(700, 430))
        release(pet, QPoint(700, 700))
        assert ctrl.kind is None and pet.state == 'flip'

        # A valid edge candidate whose sprite would be clipped must not consume drag state.
        ctrl.windows = Surfaces(WindowSurface(14, QRectF(1000, 300, 910, 500)))
        pet.begin_drag(QPoint(1910, 500))
        pet.screen_area = area
        before = (ctrl.surface, ctrl.side, ctrl.point, ctrl.direction)
        assert not ctrl.try_window(QPoint(1910, 500))
        assert pet.dragging and pet.drag_cursor == QPoint(1910, 500)
        assert (ctrl.surface, ctrl.side, ctrl.point, ctrl.direction) == before
        pet.finish_drag()
        assert pet.state == 'flip' and not pet.dragging

        # Use an actual native window's DWM bounds for a complete release -> sit check.
        import sys
        if sys.platform == 'win32':
            window = QWidget()
            window.resize(600, 300); window.move(400, 400); window.show()
            app.processEvents()
            native = WindowsSurfaces(exclude_process=0).get(int(window.winId()))
            assert native is not None
            ctrl.windows = Surfaces(native)
            point = QPoint(round(native.rect.center().x()), round(native.rect.top() + 34))
            pet.begin_drag(QPoint(point.x(), point.y() + 150))
            release(pet, point)
            assert ctrl.kind == 'window_sit'
            assert ctrl.point.y() == native.rect.top()
            ctrl.cancel(); window.close()
        pet.close()
    print('PASS: 36 nearby releases across 3 characters, 3 sizes and both roam modes; jump/fall/resume.')
    print('PASS: stale move coordinates, rejected pose rollback, occlusion, side hanging and native window attachment.')


if __name__ == '__main__': main()
