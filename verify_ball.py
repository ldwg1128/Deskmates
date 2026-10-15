"""Ball physics, swept head contacts and actual desktop kick transitions."""
from pathlib import Path
import json
import math
import tempfile
from unittest.mock import patch
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication
from ball_physics import BallMotion
from desktop_pet import DesktopPet


def physics():
    bounds=(-1200,-200,1200,1000)
    ball=BallMotion(); ball.release(-300,100); ball.advance(.2,bounds)
    assert abs(ball.y-126)<.001 and abs(ball.vy-260)<.001
    up=0; last=ball.vy
    for _ in range(1000):
        ball.advance(.01,bounds)
        if last>0 and ball.vy<0: up+=1
        last=ball.vy
    assert up>=3 and ball.grounded and ball.y==982 and ball.vy==0
    calls=[]
    def contact(x,y,floor):
        calls.append((x,y)); return (100,-250)
    ball.release(-300,0); ball.advance(.5,bounds,(-325,100,-275),contact)
    assert len(calls)==1 and ball.head_contacted and ball.x>-300
    ball.advance(3,bounds,(-325,100,-275),contact); assert len(calls)==1
    ball.release(-100,0); ball.advance(.5,bounds,(-325,100,-275),contact); assert len(calls)==1
    for direction in (-1,1):
        ball.release(0,500); ball.vx,ball.vy=ball.head_launch(0,500,982,direction,180,65)
        for _ in range(1500): ball.advance(.01,bounds)
        assert ball.grounded and 150<ball.x*direction<215,(direction,ball.x)
    positions=[]
    for dt in (1/30,1/60,1/144):
        ball.release(0,100); ball.vx=160
        for _ in range(round(8/dt)): ball.advance(dt,bounds)
        positions.append((ball.x,ball.y))
    assert max(x for x,y in positions)-min(x for x,y in positions)<3,positions
    ball.release(-1500,-500); ball.advance(.01,bounds)
    assert -1182<=ball.x<=1182 and ball.y>=-182
    before=(ball.x,ball.y); ball.advance(0,bounds); assert before==(ball.x,ball.y)
    print('PASS: gravity, repeated damped bounces, settling, swept head hit/miss, one contact per drop, both finite launch directions, negative coordinates and 30/60/144 FPS.')


def main():
    physics()
    app=QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    far=QPoint(-10000,-10000); output=Path('artifacts/ball'); output.mkdir(parents=True,exist_ok=True)
    snapshots=[]; records=[]
    with tempfile.TemporaryDirectory() as tmp:
        pet=DesktopPet(Path(tmp)/'settings.json',start_timer=False); pet.show(); app.processEvents()
        ctrl=pet.interactions; ball=ctrl.ball
        ctrl.sleep_enabled=ctrl.rare_enabled=ctrl.cursor_enabled=False
        pet.next_gaze=pet.next_hunger=float('inf'); pet.speed=100

        def reset(character,height=160):
            ctrl.cancel(); ball.hide(); pet.paused=False; pet.stationary=False
            pet.set_character(character); pet.set_size(height,save=False)
            pet.set_roaming('free','clockwise',save=False); pet.screen_area=QApplication.primaryScreen().availableGeometry()
            area=pet.screen_area; idle=pet.frames['idle'][0]; ground=QRegion(idle.mask()).boundingRect().bottom()+1
            pet.anchor_x=pet.x=area.center().x(); pet.anchor_y=pet.y=area.bottom()+1
            pet.radius=80; pet.enter_state('idle',1000); pet.position_window(); pet.update_frame(); app.processEvents()
            ctrl.ball_retry=0; pet.speed=100; pet.next_gaze=pet.next_hunger=float('inf')
            ctrl.sleep_enabled=ctrl.rare_enabled=ctrl.cursor_enabled=False

        def floor_ball(x):
            ctrl.ball_retry=0
            ball.spawn(); ball.motion.release(x,ball.area().bottom()+1-ball.inset)
            ball.motion.grounded=True; ball.place(); ball.age=2; app.processEvents()

        for character in ('liberta','zenith','seir'):
            for height in (64,160,400):
                reset(character,height)
                assert abs(ball.motion.radius-height*.1)<=.5 and ball.width()==round(height*.2+4)
                original=pet.pixmap.copy(); point=ctrl.feet(); anchor=(pet.anchor_x,pet.anchor_y)
                for direction in (-1,1):
                    floor_ball(point.x()+direction*(ctrl._ball_reach()+ball.motion.radius*.4))
                    pet.advance(.01,far); assert ctrl.kind=='kick',(character,height,ctrl.kind)
                    assert not ball.flying
                    # First and final idle drawings occupy the exact same world pixel grid.
                    first=pet.pixmap.copy(); local=QRegion(first.mask()).boundingRect()
                    idle_box=QRegion(original.mask()).boundingRect()
                    assert abs(local.height()-idle_box.height())<=1
                    world_first=local.translated(pet.pos()); contact=QPointF(ctrl.point)
                    frames=[]
                    for fraction in (.13,.31,.49,.69,.87):
                        ctrl.time=ctrl.duration*fraction; ctrl.render(); app.processEvents()
                        box=QRegion(pet.pixmap.mask()).boundingRect()
                        assert box.left()>0 and box.right()<pet.width()-1 and box.top()>0
                        assert ctrl.point==contact
                        # The planted sole stays on the same ground throughout the kick.
                        assert abs(box.bottom()+1+pet.y-pet.height()-contact.y())<=2,(character,height,fraction,box)
                        frames.append(pet.pixmap.copy())
                        if height==160 and direction==1: snapshots.append((f'{character}: kick {fraction:.2f}',pet.pixmap.copy()))
                    assert first.toImage()==frames[-1].toImage(),(character,height,'idle recovery changed')
                    ctrl.time=ctrl.kick_impact_time()-.02
                    pet.advance(.01,far); assert not ball.flying
                    pet.advance(.02,far); assert ball.flying and ctrl.ball_hit
                    assert math.copysign(1,ball.motion.vx)==direction
                    pet.advance(1.1,far)
                    assert ctrl.kind is None and not ball.isVisible() and (pet.anchor_x,pet.anchor_y)==anchor,(character,height,direction,ctrl.kind,ball.isVisible(),(pet.anchor_x,pet.anchor_y),anchor,ctrl.point)
                    assert abs(ctrl.feet().x()-point.x())<1 and abs(ctrl.feet().y()-point.y())<1
                    records.append(dict(character=character,height=height,direction=direction,ground_fixed=True,idle_restored=True))
                # Downward contact triggers the new reaction even when paused/stationary.
                for direction in (-1,1):
                    reset(character,height); pet.paused=True; pet.stationary=True
                    surface=ctrl.head_surface(); assert surface
                    x=(surface[0]+surface[2])/2
                    ball.spawn(); ball.motion.release(x,max(ball.area().top()+ball.inset,surface[1]-height*.4-30)); ball.place()
                    with patch.object(ctrl.rng,'choice',return_value=direction):
                        for _ in range(200):
                            pet.advance(.01,far)
                            if ball.motion.head_contacted: break
                    assert ball.motion.head_contacted and ctrl.kind=='head_bump',(character,height,direction)
                    assert ball.motion.vx*direction>0 and ball.motion.vy<0
                    if height==160 and direction==1:
                        for fraction in (.05,.3,.55,.8):
                            ctrl.time=ctrl.duration*fraction; ctrl.render()
                            snapshots.append((f'{character}: head {fraction:.2f}',pet.pixmap.copy()))
                    for _ in range(1000): pet.advance(.01,far)
                    assert ball.motion.grounded and not ball.flying and ball.isVisible() and ctrl.kind is None
                    assert 40<abs(ball.motion.x-x)<max(220,height*1.5),(height,ball.motion.x-x)
                    ball.hide()
            # A ball beyond the normal walk radius is approached rather than kicked in place.
            reset(character); pet.speed=20; anchor=(pet.anchor_x,pet.anchor_y)
            target_x=min(pet.screen_area.right()-100,pet.x+350)
            floor_ball(target_x); pet.advance(.01,far); assert ctrl.kind=='ball_approach'
            old_x=pet.x
            for _ in range(40): pet.advance(.1,far)
            assert ctrl.kind=='ball_approach' and not ball.flying and pet.x>old_x+70
            for _ in range(250):
                pet.advance(.1,far)
                if ball.flying: break
            assert ball.flying and ctrl.kind=='kick' and abs(ball.motion.x-ctrl.point.x())<=85
            for _ in range(300):
                pet.advance(.1,far)
                if ctrl.kind is None: break
            assert ctrl.kind is None and (pet.anchor_x,pet.anchor_y)==anchor
            assert pet.bounds()[0]<=pet.x<=pet.bounds()[1]
            # Moving the ball during wind-up cancels without an impulse.
            reset(character); floor_ball(pet.x+ctrl._ball_reach()); pet.advance(.01,far); assert ctrl.kind=='kick'
            ball.motion.x+=350; ball.place(); pet.advance(.1,far)
            assert ctrl.kind is None and not ball.flying and ctrl.ball_retry>0
            # Paused and stationary pets never chase distant balls.
            for mode in ('paused','stationary'):
                reset(character); setattr(pet,mode,True); floor_ball(pet.x+300)
                x=pet.x; pet.advance(2,far)
                assert ctrl.kind is None and pet.x==x
            # A dragged/removed ball aborts approach and walks back without teleporting.
            reset(character); floor_ball(pet.x+350); pet.advance(.01,far)
            for _ in range(20): pet.advance(.1,far)
            before=ctrl.feet(); ball.dragging=True; pet.advance(.01,far)
            assert ctrl.kind=='ball_return' and abs(ctrl.feet().x()-before.x())<1
            ball.hide(); ball.dragging=False
            for _ in range(150):
                pet.advance(.1,far)
                if ctrl.kind is None: break
            assert ctrl.kind is None
        reset('zenith'); ball.spawn(); ball.grab().save(str(output/'ball-3d.png')); ball.hide()
        pet.hide(); pet.deleteLater()
    cell=260; columns=5; rows=math.ceil(len(snapshots)/columns)
    sheet=QImage(cell*columns,cell*rows,QImage.Format.Format_ARGB32); sheet.fill(QColor('#e9edf4'))
    painter=QPainter(sheet)
    for i,(label,sprite) in enumerate(snapshots):
        x=i%columns*cell; y=i//columns*cell
        painter.setPen(QColor('#27364b')); painter.drawText(x+6,y+18,label)
        scaled=sprite.scaled(cell-8,cell-28,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(x+(cell-scaled.width())//2,y+25,scaled)
    painter.end(); sheet.save(str(output/'ball-reactions-preview.png'))
    (output/'results.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print('PASS: three characters at64/160/400px, both kick directions, fixed ground, exact idle recovery, frame-synchronized impulse, head reactions and bounce while paused/stationary.')
    print('PASS: slow distant approach beyond walk radius, contact-only kick, moved/dragged ball cancellation, smooth return, original anchor and settings preserved.')


if __name__=='__main__': main()
