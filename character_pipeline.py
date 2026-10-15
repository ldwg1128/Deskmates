"""Offline-first authoring pipeline. Pillow is a developer-only dependency.

Generation providers receive whole-action jobs and return PNG paths. They are
explicitly selected Python plugins, never loaded from untrusted character JSON.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import re
import shutil
from typing import Protocol
from PIL import Image, ImageDraw, ImageFont

from character_resources import (CATALOG, ROOT, Character, action_spec, extract_frames,
                                 load_art)
from character_validation import audit, digest, validate_structure


def write_json(path, data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


def open_character(path):
    path=Path(path)
    if path.is_dir(): path=path/'character.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('animations'),dict):
        raise ValueError('Invalid character manifest')
    return Character(path.resolve(), data)


def pil_pixmap(p):
    from PySide6.QtGui import QImage
    im=p.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA',(im.width(),im.height()),bytes(im.constBits()),'raw','RGBA',im.bytesPerLine())


def canonical_image(character):
    spec=character.data['canonical']
    if digest(character.path(spec['file']))!=spec['sha256']:
        raise ValueError('Canonical Reference hash changed; explicitly choose/review a new reference')
    image=Image.open(character.path(spec['file'])).convert('RGBA')
    if spec.get('rect'):
        x,y,w,h=spec['rect']; image=image.crop((x,y,x+w,y+h))
    return image


def init_character(folder, character_id, name, reference, *, identity='', cell=(256,320), anchor=None):
    """Copy an approved canonical reference; no existing asset is ever overwritten."""
    folder=Path(folder)
    if (folder/'character.json').exists(): raise ValueError('Character already exists; use sync')
    if not re.fullmatch(r'[a-z][a-z0-9_-]*',character_id): raise ValueError('ID must be lowercase ASCII slug')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'animations').mkdir(exist_ok=True)
    im=Image.open(reference).convert('RGBA')
    if not im.getchannel('A').getbbox(): raise ValueError('Empty canonical reference')
    canonical=folder/'canonical.png'; im.save(canonical)
    w,h=cell; anchor=list(anchor or (w/2,h*.95))
    data={'version':1,'id':character_id,'name':name,'renderer':'manifest-v1','enabled':False,
          'body_height':h,'anchor':anchor,
          'canonical':{'file':'canonical.png','sha256':digest(canonical),'reviewed':True,
                       'identity':identity or 'Preserve exact face, eyes, hair, clothing, accessories and anatomical proportions.'},
          'animations':{key:{'frame_count':spec['frames'],'fps':spec['fps'],
                             'loop':spec['loop'],'anchor':anchor,'cell':list(cell)}
                        for key,spec in CATALOG['actions'].items()}}
    write_json(folder/'character.json',data)
    return open_character(folder)


def sync_character(character):
    """Catalog additions appear immediately in checks; sync creates editable stubs."""
    for key,spec in CATALOG['actions'].items():
        character.data['animations'].setdefault(key,{'frame_count':spec['frames'],
             'fps':spec['fps'],'loop':spec['loop'],'anchor':character.data.get('anchor',spec['anchor']),
             'cell':spec['cell']})
    write_json(character.manifest,character.data)


def specification(character):
    result=[]
    for key,default in CATALOG['actions'].items():
        spec=action_spec(character,key)
        source=character.data['animations'].get(key,{})
        source_cell=None
        if source.get('rects'): source_cell=[list(size) for size in sorted({tuple(r[2:]) for r in source['rects']})]
        elif source.get('file') and source.get('grid'):
            with Image.open(character.path(source['file'])) as image:
                cols,rows=source['grid']
                source_cell=[source.get('cell_crop',[0,0,image.width//cols,image.height//rows])[2:]]
        elif source.get('files'):
            with Image.open(character.path(source['files'][0])) as image: source_cell=[list(image.size)]
        result.append({'action_id':key,'name':default['name'],'required':default['required'],
            'frame_count':source.get('frame_count',default['frames']),
            'cell':source.get('cell',default['cell']), 'recommended_resolution':default['cell'],
            'source_cells_before_alpha_crop':source_cell,
            'direction':spec.get('direction',default['direction']),'frame_order':default['description'],
            'fps':spec['fps'],'loop':spec['loop'],'anchor':spec.get('anchor',default['anchor']),
            'support_anchor':spec.get('support_anchor'),
            'file':source.get('file',f'animations/{key}.png'),
            'files':source.get('files'), 'rects':source.get('rects'), 'grid':source.get('grid'),
            'fallback':spec.get('fallback'),'complete':bool(source.get('file') or source.get('files')),
            'timing':default.get('timing','FPS controls frame playback; existing state transitions are retained')})
    return result


def checklist(character, output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    specs=specification(character)
    write_json(output/'specification.json',{'character':character.id,'canonical':character.data['canonical'],
                                          'actions':specs})
    complete=sum(a['complete'] for a in specs)
    lines=[f'# {character.name}: 제작 체크리스트', '',f'리소스 연결: {complete}/{len(specs)} ({100*complete/len(specs):.1f}%). 파일 유효성은 validate로 별도 검사한다.',
        '', 'Canonical Reference: '+character.data['canonical']['file'],
        '', '| 완료 | 행동 / Action ID | 필수 | 프레임 | 원본 셀 | 제작 셀 | FPS | 반복 | 방향 | 파일 |',
        '|---|---|---|---|---|---|---|---|---|---|']
    for a in specs:
        lines.append(f"| {'[x]' if a['complete'] else '[ ]'} | {a['name']} / {a['action_id']} | {'필수' if a['required'] else '선택'} | {a['frame_count']} | {a['source_cells_before_alpha_crop']} | {a['cell']} | {a['fps']:.4g} | {a['loop']} | {a['direction']} | {a['file']} |")
    for a in specs:
        lines.extend(['',f"## {a['action_id']}",a['frame_order'],f"기준 위치: {a['anchor']}; 접촉점: {a['support_anchor']}; fallback: {a['fallback']}; {a['timing']}"])
    (output/'checklist.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return specs


def templates(character, output, *, gap=0, reference=None):
    """Game PNGs are empty/transparent. All text and pose guides live elsewhere."""
    if gap<0: raise ValueError('Gap cannot be negative')
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    canonical_image(character).save(output/'canonical.png')
    ref_art=load_art(reference).resize(320) if reference else None
    layouts={}
    for a in specification(character):
        key=a['action_id']; count=a['frame_count']; w,h=a['cell']
        if count<1 or min(w,h)<1: raise ValueError(f'{key}: invalid geometry')
        folder=output/key; (folder/'frames').mkdir(parents=True,exist_ok=True)
        rects=[[i*(w+gap),0,w,h] for i in range(count)]
        size=(count*w+(count-1)*gap,h)
        Image.new('RGBA',size).save(folder/'template.png')
        guide=Image.new('RGBA',size,(235,237,242,255)); draw=ImageDraw.Draw(guide)
        for i,(x,y,_,_) in enumerate(rects):
            draw.rectangle((x,0,x+w-1,h-1),outline=(100,105,120),width=2)
            anchor=a['anchor'] if isinstance(a['anchor'],list) else [w/2,h*.95]
            ax,ay=x+anchor[0],anchor[1]
            draw.line((ax,0,ax,h),fill=(160,180,220)); draw.line((x,ay,x+w,ay),fill=(220,140,150))
            if a['support_anchor']:
                sx,sy=a['support_anchor']; sx+=x
                draw.ellipse((sx-4,sy-4,sx+4,sy+4),outline=(35,160,80),width=2)
            draw.text((x+6,6),f'{key} / {i+1:03}',fill=(30,30,40))
            Image.new('RGBA',(w,h)).save(folder/'frames'/f'{i:03}.png')
        guide.save(folder/'guide.png')
        layout={'action_id':key,'image_size':list(size),'cell':[w,h],'gap':gap,'rects':rects,
                'frame_order':a['frame_order'],'anchor':a['anchor'],'fps':a['fps'],'loop':a['loop'],
                'support_anchor':a['support_anchor'],
                'game_template':'template.png','reference_only':'guide.png'}
        write_json(folder/'layout.json',layout); layouts[key]=layout
        if ref_art:
            mapping={'motion':ref_art.motion_frames,'corner':ref_art.corner_frames,
                     'feeding':ref_art.feed_frames,'refusal':ref_art.refusal_frames}
            poses=mapping.get(key,ref_art.frames.get(key))
            if poses is None: poses=extract_frames(reference,key)
            pil=[pil_pixmap(p) for p in poses]
            shared=min((w-16)/max(p.width for p in pil),(h-40)/max(p.height for p in pil))
            reference_sheet=guide.copy()
            for i in range(count):
                p=pil[min(len(pil)-1,i*len(pil)//count)]
                p=p.resize((max(1,round(p.width*shared)),max(1,round(p.height*shared))),Image.Resampling.LANCZOS)
                reference_sheet.alpha_composite(p,(round(i*(w+gap)+(w-p.width)/2),h-p.height-12))
            ImageDraw.Draw(reference_sheet).text((6,h-12),'POSE REFERENCE ONLY - DO NOT IMPORT',fill=(120,20,20))
            reference_sheet.save(folder/'pose-reference.png')
    write_json(output/'layouts.json',layouts)
    return layouts


def jobs(character, output, *, gap=0, reference=None):
    output=Path(output)
    layouts=templates(character,output,gap=gap,reference=reference)
    canonical_hash=digest(output/'canonical.png')
    checklist(character,output)
    result=[]
    for spec in specification(character):
        key=spec['action_id']; layout=layouts[key]
        prompt=(f"Create ONE coherent animation sprite strip for {character.name}. "
            f"Canonical Reference is the attached canonical.png, SHA-256 {canonical_hash}. "
            f"Identity lock: {character.data['canonical']['identity']} "
            "Match the same face and eye shape/color, hair silhouette/color, costume details and body ratios in EVERY frame. "
            "Do not independently redesign or individually rescale poses. Preserve rendering style and palette. "
            f"Action ID: {key}. Direction: {spec['direction']}. Ordered poses: {spec['frame_order']}. "
            f"Exactly {spec['frame_count']} frames, left to right; canvas {layout['image_size']}; "
            f"cells {layout['cell']}; gap {gap}; rectangles {layout['rects']}. "
            f"Body anchor in each cell: {layout['anchor']}. Shared anatomical scale; intentional jumping may lift feet. "
            f"Fixed window contact point (when present): {layout['support_anchor']}; keep hands/seat attached there in every frame. "
            f"Playback {spec['fps']:.5g} FPS, {spec['loop']}. "
            "For cycles, ensure last-to-first contact/velocity continuity; do not add a duplicate terminal frame. "
            "Transparent RGBA background, no ground, shadow panel, text, numbers, grid or guide lines. "
            "Use guide.png only for geometry; pose-reference.png, when supplied, only for motion, never copy its character. "
            "Return only the complete strip. A reviewer must compare identity with canonical before registration.")
        (output/key/'prompt.txt').write_text(prompt+'\n',encoding='utf-8')
        result.append({'action_id':key,'status':'awaiting_external_image','canonical':str((output/'canonical.png').resolve()),
            'canonical_sha256':digest(output/'canonical.png'),'layout':str((output/key/'layout.json').resolve()),
            'guide':str((output/key/'guide.png').resolve()),'prompt':prompt,
            'output':str((output/key/'generated.png').resolve())})
    write_json(output/'jobs.json',{'version':1,'character':character.id,'jobs':result})
    return result


@dataclass(frozen=True)
class GenerationJob:
    action_id: str
    prompt: str
    canonical: Path
    guide: Path
    layout: dict
    destination: Path


class ImageProvider(Protocol):
    def generate(self, job: GenerationJob) -> Path: ...


def generate(job_file, provider=None, action=None):
    data=json.loads(Path(job_file).read_text(encoding='utf-8'))
    if provider is None:
        return {'mode':'manual','jobs':[j for j in data['jobs'] if action is None or j['action_id']==action]}
    module,name=provider.split(':',1)
    plugin=getattr(importlib.import_module(module),name)()
    results=[]
    for raw in data['jobs']:
        if action and raw['action_id']!=action: continue
        if digest(raw['canonical'])!=raw['canonical_sha256']: raise ValueError('Job reference changed')
        job=GenerationJob(raw['action_id'],raw['prompt'],Path(raw['canonical']),Path(raw['guide']),
                          json.loads(Path(raw['layout']).read_text(encoding='utf-8')),Path(raw['output']))
        path=Path(plugin.generate(job))
        if not path.is_file(): raise ValueError('Provider returned no image')
        results.append({'action_id':job.action_id,'file':str(path),'status':'generated_unreviewed'})
    return {'mode':'provider','results':results}


def import_animation(character, action, source, layout_path=None, *, individual=False):
    """Stage external files, retain source, inspect, then atomically connect metadata.

    No opaque-background guessing and no automatic per-frame scale/crop fitting.
    External services are unnecessary; the same path handles optional providers.
    """
    if action not in CATALOG['actions']: raise ValueError('Unknown Action ID; add to catalog first')
    if character.data.get('renderer')=='legacy-v1': raise ValueError('Built-in images are preserved; create a new character pack')
    source=Path(source)
    if individual:
        paths=sorted(source.glob('*.png'))
        if not paths: raise ValueError('No PNG frames')
        frames=[Image.open(p).convert('RGBA') for p in paths]
        if len({im.size for im in frames})!=1: raise ValueError('Individual frame sizes differ')
        count=len(frames); w,h=frames[0].size
        layout={'rects':[[i*w,0,w,h] for i in range(count)],'image_size':[w*count,h],
                'anchor':character.data.get('anchor',[w/2,h]),'fps':action_spec(character,action)['fps'],
                'loop':action_spec(character,action)['loop']}
        sheet=Image.new('RGBA',(w*count,h))
        for i,im in enumerate(frames): sheet.alpha_composite(im,(i*w,0))
    else:
        if not layout_path: raise ValueError('Strip import requires layout.json')
        layout=json.loads(Path(layout_path).read_text(encoding='utf-8'))
        image=Image.open(source)
        if image.mode!='RGBA': raise ValueError('Import requires RGBA PNG')
        sheet=image.copy(); w,h=layout['cell']; count=len(layout['rects'])
        if list(sheet.size)!=layout['image_size']: raise ValueError('Strip resolution differs from guide; resize the whole strip explicitly before import')
    if layout.get('action_id',action)!=action: raise ValueError('Layout belongs to another action')
    rects=layout['rects']
    if count!=character.data['animations'].get(action,{}).get('frame_count',CATALOG['actions'][action]['frames']):
        raise ValueError('Frame count differs from character specification; edit metadata explicitly first')
    if layout.get('anchor') is not None and not isinstance(layout['anchor'],list): raise ValueError('New packs need a numeric pixel anchor')
    for x,y,rw,rh in rects:
        if min(x,y)<0 or min(rw,rh)<=0 or x+rw>sheet.width or y+rh>sheet.height: raise ValueError('Invalid strip rectangle')
        frame=sheet.crop((x,y,x+rw,y+rh)); alpha=frame.getchannel('A')
        if not alpha.getbbox(): raise ValueError('Blank template cannot be imported as completed artwork')
        if alpha.getextrema()[0]!=0: raise ValueError('Frame has no transparent background')
    # All mutation follows validation. Imported sources are versioned by hash.
    import io
    buf=io.BytesIO(); sheet.save(buf,format='PNG')
    import hashlib
    image_hash=hashlib.sha256(buf.getvalue()).hexdigest()
    relative=f'animations/{action}-{image_hash[:12]}.png'
    target=character.path(relative); target.parent.mkdir(exist_ok=True)
    target.write_bytes(buf.getvalue())
    raw_dir=character.manifest.parent/'sources'/action/image_hash[:12]; raw_dir.mkdir(parents=True,exist_ok=True)
    if individual:
        for path in paths: shutil.copy2(path,raw_dir/path.name)
    else: shutil.copy2(source,raw_dir/'original.png')
    previous=character.data['animations'].get(action,{}).copy()
    character.data['animations'][action]={**previous,'file':relative,'rects':rects,'frame_count':count,
        'cell':[w,h],'image_size':list(sheet.size),'crop':'none','fps':layout['fps'],'loop':layout['loop'],
        'anchor':layout['anchor'],'review':{'status':'pending','image_sha256':image_hash,
                'canonical_sha256':character.data['canonical']['sha256']}}
    if layout.get('support_anchor') is not None:
        character.data['animations'][action]['support_anchor']=layout['support_anchor']
    character.data['animations'][action].pop('files',None)
    character.data['animations'][action].pop('anchors',None)
    character.data['enabled']=False
    # Incomplete pack may lack required idle while other actions are being authored.
    own_errors=[e for e in validate_structure(character)['errors'] if e.startswith(action+':')]
    if own_errors:
        character.data['animations'][action]=previous
        raise ValueError('; '.join(own_errors))
    write_json(character.manifest,character.data)
    return target


def review(character, action, note):
    if character.data.get('renderer')=='legacy-v1': raise ValueError('Built-ins are immutable')
    if not note.strip(): raise ValueError('Record visual review findings')
    canonical_image(character)
    spec=character.data['animations'][action]
    if not spec.get('file'): raise ValueError('No imported image')
    result=audit(character)
    errors=[e for e in result['errors'] if e.startswith(action+':') or e.startswith('Canonical Reference')]
    if errors: raise ValueError('; '.join(errors))
    spec['review']={'status':'approved','image_sha256':digest(character.path(spec['file'])),
                    'canonical_sha256':character.data['canonical']['sha256'],'note':note}
    write_json(character.manifest,character.data)


def register(character):
    """Only reviewed, structurally valid packs are enabled for game discovery."""
    result=audit(character)
    if result['errors']: raise ValueError('; '.join(result['errors']))
    if character.data.get('renderer')=='legacy-v1': raise ValueError('Built-ins already registered')
    for key,spec in character.data['animations'].items():
        if not spec.get('file') and not spec.get('files'): continue
        status=spec.get('review',{})
        if not spec.get('file'): raise ValueError('Review individual files via strip import first')
        if status.get('status')!='approved' or status.get('image_sha256')!=digest(character.path(spec['file'])) or status.get('canonical_sha256')!=character.data['canonical']['sha256']:
            raise ValueError(f'{key}: current artwork needs visual review')
    character.data['enabled']=True
    write_json(character.manifest,character.data)
    return result


def preview(character, output, action=None):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    art=load_art(character).resize(160)
    mapping={'motion':art.motion_frames,'corner':art.corner_frames,'feeding':art.feed_frames,'refusal':art.refusal_frames}
    for key in ([action] if action else CATALOG['actions']):
        frames=mapping.get(key,art.frames.get(key))
        if frames is None: frames=extract_frames(character,key)
        images=[pil_pixmap(p) for p in frames]
        w=max(p.width for p in images); h=max(p.height for p in images)
        normalized=[]
        for p in images:
            bg=Image.new('RGBA',(w,h),(238,240,244,255)); bg.alpha_composite(p,((w-p.width)//2,h-p.height))
            normalized.append(bg.convert('RGB'))
        fps=action_spec(character,key).get('fps',0)
        spec=action_spec(character,key)
        duration=round(1000/fps) if fps else 250
        # Physics/feeding use phase timings rather than a uniform animation timer.
        if key=='refusal' and len(normalized)==4:
            durations=[220,540,540,1500]
        else: durations=[duration]*len(normalized)
        if spec.get('loop')=='pingpong' and len(normalized)>1:
            normalized+=normalized[-2:0:-1]; durations+=durations[-2:0:-1]
        repeat={'loop':0} if spec.get('loop') in ('loop','pingpong') else {}
        normalized[0].save(output/f'{key}.gif',save_all=True,append_images=normalized[1:],
                           duration=durations,disposal=2,**repeat)
        contact=Image.new('RGB',(w*len(normalized),h+22),(238,240,244))
        for i,p in enumerate(normalized):
            contact.paste(p,(i*w,22)); ImageDraw.Draw(contact).text((i*w+4,4),f'{key} {i+1}',fill='black')
        contact.save(output/f'{key}-contact.png')
    return output


def analyze(output):
    """Inventory actual manifests/assets and AST behavior assignments/bindings."""
    from character_resources import discover_characters
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    text=(ROOT/'desktop_pet.py').read_text(encoding='utf-8'); tree=ast.parse(text)
    states=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Attribute) and t.attr=='state' for t in node.targets) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str): states.add(node.value.value)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='enter_state' and node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str): states.add(node.args[0].value)
    # Dynamic transitions select keys from CLIPS; union with catalog bindings.
    states.update(CATALOG['bindings'])
    missing_bindings=sorted(states-set(CATALOG['bindings']))
    chars=discover_characters([]); used=set(); manifests={}
    for cid,c in chars.items():
        manifests[cid]={'name':c.name,'renderer':c.data['renderer'],'specs':specification(c),'validation':validate_structure(c)}
        for a in c.data['animations'].values():
            for name in ([a['file']] if a.get('file') else a.get('files',[])): used.add(c.path(name))
    used.add((ROOT/'assets/bread.png').resolve())
    assets=[]
    for path in sorted((ROOT/'assets').glob('*.png')):
        im=Image.open(path)
        assets.append({'file':path.relative_to(ROOT).as_posix(),'size':list(im.size),'mode':im.mode,
                       'sha256':digest(path),'used':path.resolve() in used})
    report={'catalog_actions':len(CATALOG['actions']),'states':sorted(states),'bindings':CATALOG['bindings'],
            'unmapped_states':missing_bindings,'characters':manifests,'assets':assets,
            'dynamic_analysis_limit':'AST + declared runtime bindings; regression tests exercise actual execution'}
    write_json(output/'inventory.json',report)
    lines=['# 기존 캐릭터·애니메이션 분석', '',f"행동 리소스 {len(CATALOG['actions'])}개, 게임 상태/바인딩 {len(states)}개. 자동 AST 검사에서 미등록 상태: {missing_bindings}.",
        '', '파일명은 기존 assets/{id}-*.png를 보존하고 manifest가 연결한다. 새 팩은 characters/{id}/animations/{action}-{hash}.png를 사용한다.',
        '', '| 파일 | 원본 해상도 | 사용 | SHA-256 |','|---|---|---|---|']
    for a in assets: lines.append(f"| {a['file']} | {a['size']} | {'사용' if a['used'] else '미사용·보존'} | {a['sha256']} |")
    for cid,c in chars.items():
        lines.extend(['',f'## {c.name}',f"원본 신체 높이 기준: {c.body_height}px. 렌더러: {c.data['renderer']}.",
            '', '| Action ID | 프레임 | FPS | 반복 | 원본 셀/좌표 | 자르기 |', '|---|---|---|---|---|---|'])
        for key,a in c.data['animations'].items():
            geometry=a.get('rects',a.get('grid'))
            lines.append(f"| {key} | {a['frame_count']} | {a['fps']:.5g} | {a['loop']} | {geometry} | {a.get('crop','none')} |")
    (output/'inventory.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report
