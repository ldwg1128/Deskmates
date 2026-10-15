"""Optional desktop play, kept separate from the original roaming/feeding controller."""
from __future__ import annotations
import math
import random
import time
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from character_resources import CATALOG, Character, action_spec, extract_frames
from window_surfaces import WindowsSurfaces, select_ledge
from ball_physics import BallMotion
from sprite_quality import scale_sprite

EXTRA_ACTIONS=('window_sit','ledge_struggle','sleep','wake_annoyed','cursor_grab','kick','secret_snack','head_bump')
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
        frames=[scale_sprite(p,max(1,round(p.height()*scale)),character) for p in source]
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
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('끌어서 옮기면 가까운 캐릭터가 공을 찹니다.')
        self.dragging=False; self.flight=0.0; self.flying=False; self.age=0.0
        self.offset=QPoint(); self.motion=BallMotion(); self.angle=0
        self.last_position=QPoint(); self.screen_name=''
        self.resize_for_pet()
        self.hide()

    @property
    def inset(self): return self.width()/2

    def resize_for_pet(self):
        old_radius=self.motion.radius
        side=max(8,round(self.controller.pet.body_height*.2+4))
        self.setFixedSize(side,side); self.motion.radius=side/2-2
        if self.motion.grounded: self.motion.y+=old_radius-self.motion.radius
        self.place(); self.update()

    def spawn(self):
        pet=self.controller.pet; area=pet.screen_area
        direction=1 if pet.x<area.center().x() else -1
        x=bounded(pet.x+direction*max(130,pet.body_height*1.8),area.left()+self.inset,area.right()+1-self.inset)
        screen=QApplication.screenAt(area.center()) or QApplication.primaryScreen()
        self.screen_name=screen.name()
        self.motion.release(x,area.bottom()+1-self.inset)
        self.motion.grounded=True
        self.dragging=self.flying=False; self.age=0; self.flight=0
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.place(); self.show(); self.update()
        self.controller.activity()

    def kick(self,direction):
        if self.dragging or self.flying or not self.isVisible(): return False
        self.flying=True; self.flight=0
        self.motion.vx=direction*720; self.motion.vy=-250
        self.motion.grounded=False; self.motion.head_contacted=True
        self.setCursor(Qt.CursorShape.ArrowCursor)
        return True

    def center(self): return QPointF(self.motion.x,self.motion.y)

    def area(self):
        screen=next((s for s in QApplication.screens() if s.name()==self.screen_name),QApplication.primaryScreen())
        return screen.availableGeometry()

    def place(self):
        self.move(round(self.motion.x-self.inset),round(self.motion.y-self.inset))
        self.last_position=QPoint(self.pos())

    def advance(self,dt):
        if not self.isVisible(): return
        if self.dragging: return
        # Honor externally repositioned widgets, including native move operations.
        if self.pos()!=self.last_position:
            self.motion.release(self.x()+self.inset,self.y()+self.inset)
            screen=QApplication.screenAt(QPoint(round(self.motion.x),round(self.motion.y)))
            if screen: self.screen_name=screen.name()
        self.age+=dt
        area=self.area()
        self.motion.advance(dt,(area.left(),area.top(),area.right()+1,area.bottom()+1),
                            self.controller.head_surface(),self.controller.bounce_on_head)
        self.angle+=math.degrees(self.motion.vx/max(1,self.motion.radius)*dt)
        if self.flying:
            self.flight+=dt
            if self.flight>=.9: self.hide(); self.flying=False; return
        self.place(); self.update()

    def paintEvent(self,event):
        p=QPainter(self); p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(),Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.inset,self.inset); p.scale(self.motion.radius/16,self.motion.radius/16); p.translate(-18,-18)
        p.setOpacity(max(0,1-self.flight/.9) if self.flying else 1)
        sphere=QPainterPath(); sphere.addEllipse(QRectF(2,2,32,32))
        base=QRadialGradient(QPointF(11,8),30,QPointF(9,6))
        for at,color in ((0,'#ffffff'),(.42,'#f0f4f7'),(.75,'#aebdcd'),(1,'#526982')): base.setColorAt(at,QColor(color))
        p.setPen(QPen(QColor('#43556c'),.9)); p.setBrush(base); p.drawPath(sphere)
        p.save(); p.setClipPath(sphere); p.translate(18,18); p.rotate(self.angle)
        polygon=QPolygonF([QPointF(math.sin(i*math.tau/5)*6.7,-math.cos(i*math.tau/5)*6.7) for i in range(5)])
        p.setPen(QPen(QColor('#758599'),.65)); p.setBrush(QColor('#273b55')); p.drawPolygon(polygon)
        for i,point in enumerate(polygon):
            outer=point*2.5; p.drawLine(point,outer)
            tangent=QPointF(math.cos(i*math.tau/5)*4.3,math.sin(i*math.tau/5)*4.3)
            p.drawPolygon(QPolygonF([outer-tangent,point*1.9,outer+tangent,outer*1.5]))
        p.restore(); p.save(); p.setClipPath(sphere)
        shade=QRadialGradient(QPointF(10,7),33)
        shade.setColorAt(0,QColor(255,255,255,65)); shade.setColorAt(.48,QColor(255,255,255,0))
        shade.setColorAt(1,QColor(14,32,63,135)); p.fillPath(sphere,shade)
        shine=QRadialGradient(QPointF(10,8),8)
        shine.setColorAt(0,QColor(255,255,255,190)); shine.setColorAt(1,QColor(255,255,255,0))
        p.fillPath(sphere,shine); p.restore()

    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or self.flying: return
        self.controller.activity(wake=True)
        self.dragging=True; self.offset=event.globalPosition().toPoint()-self.pos()
        self.motion.vx=self.motion.vy=0; self.age=0
        self.setCursor(Qt.CursorShape.ClosedHandCursor); event.accept()

    def mouseMoveEvent(self,event):
        if not self.dragging: return
        point=event.globalPosition().toPoint(); screen=QApplication.screenAt(point)
        area=(screen or QApplication.primaryScreen()).availableGeometry()
        self.screen_name=(screen or QApplication.primaryScreen()).name()
        position=point-self.offset
        self.move(round(bounded(position.x(),area.left(),area.right()+1-self.width())),
                  round(bounded(position.y(),area.top(),area.bottom()+1-self.height())))
        self.motion.release(self.x()+self.inset,self.y()+self.inset); self.last_position=QPoint(self.pos()); event.accept()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.dragging=False; self.age=0; self.setCursor(Qt.CursorShape.OpenHandCursor); event.accept()
            self.motion.release(self.x()+self.inset,self.y()+self.inset)
            self.last_position=QPoint(self.pos())


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
        self.snack_counted=False; self.ball_hit=False; self.ball_retry=0
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

    def reload_art(self):
        self.frames=extra_frames(self.pet.character,self.pet.body_height)
        self.ball.resize_for_pet()

    def activity(self,*,wake=False):
        self.last_activity=self.clock
        if wake and self.kind in ('sleep','sleep_walk'): self.wake()

    def feet(self):
        if self.kind and self.kind not in ('sleep_walk','cursor_approach','ball_approach','ball_return'):
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
        else:
            pet.setFixedSize(self.base_size)
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
        walking=self.kind in ('sleep_walk','cursor_approach','ball_approach','ball_return')
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
                ('cursor_approach','cursor_grab','ball_approach','ball_return','kick','head_bump','secret_snack') else (pet.x,pet.y))
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
        previous=(self.surface,self.side,self.surface_offset,self.surface_y_offset,
                  self.direction,QPointF(self.point))
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
                (self.surface,self.side,self.surface_offset,self.surface_y_offset,
                 self.direction,self.point)=previous
                return False
        # Commit only after every pose fits. A rejected attachment must keep
        # the release cursor intact for falling or returning to edge walking.
        self.activity(); self.pet.dragging=False; self.pet.drag_cursor=None
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

    def head_surface(self):
        pet=self.pet
        if (self.kind or not pet.isVisible() or pet.dragging or pet.menu_open or
                pet.press_global is not None or pet.roam_mode!='free' or
                pet.state in ('flip','land','feed_drop','feed_eat','feed_happy','feed_refuse') or pet.pixmap.isNull()):
            return None
        body=QRegion(pet.pixmap.mask()).boundingRect().translated(pet.pos())
        # A narrow forehead plane excludes hair tips, ears and the shoulders.
        half=max(10,pet.body_height*.20)
        return (body.center().x()-half,body.top()+body.height()*.14,body.center().x()+half)

    def bounce_on_head(self,x,y,floor):
        if self.head_surface() is None: return None
        pet=self.pet; area=self.ball.area(); direction=self.rng.choice((-1,1))
        room=lambda sign: area.right()+1-self.ball.inset-x if sign>0 else x-area.left()-self.ball.inset
        if room(direction)<max(50,pet.body_height*.5): direction=-direction
        distance=min(max(0,room(direction)-4),self.rng.uniform(max(80,pet.body_height*.65),max(140,pet.body_height*1.1)))
        velocity=self.ball.motion.head_launch(x,y,floor,direction,distance,bounded(pet.body_height*.35,38,100))
        self.point=self.feet(); self.activity(); self._enter('head_bump',1.15); self._position()
        pet.say('앗! 머리야…',1150); pet.update_frame()
        return velocity

    def _ball_ready(self):
        ball=self.ball
        return (ball.isVisible() and not ball.dragging and not ball.flying and ball.age>=1.2 and
                ball.motion.grounded and self.pet.screen_area.contains(ball.center().toPoint()))

    def _ball_contact(self,point=None):
        if not self._ball_ready(): return False
        delta=self.ball.center()-(point if point is not None else self.feet())
        reach=self._ball_reach()
        return (abs(delta.x())<=reach+self.ball.motion.radius*.75 and
                abs(delta.y())<=max(28,self.pet.body_height*.2) and delta.x()*self.direction>=-8)

    def _ball_reach(self):
        return self.pet.body_height*action_spec(self.pet.character,'kick').get('contact_reach',.42)

    def _ball_target(self):
        pet=self.pet; ball=self.ball; center=ball.center(); idle=pet.frames['idle'][0]
        body=QRegion(idle.mask()).boundingRect(); area=pet.screen_area
        left=area.left()+idle.width()/2-body.left()
        right=area.right()+1+idle.width()/2-(body.right()+1)
        for direction in (self.direction,-self.direction):
            point=QPointF(bounded(center.x()-direction*(self._ball_reach()+ball.motion.radius*.45),left,right),center.y()+ball.motion.radius)
            dx=center.x()-point.x()
            if -8<=dx*direction<=self._ball_reach()+ball.motion.radius*.75:
                self.direction=direction
                return point
        return None

    def _return_from_ball(self):
        pet=self.pet; point=self.feet(); self.ball_retry=2
        if self.base_size is not None: pet.setFixedSize(self.base_size)
        idle=pet.frames['idle'][0]; ground=QRegion(idle.mask()).boundingRect().bottom()+1
        correction=idle.height()-ground
        pet.x=point.x(); pet.y=point.y()+correction
        left,right,top,bottom=pet.bounds()
        target=QPointF(bounded(pet.x,left,right),bounded(pet.y,top,bottom)-correction)
        distance=math.hypot(target.x()-point.x(),target.y()-point.y())
        self.point=point
        if distance>1 and not pet.stationary and pet.roam_mode=='free':
            self.target=target
            self._enter('ball_return',distance/max(1,pet.speed)+1,walking='right' if target.x()>point.x() else 'left')
            pet.position_window(); pet.update_frame()
        else: self.finish()

    def kick_impact_time(self):
        frames=self.frames['kick'][0]
        index=bounded(action_spec(self.pet.character,'kick').get('impact_frame',2),0,len(frames)-1)
        return self.duration*(.12+.72*index/len(frames))

    def tick(self,dt,cursor):
        self.clock+=max(0,dt); self.cursor_cooldown=max(0,self.cursor_cooldown-dt)
        self.ball_retry=max(0,self.ball_retry-dt)
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
            if pet.roam_mode=='free' and not self.ball_retry and self._ball_ready():
                feet=self.feet(); self.direction=1 if ball.center().x()>=feet.x() else -1
                self.point=feet; self.ball_hit=False
                if self._ball_contact():
                    self._enter('kick',.95); self._position(); return True
                if not pet.stationary and not pet.cursor_is_near(cursor):
                    target=self._ball_target()
                    if target is not None:
                        self.target=target; distance=math.hypot(target.x()-feet.x(),target.y()-feet.y())
                        self._enter('ball_approach',distance/max(1,pet.speed)+2,
                                    walking='right' if target.x()>feet.x() else 'left')
                        return True
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
        if pet.paused and kind not in ('window_sit','ledge_struggle','interaction_jump','interaction_fall','interaction_land','wake_annoyed','head_bump'):
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
        elif kind=='ball_approach':
            if not self._ball_ready(): self._return_from_ball(); return True
            target=self._ball_target()
            if target is None: self._return_from_ball(); return True
            self.target=target
            if self._ball_contact():
                self.point=self.feet(); self._enter('kick',.95); self._position()
            elif self.time>=self.duration:
                self._return_from_ball(); return True
            else:
                pet.state='right' if target.x()>self.feet().x() else 'left'
                self._walk_to(target,dt)
        elif kind=='ball_return':
            if self._walk_to(self.target,dt) or self.time>=self.duration:
                self.finish(); return True
        elif kind=='cursor_approach':
            if kind=='cursor_approach' and math.hypot(cursor.x()-self.grab_target.x(),cursor.y()-self.grab_target.y())>pet.body_height*.5:
                self.cursor_cooldown=8; self.finish(); return True
            if self._walk_to(self.target,dt) or self.time>=self.duration:
                self._enter('cursor_grab',1.1)
                self._position()
        elif kind=='kick':
            if not self.ball_hit:
                if not self._ball_contact(self.point): self._return_from_ball(); return True
                if self.time>=self.kick_impact_time():
                    self.ball_hit=self.ball.kick(self.direction)
            if self.time>=self.duration: self._return_from_ball(); return True
        elif kind=='secret_snack':
            if self.time>=2.2 and not self.snack_counted:
                self.snack_counted=True; pet.appetite.eat(time.time()); pet.save_settings()
            if self.time>=self.duration: self.finish(); return True
        elif kind in ('interaction_land','wake_annoyed','cursor_grab','head_bump') and self.time>=self.duration:
            if kind=='cursor_grab': self.cursor_cooldown=20
            self.finish(); return True
        pet.update_frame(cursor)
        return True

    def render(self):
        if not self.kind or self.kind in ('sleep_walk','cursor_approach','ball_approach','ball_return'): return False
        pet=self.pet; kind=self.kind
        if kind in ('interaction_fall','interaction_land'):
            sprite=pet.motion_frames[3 if kind=='interaction_fall' else 4 if self.time<.28 else 5]
            anchor=QPointF(sprite.width()/2,sprite.height())
        elif kind=='interaction_jump':
            frames=pet.frames['jump']; sprite=frames[min(len(frames)-1,int(self.time/self.duration*len(frames)))]
            anchor=QPointF(sprite.width()/2,sprite.height())
        elif kind=='kick' and (self.time/self.duration<.12 or self.time/self.duration>=.84):
            sprite=pet.frames['idle'][0]
            anchor=QPointF(sprite.width()/2,QRegion(sprite.mask()).boundingRect().bottom()+1)
        else:
            frames,anchor=self.frames[kind]
            fps=action_spec(pet.character,kind).get('fps',5)
            index=int(self.time*fps)%len(frames) if kind in ('window_sit','ledge_struggle','sleep') else min(len(frames)-1,int(self.time/self.duration*len(frames)))
            if kind=='kick': index=min(len(frames)-1,max(0,int((self.time/self.duration-.12)/.72*len(frames))))
            sprite,anchor=self._pose(kind,index)
        pet.pixmap=QPixmap(pet.size()); pet.pixmap.fill(Qt.GlobalColor.transparent)
        painter=QPainter(pet.pixmap)
        painter.drawPixmap(QPointF(pet.width()/2-anchor.x(),pet.height()/2-anchor.y()),sprite)
        painter.end(); pet.frame_key=None; pet.update()
        return True
