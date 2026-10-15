"""Pack reviewed ball reaction atlases without altering original character images.

Authoring: Pillow, NumPy, SciPy. Only Pillow is also used by display resampling.
One anatomical scale per character/action; translate the planted shoe, never
independently fit the four poses. Raw atlases and source coordinates are retained.
"""
from pathlib import Path
import hashlib
import json
import statistics
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication
from character_resources import discover_characters, load_art


def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def components(path):
    pixels=np.asarray(Image.open(path).convert('RGBA'))
    labels,n=ndimage.label(pixels[:,:,3]>=128)
    sizes=np.bincount(labels.ravel()); boxes=ndimage.find_objects(labels)
    ids=sorted(range(1,n+1),key=lambda i:sizes[i],reverse=True)[:12]
    assert len(ids)==12 and sizes[ids[-1]]>3000,(path,sizes[ids[-1]])
    ordered=sorted(ids,key=lambda i:(boxes[i-1][0].start+boxes[i-1][0].stop)/2)
    ids=[]
    for row in range(3):
        ids+=sorted(ordered[row*4:row*4+4],key=lambda i:boxes[i-1][1].start)
    distance,indices=ndimage.distance_transform_edt(~np.isin(labels,ids),return_indices=True)
    nearest=labels[tuple(indices)]; output=[]
    for label in ids:
        y,x=boxes[label-1]
        box=(max(0,x.start-3),max(0,y.start-3),min(pixels.shape[1],x.stop+3),min(pixels.shape[0],y.stop+3))
        x0,y0,x1,y1=box; frame=pixels[y0:y1,x0:x1].copy()
        keep=(nearest[y0:y1,x0:x1]==label)&(distance[y0:y1,x0:x1]<=3)&(frame[:,:,3]>=32)
        frame[~keep]=0
        output.append((Image.fromarray(frame),box))
    return output


def contact(image,left_shoe=False):
    mask=np.asarray(image.getchannel('A'))>=128
    ys,xs=np.where(mask); bottom=ys.max()+1
    band=bottom-max(3,round((bottom-ys.min())*.045))
    shoe=np.where(mask[band:])[1]
    # In the kick strips the leftmost grounded shoe is the support foot.
    if left_shoe:
        unique=np.unique(shoe); gaps=np.where(np.diff(unique)>2)[0]
        if len(gaps): shoe=shoe[shoe<=unique[gaps[0]]]
    return (float(shoe.min()+shoe.max()+1)/2,float(bottom))


def main():
    app=QApplication.instance() or QApplication([])
    chars=discover_characters([])
    provenance={}
    for action,source,version in (('kick','kick-transition-raw-v2.png',2),('head_bump','head-bump-raw-v1.png',1)):
        frames=components(ROOT/'artwork/ball'/source)
        for row,name in enumerate(('zenith','liberta','seir')):
            c=chars[name]; art=load_art(c).resize(160); idle=art.frames['idle'][0]
            idle_box=QRegion(idle.mask()).boundingRect()
            poses=frames[row*4:row*4+4]
            heights=[]
            for i in (0,3):
                box=poses[i][0].getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
                heights.append(box[3]-box[1])
            # Match the old idle's visible height, including its existing ears/bow.
            scale=(idle_box.height()*300/160)/statistics.mean(heights)
            sheet=Image.new('RGBA',(384*4,384)); placements=[]
            for i,(original,box) in enumerate(poses):
                local=contact(original,action=='kick')
                target=(174 if action=='kick' else 192,376)
                sprite=original.resize((round(original.width*scale),round(original.height*scale)),Image.Resampling.LANCZOS)
                offset=(round(target[0]-local[0]*scale),round(target[1]-local[1]*scale))
                alpha=sprite.getchannel('A'); visible=alpha.getbbox()
                translated=(visible[0]+offset[0],visible[1]+offset[1],visible[2]+offset[0],visible[3]+offset[1])
                assert min(translated[:2])>=2 and max(translated[2:])<=382,(name,action,i,translated)
                sheet.paste(sprite,(i*384+offset[0],offset[1]))
                placements.append(dict(source_bbox=box,shared_scale=scale,offset=offset,contact=local,visible_bbox=translated))
            folder=c.manifest.parent; destination=folder/f'animations/{action}-v{version}.png'
            sheet.save(destination)
            spec=dict(file=destination.relative_to(folder).as_posix(),grid=[4,1],indices=list(range(4)),frame_count=4,
                      image_size=[1536,384],cell=[384,384],body_height=300,anchor=[192,376],
                      fps=6 if action=='kick' else 4,loop='once',crop='none',clean_alpha=True)
            if action=='kick':
                spec['impact_frame']=2
                impact=sheet.crop((768,0,1152,384)).getchannel('A').point(lambda a:255 if a>=128 else 0).getbbox()
                spec['contact_reach']=round((impact[2]-192)/300,5)
            spec['review']=dict(status='approved',image_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                                canonical_sha256=c.data['canonical']['sha256'],
                                note='Reviewed against canonical and idle; one anatomical scale and fixed support shoe. Raw atlas retained in artwork/ball; packing coordinates in ball-packing-layout-v1.json.')
            c.data['animations'][action]=spec
            write(c.manifest,c.data)
            provenance[f'{name}/{action}']=placements
    write(ROOT/'artwork/ball/ball-packing-layout-v1.json',provenance)
    print('Packed 24 frames: kick transitions and head bump reactions for all three characters; original files preserved.')


if __name__=='__main__': main()
