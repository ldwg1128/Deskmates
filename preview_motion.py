"""Render only our pet into an animation preview; never capture other apps."""
from pathlib import Path
import tempfile
import argparse

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from desktop_pet import APP_NAME, CHARACTERS, DesktopPet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", choices=CHARACTERS, default="liberta")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path("artifacts")
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        pet = DesktopPet(Path(temporary) / "settings.json", start_timer=False)
        pet.set_character(args.character)
        pet.set_size(160, save=False)
        pet.paused = True
        area = pet.screen_area
        pet.begin_drag(QPoint(area.center().x(), area.top() + 180))
        frames = []
        snapshots = []
        floor = pet.screen_area.bottom() - 4
        width, height = 300, area.height() + 40
        duration = 0
        for frame_number in range(140):
            if frame_number == 15:
                pet.drag_angle = 0
                pet.drag_velocity = (0, 0)
                pet.finish_drag()
                duration = pet.fall_duration
            if frame_number >= 15:
                pet.advance(1 / 30, QPoint(-10000, -10000))
            else:
                pet.advance(1 / 30)
            scene = QPixmap(width, height)
            scene.fill(QColor("#edf1f7"))
            painter = QPainter(scene)
            painter.setPen(QColor("#9caabf"))
            floor_local = floor - area.top() + 20
            painter.drawLine(15, floor_local, width - 15, floor_local)
            painter.setPen(QColor("#42516b"))
            painter.drawText(16, 24, f"{APP_NAME} · {pet.character.name} · {frame_number / 30:.2f}s")
            painter.drawPixmap(QPointF((width - pet.width()) / 2,
                                      pet.pos().y() - area.top() + 20), pet.pixmap)
            painter.end()
            image = scene.toImage().convertToFormat(scene.toImage().Format.Format_RGBA8888)
            frame = Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()),
                                    "raw", "RGBA", image.bytesPerLine())
            frames.append(frame.convert("RGB"))
            if frame_number in (14, 19, 25, 31, 40, 49, 58, 70):
                snapshots.append(scene.copy())
            if frame_number > 15 + round((duration + 0.85) * 30):
                break
        frames[0].save(output / f"{pet.character_id}-landing-preview.gif", save_all=True,
                       append_images=frames[1:], duration=33, loop=0, optimize=True)
        contact = QPixmap(width * len(snapshots), height)
        contact.fill(Qt.GlobalColor.white)
        painter = QPainter(contact)
        for index, scene in enumerate(snapshots):
            painter.drawPixmap(index * width, 0, scene)
        painter.end()
        contact.save(str(output / f"{pet.character_id}-landing-frames.png"))
        pet.hide()
        print(f"Preview saved: {len(frames)} frames, drop lasts {duration:.2f}s.")


if __name__ == "__main__":
    main()
