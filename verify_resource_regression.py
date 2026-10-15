"""Capture/compare deterministic game frames without touching user settings."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from desktop_pet import DesktopPet


def capture():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = {"assets": {}, "frames": {}}
    for path in sorted(Path("assets").glob("*.png")):
        result["assets"][path.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory() as folder:
        pet = DesktopPet(Path(folder)/"settings.json", start_timer=False)
        pet.next_hunger = float("inf")

        def sample(key):
            image = pet.pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            result["frames"][key] = {"size": [image.width(), image.height()],
                "sha256": hashlib.sha256(bytes(image.constBits())).hexdigest(),
                "position": [round(pet.x, 6), round(pet.y, 6)], "state": pet.state}

        for character in ("zenith", "liberta"):
            pet.set_character(character)
            for height in (64, 160, 320, 400):
                pet.set_roaming("free", "clockwise", save=False)
                pet.screen_area = QRect(0, 0, 1920, 1080)
                pet.anchor_x, pet.anchor_y = 960, 1020
                pet.x, pet.y = 960, 1020
                pet.set_size(height, save=False)
                for state in ("idle", "left", "right", "wave", "jump", "bow", "shy", "think", "tilt", "gaze", "hungry", "feed_eat", "feed_happy", "feed_refuse"):
                    pet.enter_state(state, 10)
                    for t in (0, .23, .6, 1.4):
                        pet.state_time = t
                        pet.walk_distance = t*46
                        pet.update_frame(QPoint(1100, 600))
                        sample(f"{character}/{height}/free/{state}/{t}")
                pet.begin_drag(QPoint(960, 300))
                pet.drag_angle = 11
                pet.update_frame()
                sample(f"{character}/{height}/drag")
                pet.drag_velocity = (0, 0)
                pet.finish_drag()
                for i in range(1, 13):
                    pet.advance(pet.fall_duration/12, QPoint(-10000, -10000))
                    sample(f"{character}/{height}/fall/{i}")
                pet.advance(1, QPoint(-10000, -10000))
                pet.set_roaming("edge", "clockwise", save=False)
                for direction in ("clockwise", "counterclockwise"):
                    pet.set_roaming("edge", direction, save=False)
                    for segment, length in enumerate(pet.edge_route.lengths):
                        for fraction in (.1, .5, .9):
                            pet.edge_progress = pet.edge_route.starts[segment]+length*fraction
                            pet.enter_state("left" if pet.edge_sign > 0 else "right", 10)
                            pet.walk_distance = fraction*height
                            pet.place_edge()
                            pet.update_frame()
                            sample(f"{character}/{height}/{direction}/{segment}/{fraction}")
                pet.set_roaming("free", "clockwise", save=False)
        pet.hide()
        pet.deleteLater()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    if not args.record and not args.compare:
        args.compare = Path(__file__).resolve().parent / 'tests/fixtures/render-baseline.json'
    actual = capture()
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(actual, indent=2), encoding="utf-8")
    if args.compare:
        expected = json.loads(args.compare.read_text(encoding="utf-8"))
        differences = [key for key in expected["frames"] if expected["frames"][key] != actual["frames"].get(key)]
        assert expected["assets"] == actual["assets"], "Original PNG bytes changed"
        assert not differences, differences[:12]
        assert expected["frames"].keys() == actual["frames"].keys()
    print(f"PASS: {len(actual['frames'])} deterministic frames; {len(actual['assets'])} original PNG hashes.")


if __name__ == "__main__":
    main()
