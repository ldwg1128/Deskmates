"""Integration checks for perimeter direction, corner jumps and saved options."""
from pathlib import Path
import tempfile

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from desktop_pet import BehaviorSettingsDialog, DesktopPet
from edge_path import EdgeRoute


def run():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    far = QPoint(-10000, -10000)
    route = EdgeRoute(-1280, -120, 1280, 900, 90)
    for start in route.starts:
        before, after = route.at(start-1e-5), route.at(start+1e-5)
        assert abs(before.x-after.x)+abs(before.y-after.y) < 1e-3
        assert abs((before.angle-after.angle+180) % 360-180) < 1e-3
        assert abs((route.project(after.x, after.y)-start+route.length/2) % route.length-route.length/2) < 1e-3
    with tempfile.TemporaryDirectory() as temporary:
        settings = Path(temporary) / "settings.json"
        pet = DesktopPet(settings, start_timer=False)
        pet.next_hunger = float("inf")
        for character in ("zenith", "liberta"):
            pet.set_character(character)
            pet.set_size(160, save=False)
            for direction in ("clockwise", "counterclockwise"):
                pet.set_roaming("free", "clockwise", save=False)
                pet.screen_area = QRect(-1280, -120, 1280, 900)
                pet.x, pet.y = -300, 720
                pet.anchor_x, pet.anchor_y = pet.x, pet.y
                pet.stationary = pet.paused = False
                pet.set_roaming("edge", direction, save=False)
                pet.rng.seed(4)
                pet.next_gaze = float("inf")
                pet.gaze_elapsed = 0
                segments, states = set(), set()
                for _ in range(1200):
                    old_progress, old_state = pet.edge_progress, pet.state
                    pet.advance(0.1, far)
                    difference = pet.edge_progress-old_progress
                    assert difference*pet.edge_sign >= -1e-7
                    if old_state not in ("left", "right") and pet.state not in ("left", "right"):
                        assert difference == 0
                    pose = pet.edge_route.at(pet.edge_progress, pet.edge_sign)
                    segments.add(pose.segment)
                    states.add(pet.state)
                    box = QRegion(pet.pixmap.mask()).boundingRect()
                    box.translate(pet.pos())
                    assert pet.screen_area.contains(box), (character, direction, pet.state, box)
                assert segments == set(range(8))
                assert {"idle", "wave", "jump"} <= states
                assert ("left" if pet.edge_sign > 0 else "right") in states
                assert ("right" if pet.edge_sign > 0 else "left") not in states
                # A pending rest and nearby cursor cannot interrupt a corner jump.
                segment = 1
                pet.edge_progress = pet.edge_route.starts[segment] + pet.edge_route.lengths[segment]/2
                pet.enter_state("left" if pet.edge_sign > 0 else "right", 0.01)
                pet.place_edge()
                pet.update_frame()
                near = QPoint(round(pet.x), round(pet.y-pet.height()/2))
                pet.advance(0.1, near)
                assert pet.edge_jumping() and not pet.near_cursor
                pet.set_paused(True)
                old = (pet.edge_progress, pet.state_time, pet.x, pet.y)
                pet.advance(0.1, near)
                assert (pet.edge_progress, pet.state_time, pet.x, pet.y) == old
                pet.set_paused(False)
                pet.advance(0.3, far)
                assert not pet.edge_jumping() and pet.state not in ("left", "right")
            # Resizing and quarter-turn rotation retain every visible limb.
            for height in (64, 400):
                pet.set_size(height, save=False)
                for segment, length in enumerate(pet.edge_route.lengths):
                    for fraction in (0.1, 0.5, 0.9):
                        pet.edge_progress = pet.edge_route.starts[segment]+length*fraction
                        pet.enter_state("right", 10)
                        pet.place_edge()
                        pet.update_frame(far)
                        box = QRegion(pet.pixmap.mask()).boundingRect()
                        box.translate(pet.pos())
                        assert pet.screen_area.contains(box), (character, height, segment, fraction, box)
            pet.set_size(160, save=False)
            dialog = BehaviorSettingsDialog(pet)
            dialog.free_radio.click()
            assert dialog.edge_options.isHidden() and not dialog.free_options.isHidden()
            dialog.reject()
            assert pet.roam_mode == "edge"
            dialog = BehaviorSettingsDialog(pet)
            dialog.edge_radio.click()
            dialog.edge_direction.setCurrentIndex(dialog.edge_direction.findData("clockwise"))
            assert not dialog.edge_options.isHidden() and dialog.free_options.isHidden()
            dialog.accept()
            restored = DesktopPet(settings, start_timer=False)
            assert restored.roam_mode == "edge" and restored.edge_direction == "clockwise"
            assert abs(restored.edge_phase-pet.edge_phase) < 1e-8
            restored.close()
            # Drag release attaches to the nearest edge instead of falling.
            cursor = QApplication.primaryScreen().availableGeometry().center()
            pet.begin_drag(cursor)
            pet.finish_drag()
            assert pet.state == "idle" and not pet.dragging and pet.roam_mode == "edge"
            assert abs(pet.edge_route.project(pet.x, pet.y-pet.height()/2)-pet.edge_progress) < 1e-5
            pet.set_stationary(True)
            position = pet.edge_progress
            for _ in range(100):
                pet.advance(0.1, far)
                assert pet.edge_progress == position
            pet.set_stationary(False)
            pet.set_roaming("free", "clockwise", save=False)
        pet.quit_pet()
    print("PASS: both characters and directions complete all four edges without reversing;")
    print("      walking/rest cycles, 90-degree jumps, pause, cursor priority and visible containment.")
    print("PASS: 64px/400px corner poses, option Save/Cancel, direction/phase restore,")
    print("      stationary behavior, edge drag attachment and return to normal roaming.")


if __name__ == "__main__":
    run()
