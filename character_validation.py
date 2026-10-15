"""Registration checks requiring only Qt; deeper authoring QA uses optional Pillow."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_structure(character):
    from character_resources import CATALOG, ROOT, action_spec
    errors, warnings, missing = [], [], []
    data = character.data
    profile=data.get('profile',{})
    if not isinstance(profile,dict) or profile.get('render_quality') not in (None,'clarity-v1'):
        errors.append('Unsupported render_quality profile')
    animations = data.get('animations', {})
    if not isinstance(animations, dict):
        return {'errors':['animations must be an object'], 'warnings':[], 'missing':[]}
    builtin = character.manifest.is_relative_to((ROOT/'characters').resolve())
    allowed = ROOT.resolve() if builtin else character.manifest.parent.resolve()
    if not builtin and data.get('renderer')=='legacy-v1':
        errors.append('legacy-v1 is reserved for preserved built-in artwork')
    def read(name):
        path=character.path(name)
        if not path.is_relative_to(allowed): raise ValueError(f'Path outside resource root: {name}')
        image=QImage(str(path))
        if image.isNull(): raise ValueError(f'Cannot load: {name}')
        if not image.hasAlphaChannel(): raise ValueError(f'Image has no alpha channel: {name}')
        return image
    for action, default in CATALOG['actions'].items():
        spec=animations.get(action,{})
        if not isinstance(spec,dict):
            errors.append(f'{action}: animation must be an object'); continue
        if not spec.get('file') and not spec.get('files'):
            missing.append(action)
            if default.get('required'): errors.append(f'{action}: required animation missing')
            seen=set(); target=action
            while target:
                if target in seen: errors.append(f'{action}: fallback cycle'); break
                seen.add(target)
                if animations.get(target,{}).get('file') or animations.get(target,{}).get('files'): break
                target=action_spec(character,target).get('fallback')
                if target and target not in CATALOG['actions']:
                    errors.append(f'{action}: unknown fallback {target}'); break
            else:
                errors.append(f'{action}: no usable fallback')
            continue
        try:
            fps=spec.get('fps',default.get('fps',0))
            if not isinstance(fps,(float,int)) or not math.isfinite(fps) or not 0<=fps<=240: raise ValueError('FPS must be 0..240')
            if spec.get('loop',default['loop']) not in ('once','loop','pingpong'): raise ValueError('Invalid loop mode')
            if spec.get('files'):
                images=[read(name) for name in spec['files']]
                count=len(images)
                if len({(p.width(),p.height()) for p in images})>1: raise ValueError('Individual frame dimensions differ')
            else:
                image=read(spec['file'])
                if spec.get('image_size') and spec['image_size'] != [image.width(),image.height()]: raise ValueError('Image resolution mismatch')
                rects=spec.get('rects')
                if rects is None:
                    cols,rows=spec['grid']
                    if not isinstance(cols,int) or not isinstance(rows,int) or min(cols,rows)<=0: raise ValueError('Invalid grid')
                    # Old pose sheets contain an intentional unused last row.
                    if (image.width()%cols or image.height()%rows) and data.get('renderer')!='legacy-v1': raise ValueError('Grid does not divide image')
                    cw,ch=image.width()//cols,image.height()//rows
                    crop=spec.get('cell_crop',[0,0,cw,ch]); x,y,w,h=crop
                    if min(x,y)<0 or min(w,h)<=0 or x+w>cw or y+h>ch: raise ValueError('Crop exceeds cell')
                    indices=spec.get('indices',list(range(cols*rows)))
                    if not indices or any(not isinstance(i,int) or i<0 or i>=cols*rows for i in indices): raise ValueError('Invalid frame index')
                    rects=[[i%cols*cw+x,i//cols*ch+y,w,h] for i in indices]
                if not rects: raise ValueError('Empty frame sequence')
                for rect in rects:
                    if len(rect)!=4 or any(not isinstance(v,int) for v in rect) or min(rect[2:])<=0 or not image.rect().contains(QRect(*rect)): raise ValueError(f'Invalid rectangle: {rect}')
                count=len(rects)
            if count!=spec.get('frame_count',count): raise ValueError('Declared frame count mismatch')
            if spec.get('anchors') and len(spec['anchors'])!=count: raise ValueError('Per-frame anchor count mismatch')
            contact=spec.get('support_anchor')
            if contact is not None and not isinstance(contact,list): raise ValueError('Invalid support anchor')
            for anchor in spec.get('anchors',[]) + ([spec['anchor']] if isinstance(spec.get('anchor'),list) else []) + ([contact] if contact is not None else []):
                if len(anchor)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in anchor): raise ValueError('Invalid anchor')
        except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError) as error:
            errors.append(f'{action}: {error}')
    try:
        canonical=data['canonical']; image=read(canonical['file'])
        if canonical.get('rect') and not image.rect().contains(QRect(*canonical['rect'])): errors.append('Canonical Reference rectangle out of bounds')
        if canonical.get('sha256')!=digest(character.path(canonical['file'])): errors.append('Canonical Reference hash changed; review required')
    except (OSError,ValueError,KeyError,TypeError) as error: errors.append(f'Canonical Reference: {error}')
    if data.get('renderer') not in ('legacy-v1','manifest-v1'): errors.append('Unsupported renderer')
    if data.get('renderer')=='manifest-v1' and data.get('enabled',True):
        for action,spec in animations.items():
            if not isinstance(spec,dict) or not spec.get('file'): continue
            try:
                reviewed=spec.get('review',{})
                if reviewed.get('status')!='approved' or reviewed.get('image_sha256')!=digest(character.path(spec['file'])) or reviewed.get('canonical_sha256')!=data.get('canonical',{}).get('sha256'):
                    errors.append(f'{action}: enabled pack has unreviewed or changed artwork')
            except OSError: pass  # Loading error already reported above.
    if data.get('renderer')!='legacy-v1' and (not isinstance(data.get('body_height'),(int,float)) or not math.isfinite(data['body_height']) or data['body_height']<=0):
        errors.append('body_height must be positive')
    return {'errors':errors,'warnings':warnings,'missing':missing,
            'completion':round(100*(len(CATALOG['actions'])-len(missing))/len(CATALOG['actions']),1)}


def audit(character):
    """Advisory visual statistics. These cannot prove semantic character identity."""
    from PIL import Image, ImageChops, ImageStat
    from character_resources import CATALOG, extract_frames
    report=validate_structure(character)
    report.update(actions={},duplicates=[],identity='heuristics only; visual review required')
    if report['errors']: return report
    hashes={}
    for path in sorted(character.manifest.parent.rglob('*.png')):
        h=digest(path)
        if h in hashes: report['duplicates'].append([str(hashes[h]),str(path)])
        else: hashes[h]=path
    canonical=Image.open(character.path(character.data['canonical']['file'])).convert('RGBA')
    if character.data['canonical'].get('rect'):
        x,y,w,h=character.data['canonical']['rect']; canonical=canonical.crop((x,y,x+w,y+h))
    canonical.thumbnail((64,64))
    canon_mean=ImageStat.Stat(canonical.convert('RGB'),canonical.getchannel('A').point(lambda x:255 if x>=128 else 0)).mean
    for action in CATALOG['actions']:
        if action in report['missing']: continue
        frames=[]; bounds=[]; anchors=[]; warnings=[]
        for i,p in enumerate(extract_frames(character,action,fallback=False)):
            im=p.toImage(); from PySide6.QtGui import QImage
            im=im.convertToFormat(QImage.Format.Format_RGBA8888)
            frame=Image.frombytes('RGBA',(im.width(),im.height()),bytes(im.constBits()),'raw','RGBA',im.bytesPerLine())
            frames.append(frame)
            alpha=frame.getchannel('A'); box=alpha.point(lambda a:255 if a>=32 else 0).getbbox()
            if not box: report['errors'].append(f'{action}/{i}: blank frame'); continue
            if alpha.getextrema()[0]!=0: report['errors'].append(f'{action}/{i}: no transparent background pixels')
            bounds.append([box[2]-box[0],box[3]-box[1]])
            anchors.append([(box[0]+box[2])/2,box[3]])
        if len(bounds)==len(frames):
            heights=[b[1] for b in bounds]; widths=[b[0] for b in bounds]
            spread=max(heights)/min(heights)
            drift=max(a[0] for a in anchors)-min(a[0] for a in anchors)
            if spread>1.3: warnings.append('Body height spread >30%; inspect pose/proportion')
            if drift>frames[0].width*.12: warnings.append('Horizontal content drift >12%; inspect declared anchors')
            mean=ImageStat.Stat(frames[0].convert('RGB'),frames[0].getchannel('A').point(lambda x:255 if x>=128 else 0)).mean
            if sum(abs(a-b) for a,b in zip(mean,canon_mean))/3>45: warnings.append('Palette differs from canonical reference')
        seam=None
        if len(frames)>1 and len({f.size for f in frames})==1:
            def difference(a,b):
                # Compare visible color and alpha; ignore hidden RGB generation residue.
                bg=Image.new('RGBA',a.size,(0,0,0,255)); a=Image.alpha_composite(bg,a); b=Image.alpha_composite(bg,b)
                return sum(ImageStat.Stat(ImageChops.difference(a,b)).mean)/4
            internal=[difference(a,b) for a,b in zip(frames,frames[1:])]
            seam=difference(frames[-1],frames[0])
            spec=character.data['animations'][action]
            if spec.get('loop',CATALOG['actions'][action]['loop'])=='loop' and seam>max(6, sum(internal)/len(internal)*1.8):
                warnings.append('Loop seam exceeds adjacent-frame difference; inspect contact phase')
        report['actions'][action]={'frame_count':len(frames),'sizes':[list(f.size) for f in frames],
            'bounds':bounds,'content_anchors':anchors,'seam_difference':seam,'warnings':warnings}
        report['warnings'].extend(f'{action}: {w}' for w in warnings)
    return report
