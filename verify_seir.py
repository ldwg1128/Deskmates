"""Real registered Seir pack: all resources, gameplay phases and native desktop play."""
import json
from pathlib import Path
import tempfile
import time
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QMenu
from character_resources import CATALOG, discover_characters, extract_frames
from character_validation import audit
from desktop_pet import DesktopPet, FEED_STATES
from appetite import Appetite


def main():
    app=QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    character=discover_characters([])['seir']
    assert character.name=='세이르 (Seir)'
    qa=audit(character)
    assert not qa['errors'] and not qa['missing'] and qa['completion']==100
    assert set(qa['actions'])==set(CATALOG['actions'])
    assert sum(x['frame_count'] for x in qa['actions'].values())==110
    left,right=extract_frames(character,'left'),extract_frames(character,'right')
    assert len(left)==len(right)==8
    for a,b in zip(left,right):
        assert a.toImage()==b.toImage().flipped(Qt.Orientation.Horizontal)
    far=QPoint(-10000,-10000); snapshots=[]
    with tempfile.TemporaryDirectory() as folder:
        settings=Path(folder)/'settings.json'
        settings.write_text(json.dumps({'character':'seir','feeding_enabled':True}),encoding='utf-8')
        pet=DesktopPet(settings,start_timer=False); pet.show(); app.processEvents()
        pet.next_hunger=pet.next_gaze=float('inf')
        pet.interactions.sleep_enabled=pet.interactions.rare_enabled=False
        menu=QMenu(); pet.populate_menu(menu)
        chars=next(a.menu() for a in menu.actions() if a.text()=='캐릭터 전환')
        assert any(a.text()=='세이르 (Seir)' and a.isChecked() for a in chars.actions())
        for height in (64,160,320,400):
            pet.set_size(height,save=False)
            assert pet.walk_originals  # metadata enables horizontal, distance-paced side walk
            for frame in pet.frames['idle']:
                bounds=QRegion(frame.mask()).boundingRect()
                assert not bounds.isEmpty() and abs(bounds.height()-height)<=max(3,round(height*.04))
            for state in ('idle','left','right','wave','jump','bow','shy','think','tilt','gaze','hungry','feed_eat','feed_happy','feed_refuse'):
                pet.enter_state(state,10)
                for t in (0,.23,.7,1.3,2.7):
                    pet.state_time=t; pet.walk_distance=t*46; pet.update_frame(QPoint(900,300))
                    rect=QRegion(pet.pixmap.mask()).boundingRect()
                    assert not rect.isEmpty() and pet.pixmap.rect().contains(rect)
                if height==160: snapshots.append((state,pet.pixmap.copy()))
            pet.set_roaming('free','clockwise',save=False)
            pet.screen_area=QRect(0,0,1920,1080); pet.anchor_x=pet.x=960; pet.anchor_y=pet.y=1020
            pet.position_window(); pet.enter_state('idle',1)
            for _ in range(10):
                pet.start_walk(); assert pet.target[1]==pet.y
            pet.begin_drag(QPoint(960,400)); pet.finish_drag()
            for _ in range(200):
                pet.advance(.03,far)
                if pet.state not in ('flip','land'): break
            assert not pet.dragging and pet.state not in ('flip','land')
            for direction in ('clockwise','counterclockwise'):
                pet.set_roaming('edge',direction,save=False)
                for segment,length in enumerate(pet.edge_route.lengths):
                    pet.edge_progress=pet.edge_route.starts[segment]+length*.5
                    pet.enter_state('right',20); pet.place_edge(); pet.update_frame()
                    assert not QRegion(pet.pixmap.mask()).boundingRect().isEmpty()
            pet.set_roaming('free','clockwise',save=False)
        pet.set_size(160,save=False); pet.set_roaming('free','clockwise',save=False)
        pet.enter_state('idle',10); pet.interactions.cursor_enabled=False
        for stacks in (0,5):
            pet.appetites['seir']=Appetite(stacks,time.time(),pet.digest_seconds)
            pet.feed_cooldown=0; pet.speech.hide(); pet.near_cursor=True
            pet.update_bread_button(.8); assert pet.bread_button.isVisible()
            pet.bread_button.click(); assert pet.state=='feed_drop'
            for _ in range(100):
                pet.advance(.1,far)
                if pet.state not in FEED_STATES: break
            assert pet.state not in FEED_STATES and pet.appetite.stacks==(1 if stacks==0 else 5)
        pet.set_size(400,save=False)
        pet.set_character('liberta'); pet.set_character('seir'); pet.save_settings()
        restored=DesktopPet(settings,start_timer=False)
        assert restored.character_id=='seir' and restored.body_height==400
        restored.hide(); pet.hide()
        from tools.stage_runtime_characters import stage
        staged=Path(folder)/'runtime-characters'; paths=stage(staged)
        assert (staged/'seir/character.json').is_file()
        for path in paths:
            assert 'prompts' not in path.parts and 'sources' not in path.parts
        frozen_pack=type(character)(staged/'seir/character.json',character.data)
        from character_validation import validate_structure
        assert not validate_structure(frozen_pack)['errors']
    output=Path('artifacts/seir'); output.mkdir(parents=True,exist_ok=True)
    width=220; columns=5; rows=(len(snapshots)+columns-1)//columns
    sheet=QImage(columns*width,rows*240,QImage.Format.Format_ARGB32); sheet.fill(QColor('#e9edf4'))
    painter=QPainter(sheet)
    for i,(name,pixmap) in enumerate(snapshots):
        x=i%columns*width; y=i//columns*240
        painter.setPen(QColor('#27364b')); painter.drawText(x+8,y+18,name)
        p=pixmap.scaled(210,210,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(x+(width-p.width())//2,y+24,p)
    painter.end(); sheet.save(str(output/'game-preview.png'))
    from verify_desktop_interactions import run
    run(('seir',),output/'desktop-play')
    print('PASS: Seir discovered and selectable; 22 actions/110 frames, mirrored walking, 4 sizes, all game states, drag/fall/landing, both edge directions and settings restore.')


if __name__=='__main__': main()
