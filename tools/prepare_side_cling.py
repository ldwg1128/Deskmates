"""Pack generated side-profile artwork with a fixed hand contact, without repainting it.

Usage: python tools/prepare_side_cling.py zenith PATH_TO_GENERATED_PNG
The generated original is retained under characters/<id>/sources/.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from PIL import Image


LAYOUTS = {
    'zenith': {'scale': .4, 'hands': [(106,282),(631,284),(1177,287),(1717,284)]},
    'liberta': {'scale': .46, 'hands': [(117,240),(660,240),(1202,240),(1745,240)]},
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('character',choices=LAYOUTS)
    parser.add_argument('source',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'characters'/args.character
    source=root/'sources/side-cling-raw-v2.png'
    shutil.copyfile(args.source,source)
    image=Image.open(source).convert('RGBA')
    if image.size!=(2172,724): raise ValueError('Layout was reviewed for a 2172x724 strip')
    layout=LAYOUTS[args.character]
    anchor=(32,120); cell=(256,320); scale=layout['scale']
    sheet=Image.new('RGBA',(cell[0]*4,cell[1]))
    records=[]
    for i,(hx,hy) in enumerate(layout['hands']):
        left=i*543
        frame=image.crop((left,0,left+543,724))
        frame=frame.resize((round(543*scale),round(724*scale)),Image.Resampling.LANCZOS)
        offset=(anchor[0]-round((hx-left)*scale),anchor[1]-round(hy*scale))
        canvas=Image.new('RGBA',cell); canvas.paste(frame,offset)
        sheet.paste(canvas,(i*cell[0],0))
        records.append({'source_rect':[left,0,543,724],'source_hand':[hx,hy],'offset':offset})
    target=root/'animations/ledge-struggle-side-v2.png'; sheet.save(target)
    info={'tool':'built-in image_gen','raw_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'scale':scale,'cell':cell,'support_anchor':anchor,'frames':records,
          'direction':'left; character outside right vertical window edge; mirror at left edge'}
    (root/'sources/side-cling-layout-v2.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
    manifest=root/'character.json'; data=json.loads(manifest.read_text(encoding='utf-8'))
    data['animations']['ledge_struggle'].update(file=target.relative_to(root).as_posix(),
        support_anchor=list(anchor),direction='left')
    manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(target)


if __name__=='__main__': main()
