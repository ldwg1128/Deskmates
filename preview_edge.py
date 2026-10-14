"""Render the app's perimeter animation without capturing the desktop."""
import argparse
from pathlib import Path
import tempfile

from PIL import Image
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from desktop_pet import CHARACTERS, DesktopPet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", choices=CHARACTERS, default="liberta")
    parser.add_argument("--direction", choices=("clockwise", "counterclockwise"), default="clockwise")
    args = parser.parse_args()
    app = QApplication([])
    frames = []
    with tempfile.TemporaryDirectory() as temporary:
        pet = DesktopPet(Path(temporary)/"settings.json", start_timer=False)
        pet.set_character(args.character)
        pet.set_size(80, save=False)
        pet.screen_area = QRect(0, 0, 640, 420)
        pet.x, pet.y = 320, 408
        pet.anchor_x, pet.anchor_y = pet.x, pet.y
        pet.speed = 100
        pet.set_roaming("edge", args.direction, save=False)
        pet.next_gaze = float("inf")
        pet.rng.seed(4)
        distance = 0
        for _ in range(340):
            before = pet.edge_progress
            pet.advance(0.08, QPoint(-10000, -10000))
            distance += abs(pet.edge_progress-before)
            scene = QPixmap(640, 420)
            scene.fill(QColor("#edf1f7"))
            painter = QPainter(scene)
            painter.setPen(QColor("#9caabf"))
            painter.drawRect(1, 1, 637, 417)
            painter.setPen(QColor("#42516b"))
            painter.drawText(190, 190, f"{pet.character.name} · {args.direction}")
            painter.drawText(190, 212, "walk / rest / 90-degree corner jump")
            painter.drawPixmap(pet.pos(), pet.pixmap)
            painter.end()
            image = scene.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            frames.append(Image.frombytes("RGBA", (640, 420), bytes(image.constBits()),
                                          "raw", "RGBA", image.bytesPerLine()).convert("RGB"))
            if distance >= pet.edge_route.length + 10:
                break
        path = Path("artifacts")/f"{args.character}-edge-{args.direction}.gif"
        path.parent.mkdir(exist_ok=True)
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
        frames[len(frames)//2].save(path.with_suffix(".png"))
        pet.quit_pet()
        print(f"Saved {path}: {len(frames)} frames")


if __name__ == "__main__":
    main()
