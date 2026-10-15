"""Copy only registered character manifests and their runtime PNGs for a build.

Generated originals, prompts, QA reports and templates remain in the repository.
The destination must be new; this tool never removes or overwrites existing files.
"""
import argparse
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def stage(output, root=ROOT):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    copied=[]
    for manifest in sorted((root/'characters').glob('*/character.json')):
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('enabled',True) is False: continue
        pack=manifest.parent.resolve(); target=output/pack.name
        target.mkdir(); shutil.copy2(manifest,target/'character.json')
        copied.append(target/'character.json')
        names={data['canonical']['file']}
        for section in ('animations','legacy_originals'):
            for spec in data.get(section,{}).values():
                if spec.get('file'): names.add(spec['file'])
                names.update(spec.get('files',[]))
        for name in sorted(names):
            source=(pack/name).resolve()
            if not source.is_file(): raise ValueError(f'Missing runtime resource: {source}')
            if not source.is_relative_to(pack):
                if source.is_relative_to((root/'assets').resolve()): continue  # packaged separately
                raise ValueError(f'Character reference leaves resource roots: {source}')
            destination=target/source.relative_to(pack)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,destination); copied.append(destination)
    return copied


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); paths=stage(args.output)
    print(f'Character runtime package: {len(paths)} files, {sum(p.stat().st_size for p in paths):,} bytes')


if __name__=='__main__': main()
