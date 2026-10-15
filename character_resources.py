"""Manifest-based character registry and pixel-compatible legacy art adapter."""
from __future__ import annotations
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import sys
from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QRegion, QTransform

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CATALOG = json.loads((ROOT / "animation_catalog.json").read_text(encoding="utf-8"))
CLIPS = {key: (i, spec["frames"], 1/spec["fps"]) for i,(key,spec) in enumerate(CATALOG["actions"].items()) if key in ("idle","right","left","wave","jump","bow","shy","think","tilt")}
CELL_W, CELL_H = 192, 208

@dataclass(frozen=True)
class Character:
    manifest: Path
    data: dict
    @property
    def id(self): return self.data["id"]
    @property
    def name(self): return self.data["name"]
    @property
    def profile(self): return self.data.get("profile", {})
    def __getattr__(self, key):
        if key == "motion_angles": return self.profile.get(key, (0,30,140,180))
        if key == "body_height": return self.profile.get(key, self.data.get("body_height",320))
        try: return self.profile[key]
        except KeyError: raise AttributeError(key) from None
    def path(self, name): return (self.manifest.parent/name).resolve()


def action_spec(character, action):
    return {**CATALOG['actions'].get(action, {}),
            **character.data.get('animations', {}).get(action, {})}


def extract_frames(character, action, *, fallback=True, visited=()):
    """Read variable-sized strips, explicit rectangles or individual files."""
    if action in visited:
        raise ValueError(f'Fallback cycle: {visited + (action,)}')
    spec = character.data.get('animations', {}).get(action, {})
    if not spec.get('file') and not spec.get('files'):
        target = action_spec(character, action).get('fallback')
        if fallback and target:
            return extract_frames(character, target, visited=visited+(action,))
        raise ValueError(f'{character.id}: missing animation {action}')
    if spec.get('files'):
        frames = [QPixmap(str(character.path(name))) for name in spec['files']]
        if any(p.isNull() for p in frames):
            raise ValueError(f'{action}: unreadable frame file')
    else:
        path = character.path(spec['file'])
        sheet = load_feeding_art(str(path)) if spec.get('clean_alpha') else QPixmap(str(path))
        if sheet.isNull():
            raise ValueError(f'{action}: unreadable image {path}')
        rects = spec.get('rects')
        if rects is None:
            cols, rows = spec['grid']
            cw, ch = sheet.width()//cols, sheet.height()//rows
            x,y,w,h = spec.get('cell_crop', [0,0,cw,ch])
            rects = [[i%cols*cw+x, i//cols*ch+y,w,h]
                     for i in spec.get('indices', range(cols*rows))]
        for rect in rects:
            if len(rect)!=4 or rect[2]<=0 or rect[3]<=0 or not sheet.rect().contains(QRect(*rect)):
                raise ValueError(f'{action}: out of bounds rectangle {rect}')
        frames = [sheet.copy(*rect) for rect in rects]
    if not frames:
        raise ValueError(f'{action}: empty sequence')
    crop = spec.get('crop', 'none')
    if crop == 'shared_mask':
        bounds = QRect()
        for frame in frames:
            bounds = bounds.united(QRegion(frame.mask()).boundingRect())
        if bounds.isEmpty(): raise ValueError(f'{action}: empty sheet')
        frames = [p.copy(bounds) for p in frames]
    elif crop == 'alpha_bounds':
        cropped = []
        for p in frames:
            im = p.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            bits = memoryview(im.constBits())
            points = [(x,y) for y in range(im.height()) for x in range(im.width())
                      if bits[y*im.bytesPerLine()+4*x+3]>=32]
            if not points: raise ValueError(f'{action}: empty frame')
            xs,ys = zip(*points)
            cropped.append(p.copy(min(xs),min(ys),max(xs)-min(xs)+1,max(ys)-min(ys)+1))
        frames = cropped
    if spec.get('mirror'):
        frames = [p.transformed(QTransform().scale(-1,1)) for p in frames]
    return frames


def discover_characters(extra_roots=None):
    """Built-ins win ID collisions. Invalid external packs cannot break startup."""
    roots = [ROOT/'characters']
    external = Path(sys.executable).parent/'characters' if getattr(sys,'frozen',False) else None
    if external and external.resolve()!=roots[0].resolve(): roots.append(external)
    roots.extend(Path(p) for p in (extra_roots if extra_roots is not None else
                  filter(None, os.environ.get('DESKMATES_CHARACTER_PATH','').split(os.pathsep))))
    found = {}
    for root in roots:
        for path in sorted(root.glob('*/character.json')):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data,dict): raise ValueError('Manifest must be an object')
                if data.get('enabled', True) is False: continue
                if data.get('version')!=1 or not isinstance(data.get('id'),str) or not data.get('name'):
                    raise ValueError('Invalid character manifest')
                character = Character(path.resolve(), data)
                # Structural checks work before QApplication exists.
                from character_validation import validate_structure
                report = validate_structure(character)
                if report['errors']: raise ValueError('; '.join(report['errors']))
                if character.id in found:
                    logging.warning('Duplicate character ID ignored: %s', path)
                    continue
                found[character.id] = character
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                logging.warning('Character pack skipped: %s: %s', path, error)
    return found


def slots(frames, count):
    """Map directional/physics phase slots; optional actions may have one pose."""
    return [frames[min(len(frames)-1, i*len(frames)//count)] for i in range(count)]


class ManifestArt:
    """New packs use one anatomical scale and declared anchors, never per-frame fitting."""
    def __init__(self, character):
        self.character = character
        self.raw = {key: extract_frames(character,key) for key in CATALOG['actions']}
        self.originals = {key:self.raw[key] for key in CLIPS}
        self.originals['gaze'] = slots(self.raw['gaze'],16)
        self.motion_originals = slots(self.raw['motion'],6)
        self.corner_originals = slots(self.raw['corner'],4)
        self.feed_originals = slots(self.raw['feeding'],4)
        self.hunger_originals = self.raw['hungry']
        self.refusal_originals = slots(self.raw['refusal'],4)
        self.motion_reference_height = character.body_height
        self.walk_originals = []

    def resize(self, height):
        scale = height/self.character.body_height
        idle_source = self.raw['idle'][0]
        target = QSize(max(1,round(idle_source.width()*scale)),
                       max(1,round(idle_source.height()*scale)))
        idle_anchor = self.character.data.get('anchor',[idle_source.width()/2,idle_source.height()])
        def normalized(action):
            spec = action_spec(self.character, action)
            # Fallback image has the fallback anchor as well.
            actual = action
            seen = set()
            while not self.character.data['animations'].get(actual,{}).get('file') and not self.character.data['animations'].get(actual,{}).get('files'):
                if actual in seen: raise ValueError('Fallback cycle')
                seen.add(actual)
                actual = action_spec(self.character,actual).get('fallback')
                if not actual: break
            spec = action_spec(self.character, actual or action)
            anchors = spec.get('anchors')
            anchor = spec.get('anchor',self.character.data.get('anchor',idle_anchor))
            if not isinstance(anchor,list): anchor=idle_anchor
            result=[]
            for i,source in enumerate(self.raw[action]):
                a = anchors[i] if anchors else anchor
                sprite = source.scaledToHeight(max(1,round(source.height()*scale)), Qt.TransformationMode.SmoothTransformation)
                frame=QPixmap(target); frame.fill(Qt.GlobalColor.transparent)
                painter=QPainter(frame)
                painter.drawPixmap(round((idle_anchor[0]-a[0])*scale),round((idle_anchor[1]-a[1])*scale),sprite)
                painter.end(); result.append(frame)
            return result
        self.frames={key:normalized(key) for key in CATALOG['actions']}
        self.frames['gaze']=slots(self.frames['gaze'],16)
        self.motion_frames=slots(self.frames['motion'],6)
        self.corner_frames=slots(self.frames['corner'],4)
        self.feed_frames=slots(self.frames['feeding'],4)
        self.refusal_frames=slots(self.frames['refusal'],4)
        self.feed_look_frame=self.frames['gaze'][0]
        return self


def load_art(character):
    return LegacyArt(character) if character.data.get('renderer')=='legacy-v1' else ManifestArt(character)


def playback_index(character, action, elapsed, count):
    spec=action_spec(character,action)
    fps=spec.get('fps',0)
    step=int(elapsed*fps) if fps else 0
    # Legacy gestures intentionally repeat until the existing state transition.
    if character.data.get('renderer')=='legacy-v1':
        return int(elapsed/(1/fps)) % count if fps else 0
    mode=spec.get('loop','once')
    if mode=='pingpong' and count>1:
        n=step%(2*count-2); return min(n,2*count-2-n)
    return step%count if mode=='loop' else min(count-1,step)

def load_feeding_art(name: str) -> QPixmap:
    """Discard invisible generation residue before sprite bounds/hit testing."""
    image = QImage(str(Path(name))).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        raise ValueError(f"빵 주기 이미지를 불러올 수 없습니다: {name}")
    pixels = memoryview(image.bits())
    for offset in range(3, image.sizeInBytes(), 4):
        if pixels[offset] < 32:
            pixels[offset] = 0
    return QPixmap.fromImage(image)


def standing_feet(sprite: QPixmap) -> QPointF:
    """Locate the midpoint of both shoes and the floor of a standing pose."""
    image = sprite.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = memoryview(image.constBits())
    stride = image.bytesPerLine()
    for bottom in range(image.height(), 0, -1):
        if any(pixels[(bottom-1)*stride+x*4+3] >= 128 for x in range(image.width())):
            break
    else:
        raise ValueError("서 있는 캐릭터의 발 위치를 찾을 수 없습니다.")
    top = next(y for y in range(bottom)
               if any(pixels[y*stride+x*4+3] >= 128 for x in range(image.width())))
    shoe_band = max(2, round((bottom-top)*0.08))
    xs = [x for y in range(max(0, bottom-shoe_band), bottom) for x in range(image.width())
          if pixels[y*stride+x*4+3] >= 128]
    return QPointF((min(xs)+max(xs)+1)/2, bottom)


def load_pose_sheet(name: str) -> list[QPixmap]:
    sheet = load_feeding_art(name)
    if sheet.width() < 2 or sheet.height() < 2:
        raise ValueError(f"동작 시트는 2×2 격자여야 합니다: {name}")
    cw, ch = sheet.width()//2, sheet.height()//2
    cells = [sheet.copy(i % 2*cw, i//2*ch, cw, ch) for i in range(4)]
    content = QRect()
    for cell in cells:
        content = content.united(QRegion(cell.mask()).boundingRect())
    if content.isEmpty():
        raise ValueError(f"동작 이미지가 비어 있습니다: {name}")
    return [cell.copy(content) for cell in cells]



class LegacyArt:
    def __init__(self, character):
        self.character = character
        self.load_character_art()

    def load_character_art(self):
        character=self.character
        base=Character(character.manifest,{**character.data,"animations":character.data["legacy_originals"]})
        self.originals={key:extract_frames(base,key,fallback=False) for key in CLIPS}
        self.originals["gaze"]=extract_frames(character,"gaze",fallback=False)
        self.motion_originals=extract_frames(character,"motion",fallback=False)
        self.motion_reference_height=character.motion_body_height
        if self.motion_reference_height is None:
            spec={**character.data["animations"]["motion"],"indices":[character.motion_reference]}
            ref=Character(character.manifest,{**character.data,"animations":{"reference":spec}})
            self.motion_reference_height=extract_frames(ref,"reference",fallback=False)[0].height()
        self.walk_originals=extract_frames(character,"right",fallback=False) if character.walk_indices else []
        self.corner_originals=extract_frames(character,"corner",fallback=False)
        self.feed_originals=extract_frames(character,"feeding",fallback=False)
        self.hunger_originals=extract_frames(character,"hungry",fallback=False)
        self.refusal_originals=extract_frames(character,"refusal",fallback=False)

    def resize(self, height):
        self.body_height = height
        # Specify HEIGHT ONLY with scaledToHeight. Qt chooses the width from
        # the original aspect ratio; no stretch or per-frame resizing occurs.
        target_height = round(self.character.profile["base_cell_height"] * self.body_height / self.character.body_height)
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
        idle = self.frames["idle"][0]
        idle_feet = standing_feet(idle)

        def align_standing_pose(sprite):
            offset = idle_feet - standing_feet(sprite)
            frame = QPixmap(idle.size())
            frame.fill(Qt.GlobalColor.transparent)
            painter = QPainter(frame)
            painter.drawPixmap(round(offset.x()), round(offset.y()), sprite)
            painter.end()
            return frame

        self.feed_frames = [align_standing_pose(original.scaledToHeight(
            self.body_height, Qt.TransformationMode.SmoothTransformation))
            for original in self.feed_originals]
        self.feed_look_frame = align_standing_pose(self.frames["gaze"][0])
        self.frames["hungry"] = [align_standing_pose(original.scaledToHeight(
            self.body_height, Qt.TransformationMode.SmoothTransformation))
            for original in self.hunger_originals]
        self.refusal_frames = [align_standing_pose(original.scaledToHeight(
            self.body_height, Qt.TransformationMode.SmoothTransformation))
            for original in self.refusal_originals]
        return self
