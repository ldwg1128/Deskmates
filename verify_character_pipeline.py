"""Registration, tooling, provider contract, scaling, fallback and actual game tests."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from character_resources import CATALOG, Character, discover_characters, load_art, playback_index
from character_pipeline import (GenerationJob, analyze, audit, checklist, generate, import_animation,
    jobs, open_character, preview, register, review, specification, sync_character, templates, write_json)
from character_validation import digest, validate_structure


class FixtureProvider:
    """Optional-provider contract fixture: produce test geometry, no network/API."""
    def generate(self, job: GenerationJob):
        from examples.create_dummy import pose
        w,h=job.layout['cell']; im=Image.new('RGBA',job.layout['image_size'])
        for i,(x,y,_,_) in enumerate(job.layout['rects']):
            p=pose(job.action_id,i,len(job.layout['rects'])).resize((w,h))
            im.alpha_composite(p,(x,y))
        im.save(job.destination)
        return job.destination


def expect_failure(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('Expected validation failure')


def main():
    app=QApplication.instance() or QApplication([]); app.setQuitOnLastWindowClosed(False)
    from examples.create_dummy import create
    # Persist a real registered fixture and game previews for review.
    demo=Path('artifacts/demo-characters/dummy')
    if not (demo/'character.json').exists(): create(demo)
    c=open_character(demo)
    assert not audit(c)['errors']
    assert audit(c)['completion']==100
    core_hash=digest('desktop_pet.py')
    original_hashes={str(p):digest(p) for p in Path('assets').glob('*.png')}
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp); pack=root/'packs'/'dummy'; shutil.copytree(demo,pack)
        c=open_character(pack)
        assert 'dummy' in discover_characters([pack.parent])
        # Incomplete optional actions still run through every physics/feeding slot.
        fallback=copy.deepcopy(c.data); fallback['id']='fallback'; fallback['name']='Fallback'
        fallback['animations']={'idle':copy.deepcopy(c.data['animations']['idle'])}
        f=Character(c.manifest,fallback)
        report=validate_structure(f)
        assert not report['errors'] and len(report['missing'])==len(CATALOG['actions'])-1
        art=load_art(f).resize(160)
        assert len(art.motion_frames)==6 and len(art.corner_frames)==4 and len(art.frames['gaze'])==16
        for values in art.frames.values(): assert values and all(not p.isNull() for p in values)
        bad=copy.deepcopy(c.data); bad['animations']['idle']['rects'][0]=[-1,0,96,128]
        assert validate_structure(Character(c.manifest,bad))['errors']
        bad=copy.deepcopy(fallback); bad['animations']['hungry']={'fallback':'hungry'}
        assert any('cycle' in e for e in validate_structure(Character(c.manifest,bad))['errors'])
        bad=copy.deepcopy(c.data); bad['canonical']['sha256']='changed'
        assert any('hash' in e for e in validate_structure(Character(c.manifest,bad))['errors'])
        bad=copy.deepcopy(c.data); bad['animations']['idle']['file']='../escape.png'
        assert validate_structure(Character(c.manifest,bad))['errors']
        assert [playback_index(c,'idle',t/7,7) for t in (0,6,7,12)]==[0,6,5,0]
        # Variable catalog scales without editing game code or every character.
        extra={f'test_{i}':{**CATALOG['actions']['wave'],'name':f'Test {i}'} for i in range(300)}
        try:
            CATALOG['actions'].update(extra)
            assert len(specification(c))>=300
            assert len(validate_structure(c)['missing'])==300
            sync_character(c)
            assert all(k in c.data['animations'] for k in extra)
        finally:
            for key in extra: CATALOG['actions'].pop(key)
            for key in extra: c.data['animations'].pop(key)
            write_json(c.manifest,c.data)
        output=root/'jobs'; jobs(c,output,gap=3,reference=open_character('characters/zenith'))
        layout=json.loads((output/'right/layout.json').read_text(encoding='utf-8'))
        assert layout['gap']==3 and len(layout['rects'])==10
        assert Image.open(output/'right/template.png').getchannel('A').getbbox() is None
        assert (output/'right/pose-reference.png').exists() and (output/'right/frames/009.png').exists()
        expect_failure(lambda:import_animation(c,'right',output/'right/template.png',output/'right/layout.json'))
        assert generate(output/'jobs.json')['mode']=='manual'
        assert len(generate(output/'jobs.json','verify_character_pipeline:FixtureProvider','right')['results'])==1
        import_animation(c,'right',output/'right/generated.png',output/'right/layout.json')
        expect_failure(lambda:register(c))  # changed artwork invalidates previous visual approval
        review(c,'right','Fixture provider preserves deterministic robot design; reviewed guide and preview.')
        register(c)
        # Individual frame input and invalid opaque output.
        frames=root/'individual'; frames.mkdir()
        sheet=Image.open(output/'right/generated.png')
        for i,(x,y,w,h) in enumerate(layout['rects']): sheet.crop((x,y,x+w,y+h)).save(frames/f'{i:03}.png')
        import_animation(c,'right',frames,individual=True)
        review(c,'right','Individual fixture frames reviewed after strip assembly.')
        register(c)
        opaque=Image.new('RGBA',layout['image_size'],'black'); opaque.save(root/'opaque.png')
        expect_failure(lambda:import_animation(c,'right',root/'opaque.png',output/'right/layout.json'))
        # Invalid external pack is ignored, leaving built-ins intact.
        malformed=root/'packs'/'malformed'; malformed.mkdir(); (malformed/'character.json').write_text('[]')
        assert {'zenith','liberta','dummy'}<=discover_characters([pack.parent]).keys()
        # Actual registry discovery precedes importing game. No CHARACTERS mutation.
        os.environ['DESKMATES_CHARACTER_PATH']=str(pack.parent.resolve())
        from desktop_pet import DesktopPet, CHARACTERS
        assert 'dummy' in CHARACTERS
        settings=root/'settings.json'; settings.write_text(json.dumps({'character':'dummy','appetites':{'removed_pack':{'stack':2}}}),encoding='utf-8')
        pet=DesktopPet(settings,start_timer=False); assert pet.character_id=='dummy'
        for height in (64,160,400):
            pet.set_size(height,save=False)
            for mode in ('free','edge'):
                for direction in ('clockwise','counterclockwise'):
                    pet.set_roaming(mode,direction,save=False)
                    for state in ('idle','left','right','wave','jump','bow','shy','think','tilt','gaze','hungry','feed_drop','feed_eat','feed_happy','feed_refuse'):
                        pet.enter_state(state,10)
                        for t in (0,.23,.7,1.4,2.7):
                            pet.state_time=t; pet.walk_distance=20*t; pet.update_frame(QPoint(600,300))
                            assert not pet.pixmap.isNull()
                    if mode=='edge':
                        for segment,length in enumerate(pet.edge_route.lengths):
                            pet.edge_progress=pet.edge_route.starts[segment]+length*.5
                            pet.enter_state('right',10); pet.place_edge(); pet.update_frame()
        pet.set_roaming('free','clockwise',save=False)
        pet.enter_state('idle',10); pet.begin_drag(QPoint(round(pet.x),round(pet.y-60)))
        pet.update_frame(); pet.finish_drag()
        for _ in range(120): pet.advance(.03,QPoint(-9999,-9999))
        pet.save_settings(); assert 'removed_pack' in json.loads(settings.read_text(encoding='utf-8'))['appetites']
        pet.quit_pet()
        os.environ.pop('DESKMATES_CHARACTER_PATH',None)
    preview(open_character(demo),'artifacts/demo-preview')
    result=analyze('docs/generated')
    assert not result['unmapped_states'], result['unmapped_states']
    assert core_hash==digest('desktop_pet.py')
    assert original_hashes=={str(p):digest(p) for p in Path('assets').glob('*.png')}
    print('PASS: registered dummy through external folder discovery; 3 sizes, both roam modes/directions, all states, corners, drag/fall/land.')
    print('PASS: 300 added catalog actions, fallback, validation failures, manual import, optional provider, guides, identity review and GIF previews.')


if __name__=='__main__': main()
