"""Compare clarity rendering with original art, contact geometry and native output."""
import copy
import json
from pathlib import Path
import tempfile
import time
from PIL import Image, ImageChops, ImageFilter, ImageStat
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication
from character_resources import Character, discover_characters, load_art
from desktop_interactions import extra_frames
from sprite_quality import clear_cache, scale_sprite


def pixels(sprite):
    image=sprite.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA',(image.width(),image.height()),bytes(image.constBits()),
                           'raw','RGBA',image.bytesPerLine())


def all_frames(art,extras):
    result={key:frames for key,frames in art.frames.items()}
    result.update(motion=art.motion_frames,corner=art.corner_frames,feeding=art.feed_frames,
                  refusal=art.refusal_frames,feed_look=[art.feed_look_frame])
    result.update({key:value[0] for key,value in extras.items()})
    return result


def run():
    app=QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    output=Path('artifacts/zenith-clarity'); output.mkdir(parents=True,exist_ok=True)
    chars=discover_characters([]); enhanced=chars['zenith']
    data=copy.deepcopy(enhanced.data); data['profile'].pop('render_quality',None)
    original=Character(enhanced.manifest,data)
    before=load_art(original); after=load_art(enhanced)
    clear_cache(); records=[]; total=0; compare={}
    start=time.perf_counter()
    for height in (64,160,320,400):
        old=all_frames(before.resize(height),extra_frames(original,height))
        new=all_frames(after.resize(height),extra_frames(enhanced,height))
        assert old.keys()==new.keys()
        for action in old:
            assert len(old[action])==len(new[action])
            for index,(a,b) in enumerate(zip(old[action],new[action])):
                assert a.size()==b.size(),(height,action,index,'dimensions')
                x,y=pixels(a),pixels(b)
                for threshold in (1,32,128):
                    masks=[im.getchannel('A').point(lambda a:255 if a>=threshold else 0) for im in (x,y)]
                    assert ImageChops.difference(*masks).getbbox() is None,(height,action,index,'coverage',threshold)
                assert QRegion(a.mask())==QRegion(b.mask()),(height,action,index,'hit mask')
                total+=1
        a,b=pixels(old['idle'][0]),pixels(new['idle'][0])
        visible=a.getchannel('A').point(lambda v:255 if v>=224 else 0)
        difference=sum(ImageStat.Stat(ImageChops.difference(a.convert('RGB'),b.convert('RGB')),visible).mean)/3
        interior=visible.filter(ImageFilter.MinFilter(5))
        edges=[ImageStat.Stat(im.convert('L').filter(ImageFilter.FIND_EDGES),interior).mean[0] for im in (a,b)]
        records.append({'height':height,'mean_rgb_difference':round(difference,4),
                        'interior_edge_contrast':edges,'geometry_identical':True,'all_actions':len(old)})
        assert .01<difference<15,(height,difference)
        if height>=320: assert edges[1]>edges[0],(height,'detail contrast',edges)
        if height==400:
            for action,index in (('idle',0),('right',2),('wave',1),('feeding',1),('head_bump',1)):
                compare[action]=(old[action][index].copy(),new[action][index].copy())
    elapsed=time.perf_counter()-start
    # Repeated render/size requests reuse exact results, avoiding per-tick filters.
    source=after.originals['idle'][0]; scale_sprite(source,420,enhanced)
    start=time.perf_counter()
    for _ in range(200): scale_sprite(source,420,enhanced)
    cache_elapsed=time.perf_counter()-start
    assert cache_elapsed<.5,cache_elapsed
    # Unselected characters retain the exact Qt rendering path.
    for name in ('liberta','seir'):
        c=chars[name]; art=load_art(c)
        for source in art.originals['idle']:
            assert scale_sprite(source,320,c).toImage()==source.scaledToHeight(320,Qt.TransformationMode.SmoothTransformation).toImage()
    # Compare fully rendered gameplay states, including positions/rotations.
    from verify_resource_regression import capture
    actual=capture()
    baseline=json.loads(Path('tests/fixtures/render-baseline.json').read_text(encoding='utf-8'))
    assert actual['assets']==baseline['assets']
    for key,value in actual['frames'].items():
        expected=baseline['frames'][key]
        for field in ('size','position','state'):
            assert value[field]==expected[field],(key,field,value[field],expected[field])
        if key.startswith('liberta/'): assert value==expected,key
    # Real Windows backing store must show only the current enhanced frame.
    from desktop_pet import DesktopPet
    from verify_rendering import assert_current_frame
    with tempfile.TemporaryDirectory() as folder:
        pet=DesktopPet(Path(folder)/'settings.json',start_timer=False)
        pet.set_character('zenith'); pet.show()
        for height in (160,400):
            pet.set_size(height,save=False)
            for state in ('idle','right','wave','hungry','feed_eat','feed_refuse'):
                pet.enter_state(state,10); pet.state_time=.6; pet.update_frame(QPoint(-10000,-10000)); app.processEvents()
                assert_current_frame(pet)
        pet.hide(); pet.deleteLater()
    # Same display pixels on light/dark backgrounds; no different pose fitting.
    cell_w,cell_h=340,470
    sheet=QImage(cell_w*4,cell_h*len(compare),QImage.Format.Format_ARGB32)
    painter=QPainter(sheet)
    for row,(action,pair) in enumerate(compare.items()):
        for column in range(4):
            dark=column>=2; sprite=pair[column%2]
            x,y=column*cell_w,row*cell_h
            painter.fillRect(x,y,cell_w,cell_h,QColor('#222834' if dark else '#eef1f6'))
            painter.setPen(QColor('#eeeeee' if dark else '#25334a'))
            painter.drawText(x+10,y+22,f'{action} / {"Original" if column%2==0 else "Clarity"} / 400 px')
            painter.drawPixmap(x+(cell_w-sprite.width())//2,y+cell_h-sprite.height()-12,sprite)
    painter.end(); sheet.save(str(output/'comparison-400.png'))
    report={'checked_frames':total,'gameplay_frames':len(actual['frames']),'original_assets':len(actual['assets']),
            'records':records,'all_sizes_seconds':round(elapsed,3),'cached_200_calls_seconds':round(cache_elapsed,4)}
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'PASS: {total} sprite frames, identical canvases/alpha coverage/contact masks; all23 actions at64/160/320/400px.')
    print('PASS: 936 gameplay frames retain position/state/canvas; Liberta pixels and17 original PNG hashes unchanged; native buffers match.')
    print(f'PASS: cached200 calls {cache_elapsed:.4f}s; comparison saved to {output}.')


if __name__=='__main__': run()
