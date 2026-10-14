"""A small, local-only Windows desktop companion made from the supplied sheet."""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
import random
import sys
import time
from dataclasses import dataclass

from edge_path import EdgeRoute

from PySide6.QtCore import QLockFile, QPoint, QPointF, QRect, QSignalBlocker, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QActionGroup, QCursor, QIcon, QImage, QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QDoubleSpinBox, QFormLayout, QLabel, QMenu, QPushButton,
                              QSpinBox, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)


APP_NAME = "DeskMates"
CELL_W, CELL_H = 192, 208
# One shared crop for every frame: it preserves the sheet's body proportions
# and foot alignment, including its intentional jumps and head movements.
CROP_X, CROP_W = 32, 128
BODY_HEIGHT = 198
# Artwork orientations, measured clockwise from the inverted hanging pose.
MOTION_ANGLES = (0.0, 30.0, 140.0, 180.0)
CLIPS = {
    "idle": (0, 6, 0.18),
    "right": (1, 8, 0.105),
    "left": (2, 8, 0.105),
    "wave": (3, 4, 0.18),
    "jump": (4, 5, 0.15),
    "bow": (5, 8, 0.17),
    "shy": (6, 6, 0.19),
    "think": (7, 6, 0.22),
    "tilt": (8, 6, 0.19),
}


@dataclass(frozen=True)
class Character:
    name: str
    sheet: str
    crop_x: int
    crop_width: int
    body_height: int
    motion_sheet: str
    motion_grid: tuple[int, int]
    motion_indices: tuple[int, ...]
    motion_angles: tuple[float, ...]
    # Optional standing frame provides a consistent scale across both sheets.
    motion_reference: int | None = None
    walk_indices: tuple[int, ...] = ()
    walk_crop: tuple[int, int, int, int] | None = None
    walk_ground: int = 0
    # Standing-equivalent anatomical scale; bent airborne poses are shorter.
    motion_body_height: int | None = None
    corner_sheet: str = ""


CHARACTERS = {
    "zenith": Character("제니스 (Zenith)", "assets/zenith-spritesheet-v2.png", CROP_X, CROP_W, BODY_HEIGHT,
                        "assets/zenith-motion-v4.png", (3, 2), tuple(range(6)), MOTION_ANGLES,
                        motion_body_height=462, corner_sheet="assets/zenith-corner-jump.png"),
    "liberta": Character("리베르타 (Liberta)", "assets/liberta-spritesheet.png", 16, 160, 167,
                         "assets/liberta-motion.png", (4, 6), (16, 18, 19, 20, 21, 22),
                         (0.0, 135.0, 90.0, 180.0), 23,
                         walk_indices=tuple(range(8, 16)), walk_crop=(96, 0, 384, 512),
                         walk_ground=497, corner_sheet="assets/liberta-corner-jump.png"),
}
DEFAULT_CHARACTER = "liberta"
HEIGHT_PRESETS = ((80, "아주 작게"), (120, "작게"), (160, "기본"),
                  (200, "크게"), (240, "아주 크게"), (320, "특대"))
RADIUS_PRESETS = ((100, "좁게"), (220, "보통"), (420, "넓게"), (700, "아주 넓게"))
SPEED_PRESETS = ((28, "느긋하게"), (46, "보통"), (75, "활발하게"))


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def gaze_index(dx: float, dy: float) -> int:
    """The supplied look row is clockwise: up, right, down, left."""
    return round(math.atan2(dx, -dy) / (2 * math.pi) * 16) % 16


class DesktopPet(QWidget):
    def __init__(self, settings_path: Path, *, start_timer: bool = True):
        super().__init__()
        self.settings_path = settings_path
        self.settings = self.load_settings()
        self.character_id = self.settings.get("character", DEFAULT_CHARACTER)
        if not isinstance(self.character_id, str) or self.character_id not in CHARACTERS:
            self.character_id = DEFAULT_CHARACTER
        self.character = CHARACTERS[self.character_id]
        self.rng = random.Random()
        self.body_height = int(clamp(self.settings.get("height", 160), 64, 400))
        self.radius = int(clamp(self.settings.get("radius", 220), 50, 800))
        self.speed = float(clamp(self.settings.get("speed", 46), 20, 100))
        self.paused = bool(self.settings.get("paused", False))
        self.stationary = bool(self.settings.get("stationary", False))
        self.click_through = bool(self.settings.get("click_through", False))
        self.roam_mode = self.settings.get("roam_mode", "free")
        if self.roam_mode not in ("free", "edge"):
            self.roam_mode = "free"
        self.edge_direction = self.settings.get("edge_direction", "clockwise")
        if self.edge_direction not in ("clockwise", "counterclockwise"):
            self.edge_direction = "clockwise"
        self.edge_phase = float(self.settings.get("edge_phase", 0.0)) % 1.0
        self.edge_route = None
        self.edge_progress = 0.0
        self.edge_angle = 0.0
        self.edge_rest_pending = False
        self.corner_duration = 0.6
        self.dragging = False
        self.drag_time = 0.0
        self.drag_angle = 0.0
        self.drag_lean = 0.0
        self.drag_cursor = None
        self.flip_angle = 0.0
        self.drag_velocity = (0.0, 0.0)
        self.drag_sample_time = time.monotonic()
        self.fall_start = (0.0, 0.0)
        self.fall_velocity = (0.0, 0.0)
        self.fall_gravity = 0.0
        self.fall_duration = 0.0
        self.rotation_duration = 0.0
        self.landing_floor = 0.0
        self.motion_pose = 0
        self.menu_open = False
        self.press_global = None
        self.press_origin = None
        self.state = "idle"
        self.state_time = 0.0
        self.state_duration = 1.5
        self.gaze_elapsed = 0.0
        self.next_gaze = self.rng.uniform(5, 10)
        self.near_cursor = False
        self.target = None
        self.walk_distance = 0.0
        self.frame_key = None
        self.last_tick = time.monotonic()

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("드래그: 위치 이동 · 우클릭: 캐릭터 전환 / 행동 설정 / 종료")
        self.load_character_art()
        self.pixmap = self.originals["idle"][0]
        self.screen_area = QApplication.primaryScreen().availableGeometry()
        self.anchor_x = self.screen_area.center().x()
        self.anchor_y = self.screen_area.bottom() - 12
        saved = self.settings.get("anchor")
        if isinstance(saved, list) and len(saved) == 2 and all(isinstance(v, (int, float)) for v in saved):
            point = QPoint(round(saved[0]), round(saved[1]))
            screen = QApplication.screenAt(point)
            if screen is not None:
                self.screen_area = screen.availableGeometry()
                self.anchor_x, self.anchor_y = saved
        self.x = self.anchor_x
        self.y = self.anchor_y
        self.set_size(self.body_height, save=False)
        self.anchor_x = self.x
        self.anchor_y = self.y - self.height()/2 if self.roam_mode == "edge" else self.y

        icon = QIcon(self.originals["idle"][0])
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.update_character_identity()
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self.refresh_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self.tray_activated)
        if start_timer:
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        if start_timer:
            self.timer.start(33)
        QApplication.instance().screenAdded.connect(self.refresh_screens)
        QApplication.instance().screenRemoved.connect(self.refresh_screens)
        for screen in QApplication.screens():
            screen.availableGeometryChanged.connect(self.refresh_screens)
        self.apply_click_through()
        if (self.roam_mode == "edge" and not self.paused and not self.stationary
                and self.edge_route.at(self.edge_progress, self.edge_sign).corner):
            self.start_walk()
        self.update_frame()

    def load_character_art(self):
        character = self.character
        sheet = QPixmap(str(resource_path(character.sheet)))
        if sheet.isNull() or sheet.width() != 1536 or sheet.height() != 2288:
            raise ValueError("스프라이트 이미지(1536×2288)를 불러올 수 없습니다.")
        self.originals = {
            name: [sheet.copy(col * CELL_W + character.crop_x, row * CELL_H,
                             character.crop_width, CELL_H)
                   for col in range(count)]
            for name, (row, count, _) in CLIPS.items()
        }
        self.originals["gaze"] = [
            sheet.copy((i % 8) * CELL_W + character.crop_x, (9 + i // 8) * CELL_H,
                       character.crop_width, CELL_H)
            for i in range(16)
        ]
        drag_sheet = QPixmap(str(resource_path(character.motion_sheet)))
        if drag_sheet.isNull():
            raise ValueError("매달리기 / 착지 이미지를 불러올 수 없습니다.")
        columns, rows = character.motion_grid
        cell_w, cell_h = drag_sheet.width() // columns, drag_sheet.height() // rows
        def crop_motion(index):
            sprite = drag_sheet.copy((index % columns) * cell_w, (index // columns) * cell_h,
                                     cell_w, cell_h)
            image = sprite.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            pixels = memoryview(image.constBits())
            stride = image.bytesPerLine()
            # Ignore near-transparent stray pixels when finding the content.
            opaque = [(x, y) for y in range(image.height()) for x in range(image.width())
                      if pixels[y * stride + x * 4 + 3] >= 32]
            if not opaque:
                raise ValueError("동작 이미지에 캐릭터가 없습니다.")
            left = min(x for x, y in opaque)
            top = min(y for x, y in opaque)
            right = max(x for x, y in opaque)
            bottom = max(y for x, y in opaque)
            return sprite.copy(left, top, right - left + 1, bottom - top + 1)
        self.motion_originals = [crop_motion(index) for index in character.motion_indices]
        self.motion_reference_height = (character.motion_body_height
                                        if character.motion_body_height is not None
                                        else crop_motion(character.motion_reference).height()
                                        if character.motion_reference is not None
                                        else self.motion_originals[3].height())
        self.walk_originals = []
        if character.walk_indices:
            # Keep a shared crop and scale: individual limb poses must not resize
            # the character or move the body anchor from frame to frame.
            x, y, width, height = character.walk_crop
            self.walk_originals = [
                drag_sheet.copy((index % columns) * cell_w + x,
                                (index // columns) * cell_h + y, width, height)
                for index in character.walk_indices
            ]
            # Almost invisible residue in the source must not create clickable
            # margins or leak into the neighboring frame after scaling.
            for index, sprite in enumerate(self.walk_originals):
                image = sprite.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
                pixels = memoryview(image.bits())
                for offset in range(3, image.sizeInBytes(), 4):
                    if pixels[offset] < 32:
                        pixels[offset] = 0
                self.walk_originals[index] = QPixmap.fromImage(image)
        corner_sheet = QPixmap(str(resource_path(character.corner_sheet)))
        if corner_sheet.isNull() or corner_sheet.width() % 2 or corner_sheet.height() % 2:
            raise ValueError("코너 점프 이미지를 불러올 수 없습니다.")
        # Reuse the same alpha-aware content crop for the new four-pose sheet.
        drag_sheet = corner_sheet
        columns, rows = 2, 2
        cell_w, cell_h = corner_sheet.width() // 2, corner_sheet.height() // 2
        self.corner_originals = [crop_motion(index) for index in range(4)]

    def update_character_identity(self):
        icon = QIcon(self.originals["idle"][0])
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.tray.setToolTip(f"{APP_NAME} · {self.character.name} · 우클릭으로 설정 / 종료")

    def set_character(self, character_id: str):
        if character_id not in CHARACTERS or character_id == self.character_id:
            return
        # Reset transient movement so no old sprite or target survives a switch.
        self.character_id = character_id
        self.character = CHARACTERS[character_id]
        self.load_character_art()
        self.dragging = False
        self.drag_cursor = None
        self.press_global = None
        self.press_origin = None
        self.target = None
        self.near_cursor = False
        self.gaze_elapsed = 0
        self.state = "idle"
        self.state_time = 0
        self.state_duration = 1.0
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.set_size(self.body_height, save=False)
        self.update_character_identity()
        self.save_settings()

    def load_settings(self) -> dict:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            for key in ("height", "radius", "speed", "edge_phase"):
                if key in data and (not isinstance(data[key], (int, float))
                                    or not math.isfinite(data[key])):
                    data.pop(key)
            return data
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        data = {"character": self.character_id, "height": self.body_height, "radius": self.radius,
                "speed": self.speed, "paused": self.paused,
                "stationary": self.stationary,
                "click_through": self.click_through,
                "roam_mode": self.roam_mode, "edge_direction": self.edge_direction,
                "edge_phase": self.edge_phase,
                "anchor": [round(self.anchor_x), round(self.anchor_y)]}
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.settings_path)
        except OSError:
            logging.exception("Could not save settings")

    def set_size(self, height: int, *, save: bool = True):
        self.body_height = int(clamp(height, 64, 400))
        # Specify HEIGHT ONLY with scaledToHeight. Qt chooses the width from
        # the original aspect ratio; no stretch or per-frame resizing occurs.
        target_height = round(CELL_H * self.body_height / self.character.body_height)
        self.frames = {name: [p.scaledToHeight(target_height, Qt.TransformationMode.SmoothTransformation)
                              for p in frames] for name, frames in self.originals.items()}
        reference_height = self.motion_reference_height
        if self.walk_originals:
            idle = self.frames["idle"][0]
            floor = QRegion(idle.mask()).boundingRect().bottom() + 1
            scale = self.body_height / reference_height
            right_frames = []
            for original in self.walk_originals:
                sprite = original.scaledToHeight(round(original.height() * scale),
                                                Qt.TransformationMode.SmoothTransformation)
                frame = QPixmap(idle.size())
                frame.fill(Qt.GlobalColor.transparent)
                painter = QPainter(frame)
                painter.drawPixmap(round((frame.width() - sprite.width()) / 2),
                                   round(floor - (self.character.walk_ground
                                                  - self.character.walk_crop[1]) * scale), sprite)
                painter.end()
                right_frames.append(frame)
            self.frames["right"] = right_frames
            self.frames["left"] = [frame.transformed(QTransform().scale(-1, 1))
                                   for frame in right_frames]
        self.motion_frames = [p.scaledToHeight(
            round(p.height() * self.body_height / reference_height),
            Qt.TransformationMode.SmoothTransformation)
            for index, p in enumerate(self.motion_originals)]
        self.corner_frames = [p.scaledToHeight(
            max(1, round(p.height() * self.body_height / self.corner_originals[3].height())),
            Qt.TransformationMode.SmoothTransformation) for p in self.corner_originals]
        # A square canvas holds the rotated sprite without clipping limbs.
        largest_diagonal = max(math.hypot(p.width(), p.height()) for p in
                               self.motion_frames + [p for frames in self.frames.values() for p in frames])
        side = math.ceil(largest_diagonal) + 16
        if self.roam_mode == "edge":
            # Rotation is around the feet, so the canvas needs a full body
            # radius on each side of that pivot rather than a center pivot.
            sprites = [p for frames in self.frames.values() for p in frames] + self.corner_frames
            side = math.ceil(2 * max(math.hypot(p.width(), p.height()) for p in sprites)) + 16
        self.setFixedSize(side, side)
        self.frame_key = None
        if self.roam_mode == "edge":
            self.rebuild_edge_route()
        self.confine()
        self.target = None
        self.update_frame()
        self.position_window()
        if save:
            self.save_settings()

    def bounds(self) -> tuple[float, float, float, float]:
        area = self.screen_area
        half = self.width() / 2
        screen_l = area.left() + half
        screen_r = max(screen_l, area.right() + 1 - half)
        screen_t = area.top() + self.height()
        screen_b = max(screen_t, area.bottom() + 1)
        ax = clamp(self.anchor_x, screen_l, screen_r)
        ay = clamp(self.anchor_y, screen_t, screen_b)
        return (max(screen_l, ax - self.radius), min(screen_r, ax + self.radius),
                max(screen_t, ay - 38), min(screen_b, ay + 38))

    def confine(self):
        if self.roam_mode == "edge" and not self.dragging and self.state not in ("flip", "land"):
            self.place_edge()
            return
        left, right, top, bottom = self.bounds()
        self.x = clamp(self.x, left, right)
        self.y = clamp(self.y, top, bottom)

    def position_window(self):
        self.move(round(self.x - self.width() / 2), round(self.y - self.height()))

    def refresh_screens(self, *_):
        screen = QApplication.screenAt(QPoint(round(self.anchor_x), round(self.anchor_y)))
        if screen is None:
            screen = QApplication.primaryScreen()
            area = screen.availableGeometry()
            self.anchor_x = area.center().x()
            self.anchor_y = area.bottom() - 12
        self.screen_area = screen.availableGeometry()
        if self.roam_mode == "edge":
            self.rebuild_edge_route()
        self.confine()
        self.target = None
        self.position_window()

    @property
    def edge_sign(self):
        return 1 if self.edge_direction == "clockwise" else -1

    def rebuild_edge_route(self):
        area = self.screen_area
        sprites = [p for frames in self.frames.values() for p in frames] + self.corner_frames
        radius = max(self.body_height * 0.45, max(p.width() for p in sprites) / 2 + 12)
        self.edge_route = EdgeRoute(area.left(), area.top(), area.width(), area.height(), radius)
        self.edge_progress = self.edge_phase * self.edge_route.length
        self.place_edge()

    def place_edge(self):
        if self.edge_route is None:
            return
        pose = self.edge_route.at(self.edge_progress, self.edge_sign)
        self.edge_angle = pose.angle
        radians = math.radians(pose.angle)
        lift = (self.body_height * 0.12 * math.sin(math.pi * pose.fraction)
                if pose.corner and self.state in ("left", "right") else 0.0)
        self.x = pose.x + math.sin(radians) * lift
        foot_y = pose.y - math.cos(radians) * lift
        self.y = foot_y + self.height() / 2
        self.anchor_x, self.anchor_y = self.x, foot_y
        self.edge_phase = (self.edge_progress % self.edge_route.length) / self.edge_route.length
        self.position_window()

    def attach_to_edge(self, x, y):
        self.rebuild_edge_route()
        self.edge_progress = self.edge_route.project(x, y)
        pose = self.edge_route.at(self.edge_progress)
        if pose.corner:
            # A dropped character rests on a real straight edge, never halfway
            # through the airborne path connecting two neighboring edges.
            candidates = (self.edge_route.starts[pose.segment],
                          self.edge_route.starts[pose.segment] + self.edge_route.lengths[pose.segment])
            self.edge_progress = min(candidates, key=lambda distance:
                (self.edge_route.at(distance).x-x)**2 + (self.edge_route.at(distance).y-y)**2)
        self.edge_rest_pending = False
        self.target = None
        self.near_cursor = False
        self.enter_state("idle", 0.8)
        self.place_edge()
        self.update_frame()

    def set_roaming(self, mode, direction, *, save=True):
        if mode not in ("free", "edge") or direction not in ("clockwise", "counterclockwise"):
            raise ValueError("Invalid roaming mode or direction")
        if mode == self.roam_mode and direction == self.edge_direction:
            return
        old_mode = self.roam_mode
        old_x = self.x
        old_y = self.y - self.height()/2 if old_mode == "edge" else self.y
        self.roam_mode, self.edge_direction = mode, direction
        self.edge_rest_pending = False
        self.target = None
        self.near_cursor = False
        self.state = "idle"
        self.state_time = 0.0
        self.state_duration = 0.8
        if old_mode != mode:
            self.x, self.y = old_x, old_y
            self.anchor_x, self.anchor_y = old_x, old_y
            self.set_size(self.body_height, save=False)
            if mode == "edge":
                self.attach_to_edge(old_x, old_y)
            else:
                self.anchor_x, self.anchor_y = self.x, self.y
        elif mode == "edge":
            self.place_edge()
        self.frame_key = None
        self.update_frame()
        if save:
            self.save_settings()

    def advance_edge(self, dt):
        # Straight walking uses the selected speed. Each corner is a short
        # jump with its own timing, so low walking speeds do not cause hovering.
        while dt > 1e-9:
            pose = self.edge_route.at(self.edge_progress, self.edge_sign)
            remaining = self.edge_route.remaining(self.edge_progress, self.edge_sign)
            if remaining < 1e-7:
                self.edge_progress += self.edge_sign * 1e-6
                continue
            speed = (self.edge_route.lengths[pose.segment] / self.corner_duration
                     if pose.corner else self.speed)
            elapsed = min(dt, remaining / speed)
            distance = speed * elapsed
            self.edge_progress += self.edge_sign * distance
            self.walk_distance += distance
            dt -= elapsed
        self.place_edge()

    def edge_jumping(self):
        return (self.roam_mode == "edge" and self.state in ("left", "right")
                and self.edge_route.at(self.edge_progress, self.edge_sign).corner)

    def enter_state(self, state: str, duration: float | None = None):
        self.state = state
        self.state_time = 0
        if state in ("left", "right"):
            self.walk_distance = 0.0
        if duration is None:
            _, count, interval = CLIPS.get(state, (0, 1, 0.1))
            duration = count * interval
        self.state_duration = duration
        self.frame_key = None
        self.update_frame()

    def start_walk(self):
        if self.stationary:
            self.target = None
            self.enter_state("idle", 0.8)
            return
        if self.roam_mode == "edge":
            self.target = None
            self.enter_state("left" if self.edge_sign > 0 else "right", self.rng.uniform(6, 11))
            return
        left, right, top, bottom = self.bounds()
        choices = [self.rng.uniform(left, right) for _ in range(5)]
        tx = max(choices, key=lambda candidate: abs(candidate - self.x))
        ty = (clamp(self.y, top, bottom) if self.walk_originals
              else self.rng.uniform(top, bottom))
        self.target = (tx, ty)
        self.enter_state("right" if tx >= self.x else "left", 15)

    def choose_action(self):
        self.target = None
        if self.roam_mode == "edge" and not self.stationary:
            if self.state in ("left", "right"):
                self.edge_rest_pending = True
                self.enter_state(self.rng.choice(["wave", "bow", "shy", "think", "tilt", "jump"]))
            elif self.edge_rest_pending:
                self.edge_rest_pending = False
                self.enter_state("idle", self.rng.uniform(0.7, 1.3))
            else:
                self.start_walk()
            return
        if not self.stationary and self.rng.random() < 0.62:
            self.start_walk()
        else:
            state = self.rng.choices(["idle", "wave", "jump", "bow", "shy", "think", "tilt"],
                                     weights=[4, 2, 3, 1, 1, 1, 2])[0]
            duration = self.rng.uniform(0.8, 2.4) if state == "idle" else None
            self.enter_state(state, duration)

    def cursor_is_near(self, cursor: QPoint) -> bool:
        # Measure distance from the visible body, excluding rotation padding.
        if self.roam_mode == "edge":
            body = QRegion(self.pixmap.mask()).boundingRect()
        else:
            sprite = self.frames["idle"][0]
            body = QRegion(sprite.mask()).boundingRect()
            body.translate(round((self.width() - sprite.width()) / 2),
                           self.height() - sprite.height())
        body.translate(self.pos())
        dx = max(body.left() - cursor.x(), 0, cursor.x() - body.right())
        dy = max(body.top() - cursor.y(), 0, cursor.y() - body.bottom())
        distance = max(72, self.body_height * 0.6)
        # A small exit margin prevents flicker at the detection boundary.
        if self.near_cursor:
            distance += 16
        return math.hypot(dx, dy) <= distance

    def advance(self, dt: float, cursor: QPoint | None = None):
        if self.menu_open:
            return
        if self.dragging:
            self.drag_time += dt
            self.drag_lean *= math.exp(-dt * 5)
            self.drag_angle = clamp(math.sin(self.drag_time * 4.8) * 6 + self.drag_lean, -17, 17)
            decay = math.exp(-dt * 4)
            self.drag_velocity = tuple(v * decay for v in self.drag_velocity)
            self.update_frame()
            return
        # User-initiated pickup / landing still finishes when roaming is paused.
        if self.state == "flip":
            self.state_time = min(self.state_time + dt, self.fall_duration)
            t = self.state_time
            self.x = self.fall_start[0] + self.fall_velocity[0] * t
            self.x = clamp(self.x, self.screen_area.left() + self.width() / 2,
                           self.screen_area.right() + 1 - self.width() / 2)
            com_y = (self.fall_start[1] + self.fall_velocity[1] * t
                     + 0.5 * self.fall_gravity * t * t)
            self.y = com_y + self.height() / 2
            if t >= self.fall_duration:
                # Anchor each landing drawing to the same floor; the transparent
                # canvas can change position without moving the contact point.
                self.y = self.landing_floor + 4
                self.anchor_x, self.anchor_y = self.x, self.y
                self.save_settings()
                self.enter_state("land", 0.48)
            self.position_window()
            self.update_frame()
            return
        if self.state == "land":
            self.state_time += dt
            if self.state_time >= self.state_duration:
                self.enter_state("idle", 1.0)
                self.gaze_elapsed = 0
            self.update_frame()
            return
        if self.press_global is not None:
            return
        if self.edge_jumping():
            # Finish a 90-degree jump before cursor gaze or a scheduled rest
            # can interrupt it; an explicit pause still freezes the jump.
            if not self.paused:
                self.state_time += dt
                self.advance_edge(dt)
                if (self.state_time >= self.state_duration or self.stationary) and not self.edge_jumping():
                    self.choose_action()
            self.update_frame(cursor)
            return
        cursor = cursor if cursor is not None else QCursor.pos()
        if self.cursor_is_near(cursor):
            if not self.near_cursor or self.state != "gaze":
                self.target = None
                self.enter_state("gaze", float("inf"))
            self.near_cursor = True
            self.update_frame(cursor)
            return
        if self.near_cursor:
            self.near_cursor = False
            self.gaze_elapsed = 0
            self.next_gaze = self.rng.uniform(6, 12)
            self.enter_state("idle", 0.6)
        if self.paused:
            return
        self.state_time += dt
        self.gaze_elapsed += dt
        if self.gaze_elapsed >= self.next_gaze and self.state != "gaze":
            self.target = None
            self.enter_state("gaze", self.rng.uniform(1.4, 2.8))
            self.gaze_elapsed = 0
            self.next_gaze = self.rng.uniform(6, 12)
        if self.roam_mode == "edge" and self.state in ("left", "right"):
            self.advance_edge(dt)
        elif self.state in ("left", "right") and self.target is not None:
            dx, dy = self.target[0] - self.x, self.target[1] - self.y
            distance = math.hypot(dx, dy)
            step = self.speed * dt
            self.walk_distance += min(distance, step)
            if distance <= step:
                self.x, self.y = self.target
                self.target = None
                self.enter_state("idle", self.rng.uniform(0.5, 1.7))
            else:
                self.x += dx / distance * step
                self.y += dy / distance * step
            self.confine()
            self.position_window()
        if (self.state_time >= self.state_duration or
                (self.roam_mode == "edge" and self.stationary and self.state in ("left", "right"))) and not self.edge_jumping():
            self.choose_action()
        self.update_frame(cursor)

    def tick(self):
        now = time.monotonic()
        dt = min(now - self.last_tick, 0.1)
        self.last_tick = now
        self.advance(dt)

    def update_frame(self, cursor: QPoint | None = None):
        if self.dragging or self.state in ("flip", "land"):
            self.render_motion()
            return
        if self.roam_mode == "edge":
            self.render_edge(cursor)
            return
        state = self.state
        if state == "gaze":
            cursor = cursor or QCursor.pos()
            head_y = self.y - self.frames["idle"][0].height() * 0.57
            index = gaze_index(cursor.x() - self.x, cursor.y() - head_y)
        else:
            _, count, interval = CLIPS[state]
            if state in ("left", "right") and self.walk_originals:
                # A cycle covers a fixed stride at the current body size, so
                # slower travel also slows the legs instead of sliding the feet.
                count = len(self.frames[state])
                index = int(self.walk_distance / (self.body_height * 0.4) * count) % count
            else:
                index = int(self.state_time / interval) % count
        key = (state, index)
        if key != self.frame_key:
            self.frame_key = key
            self.pixmap = QPixmap(self.size())
            self.pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(self.pixmap)
            sprite = self.frames[state][index]
            painter.drawPixmap(round((self.width() - sprite.width()) / 2),
                               self.height() - sprite.height(), sprite)
            painter.end()
            # Hit-test only the character: transparent margins never block
            # clicks on windows/icons underneath the pet.
            self.setMask(QRegion(self.pixmap.mask()))
            self.update()

    def render_edge(self, cursor=None):
        state = self.state
        pose = self.edge_route.at(self.edge_progress, self.edge_sign)
        pivot_x, pivot_y = self.width()/2, self.height()/2
        corner = pose.corner and state in ("left", "right")
        if corner:
            fraction = pose.fraction if self.edge_sign > 0 else 1-pose.fraction
            index = min(3, int(fraction * 4))
            sprite = self.corner_frames[index]
            # Generated jump poses face right in local space. Clockwise travel
            # uses a left-facing local sprite, with the same inward body angle.
            if self.edge_sign > 0:
                sprite = sprite.transformed(QTransform().scale(-1, 1))
            ground = sprite.height()
            foot_x = self.corner_foot_x(sprite)
        else:
            if state == "gaze":
                cursor = cursor or QCursor.pos()
                radians = math.radians(self.edge_angle)
                c, s = math.cos(radians), math.sin(radians)
                head_height = self.frames["idle"][0].height() * 0.57
                head_x = self.x + s*head_height
                head_y = self.y - self.height()/2 - c*head_height
                dx, dy = cursor.x()-head_x, cursor.y()-head_y
                index = gaze_index(dx*c+dy*s, -dx*s+dy*c)
            elif state in ("left", "right"):
                index = int(self.walk_distance/(self.body_height*0.4)*len(self.frames[state])) % len(self.frames[state])
            else:
                _, count, interval = CLIPS[state]
                index = int(self.state_time/interval) % count
            sprite = self.frames[state][index]
            foot_x = sprite.width()/2
            ground = QRegion(self.frames["idle"][0].mask()).boundingRect().bottom()+1
        key = ("edge", state, index, corner, round(self.edge_angle, 4), self.edge_direction)
        if key == self.frame_key:
            return
        self.frame_key = key
        self.pixmap = QPixmap(self.size())
        self.pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(pivot_x, pivot_y)
        painter.rotate(self.edge_angle)
        painter.drawPixmap(QPointF(-foot_x, -ground), sprite)
        painter.end()
        self.setMask(QRegion(self.pixmap.mask()))
        self.update()

    @staticmethod
    def corner_foot_x(sprite):
        image = sprite.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = memoryview(image.constBits())
        stride = image.bytesPerLine()
        xs = [x for y in range(max(0, image.height()-max(2, image.height()//20)), image.height())
              for x in range(image.width()) if pixels[y*stride+x*4+3] >= 32]
        return (min(xs)+max(xs)+1)/2 if xs else sprite.width()/2

    def render_motion(self):
        self.frame_key = None
        self.pixmap = QPixmap(self.size())
        self.pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        center_x, center_y = self.width() / 2, self.height() / 2
        hanging, tuck, extend, airborne, crouch, recover = self.motion_frames
        if self.dragging:
            painter.translate(center_x, (self.height() - hanging.height()) / 2)
            painter.rotate(self.drag_angle)
            painter.drawPixmap(QPointF(-hanging.width() / 2, 0), hanging)
        elif self.state == "flip":
            progress = clamp(self.state_time / self.rotation_duration, 0, 1)
            # Faster rotation while tucked, slower as the legs extend. Vertical
            # motion is independent of this curve and follows constant gravity.
            if progress < 0.25:
                turn = progress * 0.8
            elif progress < 0.65:
                turn = 0.2 + (progress - 0.25) * 1.5
            else:
                turn = 0.8 + (progress - 0.65) * (0.2 / 0.35)
            angle = self.flip_angle + (180 - self.flip_angle) * turn
            self.motion_pose = 0 if progress < 0.16 else 1 if progress < 0.48 else 2 if progress < 0.84 else 3
            sprite = self.motion_frames[self.motion_pose]
            painter.translate(center_x, center_y)
            painter.rotate(angle - self.character.motion_angles[self.motion_pose])
            painter.drawPixmap(QPointF(-sprite.width() / 2, -sprite.height() / 2), sprite)
        else:
            # Let both feet contact the floor before the knees absorb the fall.
            sprite = airborne if self.state_time < 0.06 else crouch if self.state_time < 0.28 else recover
            painter.drawPixmap(QPointF(center_x - sprite.width() / 2,
                                      self.height() - sprite.height() - 4), sprite)
        painter.end()
        self.setMask(QRegion(self.pixmap.mask()))
        self.update()

    def begin_drag(self, cursor: QPoint):
        self.near_cursor = False
        self.dragging = True
        self.drag_time = 0
        self.drag_angle = 0
        self.drag_lean = 0
        self.target = None
        self.drag_cursor = cursor
        self.drag_velocity = (0.0, 0.0)
        self.drag_sample_time = time.monotonic()
        self.move_drag(cursor)

    def move_drag(self, cursor: QPoint):
        now = time.monotonic()
        if self.drag_cursor is not None:
            dx, dy = cursor.x() - self.drag_cursor.x(), cursor.y() - self.drag_cursor.y()
            self.drag_lean = clamp(self.drag_lean - dx * 0.25, -12, 12)
            if dx or dy:
                interval = max(now - self.drag_sample_time, 1 / 60)
                self.drag_velocity = tuple(0.65 * old + 0.35 * new / interval
                                           for old, new in zip(self.drag_velocity, (dx, dy)))
                self.drag_sample_time = now
        self.drag_cursor = cursor
        screen = QApplication.screenAt(cursor)
        if screen:
            self.screen_area = screen.availableGeometry()
        self.x = cursor.x()
        pivot_y = (self.height() - self.motion_frames[0].height()) / 2
        self.y = cursor.y() + self.height() - pivot_y
        self.anchor_x, self.anchor_y = self.x, self.y
        if self.roam_mode != "edge":
            self.confine()
        self.position_window()
        self.update_frame()

    def finish_drag(self):
        if self.roam_mode == "edge":
            cursor = self.drag_cursor or QCursor.pos()
            self.dragging = False
            self.drag_cursor = None
            self.attach_to_edge(cursor.x(), cursor.y())
            self.save_settings()
            return
        self.flip_angle = self.drag_angle
        hanging = self.motion_frames[0]
        angle = math.radians(self.drag_angle)
        # Continue from the actual hanging body's center: no upward lift or
        # jump when the mouse releases, even when the pendulum is tilted.
        self.fall_start = (self.x - math.sin(angle) * hanging.height() / 2,
                           self.y - self.height() / 2
                           + (math.cos(angle) - 1) * hanging.height() / 2)
        recent = time.monotonic() - self.drag_sample_time < 0.12
        vx, vy = self.drag_velocity if recent else (0.0, 0.0)
        limit = self.body_height * 1.2
        self.fall_velocity = (clamp(vx, -limit, limit), clamp(vy, -limit, limit))
        self.fall_gravity = self.body_height * 3.2
        self.landing_floor = self.screen_area.bottom() - 4
        landing_com = self.landing_floor - self.motion_frames[3].height() / 2
        distance = max(1.0, landing_com - self.fall_start[1])
        self.fall_duration = (-self.fall_velocity[1] + math.sqrt(
            self.fall_velocity[1] ** 2 + 2 * self.fall_gravity * distance)) / self.fall_gravity
        self.rotation_duration = min(0.7, self.fall_duration)
        self.dragging = False
        self.drag_cursor = None
        self.x = self.fall_start[0]
        self.y = self.fall_start[1] + self.height() / 2
        self.position_window()
        self.enter_state("flip", self.fall_duration)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = event.globalPosition().toPoint()
            self.press_origin = (self.x, self.y)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.press_global is None:
            return
        delta = event.globalPosition().toPoint() - self.press_global
        if delta.manhattanLength() >= QApplication.startDragDistance():
            if not self.dragging:
                self.begin_drag(event.globalPosition().toPoint())
        if self.dragging:
            self.move_drag(event.globalPosition().toPoint())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.press_global is None:
            return
        was_dragging = self.dragging
        self.press_global = None
        self.press_origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.target = None
        if was_dragging:
            self.finish_drag()
        elif not self.edge_jumping():
            self.enter_state(self.rng.choice(["wave", "jump"]))
        event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.populate_menu(menu)
        self.menu_open = True
        try:
            menu.exec(event.globalPos())
        finally:
            self.menu_open = False
            self.last_tick = time.monotonic()
            menu.deleteLater()

    def populate_menu(self, menu: QMenu):
        title = menu.addAction(f"{APP_NAME} · {self.character.name}")
        title.setEnabled(False)
        menu.addSeparator()
        characters = menu.addMenu("캐릭터 전환")
        character_group = QActionGroup(characters)
        character_group.setExclusive(True)
        for character_id, character in CHARACTERS.items():
            action = characters.addAction(character.name)
            action.setCheckable(True)
            action.setChecked(character_id == self.character_id)
            character_group.addAction(action)
            action.triggered.connect(lambda checked=False, key=character_id: self.set_character(key))
        sizes = menu.addMenu("캐릭터 크기")
        group = QActionGroup(sizes)
        group.setExclusive(True)
        for height, label in HEIGHT_PRESETS:
            action = sizes.addAction(f"{label} · {height}px")
            action.setCheckable(True)
            action.setChecked(height == self.body_height)
            group.addAction(action)
            action.triggered.connect(lambda checked=False, h=height: self.set_size(h))
        menu.addAction("행동 설정…", self.open_behavior_settings)
        menu.addSeparator()
        menu.addAction("종료", self.quit_pet)

    def open_behavior_settings(self):
        was_open = self.menu_open
        self.menu_open = True
        dialog = BehaviorSettingsDialog(self)
        try:
            dialog.exec()
        finally:
            self.menu_open = was_open
            self.last_tick = time.monotonic()
            dialog.deleteLater()

    def refresh_tray_menu(self):
        self.tray_menu.clear()
        self.populate_menu(self.tray_menu)
        self.menu_open = True
        self.tray_menu.aboutToHide.connect(self.tray_menu_closed, Qt.ConnectionType.UniqueConnection)

    def tray_menu_closed(self):
        self.menu_open = False
        self.last_tick = time.monotonic()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.reset_position()

    def set_radius(self, radius: int):
        self.radius = radius
        self.recenter()

    def set_speed(self, speed: float):
        self.speed = speed
        self.save_settings()

    def set_paused(self, value: bool):
        self.paused = value
        self.target = None
        if not self.edge_jumping():
            self.enter_state("idle", 1)
        self.save_settings()

    def set_stationary(self, value: bool):
        self.stationary = value
        self.target = None
        if self.state in ("left", "right") and not self.edge_jumping():
            self.enter_state("idle", 0.6)
        # A running pickup/landing or gesture finishes normally.
        if self.roam_mode != "edge" and not self.dragging and self.state not in ("flip", "land"):
            self.anchor_x, self.anchor_y = self.x, self.y
        self.save_settings()

    def set_click_through(self, value: bool):
        self.click_through = value
        self.apply_click_through()
        self.save_settings()

    def apply_click_through(self):
        # WindowTransparentForInput is handled by the native window system.
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self.click_through)
        if was_visible:
            self.show()

    def recenter(self):
        if self.roam_mode == "edge":
            self.attach_to_edge(self.x, self.y-self.height()/2)
            self.save_settings()
            return
        self.anchor_x, self.anchor_y = self.x, self.y
        self.target = None
        self.confine()
        self.position_window()
        self.enter_state("idle", 0.7)
        self.save_settings()

    def reset_position(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.screen_area = screen.availableGeometry()
        if self.roam_mode == "edge":
            self.attach_to_edge(self.screen_area.center().x(), self.screen_area.bottom()-8)
            self.save_settings()
            self.show()
            return
        self.x = self.screen_area.center().x()
        self.y = self.screen_area.bottom() - 12
        self.recenter()
        self.show()

    def quit_pet(self):
        self.save_settings()
        self.timer.stop()
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.quit_pet()
        event.accept()


class BehaviorSettingsDialog(QDialog):
    """One shared set of behavior controls, used by both character and tray menus."""

    def __init__(self, pet: DesktopPet):
        # A separate focusable window also works when the pet passes mouse input.
        super().__init__()
        self.pet = pet
        self.setWindowTitle(f"{APP_NAME} · 행동 설정")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowIcon(pet.windowIcon())
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        description = QLabel("설정은 모든 캐릭터에 공통으로 적용됩니다.\n기본값을 선택하거나 고급 설정에서 직접 입력하세요.")
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.height_input = QSpinBox()
        self.height_input.setRange(64, 400)
        self.height_input.setSuffix(" px")
        self.height_input.setValue(pet.body_height)
        self.radius = QSpinBox()
        self.radius.setRange(50, 800)
        self.radius.setSuffix(" px")
        self.radius.setValue(pet.radius)
        self.speed = QDoubleSpinBox()
        self.speed.setDecimals(2)
        self.speed.setRange(20, 100)
        self.speed.setSuffix(" px/초")
        self.speed.setValue(pet.speed)
        self.height_preset = self.make_preset_combo(HEIGHT_PRESETS, self.height_input)
        self.radius_preset = self.make_preset_combo(RADIUS_PRESETS, self.radius)
        self.speed_preset = self.make_preset_combo(SPEED_PRESETS, self.speed)
        self.roam_mode = QComboBox()
        self.roam_mode.addItem("일반 산책", "free")
        self.roam_mode.addItem("모니터 테두리 산책", "edge")
        self.roam_mode.setCurrentIndex(self.roam_mode.findData(pet.roam_mode))
        self.edge_direction = QComboBox()
        self.edge_direction.addItem("시계 방향", "clockwise")
        self.edge_direction.addItem("반시계 방향", "counterclockwise")
        self.edge_direction.setCurrentIndex(self.edge_direction.findData(pet.edge_direction))
        form.addRow("산책 방식", self.roam_mode)
        form.addRow("테두리를 도는 방향", self.edge_direction)
        form.addRow("캐릭터 크기", self.height_preset)
        form.addRow("산책 범위 (중심에서 좌우)", self.radius_preset)
        form.addRow("걷는 속도", self.speed_preset)
        layout.addLayout(form)
        edge_hint = QLabel("테두리 산책은 벽·천장까지 한 방향으로 돌며 잠시 쉬었다가\n다시 걷습니다. 코너에서는 점프로 90도 회전합니다.")
        edge_hint.setWordWrap(True)
        layout.addWidget(edge_hint)
        self.stationary = QCheckBox("제자리 모드 (걷기만 멈추기)")
        self.stationary.setChecked(pet.stationary)
        self.paused = QCheckBox("잠시 멈추기")
        self.paused.setChecked(pet.paused)
        self.click_through = QCheckBox("마우스 통과")
        self.click_through.setChecked(pet.click_through)
        for control in (self.stationary, self.paused, self.click_through):
            layout.addWidget(control)
        hint = QLabel("마우스 통과 중에는 작업 표시줄의 DeskMates 아이콘을\n우클릭하여 캐릭터와 설정을 바꿀 수 있습니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("고급 설정 · 직접 입력")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_toggle)
        self.advanced_panel = QWidget()
        advanced_form = QFormLayout(self.advanced_panel)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        advanced_form.addRow("캐릭터 높이 (64~400 px)", self.height_input)
        advanced_form.addRow("산책 범위 (50~800 px)", self.radius)
        advanced_form.addRow("걷는 속도 (20~100 px/초)", self.speed)
        layout.addWidget(self.advanced_panel)
        self.advanced_panel.hide()
        self.recenter_button = QPushButton("이 위치를 산책 중심으로")
        self.recenter_button.clicked.connect(pet.recenter)
        layout.addWidget(self.recenter_button)
        self.reset_button = QPushButton("화면 아래로 데려오기")
        self.reset_button.clicked.connect(pet.reset_position)
        layout.addWidget(self.reset_button)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                       | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.roam_mode.currentIndexChanged.connect(self.refresh_roaming_controls)
        self.refresh_roaming_controls()

    def refresh_roaming_controls(self):
        edge = self.roam_mode.currentData() == "edge"
        self.edge_direction.setEnabled(edge)
        self.radius_preset.setEnabled(not edge)
        self.radius.setEnabled(not edge)
        self.recenter_button.setEnabled(not edge)

    def make_preset_combo(self, presets, editor):
        combo = QComboBox()
        combo.setEditable(False)

        def refresh(value):
            # Keep custom saved values visible without replacing them with the
            # nearest preset; block callbacks while refreshing the item list.
            blocker = QSignalBlocker(combo)
            combo.clear()
            for number, label in presets:
                combo.addItem(f"{label} · {number:g}{editor.suffix()}", number)
            selected = combo.findData(value)
            if selected < 0:
                combo.addItem(f"사용자 지정 · {value:g}{editor.suffix()}", value)
                selected = combo.count() - 1
            combo.setCurrentIndex(selected)
            del blocker

        def select(index):
            if index >= 0:
                editor.setValue(combo.itemData(index))

        editor.valueChanged.connect(refresh)
        combo.currentIndexChanged.connect(select)
        refresh(editor.value())
        return combo

    def toggle_advanced(self, expanded):
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded
                                          else Qt.ArrowType.RightArrow)
        self.advanced_panel.setVisible(expanded)
        self.adjustSize()

    def accept(self):
        pet = self.pet
        pause_changed = pet.paused != self.paused.isChecked()
        radius_changed = pet.radius != self.radius.value()
        height_changed = pet.body_height != self.height_input.value()
        if height_changed:
            pet.set_size(self.height_input.value(), save=False)
        pet.radius = self.radius.value()
        pet.speed = self.speed.value()
        pet.stationary = self.stationary.isChecked()
        pet.paused = self.paused.isChecked()
        if not pet.dragging and pet.state not in ("flip", "land"):
            if radius_changed:
                pet.anchor_x, pet.anchor_y = pet.x, pet.y
                pet.confine()
                pet.position_window()
            if (radius_changed or height_changed or pause_changed or
                    (pet.stationary and pet.state in ("left", "right"))) and not pet.edge_jumping():
                pet.target = None
                pet.enter_state("idle", 0.7)
        pet.click_through = self.click_through.isChecked()
        pet.set_roaming(self.roam_mode.currentData(), self.edge_direction.currentData(), save=False)
        pet.apply_click_through()
        pet.save_settings()
        super().accept()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--smoke-seconds", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--character", choices=CHARACTERS, help="시작 캐릭터 선택")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("DeskMates")
    app.setQuitOnLastWindowClosed(False)
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(data_dir / "pet.log"), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = QLockFile(str(data_dir / "pet.lock"))
    if not lock.tryLock(100):
        return 0
    pet = DesktopPet(data_dir / "settings.json")
    if args.character:
        pet.set_character(args.character)
    pet.show()
    app.aboutToQuit.connect(pet.save_settings)
    if args.smoke_seconds is not None:
        QTimer.singleShot(round(args.smoke_seconds * 1000), pet.quit_pet)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
