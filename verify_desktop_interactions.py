"""Exercise desktop play with injected ledges plus real Windows geometry APIs."""
from pathlib import Path
import json
import math
import sys
import tempfile
from unittest.mock import patch
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget
from appetite import Appetite
from character_resources import action_spec
from desktop_pet import BehaviorSettingsDialog, DesktopPet
from window_surfaces import WindowSurface, WindowsSurfaces, select_ledge


class FakeWindows:
    def __init__(self): self.surface=WindowSurface(12,QRectF(220,430,900,300))
    def all(self): return [self.surface] if self.surface else []
    def get(self,handle): return self.surface if self.surface and self.surface.handle==handle else None


def run(characters=('zenith','liberta'), output=Path('artifacts/interactions')):
    app=QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    far=QPoint(-10000,-10000)
    snapshots=[]
    with tempfile.TemporaryDirectory() as folder:
        pet=DesktopPet(Path(folder)/'settings.json',start_timer=False)
        pet.show(); app.processEvents()
        ctrl=pet.interactions
        ctrl.sleep_enabled=ctrl.rare_enabled=False
        for character in characters:
            pet.set_character(character)
            pet.screen_area=QRect(0,0,1600,1000)
            pet.anchor_x,pet.anchor_y=800,950; pet.x,pet.y=800,950
            pet.next_hunger=float('inf')
            for mode in ('free','edge'):
                pet.set_roaming(mode,'counterclockwise',save=False)
                for side in (0,-1,1):
                    corner=side!=0
                    fake=FakeWindows(); ctrl.windows=fake
                    point=QPoint(220 if side<0 else 1120 if side>0 else 700,520 if corner else 430)
                    pet.begin_drag(point); pet.finish_drag()
                    assert ctrl.kind==('ledge_struggle' if corner else 'window_sit')
                    if corner:
                        assert ctrl.side==side and ctrl.point.y()==520
                        sprite,contact=ctrl._pose('ledge_struggle')
                        assert (QRegion(sprite.mask()).boundingRect().center().x()-contact.x())*side>0
                    assert pet.roam_mode==mode and pet.edge_direction=='counterclockwise'
                    before=QPointF(ctrl.point)
                    fake.surface=WindowSurface(12,fake.surface.rect.translated(25,12))
                    pet.advance(.1,far)
                    assert ctrl.point==before+QPointF(25,12)
                    if mode=='free':
                        preview=pet.pixmap.copy()
                        if corner:
                            preview.fill(Qt.GlobalColor.transparent); painter=QPainter(preview)
                            cx,cy=pet.width()/2,pet.height()/2
                            painter.setPen(QPen(QColor('#7a91ac'),2)); painter.setBrush(QColor('#d4dfea'))
                            painter.drawRect(QRectF(cx-150 if side>0 else cx,cy-70,150,260))
                            painter.drawPixmap(0,0,pet.pixmap); painter.end()
                        snapshots.append((f'{character}: {ctrl.kind} {side:+}',preview))
                    if corner:
                        fake.surface=None; pet.advance(.1,far)
                        assert ctrl.kind=='interaction_fall'
                    else:
                        pet.advance(ctrl.duration,far)
                        assert ctrl.kind=='interaction_jump'
                    for _ in range(150):
                        pet.advance(.1,far)
                        if ctrl.kind is None: break
                    assert ctrl.kind is None and pet.state=='idle'
                    assert pet.roam_mode==mode and pet.edge_direction=='counterclockwise'
                    assert pet.paused is False
            # 30 minutes of no interaction, then walking to a corner and waking.
            pet.set_roaming('free','clockwise',save=False)
            pet.screen_area=QRect(0,0,1600,1000)
            pet.set_size(160,save=False); pet.anchor_x=pet.x=800; pet.anchor_y=pet.y=950
            pet.speed=100; ctrl.sleep_enabled=True; ctrl.sleep_seconds=1800; ctrl.activity()
            pet.advance(1799,far); assert ctrl.kind is None
            # Cross the threshold slightly; accumulated fractional animation
            # ticks may put a nominal 1800.0 a few microseconds below it.
            pet.advance(1.01,far); assert ctrl.kind=='sleep_walk'
            for _ in range(220):
                pet.advance(.1,far)
                if ctrl.kind=='sleep': break
            assert ctrl.kind=='sleep'
            assert min(abs(ctrl.point.x()-pet.screen_area.left()),abs(ctrl.point.x()-pet.screen_area.right()))<200
            snapshots.append((f'{character}: sleeping',pet.pixmap.copy()))
            pet.advance(1,far); assert ctrl.kind=='sleep'
            local=QRegion(pet.pixmap.mask()).boundingRect().center()
            QTest.mouseClick(pet,Qt.MouseButton.LeftButton,pos=local)
            assert ctrl.kind=='wake_annoyed' and pet.state=='wake_annoyed'
            assert '조금만 더' in pet.speech.text()
            snapshots.append((f'{character}: annoyed wake',pet.pixmap.copy()))
            pet.advance(1.9,far); assert ctrl.kind is None
            ctrl.sleep_enabled=False
            # A stationary pet stays in place; edge sleep walks along the chosen route.
            pet.stationary=True; old=QPointF(ctrl.feet()); ctrl.start_sleep()
            assert ctrl.kind=='sleep' and ctrl.point==old
            ctrl.wake(); pet.advance(2,far); pet.stationary=False
            pet.set_roaming('edge','counterclockwise',save=False)
            pet.edge_progress=pet.edge_route.starts[4]+pet.edge_route.lengths[4]*.5
            pet.place_edge(); ctrl.start_sleep()
            for _ in range(200):
                pet.advance(.1,far)
                if ctrl.kind=='sleep': break
            assert ctrl.kind=='sleep' and pet.edge_direction=='counterclockwise'
            ctrl.wake(); pet.advance(2,far)
            assert ctrl.kind is None and pet.roam_mode=='edge'
            # Waist cursor approach/grasp, escape, cooldown and unchanged walk anchor.
            pet.set_roaming('free','clockwise',save=False)
            pet.anchor_x=pet.x=800; pet.anchor_y=pet.y=950; pet.speed=100
            pet.position_window(); pet.update_frame()
            anchor=(pet.anchor_x,pet.anchor_y)
            waist=pet.feeding_point(pet.body_height*.45)
            cursor=QPoint(round(pet.x+100),round(waist.y()))
            ctrl.cursor_cooldown=0; pet.advance(.71,cursor)
            assert ctrl.kind=='cursor_approach'
            for _ in range(30):
                pet.advance(.1,cursor)
                if ctrl.kind=='cursor_grab': break
            assert ctrl.kind=='cursor_grab'
            snapshots.append((f'{character}: cursor grab',pet.pixmap.copy()))
            pet.advance(1.2,cursor)
            assert ctrl.kind is None and (pet.anchor_x,pet.anchor_y)==anchor and ctrl.cursor_cooldown>0
            ctrl.cursor_cooldown=0; waist=pet.feeding_point(pet.body_height*.45)
            cursor=QPoint(round(pet.x+100),round(waist.y()))
            pet.advance(.71,cursor); assert ctrl.kind=='cursor_approach'
            pet.advance(.1,far); assert ctrl.kind is None
            # Ball has its own draggable native widget and disappears after a kick.
            ctrl.ball.spawn(); app.processEvents()
            ball=ctrl.ball; position=ball.pos()
            QTest.mousePress(ball,Qt.MouseButton.LeftButton,pos=QPoint(18,18))
            QTest.mouseMove(ball,QPoint(38,18))
            QTest.mouseRelease(ball,Qt.MouseButton.LeftButton,pos=QPoint(18,18))
            assert not ball.dragging and ball.pos()!=position
            pet.screen_area=ball.area()
            idle=pet.frames['idle'][0]; ground=QRegion(idle.mask()).boundingRect().bottom()+1
            pet.anchor_y=pet.y=pet.screen_area.bottom()-2+idle.height()-ground
            pet.position_window(); pet.update_frame()
            feet=ctrl.feet(); ball.motion.release(feet.x()+ctrl._ball_reach(),pet.screen_area.bottom()+1-ball.inset)
            ball.motion.grounded=True; ball.place()
            ball.age=2; pet.advance(.1,far)
            assert ctrl.kind=='kick'
            snapshots.append((f'{character}: kick',pet.pixmap.copy()))
            pet.advance(ctrl.kick_impact_time()+.01,far); assert ball.flying
            pet.advance(1,far)
            for _ in range(30):
                if ctrl.kind is None: break
                pet.advance(.1,far)
            assert not ball.isVisible() and ctrl.kind is None
            # Rare snack is unavailable when fed/disabled/paused; count once only.
            pet.appetites[character]=Appetite(0,0,pet.digest_seconds)
            ctrl.rare_enabled=True; ctrl.next_snack=0; ctrl.clock=1000; pet.near_cursor=False
            with patch.object(ctrl.rng,'random',return_value=0):
                pet.choose_action()
            assert ctrl.kind=='secret_snack'
            assert pet.appetite.stacks==0
            snapshots.append((f'{character}: secret snack',pet.pixmap.copy()))
            pet.advance(2.19,far); assert pet.appetite.stacks==0
            pet.advance(.02,far); assert pet.appetite.stacks==1
            pet.advance(1.1,far); assert ctrl.kind is None and pet.appetite.stacks==1
            ctrl.next_snack=0
            assert not ctrl.maybe_snack()
            pet.appetites[character]=Appetite(0,0,pet.digest_seconds)
            ctrl.next_snack=0
            with patch.object(ctrl.rng,'random',return_value=0): assert ctrl.maybe_snack()
            pet.begin_drag(QPoint(800,300)); assert ctrl.kind is None and pet.appetite.stacks==0
            pet.dragging=False; pet.reset_position(); ctrl.rare_enabled=False
            for height in (64,400):
                pet.set_size(height,save=False); ctrl.point=QPointF(700,600)
                for action in ctrl.frames:
                    ctrl._enter(action,3); ctrl._position()
                    for index in range(4):
                        ctrl.time=(index/action_spec(pet.character,action)['fps']+.01 if action in
                                   ('window_sit','ledge_struggle','sleep') else index*.75+.01)
                        pet.update_frame(); app.processEvents()
                        rect=QRegion(pet.pixmap.mask()).boundingRect()
                        assert not rect.isEmpty() and rect.left()>0 and rect.top()>0 and rect.right()<pet.width()-1 and rect.bottom()<pet.height()-1,(action,height,rect,pet.size())
                        if sys.platform=='win32':
                            from verify_rendering import assert_current_frame
                            assert_current_frame(pet)
                    ctrl.finish()
            pet.set_size(160,save=False)
        # Common settings stage changes until Save, retain 30-minute default.
        ctrl.sleep_seconds=1800; ctrl.sleep_enabled=True
        dialog=BehaviorSettingsDialog(pet)
        assert dialog.sleep_delay.currentData()==1800
        dialog.window_interactions.setChecked(False); dialog.sleep_delay.setCurrentIndex(0); dialog.reject()
        assert ctrl.window_enabled and ctrl.sleep_seconds==1800
        dialog=BehaviorSettingsDialog(pet)
        dialog.window_interactions.setChecked(False); dialog.sleep_delay.setCurrentIndex(0)
        dialog.cursor_play_enabled.setChecked(False); dialog.rare_actions_enabled.setChecked(False)
        dialog.accept()
        restored=DesktopPet(pet.settings_path,start_timer=False)
        assert not restored.interactions.window_enabled and restored.interactions.sleep_seconds==300
        assert not restored.interactions.cursor_enabled and not restored.interactions.rare_enabled
        menu=QMenu(); pet.populate_menu(menu)
        assert any(a.text()=='공 꺼내기' for a in menu.actions())
        assert [a.text() for a in menu.actions()[-2:]]==['마우스 통과','종료']
        ctrl.ball.spawn(); pet.hide(); assert not ctrl.ball.isVisible()
        restored.hide(); restored.deleteLater(); pet.deleteLater()
    # Real native visibility/minimize checks, never change another app.
    if sys.platform=='win32':
        window=QWidget(); window.setWindowTitle('DeskMates ledge geometry test')
        window.resize(500,240); window.move(300,350); window.show(); app.processEvents()
        provider=WindowsSurfaces(exclude_process=0); handle=int(window.winId())
        surface=provider.get(handle); assert surface and surface.rect.width()>=500
        assert select_ledge([surface],QPointF(surface.rect.center().x(),surface.rect.top()),160,QRect(0,0,2000,1400))
        window.showMinimized(); app.processEvents(); assert provider.get(handle) is None
        window.close()
    cell=300; columns=4; rows=math.ceil(len(snapshots)/columns)
    sheet=QImage(cell*columns,cell*rows,QImage.Format.Format_ARGB32); sheet.fill(QColor('#e9edf4'))
    painter=QPainter(sheet)
    for i,(label,pixmap) in enumerate(snapshots):
        x=i%columns*cell; y=i//columns*cell
        painter.setPen(QColor('#27364b')); painter.drawText(x+8,y+18,label)
        scaled=pixmap.scaled(cell-8,cell-30,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(x+(cell-scaled.width())//2,y+24,scaled)
    painter.end(); sheet.save(str(output/'all-interactions-preview.png'))
    print('PASS: ledge sitting/jump, corner struggle/fall, moving/minimized/closed windows; original roam settings restored.')
    print('PASS: 30-minute sleep/corner/wake, stationary/edge modes, waist cursor approach/escape, independent draggable ball/kick, rare snack count/cancel.')
    print('PASS: settings Save/Cancel/restore, native Windows geometry, all new poses unclipped at64/400px with live buffer pixel equality; preview saved.')


if __name__=='__main__':
    run()
