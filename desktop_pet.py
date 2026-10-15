"""A small, local-only Windows desktop companion made from the supplied sheet."""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
import random
import sys
import time

from edge_path import EdgeRoute
from appetite import Appetite, BREAD_LIMIT

from PySide6.QtCore import QLockFile, QPoint, QPointF, QRect, QSize, QSignalBlocker, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QActionGroup, QColor, QCursor, QIcon, QImage, QPainter, QPen, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMenu, QPushButton,
                              QRadioButton, QSpinBox, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget)


APP_NAME = "DeskMates"
CELL_W, CELL_H = 192, 208
# One shared crop for every frame: it preserves the sheet's body proportions
# and foot alignment, including its intentional jumps and head movements.
CROP_X, CROP_W = 32, 128
BODY_HEIGHT = 198
# Artwork orientations, measured clockwise from the inverted hanging pose.
MOTION_ANGLES = (0.0, 30.0, 140.0, 180.0)
from character_resources import (Character, CATALOG, CLIPS, discover_characters, load_art,
                                 action_spec, playback_index, standing_feet, load_pose_sheet)
CHARACTERS = discover_characters()
DEFAULT_CHARACTER = "liberta"
HEIGHT_PRESETS = ((80, "아주 작게"), (120, "작게"), (160, "기본"),
                  (200, "크게"), (240, "아주 크게"), (320, "특대"))
RADIUS_PRESETS = ((100, "좁게"), (220, "보통"), (420, "넓게"), (700, "아주 넓게"))
SPEED_PRESETS = ((28, "느림"), (46, "보통"), (75, "빠름"))
WINDOWS_TOOLS = {"notepad": ("메모장", "notepad.exe"),
                 "paint": ("그림판", "mspaint.exe"),
                 "calculator": ("계산기", "calc.exe")}
FEED_STATES = ("feed_drop", "feed_eat", "feed_happy", "feed_refuse")
ANIMATION_CLIPS = {**CLIPS, "hungry": (0, CATALOG['actions']['hungry']['frames'],
                                     1/CATALOG['actions']['hungry']['fps'])}
FULL_MESSAGES = ("너무 배불러…\n이제 못 먹겠어!", "내 배는 빵 보관함이 아니야…!",
                 "한 입도 못 먹겠어!\n조금만 쉬자…")


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def gaze_index(dx: float, dy: float) -> int:
    """The supplied look row is clockwise: up, right, down, left."""
    return round(math.atan2(dx, -dy) / (2 * math.pi) * 16) % 16


def load_feeding_art(name: str) -> QPixmap:
    """Discard invisible generation residue before sprite bounds/hit testing."""
    image = QImage(str(resource_path(name))).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise ValueError(f"빵 주기 이미지를 불러올 수 없습니다: {name}")
    pixels = memoryview(image.bits())
    for offset in range(3, image.sizeInBytes(), 4):
        if pixels[offset] < 32:
            pixels[offset] = 0
    return QPixmap.fromImage(image)


class FallingBread(QWidget):
    """A tiny visual-only window; falling food never takes desktop clicks."""

    def __init__(self, pet, sprite):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.sprite = sprite
        self.setFixedSize(sprite.size())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.sprite)


class SpeechBubble(QLabel):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#c79652"), 2))
        painter.setBrush(QColor("#fff3d5"))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)
        painter.end()
        super().paintEvent(event)


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
        saved_appetites = self.settings.get("appetites", {})
        if not isinstance(saved_appetites, dict):
            saved_appetites = {}
        self.saved_appetites = saved_appetites.copy()
        now = time.time()
        self.appetites = {key: Appetite.restore(saved_appetites.get(key), now) for key in CHARACTERS}
        self.meal_pending = False
        self.feed_refusing = False
        self.refusal_count = 0
        self.next_hunger = time.monotonic()+self.rng.uniform(6, 10)
        self.body_height = int(clamp(self.settings.get("height", 160), 64, 400))
        self.radius = int(clamp(self.settings.get("radius", 220), 50, 800))
        self.speed = float(clamp(self.settings.get("speed", 46), 20, 100))
        self.paused = bool(self.settings.get("paused", False))
        self.stationary = bool(self.settings.get("stationary", False))
        self.click_through = bool(self.settings.get("click_through", False))
        self.show_windows_tools = bool(self.settings.get("show_windows_tools", False))
        self.feeding_enabled = bool(self.settings.get("feeding_enabled", True))
        self.feed_hover = 0.0
        self.feed_cooldown = 0.0
        self.feed_start = QPointF()
        self.feed_end = QPointF()
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

        bread = load_feeding_art("assets/bread.png")
        bread = bread.copy(QRegion(bread.mask()).boundingRect())
        bread = bread.scaled(30, 30, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.bread_button = QToolButton(self)
        self.bread_button.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                        | Qt.WindowType.WindowStaysOnTopHint
                                        | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.bread_button.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.bread_button.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.bread_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bread_button.setFixedSize(44, 44)
        self.bread_button.setIcon(QIcon(bread))
        self.bread_button.setIconSize(QSize(30, 30))
        self.bread_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bread_button.setToolTip("빵 주기")
        self.bread_button.setAccessibleName("빵 주기")
        self.bread_button.setStyleSheet(
            "QToolButton { background: #fff3d5; border: 2px solid #c79652; border-radius: 16px; }"
            "QToolButton:hover { background: #ffe1a0; border-color: #99662c; }"
            "QToolButton:pressed { background: #f5c975; }")
        self.bread_button.clicked.connect(self.start_feeding)
        self.bread_button.hide()
        self.falling_bread = FallingBread(self, bread)
        self.falling_bread.hide()
        self.speech = SpeechBubble(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.WindowStaysOnTopHint
                             | Qt.WindowType.WindowDoesNotAcceptFocus
                             | Qt.WindowType.WindowTransparentForInput)
        self.speech.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.speech.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.speech.setWordWrap(True)
        self.speech.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speech.setFixedWidth(240)
        self.speech.setContentsMargins(12, 10, 12, 10)
        self.speech.setStyleSheet("QLabel { color: #594332; font-size: 14px; }")
        self.speech.hide()
        self.speech_timer = QTimer(self)
        self.speech_timer.setSingleShot(True)
        self.speech_timer.timeout.connect(self.speech.hide)

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
        self.art = load_art(self.character)
        for key in ("originals", "motion_originals", "motion_reference_height", "walk_originals",
                    "corner_originals", "feed_originals", "hunger_originals", "refusal_originals"):
            setattr(self, key, getattr(self.art, key))

    def clip(self, state):
        if state not in self.frames or state == 'gaze':
            return 0, 1, .1  # Physics/food/gaze transitions retain their existing phase timers.
        spec = action_spec(self.character, state)
        return 0, len(self.frames[state]), 1/spec.get("fps", 10) if spec.get("fps",10) else .1

    def update_character_identity(self):
        icon = QIcon(self.originals["idle"][0])
        self.setWindowIcon(icon)
        self.tray.setIcon(icon)
        self.tray.setToolTip(f"{APP_NAME} · {self.character.name} · 우클릭으로 설정 / 종료")

    def set_character(self, character_id: str):
        if character_id not in CHARACTERS or character_id == self.character_id:
            return
        self.cancel_feeding()
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
        for appetite in self.appetites.values():
            appetite.digest(time.time())
        data = {"character": self.character_id, "height": self.body_height, "radius": self.radius,
                "speed": self.speed, "paused": self.paused,
                "stationary": self.stationary,
                "click_through": self.click_through,
                "show_windows_tools": self.show_windows_tools,
                "feeding_enabled": self.feeding_enabled,
                "appetites": {**self.saved_appetites,
                              **{key: value.as_dict() for key, value in self.appetites.items()}},
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
        self.cancel_feeding()
        self.body_height = int(clamp(height, 64, 400))
        self.art.resize(self.body_height)
        for key in ("frames", "motion_frames", "corner_frames", "feed_frames", "feed_look_frame", "refusal_frames"):
            setattr(self, key, getattr(self.art, key))
        # A square canvas holds the rotated sprite without clipping limbs.
        largest_diagonal = max(math.hypot(p.width(), p.height()) for p in
                               self.motion_frames + self.feed_frames + self.refusal_frames + [p for frames in self.frames.values() for p in frames])
        side = math.ceil(largest_diagonal) + 16
        if self.roam_mode == "edge":
            # Rotation is around the feet, so the canvas needs a full body
            # radius on each side of that pivot rather than a center pivot.
            sprites = [p for frames in self.frames.values() for p in frames] + self.corner_frames + self.feed_frames + self.refusal_frames
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
        if hasattr(self, "speech") and self.speech.isVisible():
            self.position_speech()

    def refresh_screens(self, *_):
        self.cancel_feeding()
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
        sprites = [p for frames in self.frames.values() for p in frames] + self.corner_frames + self.feed_frames + self.refusal_frames
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
        self.cancel_feeding()
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
        if state != "gaze" and hasattr(self, "bread_button"):
            self.bread_button.hide()
            self.feed_hover = 0.0
        if self.state in FEED_STATES and state not in FEED_STATES:
            self.hide_food(keep_speech=True)
            self.feed_cooldown = 3.0
            self.meal_pending = self.feed_refusing = False
        self.state = state
        self.state_time = 0
        if state in ("left", "right"):
            self.walk_distance = 0.0
        if duration is None:
            _, count, interval = self.clip(state)
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
        if (self.feeding_enabled and self.appetite.stacks == 0
                and time.monotonic() >= self.next_hunger):
            if self.roam_mode == "edge" and self.state in ("left", "right"):
                self.edge_rest_pending = True
            self.next_hunger = time.monotonic()+self.rng.uniform(12, 20)
            self.enter_state("hungry")
            self.say("꼬르륵…\n빵 먹고 싶어.", 1800)
            return
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

    @property
    def appetite(self):
        appetite = self.appetites[self.character_id]
        appetite.digest(time.time())
        return appetite

    def position_speech(self):
        body = QRegion(self.pixmap.mask()).boundingRect().translated(self.pos())
        width, height = self.speech.width(), self.speech.height()
        candidates = (QRect(body.center().x()-width//2, body.top()-height-10, width, height),
                      QRect(body.center().x()-width//2, body.bottom()+10, width, height),
                      QRect(body.right()+10, body.center().y()-height//2, width, height),
                      QRect(body.left()-width-10, body.center().y()-height//2, width, height))
        area = self.screen_area
        rect = next((rect for rect in candidates if area.contains(rect)), candidates[0])
        self.speech.move(round(clamp(rect.x(), area.left(), area.right()+1-width)),
                         round(clamp(rect.y(), area.top(), area.bottom()+1-height)))

    def say(self, message, milliseconds=3500):
        if not self.isVisible():
            return
        self.speech.setText(message)
        self.speech.adjustSize()
        self.position_speech()
        self.speech.show()
        self.speech_timer.start(milliseconds)

    def hide_food(self, *, keep_speech=False):
        self.feed_hover = 0.0
        if hasattr(self, "bread_button"):
            self.bread_button.hide()
        if hasattr(self, "falling_bread"):
            self.falling_bread.hide()
        if not keep_speech and hasattr(self, "speech"):
            self.speech.hide()
            self.speech_timer.stop()

    def cancel_feeding(self):
        self.hide_food()
        if self.state in FEED_STATES:
            self.enter_state("idle", 0.8)

    def feeding_point(self, height):
        """World point above the feet, following a wall/ceiling orientation."""
        if self.roam_mode == "edge":
            angle = math.radians(self.edge_angle)
            return QPointF(self.x + math.sin(angle)*height,
                           self.y - self.height()/2 - math.cos(angle)*height)
        idle = self.frames["idle"][0]
        ground = QRegion(idle.mask()).boundingRect().bottom()+1
        return QPointF(self.x, self.y - idle.height() + ground - height)

    def update_bread_button(self, dt):
        if (not self.feeding_enabled or self.click_through or self.menu_open
                or self.feed_cooldown > 0 or self.speech.isVisible() or not self.isVisible()):
            self.bread_button.hide()
            self.feed_hover = 0.0
            return
        self.feed_hover += dt
        if self.feed_hover < 0.7:
            return
        point = self.feeding_point(self.body_height + 36)
        area = self.screen_area
        # This separate 44px window is the only extra clickable area.
        self.bread_button.move(round(clamp(point.x()-22, area.left(), area.right()-43)),
                               round(clamp(point.y()-22, area.top(), area.bottom()-43)))
        self.bread_button.show()
        self.bread_button.setToolTip(f"빵 주기 · {self.appetite.label} ({self.appetite.stacks}/{BREAD_LIMIT})")

    def start_feeding(self):
        if (not self.feeding_enabled or self.click_through or self.menu_open or self.dragging
                or self.state in FEED_STATES + ("flip", "land") or self.edge_jumping()
                or self.feed_cooldown > 0 or not self.bread_button.isVisible()):
            return
        self.feed_start = QPointF(self.bread_button.geometry().center())
        self.feed_end = self.feeding_point(self.body_height * 0.58)
        self.bread_button.hide()
        self.near_cursor = False
        self.target = None
        self.edge_rest_pending = False
        self.feed_refusing = self.appetite.stacks >= BREAD_LIMIT
        self.meal_pending = not self.feed_refusing
        self.enter_state("feed_drop", 0.65)

    def advance_feeding(self, dt):
        # Feeding is an explicit interaction and also works while auto-roaming
        # is paused. No edge progress/direction or saved walk anchor is changed.
        self.state_time += dt
        if self.state_time >= self.state_duration:
            if self.state == "feed_drop":
                self.falling_bread.hide()
                if self.feed_refusing:
                    self.enter_state("feed_refuse", 2.8)
                    self.say(FULL_MESSAGES[self.refusal_count % len(FULL_MESSAGES)])
                    self.refusal_count += 1
                else:
                    self.enter_state("feed_eat", 1.6)
            elif self.state == "feed_eat":
                self.enter_state("feed_happy", 0.85)
                if self.meal_pending:
                    self.meal_pending = False
                    self.appetite.eat(time.time())
                    self.save_settings()
                    if self.appetite.stacks >= BREAD_LIMIT:
                        self.say(FULL_MESSAGES[0])
            else:
                self.near_cursor = False
                self.gaze_elapsed = 0.0
                self.next_gaze = self.rng.uniform(6, 12)
                self.enter_state("idle", 0.8)
                if self.roam_mode == "edge" and not self.paused and not self.stationary:
                    self.start_walk()
                return
        self.update_frame()

    def render_feeding(self):
        ground = QRegion(self.frames["idle"][0].mask()).boundingRect().bottom()+1
        if self.state == "feed_drop":
            progress = clamp(self.state_time/self.state_duration, 0, 1)
            point = self.feed_start + (self.feed_end-self.feed_start) * progress**2
            self.falling_bread.move(round(point.x()-self.falling_bread.width()/2),
                                    round(point.y()-self.falling_bread.height()/2))
            if progress < 0.85:
                self.falling_bread.show()
                sprite = self.feed_look_frame
            else:
                self.falling_bread.hide()
                sprite = self.refusal_frames[0] if self.feed_refusing else self.feed_frames[0]
        elif self.state == "feed_refuse":
            self.falling_bread.hide()
            index = 3 if self.state_time >= 1.3 else 1+int(self.state_time/0.22) % 2
            sprite = self.refusal_frames[index]
        else:
            self.falling_bread.hide()
            index = 1 + (int(self.state_time/0.22) % 2) if self.state == "feed_eat" else 3
            sprite = self.feed_frames[index]
        self.pixmap = QPixmap(self.size())
        self.pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.roam_mode == "edge":
            painter.translate(self.width()/2, self.height()/2)
            painter.rotate(self.edge_angle)
            origin = QPointF(-sprite.width()/2, -ground)
        else:
            idle = self.frames["idle"][0]
            # Match normal idle rendering's integer placement as well as its
            # shoe anchor; a half-pixel translation can otherwise shift edges.
            origin = QPointF(round((self.width()-sprite.width())/2), self.height()-idle.height())
        painter.drawPixmap(origin, sprite)
        painter.end()
        self.frame_key = None
        self.update()

    def advance(self, dt: float, cursor: QPoint | None = None):
        if any([appetite.digest(time.time()) for appetite in self.appetites.values()]):
            self.save_settings()
        self.feed_cooldown = max(0.0, self.feed_cooldown - dt)
        if self.menu_open:
            self.hide_food()
            return
        if self.state in FEED_STATES:
            self.advance_feeding(dt)
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
            self.update_bread_button(dt)
            return
        self.feed_hover = 0.0
        self.bread_button.hide()
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
        if self.speech.isVisible():
            self.position_speech()

    def update_frame(self, cursor: QPoint | None = None):
        if self.state in FEED_STATES:
            self.render_feeding()
            return
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
            _, count, interval = self.clip(state)
            if state in ("left", "right") and self.walk_originals:
                # A cycle covers a fixed stride at the current body size, so
                # slower travel also slows the legs instead of sliding the feet.
                count = len(self.frames[state])
                index = int(self.walk_distance / (self.body_height * 0.4) * count) % count
            else:
                index = playback_index(self.character, state, self.state_time, count)
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
                _, count, interval = self.clip(state)
                index = playback_index(self.character, state, self.state_time, count)
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
        self.update()

    def begin_drag(self, cursor: QPoint):
        self.cancel_feeding()
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
        # Replace transparent pixels as well as visible ones. A changing
        # native window mask clips the backing-store clear, leaving old poses
        # behind during rotation. Windows layered windows already pass input
        # through zero-alpha pixels, so no per-frame setMask is needed.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
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
        elif not self.edge_jumping() and self.state not in FEED_STATES:
            self.enter_state(self.rng.choice(["wave", "jump"]))
        event.accept()

    def contextMenuEvent(self, event):
        self.hide_food()
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
        if self.show_windows_tools:
            for tool_id, (label, _) in WINDOWS_TOOLS.items():
                action = menu.addAction(label)
                action.triggered.connect(lambda checked=False, key=tool_id: self.launch_windows_tool(key))
            menu.addSeparator()
        title = menu.addAction(f"{APP_NAME} · {self.character.name}")
        title.setEnabled(False)
        status = menu.addAction(f"{self.appetite.label} · 빵 {self.appetite.stacks}/{BREAD_LIMIT}")
        status.setEnabled(False)
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
        click_through = menu.addAction("마우스 통과")
        click_through.setCheckable(True)
        click_through.setChecked(self.click_through)
        click_through.toggled.connect(self.set_click_through)
        menu.addAction("종료", self.quit_pet)

    def launch_windows_tool(self, tool_id: str):
        label, executable = WINDOWS_TOOLS[tool_id]
        program = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / executable)
        try:
            if tool_id == "paint":
                # Store Paint may have no mspaint.exe on PATH; its registered
                # protocol activates that version directly.
                try:
                    os.startfile("ms-paint:")
                    return
                except OSError:
                    pass
            os.startfile(program)
        except OSError:
            logging.exception("Could not launch Windows tool %s", tool_id)
            self.tray.showMessage(APP_NAME, f"{label}를 실행할 수 없습니다. Windows에 설치되어 있는지 확인해 주세요.",
                                  QSystemTrayIcon.MessageIcon.Warning, 4000)

    def open_behavior_settings(self):
        self.hide_food()
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
        self.hide_food()
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
        self.cancel_feeding()
        # WindowTransparentForInput is handled by the native window system.
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self.click_through)
        if was_visible:
            self.show()

    def recenter(self):
        self.cancel_feeding()
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
        self.cancel_feeding()
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
        self.hide_food()
        self.save_settings()
        self.timer.stop()
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.quit_pet()
        event.accept()

    def hideEvent(self, event):
        self.cancel_feeding()
        super().hideEvent(event)


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
        description = QLabel("설정은 모든 캐릭터에 공통으로 적용됩니다.")
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
        walking_box = QGroupBox("산책 방식")
        walking_layout = QVBoxLayout(walking_box)
        radio_layout = QHBoxLayout()
        self.free_radio = QRadioButton("일반 산책")
        self.edge_radio = QRadioButton("모니터 테두리 산책")
        self.roam_group = QButtonGroup(self)
        self.roam_group.addButton(self.free_radio)
        self.roam_group.addButton(self.edge_radio)
        self.free_radio.setChecked(pet.roam_mode == "free")
        self.edge_radio.setChecked(pet.roam_mode == "edge")
        radio_layout.addWidget(self.free_radio)
        radio_layout.addWidget(self.edge_radio)
        walking_layout.addLayout(radio_layout)
        self.free_options = QWidget()
        free_form = QFormLayout(self.free_options)
        free_form.setContentsMargins(0, 0, 0, 0)
        free_form.addRow("산책 범위", self.radius_preset)
        walking_layout.addWidget(self.free_options)
        self.edge_options = QWidget()
        edge_layout = QVBoxLayout(self.edge_options)
        edge_layout.setContentsMargins(0, 0, 0, 0)
        edge_form = QFormLayout()
        self.edge_direction = QComboBox()
        self.edge_direction.addItem("시계 방향", "clockwise")
        self.edge_direction.addItem("반시계 방향", "counterclockwise")
        self.edge_direction.setCurrentIndex(self.edge_direction.findData(pet.edge_direction))
        edge_form.addRow("도는 방향", self.edge_direction)
        edge_layout.addLayout(edge_form)
        self.edge_hint = QLabel("모니터의 벽·천장까지 한 방향으로 돌며 잠시 쉬었다가\n"
                                "다시 걷습니다. 코너에서는 점프로 90도 회전합니다.")
        self.edge_hint.setWordWrap(True)
        edge_layout.addWidget(self.edge_hint)
        walking_layout.addWidget(self.edge_options)
        layout.addWidget(walking_box)
        form.addRow("캐릭터 크기", self.height_preset)
        form.addRow("걷는 속도", self.speed_preset)
        layout.addLayout(form)
        self.stationary = QCheckBox("제자리 모드 (걷기만 멈추기)")
        self.stationary.setChecked(pet.stationary)
        self.paused = QCheckBox("잠시 멈추기")
        self.paused.setChecked(pet.paused)
        self.show_windows_tools = QCheckBox("윈도우 기본 도구 표시")
        self.show_windows_tools.setChecked(pet.show_windows_tools)
        self.show_windows_tools.setToolTip("우클릭 메뉴 상단에 메모장·그림판·계산기를 표시합니다.")
        self.feeding_enabled = QCheckBox("빵 주기 버튼 표시")
        self.feeding_enabled.setChecked(pet.feeding_enabled)
        self.feeding_enabled.setToolTip("가까운 커서를 약 0.7초 바라보면 빵 버튼이 나타납니다. 클릭하면 받아먹습니다.")
        for control in (self.stationary, self.paused, self.feeding_enabled):
            layout.addWidget(control)
        feeding_hint = QLabel("빵 0개: 배고픔 · 1~2개: 보통 · 3~4개: 배부름\n"
                              "5개면 받아들고 거절합니다. 스택은 1분마다 1개씩 줄어듭니다.")
        feeding_hint.setWordWrap(True)
        layout.addWidget(feeding_hint)
        self.recenter_button = QPushButton("이 위치를 산책 중심으로")
        self.recenter_button.clicked.connect(pet.recenter)
        layout.addWidget(self.recenter_button)
        self.reset_button = QPushButton("화면 아래로 데려오기")
        self.reset_button.clicked.connect(pet.reset_position)
        layout.addWidget(self.reset_button)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("고급")
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.toggle_advanced)
        layout.addWidget(self.advanced_toggle)
        self.advanced_panel = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.advanced_form = QFormLayout()
        self.advanced_form.addRow("캐릭터 높이 (64~400 px)", self.height_input)
        self.advanced_form.addRow("산책 범위 (50~800 px)", self.radius)
        self.advanced_form.addRow("걷는 속도 (20~100 px/초)", self.speed)
        advanced_layout.addLayout(self.advanced_form)
        advanced_layout.addWidget(self.show_windows_tools)
        layout.addWidget(self.advanced_panel)
        self.advanced_panel.hide()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                       | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.free_radio.toggled.connect(self.refresh_roaming_controls)
        self.edge_radio.toggled.connect(self.refresh_roaming_controls)
        self.refresh_roaming_controls()

    def refresh_roaming_controls(self):
        edge = self.edge_radio.isChecked()
        self.free_options.setVisible(not edge)
        self.edge_options.setVisible(edge)
        self.recenter_button.setVisible(not edge)
        self.advanced_form.setRowVisible(self.radius, not edge)
        self.layout().activate()
        self.adjustSize()

    def make_preset_combo(self, presets, editor):
        combo = QComboBox()
        combo.setEditable(False)

        def refresh(value):
            # Keep custom saved values visible without replacing them with the
            # nearest preset; block callbacks while refreshing the item list.
            blocker = QSignalBlocker(combo)
            combo.clear()
            for number, label in presets:
                combo.addItem(label, number)
            selected = combo.findData(value)
            if selected < 0:
                combo.addItem("사용자 지정", value)
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
        pet.show_windows_tools = self.show_windows_tools.isChecked()
        pet.feeding_enabled = self.feeding_enabled.isChecked()
        pet.set_roaming("edge" if self.edge_radio.isChecked() else "free",
                        self.edge_direction.currentData(), save=False)
        pet.save_settings()
        super().accept()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--smoke-seconds", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--character", choices=CHARACTERS, help="시작 캐릭터 선택")
    parser.add_argument("--settings-path", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("DeskMates")
    app.setQuitOnLastWindowClosed(False)
    data_dir = (args.settings_path.resolve().parent if args.settings_path else
                Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)))
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(data_dir / "pet.log"), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    lock = QLockFile(str(data_dir / "pet.lock"))
    if not lock.tryLock(100):
        return 0
    pet = DesktopPet(args.settings_path.resolve() if args.settings_path else data_dir / "settings.json")
    if args.character:
        pet.set_character(args.character)
    pet.show()
    app.aboutToQuit.connect(pet.save_settings)
    if args.smoke_seconds is not None:
        QTimer.singleShot(round(args.smoke_seconds * 1000), pet.quit_pet)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
