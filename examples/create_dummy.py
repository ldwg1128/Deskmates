"""Build a geometric QA fixture, not AI character artwork. Never touches assets/."""
import math
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from character_pipeline import init_character, import_animation, open_character, review, register, write_json
from character_resources import CATALOG


def pose(action,index,count):
    im=Image.new('RGBA',(96,128)); d=ImageDraw.Draw(im)
    phase=2*math.pi*index/max(count,1)
    step=round(math.sin(phase)*5) if action in ('left','right') else 0
    # Face, eyes, hair/antenna, outfit and anatomical scale stay identical.
    d.line((48,8,48,15),fill='#203455',width=3)
    d.ellipse((43,3,53,13),fill='#ffcb69')
    d.rounded_rectangle((22,16,74,64),12,fill='#8ecae6',outline='#203455',width=3)
    d.ellipse((32,34,39,43),fill='#203455'); d.ellipse((57,34,64,43),fill='#203455')
    d.arc((39,43,57,55),0,180,fill='#203455',width=2)
    d.rounded_rectangle((28,65,68,104),6,fill='#219ebc',outline='#203455',width=3)
    d.rectangle((42,75,54,86),fill='#ffcb69')
    arm=round(math.sin(phase)*9) if action in ('wave','feeding','refusal','hungry') else 0
    d.line((27,74,14,92-arm),fill='#203455',width=8)
    d.line((69,74,82,92+arm),fill='#203455',width=8)
    d.line((38,101,35+step,119),fill='#203455',width=9)
    d.line((58,101,61-step,119),fill='#203455',width=9)
    d.rounded_rectangle((25+step,115,42+step,123),3,fill='#203455')
    d.rounded_rectangle((54-step,115,71-step,123),3,fill='#203455')
    return im


def create(folder):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    canonical=folder/'seed.png'; pose('idle',0,1).save(canonical)
    c=init_character(folder,'dummy','더미 (Dummy)',canonical,cell=(96,128),anchor=(48,124),
        identity='Synthetic QA robot: blue rounded face, dark blue eyes and suit outline, gold antenna and chest. Fixed head/body ratio.')
    c.data['body_height']=120
    # Different frame count and FPS exercise the absence of fixed atlas constraints.
    c.data['animations']['idle'].update(frame_count=7,fps=7,loop='pingpong')
    c.data['animations']['right'].update(frame_count=10,fps=12)
    write_json(c.manifest,c.data)
    work=folder/'fixture-sources'; work.mkdir(exist_ok=True)
    for action,default in CATALOG['actions'].items():
        count=c.data['animations'][action]['frame_count']
        frames=[pose(action,i,count) for i in range(count)]
        sheet=Image.new('RGBA',(96*count,128))
        for i,p in enumerate(frames): sheet.alpha_composite(p,(96*i,0))
        source=work/f'{action}.png'; sheet.save(source)
        layout=work/f'{action}.json'
        write_json(layout,{'action_id':action,'cell':[96,128],'image_size':list(sheet.size),
            'rects':[[i*96,0,96,128] for i in range(count)],'anchor':[48,124],
            'fps':c.data['animations'][action]['fps'],'loop':c.data['animations'][action]['loop']})
        import_animation(c,action,source,layout)
        review(c,action,'Deterministic geometric QA fixture: identical face and proportions by construction. Not production character art.')
    register(c)
    return c


if __name__=='__main__':
    from PySide6.QtWidgets import QApplication
    app=QApplication([])
    c=create(sys.argv[1] if len(sys.argv)>1 else 'artifacts/demo-characters/dummy')
    print(f'Registered {c.manifest}')
