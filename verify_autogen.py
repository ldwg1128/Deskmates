"""Full generation lifecycle with deterministic faulty models, without paid calls."""
import base64
import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from PIL import Image
from PySide6.QtWidgets import QApplication
from character_autogen import (Budget, BudgetExceeded, RenderRequest, approve_frames,
    frame_qa, ingest_candidate, load_design, prepare, run)
from character_pipeline import open_character, preview
from character_resources import CATALOG, discover_characters
from character_validation import digest
from examples.create_dummy import pose


class FaultyModel:
    available=True
    usage={'test_fixture':True}
    def __init__(self,forever=False):
        self.requests=[]; self.forever=forever; self.good_zero=None
    def quote(self,kind): return '.01'
    def analyze(self,design,references):
        assert len(references)==3
        return {'appearance':'geometric blue robot','eyes':'two dark blue eyes',
                'hair':'gold antenna, no hair','outfit':'blue body, gold square',
                'body_proportions':'same proportions as reference'}
    def render(self,request):
        self.requests.append(request)
        im=Image.new('RGBA',request.layout['image_size']); n=len(request.layout['rects'])
        for i,(x,y,w,h) in enumerate(request.layout['rects']):
            p=pose(request.action,i,n).resize((w,h)); im.alpha_composite(p,(x,y))
        if request.action=='right':
            if request.previous is None:
                x,y,w,h=request.layout['rects'][2]
                im.paste((0,0,0,0),(x,y,x+w,y+h))
                self.good_zero=im.crop((0,0,96,128)).tobytes()
            else:
                assert request.selected_frames==(2,), request.selected_frames
                assert request.mask and request.references
                # Simulate a model disobeying the mask outside the defect.
                im.paste((255,0,0,255),(0,0,96,128))
                if self.forever:
                    x,y,w,h=request.layout['rects'][2]; im.paste((0,0,0,0),(x,y,x+w,y+h))
        im.save(request.destination)
        return request.destination
    def inspect(self,design,references,frames,action):
        return [{'index':i,'status':'pass' if Image.open(p).getchannel('A').getbbox() else 'fail',
                 'issues':[] if Image.open(p).getchannel('A').getbbox() else ['blank']} for i,p in enumerate(frames)]


class UnreadableModel(FaultyModel):
    def render(self,request):
        if not self.requests:
            self.requests.append(request); request.destination.write_bytes(b'not an image')
            return request.destination
        return super().render(request)


class TimeoutModel(FaultyModel):
    def render(self,request):
        self.requests.append(request)
        raise TimeoutError('simulated ambiguous paid request')


def failed(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('Expected failure')


def main():
    app=QApplication.instance() or QApplication([])
    original={str(p):digest(p) for p in Path('assets').glob('*.png')}
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        refs={}
        for role in ('front','side','back'):
            path=root/f'{role}.png'; pose('idle',0,1).save(path); refs[role]=path
        c=prepare(root/'packs'/'generated','generated','Generated QA',refs,cell=(96,128),anchor=(48,124))
        manual=run(c)
        assert manual['mode']=='manual' and not manual['registered'] and manual['reserved_usd']=='0'
        assert all(s['status']=='awaiting_image' for s in manual['actions'].values())
        # No API SDK/key => safe manual mode, no network calls.
        from image_providers import OpenAIProvider
        offline=OpenAIProvider({'api_key_env':'DESKMATES_UNUSED_TEST_KEY'})
        assert not offline.available
        # Separate fresh character lets the vision stage run before state exists.
        c=prepare(root/'packs'/'generated2','generated2','Generated QA 2',refs,cell=(96,128),anchor=(48,124))
        provider=FaultyModel()
        state=run(c,provider=provider,max_retries=2,cost_limit='1')
        assert state['registered'] and all(a['status']=='accepted' for a in state['actions'].values())
        requests=[r for r in provider.requests if r.action=='right']
        assert len(requests)==2 and requests[1].selected_frames==(2,)
        assert requests[0].design==requests[1].design
        assert requests[0].references==requests[1].references
        image=Image.open(state['actions']['right']['candidate'])
        assert image.crop((0,0,96,128)).tobytes()==provider.good_zero
        assert len(load_design(c)['references'])==3 and load_design(c)['features']['eyes']
        assert 'generated2' in discover_characters([root/'packs'])
        # Load the automatically generated pack through actual game discovery,
        # using isolated settings and unchanged core behavior code.
        os.environ['DESKMATES_CHARACTER_PATH']=str((root/'packs').resolve())
        from desktop_pet import DesktopPet
        settings=root/'game-settings.json'; settings.write_text(json.dumps({'character':'generated2'}))
        pet=DesktopPet(settings,start_timer=False)
        assert pet.character_id=='generated2'
        for action in ('idle','right','left','wave','jump','bow','shy','think','tilt','gaze','hungry','feed_drop','feed_eat','feed_happy','feed_refuse'):
            pet.enter_state(action,10); pet.state_time=.5; pet.update_frame()
            assert not pet.pixmap.isNull()
        pet.quit_pet(); os.environ.pop('DESKMATES_CHARACTER_PATH',None)
        spent=state['reserved_usd']; count=len(provider.requests)
        again=run(c,provider=provider,max_retries=2,cost_limit='1')
        assert again['reserved_usd']==spent and len(provider.requests)==count
        # Budget reservations persist across process-style resume and errors.
        limited=prepare(root/'limited','limited','Limited',refs,cell=(96,128),anchor=(48,124))
        poor=FaultyModel()
        state=run(limited,provider=poor,max_retries=2,cost_limit='.02')
        assert not state['registered'] and len(poor.requests)==1
        assert len(json.loads((limited.manifest.parent/'production/budget.json').read_text())['requests'])==2
        state=run(limited,provider=poor,max_retries=2,cost_limit='.02')
        assert len(poor.requests)==1
        # Invalid files are recoverable; failed network requests consume both
        # an attempt and a reservation rather than resetting on restart.
        unreadable=prepare(root/'unreadable','unreadable','Unreadable',refs,cell=(96,128),anchor=(48,124))
        odd=UnreadableModel()
        state=run(unreadable,provider=odd,max_retries=1,cost_limit='1',actions=['idle'])
        assert state['actions']['idle']['status']=='accepted' and len(odd.requests)==2
        timeout=prepare(root/'timeout','timeout','Timeout',refs,cell=(96,128),anchor=(48,124))
        slow=TimeoutModel()
        state=run(timeout,provider=slow,max_retries=1,cost_limit='1',actions=['idle'])
        assert state['actions']['idle']['attempts']==2 and len(slow.requests)==2
        run(timeout,provider=slow,max_retries=1,cost_limit='1',actions=['idle'])
        assert len(slow.requests)==2
        # Retry ceiling survives resume; unrepaired structural defects can't be waived.
        broken=prepare(root/'broken','broken','Broken',refs,cell=(96,128),anchor=(48,124))
        always=FaultyModel(forever=True)
        state=run(broken,provider=always,max_retries=1,cost_limit='1',actions=['idle','right'])
        assert state['actions']['right']['attempts']==2
        assert state['actions']['right']['status']=='needs_review'
        failed(lambda:approve_frames(broken,'right',[2],'Cannot approve blank frame'))
        run(broken,provider=always,max_retries=1,cost_limit='1',actions=['right'])
        assert len([r for r in always.requests if r.action=='right'])==2
        # A corrected external strip re-enters QA, with manual identity approval.
        layout=json.loads((broken.manifest.parent/'production/right/layout.json').read_text())
        fixed=Image.new('RGBA',layout['image_size'])
        for i,(x,y,w,h) in enumerate(layout['rects']): fixed.alpha_composite(pose('right',i,len(layout['rects'])),(x,y))
        fixed.save(root/'fixed.png'); ingest_candidate(broken,'right',root/'fixed.png')
        run(broken,actions=['right'])
        approve_frames(broken,'right',None,'All frames compared with the canonical robot; design and continuity accepted.')
        state=run(broken,actions=['right'])
        assert state['actions']['right']['status']=='accepted'
        assert (broken.manifest.parent/'production/review.html').exists()
        # New catalog entry is discovered and generated incrementally; accepted
        # images and previous costs do not reset.
        try:
            CATALOG['actions']['new_behavior']={**CATALOG['actions']['wave'],'name':'new behavior'}
            state=run(c,provider=provider,max_retries=1,cost_limit='1')
            assert state['actions']['new_behavior']['status']=='accepted'
            assert len(provider.requests)==count+1
        finally: CATALOG['actions'].pop('new_behavior',None)
        # Reference edits invalidate every future generation/approval.
        changed=Image.new('RGBA',(96,128),'red'); changed.save(c.path('references/front.png'))
        failed(lambda:run(c,provider=provider,cost_limit='1'))
        # Actual API adapter contract, including references and mask, mocked SDK.
        calls=[]
        def edit(**kwargs):
            calls.append(kwargs)
            out=root/'api.png'; Image.new('RGBA',(1536,1024)).save(out)
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(out.read_bytes()).decode())],usage=None)
        def response(**kwargs):
            calls.append(kwargs); return SimpleNamespace(output_text=json.dumps({'frames':[{'index':0,'status':'pass','confidence':.1}]}),usage=None)
        api=OpenAIProvider({'image_model':'configured-image','vision_model':'configured-vision','image_size':'1536x1024',
            'allowance_usd':{'render':'.01','inspect':'.01','analyze':'.01'}},
            client=SimpleNamespace(images=SimpleNamespace(edit=edit),responses=SimpleNamespace(create=response)))
        req=requests[1]
        api.render(RenderRequest(req.action,req.prompt,req.references,req.design,req.layout,root/'adapter.png',req.selected_frames,Path(state['actions']['right']['candidate']),req.mask))
        assert calls[-1]['background']=='transparent' and len(calls[-1]['image'])==4 and 'mask' in calls[-1]
        assert api.inspect({'features':{}},tuple(refs.values()),[refs['front']],'idle')[0]['status']=='review'
    assert original=={str(p):digest(p) for p in Path('assets').glob('*.png')}
    print('PASS: multiview specification, all-action generation, identity/alpha/geometry QA, frame-only repair preserving good pixels, retries, persistent budget, manual correction/approval, registration and incremental actions.')
    print('PASS: optional OpenAI adapter mocked SDK request/response contract; no paid API calls or original asset edits.')


if __name__=='__main__': main()
