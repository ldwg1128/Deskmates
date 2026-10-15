"""Optional desktop play, kept separate from the original roaming/feeding controller."""
from __future__ import annotations
import math
import random
import time
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from character_resources import CATALOG, Character, action_spec, extract_frames
from window_surfaces import WindowsSurfaces, select_ledge

EXTRA_ACTIONS=('window_sit','ledge_struggle','sleep','wake_annoyed','cursor_grab','kick','secret_snack')
DEFAULT_SLEEP_SECONDS=1800
SLEEP_PRESETS=(300,600,1800)


def bounded(value,low,high): return max(low,min(high,value))


def extra_frames(character,height):
    """A single anatomical scale per action, with explicit contact anchors.

    These frames never enlarge the original roaming canvas or change old art.
    """
    result={}
    for key in EXTRA_ACTIONS:
        actual=key; seen=set()
        while not character.data['animations'].get(actual,{}).get('file') and not character.data['animations'].get(actual,{}).get('files'):
            if actual in seen: raise ValueError('Animation fallback cycle')
            seen.add(actual); actual=action_spec(character,actual).get('fallback','idle')
        spec=action_spec(character,actual)
        source=extract_frames(character,actual,fallback=False)
        reference=spec.get('body_height',character.body_height)
        scale=height/reference
        frames=[p.scaledToHeight(max(1,round(p.height()*scale)),Qt.TransformationMode.SmoothTransformation) for p in source]
        default_anchor=spec.get('anchor')
        if not isinstance(default_anchor,list):
            default_anchor=[source[0].width()/2,source[0].height()]
        anchor=spec.get('support_anchor',default_anchor) if key in ('window_sit','ledge_struggle') else default_anchor
        result[key]=(frames,QPointF(anchor[0]*scale,anchor[1]*scale))
    return result


class PlayBall(QWidget):
    """A separately draggable desktop object. No desktop input is intercepted elsewhere."""
    def __init__(self,controller):
        self.controller=controller
        super().__init__(controller.pet,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint|
                         Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(36,36); self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('끌어서 옮기면 가까운 캐릭터가 공을 찹니다.')
        self.dragging=False; self.flight=0.0; self.flying=False; self.age=0.0
        self.offset=QPoint(); self.position=QPointF(); self.velocity=QPointF()
        self.hide()

    def spawn(self):
        pet=self.controller.pet; area=pet.screen_area
        direction=1 if pet.x<area.center().x() else -1
        x=bounded(pet.x+direction*max(130,pet.body_height*1.8),area.left()+20,area.right()-20)
        self.position=QPointF(x-18,area.bottom()-40)
        self.dragging=self.flying=False; self.age=0; self.flight=0
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.move(self.position.toPoint()); self.show(); self.update()
        self.controller.activity()

    def kick(self,direction):
        if self.dragging or self.flying or not self.isVisible(): return
        self.flying=True; self.flight=0
        self.position=QPointF(self.pos()); self.velocity=QPointF(direction*720,-180)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def advance(self,dt):
        if not self.isVisible(): return
        self.age+=dt
        if not self.flying: return
        self.flight+=dt; self.velocity.setY(self.velocity.y()+380*dt)
        self.position+=self.velocity*dt
        if self.flight>=.9: self.hide(); self.flying=False; return
        self.move(self.position.toPoint()); self.update()

    def paintEvent(self,event):
        p=QPainter(self); p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(max(0,1-self.flight/.9) if self.flying else 1)
        p.setPen(QPen(QColor('#26384d'),1.7)); p.setBrush(QColor('#faf8ec')); p.drawEllipse(2,2,32,32)
        p.translate(18,18); p.rotate(self.flight*420)
        polygon=QPolygonF([QPointF(math.sin(i*math.tau/5)*8,-math.cos(i*math.tau/5)*8) for i in range(5)])
        p.setBrush(QColor('#34435c')); p.drawPolygon(polygon)
        for point in polygon: p.drawLine(point,point*1.8)

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or self.flying: return
        self.controller.activity(wake=True)
        self.dragging=True; self.offset=event.globalPosition().toPoint()-self.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor); event.accept()

    def mouseMoveEvent(self,event):
        if not self.dragging: return
        point=event.globalPosition().toPoint(); screen=QApplication.screenAt(point)
        area=(screen or QApplication.primaryScreen()).availableGeometry()
        position=point-self.offset
        self.move(round(bounded(position.x(),area.left(),area.right()-35)),
                  round(bounded(position.y(),area.top(),area.bottom()-35)))
        self.position=QPointF(self.pos()); event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.dragging=False; self.age=0; self.setCursor(Qt.CursorShape.OpenHandCursor); event.accept()


class DesktopInteractions:
    def __init__(self,pet,*,native=True):
        self.pet=pet; self.rng=random.Random()
        self.windows=WindowsSurfaces(enabled=native)
        self.clock=0.0; self.last_activity=0.0; self.last_cursor=None
        self.kind=None; self.time=0.0; self.duration=0.0; self.changing_state=False
        self.base_size=None; self.point=QPointF(); self.direction=1
        self.surface=None; self.surface_offset=0.5; self.surface_y_offset=0.0; self.side=0
        self.cursor_hover=0.0; self.cursor_cooldown=0.0
        self.next_snack=self.rng.uniform(300,600)
        self.snack_counted=False; self.ball_hit=False
        self.ball=PlayBall(self)
        self.configure(pet.settings)
        self.frames={}; self.reload_art()

    def configure(self,data):
        self.window_enabled=bool(data.get('window_interactions',True))
        self.sleep_enabled=bool(data.get('sleep_enabled',True))
        self.cursor_enabled=bool(data.get('cursor_play_enabled',True))
        self.rare_enabled=bool(data.get('rare_actions_enabled',True))
        seconds=data.get('sleep_seconds',DEFAULT_SLEEP_SECONDS)
        self.sleep_seconds=seconds if type(seconds) in (int,float) and seconds in SLEEP_PRESETS else DEFAULT_SLEEP_SECONDS

    def settings(self):
        return dict(window_interactions=self.window_enabled,sleep_enabled=self.sleep_enabled,
                    sleep_seconds=self.sleep_seconds,cursor_play_enabled=self.cursor_enabled,
                    rare_actions_enabled=self.rare_enabled)

    def reload_art(self): self.frames=extra_frames(self.pet.character,self.pet.body_height)

    def activity(self,*,wake=False):
        self.last_activity=self.clock
        if wake and self.kind in ('sleep','sleep_walk'): self.wake()

    def feet(self):
        if self.kind and self.kind not in ('sleep_walk','cursor_approach','ball_approach'):
            return QPointF(self.point)
        return self.pet.feeding_point(0)

    def _enter(self,kind,duration,*,walking=None):
        pet=self.pet
        if self.base_size is None:
            self.base_size=pet.size()
            self.return_anchor=(pet.anchor_x,pet.anchor_y)
        self.kind=kind; self.time=0.0; self.duration=duration
        pet.target=None; pet.near_cursor=False; pet.hide_food()
        if walking is None:
            largest=max(max(math.hypot(anchor.x(),anchor.y()),math.hypot(p.width()-anchor.x(),p.height()-anchor.y()))
                        for frames,anchor in self.frames.values() for p in frames)
            side=max(self.base_size.width(),math.ceil(2*largest)+16)
            pet.setFixedSize(side,side)
        self.changing_state=True
        try: pet.enter_state(walking or kind,duration)
        finally: self.changing_state=False

    def _position(self):
        # Special poses use a contact point; the ordinary controller uses the
        # bottom of its canvas. The translation is confined to this controller.
        pet=self.pet; pet.x=self.point.x(); pet.y=self.point.y()+pet.height()/2
        pet.position_window()

    def finish(self,*,resume=True):
        if not self.kind: return
        pet=self.pet; point=QPointF(self.point); previous=self.kind
        walking=self.kind in ('sleep_walk','cursor_approach','ball_approach')
        if walking: point=self.feet()
        self.kind=None; self.surface=None; self.cursor_hover=0.0
        if self.base_size is not None: pet.setFixedSize(self.base_size)
        self.base_size=None; pet.frame_key=None
        pet.state='idle'; pet.state_time=0; pet.state_duration=.8
        if not resume:
            pet.confine(); pet.position_window()
            return
        if pet.roam_mode=='edge': pet.attach_to_edge(point.x(),point.y())
        else:
            pet.x=point.x()
            idle=pet.frames['idle'][0]; floor=QRegion(idle.mask()).boundingRect().bottom()+1
            pet.y=point.y()+idle.height()-floor
            pet.anchor_x,pet.anchor_y=(self.return_anchor if previous in
                ('cursor_approach','cursor_grab','ball_approach','kick','secret_snack') else (pet.x,pet.y))
            pet.confine(); pet.position_window(); pet.update_frame()
        pet.save_settings()

    def cancel(self): self.finish(resume=False)

    def _surface_point(self,rect):
        return QPointF(rect.left() if self.side<0 else rect.right() if self.side>0 else
                       rect.left()+rect.width()*self.surface_offset,
                       rect.top()+rect.height()*self.surface_y_offset if self.side else rect.top())

    def _pose(self,action,index=0):
        frames,anchor=self.frames[action]; sprite=frames[index]
        # The side-cling artwork faces left toward a window on the character's left.
        mirror=(action=='ledge_struggle' and self.side<0 or
                action in ('cursor_grab','kick') and self.direction<0)
        if mirror:
            sprite=sprite.transformed(QTransform().scale(-1,1))
            anchor=QPointF(sprite.width()-anchor.x(),anchor.y())
        return sprite,anchor

    def try_window(self,cursor):
        if not self.window_enabled: return False
        match=select_ledge(self.windows.all(),QPointF(cursor),self.pet.body_height,self.pet.screen_area)
        if match is None: return False
        self.activity(); self.pet.dragging=False; self.pet.drag_cursor=None
        self.surface,self.side=match
        rect=self.surface.rect
        self.surface_offset=bounded((cursor.x()-rect.left())/rect.width(),0,1)
        self.surface_y_offset=bounded((cursor.y()-rect.top())/rect.height(),
                                      min(.25,self.pet.body_height*.12/rect.height()),1)
        self.direction=-1 if self.surface_offset<.5 else 1
        self.point=self._surface_point(rect)
        action='ledge_struggle' if self.side else 'window_sit'
        for index in range(len(self.frames[action][0])):
            frame,anchor=self._pose(action,index)
            body=QRegion(frame.mask()).boundingRect().translated(
                round(self.point.x()-anchor.x()),round(self.point.y()-anchor.y()))
            if not self.pet.screen_area.contains(body):
                self.surface=None
                return False
        self._enter('ledge_struggle' if self.side else 'window_sit',self.rng.uniform(2.2,3.8))
        self._position(); self.pet.update_frame()
        return True

    def fall(self,*,jump=False):
        if self.kind=='ledge_struggle':
            frame,anchor=self._pose('ledge_struggle')
            body=QRegion(frame.mask()).boundingRect()
            self.point+=QPointF(body.center().x()-anchor.x(),body.bottom()+1-anchor.y())
        self.surface=None; self.start=QPointF(self.point)
        if jump:
            self._enter('interaction_jump',.45)
        else:
            self.velocity=QPointF(self.direction*self.pet.body_height*.25,0)
            self._enter('interaction_fall',30)

    def start_sleep(self):
        pet=self.pet; area=pet.screen_area
        self.point=self.feet(); self.activity()
        if pet.stationary:
            self._enter('sleep',float('inf')); self._position(); return
        if pet.roam_mode=='edge':
            route=pet.edge_route
            candidates=[route.starts[4]+route.lengths[4]*fraction for fraction in (.03,.97)]
            self.sleep_distance=min(candidates,key=lambda target:((target-pet.edge_progress)*pet.edge_sign)%route.length)
            self._enter('sleep_walk',float('inf'),walking='left' if pet.edge_sign>0 else 'right')
        else:
            margin=max(pet.width()/2,pet.body_height*.65)
            candidates=[area.left()+margin,area.right()-margin]
            cursor=self.last_cursor or QPoint(-10000,-10000)
            x=max(candidates,key=lambda value:abs(value-cursor.x()))
            self.target=QPointF(x,area.bottom()-8)
            self._enter('sleep_walk',float('inf'),walking='right' if x>=pet.x else 'left')

    def wake(self):
        if self.kind not in ('sleep','sleep_walk'): return False
        if self.kind=='sleep_walk': self.point=self.feet()
        self.last_activity=self.clock
        self._enter('wake_annoyed',1.8); self._position()
        self.pet.say('으으… 조금만 더 잘래…',1800)
        return True

    def maybe_snack(self):
        pet=self.pet
        if (self.kind or not self.rare_enabled or not pet.feeding_enabled or pet.paused or
                self.clock<self.next_snack or pet.appetite.stacks or pet.near_cursor): return False
        self.next_snack=self.clock+60
        if self.rng.random()>=.05: return False
        self.point=self.feet(); self.snack_counted=False
        self._enter('secret_snack',3.2); self._position()
        self.pet.say('아무도 못 봤지…?',1600)
        self.next_snack=self.clock+self.rng.uniform(900,1800)
        return True

    def toggle_ball(self):
        if self.ball.isVisible(): self.ball.hide(); self.ball.flying=False
        else: self.ball.spawn()

    def tick(self,dt,cursor):
        self.clock+=max(0,dt); self.cursor_cooldown=max(0,self.cursor_cooldown-dt)
        moved=self.last_cursor is not None and (cursor-self.last_cursor).manhattanLength()>2
        if moved and self.pet.cursor_is_near(cursor): self.activity()
        if moved and self.kind=='sleep':
            body=QRegion(self.pet.pixmap.mask()).boundingRect().translated(self.pet.pos()).adjusted(-12,-12,12,12)
            if body.contains(cursor): self.wake()
        self.last_cursor=QPoint(cursor)
        self.ball.advance(dt)

    def _walk_to(self,target,dt):
        pet=self.pet; current=self.feet(); delta=target-current; distance=math.hypot(delta.x(),delta.y())
        step=min(distance,pet.speed*dt); pet.walk_distance+=step
        point=target if distance<=step else current+delta*(step/distance)
        idle=pet.frames['idle'][0]; floor=QRegion(idle.mask()).boundingRect().bottom()+1
        pet.x=point.x(); pet.y=point.y()+idle.height()-floor
        pet.position_window(); self.point=point
        return distance<=step

    def advance(self,dt,cursor):
        pet=self.pet
        if not self.kind:
            if pet.paused or pet.dragging or pet.click_through or pet.press_global is not None or pet.edge_jumping(): return False
            if self.sleep_enabled and self.clock-self.last_activity>=self.sleep_seconds:
                self.start_sleep(); return True
            ball=self.ball
            if (pet.roam_mode=='free' and ball.isVisible() and not ball.dragging and not ball.flying and ball.age>=1.2):
                center=QPointF(ball.geometry().center()); feet=self.feet()
                dx=center.x()-feet.x(); dy=center.y()-feet.y()
                if abs(dx)<=pet.body_height*2 and abs(dy)<=pet.body_height*.35:
                    self.direction=1 if dx>=0 else -1; self.point=feet; self.ball_hit=False
                    if abs(dx)<=pet.body_height*.65:
                        self._enter('kick',.75); self._position()
                    elif not pet.stationary:
                        l,r,_,_=pet.bounds()
                        self.target=QPointF(bounded(center.x()-self.direction*pet.body_height*.42,l,r),feet.y())
                        self._enter('ball_approach',3,walking='right' if self.direction>0 else 'left')
                    return bool(self.kind)
            waist=pet.feeding_point(pet.body_height*.45)
            if (self.cursor_enabled and not self.cursor_cooldown and pet.roam_mode=='free' and
                    pet.cursor_is_near(cursor) and abs(cursor.y()-waist.y())<=max(6,pet.body_height*.075) and
                    abs(cursor.x()-pet.x)<=pet.body_height*1.3):
                self.cursor_hover+=dt
                if self.cursor_hover>=.7:
                    self.activity(); self.grab_target=QPointF(cursor); self.direction=1 if cursor.x()>pet.x else -1
                    self.point=self.feet()
                    if abs(cursor.x()-pet.x)<=pet.body_height*.35:
                        self._enter('cursor_grab',1.1); self._position(); return True
                    if pet.stationary: return False
                    l,r,_,_=pet.bounds()
                    x=bounded(cursor.x()-self.direction*pet.body_height*.22,l,r)
                    self.target=QPointF(x,self.point.y())
                    self._enter('cursor_approach',2.5,walking='right' if self.direction>0 else 'left')
                    return True
            else: self.cursor_hover=0
            return False
        kind=self.kind
        if pet.paused and kind not in ('window_sit','ledge_struggle','interaction_jump','interaction_fall','interaction_land','wake_annoyed'):
            return True
        self.time+=dt; pet.state_time+=dt
        if kind in ('window_sit','ledge_struggle'):
            surface=self.windows.get(self.surface.handle)
            if surface is None: self.fall(); return True
            rect=surface.rect
            self.point=self._surface_point(rect)
            screen=QApplication.screenAt(self.point.toPoint())
            if screen: pet.screen_area=screen.availableGeometry()
            if not pet.screen_area.contains(self.point.toPoint()) or self.time>=self.duration:
                self.fall(jump=kind=='window_sit'); return True
            self._position()
        elif kind=='interaction_jump':
            fraction=min(1,self.time/self.duration)
            self.point=self.start+QPointF(self.direction*pet.body_height*.45*fraction,-pet.body_height*.3*math.sin(math.pi*fraction))
            self._position()
            if self.time>=self.duration: self.fall()
        elif kind=='interaction_fall':
            self.velocity.setY(self.velocity.y()+pet.body_height*3.2*dt)
            self.point+=self.velocity*dt
            area=pet.screen_area; margin=pet.body_height*.6
            self.point.setX(bounded(self.point.x(),area.left()+margin,area.right()-margin))
            if self.point.y()>=area.bottom()-8:
                self.point.setY(area.bottom()-8); self._enter('interaction_land',.48)
            self._position()
        elif kind=='sleep_walk':
            if pet.stationary:
                self.point=self.feet(); self._enter('sleep',float('inf')); self._position()
            elif pet.roam_mode=='edge':
                distance=((self.sleep_distance-pet.edge_progress)*pet.edge_sign)%pet.edge_route.length
                if distance<=max(2,pet.speed*dt):
                    pet.edge_progress=self.sleep_distance; pet.place_edge(); self.point=self.feet()
                    self._enter('sleep',float('inf')); self._position()
                else: pet.advance_edge(dt); self.point=self.feet()
            elif self._walk_to(self.target,dt):
                self._enter('sleep',float('inf')); self._position()
        elif kind in ('cursor_approach','ball_approach'):
            if kind=='cursor_approach' and math.hypot(cursor.x()-self.grab_target.x(),cursor.y()-self.grab_target.y())>pet.body_height*.5:
                self.cursor_cooldown=8; self.finish(); return True
            if kind=='ball_approach' and (not self.ball.isVisible() or self.ball.dragging):
                self.finish(); return True
            if self._walk_to(self.target,dt) or self.time>=self.duration:
                self._enter('cursor_grab' if kind=='cursor_approach' else 'kick',1.1 if kind=='cursor_approach' else .75)
                self._position()
        elif kind=='kick':
            if not self.ball_hit and self.time>=.3:
                self.ball_hit=True
                center=QPointF(self.ball.geometry().center())
                if math.hypot(center.x()-self.point.x(),center.y()-self.point.y())<=pet.body_height*.9:
                    self.ball.kick(self.direction)
            if self.time>=self.duration: self.finish(); return True
        elif kind=='secret_snack':
            if self.time>=2.2 and not self.snack_counted:
                self.snack_counted=True; pet.appetite.eat(time.time()); pet.save_settings()
            if self.time>=self.duration: self.finish(); return True
        elif kind in ('interaction_land','wake_annoyed','cursor_grab') and self.time>=self.duration:
            if kind=='cursor_grab': self.cursor_cooldown=20
            self.finish(); return True
        pet.update_frame(cursor)
        return True

    def render(self):
        if not self.kind or self.kind in ('sleep_walk','cursor_approach','ball_approach'): return False
        pet=self.pet; kind=self.kind
        if kind in ('interaction_fall','interaction_land'):
            sprite=pet.motion_frames[3 if kind=='interaction_fall' else 4 if self.time<.28 else 5]
            anchor=QPointF(sprite.width()/2,sprite.height())
        elif kind=='interaction_jump':
            frames=pet.frames['jump']; sprite=frames[min(len(frames)-1,int(self.time/self.duration*len(frames)))]
            anchor=QPointF(sprite.width()/2,sprite.height())
        else:
            frames,anchor=self.frames[kind]
            fps=action_spec(pet.character,kind).get('fps',5)
            index=int(self.time*fps)%len(frames) if kind in ('window_sit','ledge_struggle','sleep') else min(len(frames)-1,int(self.time/self.duration*len(frames)))
            sprite,anchor=self._pose(kind,index)
        pet.pixmap=QPixmap(pet.size()); pet.pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pet.pixmap)
        painter.drawPixmap(QPointF(pet.width()/2-anchor.x(),pet.height()/2-anchor.y()),sprite)
        painter.end(); pet.frame_key=None; pet.update()
        return True
