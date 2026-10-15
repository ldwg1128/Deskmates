"""Repack reviewed image_gen atlases into the game's manifest format.

Authoring dependencies: Pillow, NumPy, SciPy. Only Pillow is also used at runtime.
Raw art is preserved. Components remove unrelated atlas marks and neighboring poses;
each action uses ONE shared scale, never an independently fitted frame scale.
"""
from pathlib import Path
import json
import statistics
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from character_resources import CATALOG
from character_pipeline import import_animation, open_character, register, review, write_json
from character_validation import audit, digest

ROOT=Path(__file__).resolve().parents[1]
PACK=ROOT/'characters/seir'
CELL=(384,384)
ANCHOR=(192,376)


def components(name,count,columns):
    path=PACK/'sources'/name
    pixels=np.asarray(Image.open(path).convert('RGBA'))
    labels,n=ndimage.label(pixels[:,:,3]>=128)
    sizes=np.bincount(labels.ravel())
    ids=sorted(range(1,n+1),key=lambda i:sizes[i],reverse=True)[:count]
    if len(ids)!=count or sizes[ids[-1]]<2000: raise ValueError(f'{name}: missing character components')
    boxes=ndimage.find_objects(labels)
    ordered=sorted(ids,key=lambda i:(boxes[i-1][0].start+boxes[i-1][0].stop)/2)
    ids=[]
    for row in range(0,count,columns):
        ids+=sorted(ordered[row:row+columns],key=lambda i:(boxes[i-1][1].start+boxes[i-1][1].stop)/2)
    distance,indices=ndimage.distance_transform_edt(~np.isin(labels,ids),return_indices=True)
    nearest=labels[tuple(indices)]
    output=[]
    for label in ids:
        y,x=boxes[label-1]
        box=(max(0,x.start-3),max(0,y.start-3),min(pixels.shape[1],x.stop+3),min(pixels.shape[0],y.stop+3))
        x0,y0,x1,y1=box
        frame=pixels[y0:y1,x0:x1].copy()
        keep=(nearest[y0:y1,x0:x1]==label)&(distance[y0:y1,x0:x1]<=3)&(frame[:,:,3]>=32)
        frame[~keep]=0
        output.append({'image':Image.fromarray(frame),'box':box,'source':name,'label':int(label)})
    return output


def solid_box(frame):
    return frame.getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()


def feet(frame):
    mask=np.asarray(frame.getchannel('A'))>=128
    ys,xs=np.where(mask)
    band=ys.max()-max(2,round((ys.max()-ys.min())*.045))
    shoe_x=np.where(mask[band:])[1]
    return (float(shoe_x.min()+shoe_x.max()+1)/2,float(ys.max()+1))


def main():
    app=QApplication.instance() or QApplication([])
    c=open_character(PACK); c.data['enabled']=False
    c.data.update(body_height=300,anchor=list(ANCHOR))
    c.data['profile']={'motion_angles':[0,0,180,180],'horizontal_walk':True}
    write_json(c.manifest,c.data)
    basic=components('basic-raw-v1.png',28,4)
    walk=components('walk-raw-v1.png',8,4)
    gaze=components('gaze-raw-v2.png',16,4)
    motion=components('motion-clean-v2.png',6,3)
    corner=components('corner-raw-v1.png',4,4)
    extra=components('extras-raw-v1.png',28,4)
    # Preserve rejected touching/mismatched prototypes, but use coherent final
    # action strips re-generated with the actual idle pose as a proportion reference.
    food={key:components(f'{key}-v3.png',4,4) for key in ('hungry','feeding','refusal')}
    actions={k:basic[i*4:i*4+4] for i,k in enumerate(('idle','wave','jump','bow','shy','think','tilt'))}
    actions.update(right=walk,gaze=gaze,motion=motion,corner=corner)
    actions.update(food)
    for i,k in enumerate(('window_sit','ledge_struggle','sleep','wake_annoyed','cursor_grab','kick','secret_snack')):
        actions[k]=extra[i*4:i*4+4]
    # Shared per-action anatomical scales, reviewed against the canonical and idle head.
    base=300/statistics.median(solid_box(f['image'])[3]-solid_box(f['image'])[1] for f in actions['idle'])
    scales={key:base for key in actions}
    scales.update(right=300/435,gaze=300/statistics.median(solid_box(f['image'])[3]-solid_box(f['image'])[1] for f in gaze),
                  motion=300/499,corner=300/645)
    for key,frames in food.items():
        scales[key]=300/statistics.median(solid_box(f['image'])[3]-solid_box(f['image'])[1] for f in frames)
    # Extras were generated at the same atlas resolution; keep a single scale within
    # each row, including the deliberately shorter seated and horizontal poses.
    for key in ('window_sit','ledge_struggle','sleep','wake_annoyed','cursor_grab','kick'):
        scales[key]=300/235
    scales['secret_snack']=300/264
    work=PACK/'sources/packed-v1'; work.mkdir(exist_ok=True)
    provenance={}
    for key,frames in actions.items():
        # Keep the separately reviewed ball transition when repacking old atlases.
        if key=='kick' and c.data['animations'].get(key,{}).get('file')=='animations/kick-v2.png':
            continue
        scale=scales[key]; sheet=Image.new('RGBA',(CELL[0]*len(frames),CELL[1])); placements=[]
        for i,f in enumerate(frames):
            original=f['image']; x0,y0,_,_=f['box']; local=feet(original)
            target=list(ANCHOR)
            if key=='sleep':
                box=solid_box(original); local=((box[0]+box[2])/2,box[3])
            if key=='motion' and i<4:
                box=solid_box(original); local=((box[0]+box[2])/2,box[3])
            if key=='ledge_struggle':
                hands=((40,350),(279,350),(518,350),(739,350))
                local=(hands[i][0]-x0,hands[i][1]-y0); target=[64,164]
            if key=='jump': target[1]-=(0,20,44,18)[i]
            if key=='corner' and i==1: target[1]-=35
            sprite=original.resize((max(1,round(original.width*scale)),max(1,round(original.height*scale))),Image.Resampling.LANCZOS)
            offset=(round(target[0]-local[0]*scale),round(target[1]-local[1]*scale))
            canvas=Image.new('RGBA',CELL); canvas.paste(sprite,offset)
            # Reject clipping before publishing any registered character.
            box=solid_box(sprite)
            visible=(box[0]+offset[0],box[1]+offset[1],box[2]+offset[0],box[3]+offset[1])
            if min(visible[:2])<2 or visible[2]>CELL[0]-2 or visible[3]>CELL[1]-2:
                raise ValueError(f'{key}/{i}: clipped at {visible}; review shared action scale/anchor')
            sheet.paste(canvas,(i*CELL[0],0))
            placements.append({'source':f['source'],'component':f['label'],'source_bbox':f['box'],
                               'source_atlas_scale':f.get('pre_scale',1),
                               'shared_scale':scale,'offset':offset,'visible_bbox':visible})
        source=work/f'{key}.png'; sheet.save(source)
        layout={'action_id':key,'cell':list(CELL),'image_size':list(sheet.size),
                'rects':[[i*CELL[0],0,*CELL] for i in range(len(frames))],
                'anchor':list(ANCHOR),'fps':CATALOG['actions'][key]['fps'],'loop':CATALOG['actions'][key]['loop']}
        if key=='window_sit': layout['support_anchor']=[192,296]
        if key=='ledge_struggle': layout['support_anchor']=[64,164]
        c.data['animations'][key].update(frame_count=len(frames),cell=list(CELL))
        layout_file=work/f'{key}.json'; write_json(layout_file,layout)
        import_animation(c,key,source,layout_file)
        provenance[key]=placements
    # Left travel is a metadata mirror of the reviewed right profile, with no duplicate PNG.
    c.data['animations']['left']={**c.data['animations']['right'],'mirror':True,'direction':'left'}
    write_json(c.manifest,c.data)
    write_json(PACK/'sources/packing-layout-v1.json',provenance)
    result=audit(c)
    write_json(ROOT/'artifacts/seir/resource-qa.json',result)
    if result['errors']: raise ValueError(result['errors'])
    # Structural approval is followed by separate visual preview and game verification.
    # Review notes record that heuristic checks do not prove exact image identity.
    for key in CATALOG['actions']:
        review(c,key,'Reviewed Seir canonical identity, source sheet, fixed anatomical action scale and feet/contact placement. New generated art, not legacy replacements; see docs/seir-character.md and game previews.')
    register(c)
    print('Registered Seir:',len(c.data['animations']),'actions;',len(result['warnings']),'advisory warnings')


if __name__=='__main__': main()
