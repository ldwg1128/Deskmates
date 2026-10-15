"""Run `python character_tool.py --help` for offline authoring commands."""
import argparse
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from character_pipeline import (analyze, audit, checklist, generate, import_animation,
    init_character, jobs, open_character, preview, register, review, sync_character, templates, write_json)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('analyze'); p.add_argument('--output',type=Path,default=Path('docs/generated'))
    p=commands.add_parser('init'); p.add_argument('folder',type=Path); p.add_argument('--id',required=True)
    p.add_argument('--name',required=True); p.add_argument('--canonical',type=Path,required=True)
    p.add_argument('--identity',default=''); p.add_argument('--cell',type=int,nargs=2,default=[256,320]); p.add_argument('--anchor',type=float,nargs=2)
    for name in ('checklist','templates','jobs','validate','preview','sync','import','review','register'):
        p=commands.add_parser(name); p.add_argument('character',type=Path)
        if name in ('checklist','templates','jobs','preview'): p.add_argument('--output',type=Path,required=True)
        if name in ('templates','jobs'): p.add_argument('--gap',type=int,default=0); p.add_argument('--reference',type=Path)
        if name in ('preview','review','import'): p.add_argument('--action',required=name!='preview')
        if name=='import':
            p.add_argument('--source',type=Path,required=True); p.add_argument('--layout',type=Path); p.add_argument('--individual',action='store_true')
        if name=='review': p.add_argument('--note',required=True)
        if name=='validate': p.add_argument('--output',type=Path)
    p=commands.add_parser('generate'); p.add_argument('jobs',type=Path); p.add_argument('--provider'); p.add_argument('--action')
    p=commands.add_parser('create'); p.add_argument('folder',type=Path); p.add_argument('--id',required=True); p.add_argument('--name',required=True)
    p.add_argument('--reference',action='append',required=True,help='role=path (front required; side/back optional)')
    p.add_argument('--features',type=Path); p.add_argument('--cell',nargs=2,type=int,default=[256,320]); p.add_argument('--anchor',nargs=2,type=float)
    p=commands.add_parser('auto'); p.add_argument('character',type=Path); p.add_argument('--config',type=Path)
    p.add_argument('--max-retries',type=int,default=2); p.add_argument('--cost-limit',default='0'); p.add_argument('--actions',nargs='+'); p.add_argument('--no-register',action='store_true')
    p=commands.add_parser('approve'); p.add_argument('character',type=Path); p.add_argument('--action',required=True)
    p.add_argument('--frames',type=int,nargs='+'); p.add_argument('--note',required=True)
    p=commands.add_parser('candidate'); p.add_argument('character',type=Path); p.add_argument('--action',required=True); p.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    app=QApplication.instance() or QApplication([])
    try:
        if args.command=='analyze': result=analyze(args.output)
        elif args.command=='init': result=init_character(args.folder,args.id,args.name,args.canonical,identity=args.identity,cell=args.cell,anchor=args.anchor).data
        elif args.command=='generate': result=generate(args.jobs,args.provider,args.action)
        elif args.command=='create':
            from character_autogen import prepare
            references=dict(item.split('=',1) for item in args.reference)
            features=json.loads(args.features.read_text(encoding='utf-8')) if args.features else None
            result=prepare(args.folder,args.id,args.name,references,features=features,cell=args.cell,anchor=args.anchor).data
        else:
            c=open_character(args.character)
            if args.command=='checklist': result=checklist(c,args.output)
            elif args.command in ('templates','jobs'):
                func=templates if args.command=='templates' else jobs
                result=func(c,args.output,gap=args.gap,reference=open_character(args.reference) if args.reference else None)
            elif args.command=='validate':
                result=audit(c)
                if args.output: write_json(args.output,result)
                print(json.dumps({key:result[key] for key in ('errors','warnings','missing','completion','identity') if key in result},ensure_ascii=False,indent=2))
                return 1 if result['errors'] else 0
            elif args.command=='preview': result=str(preview(c,args.output,args.action))
            elif args.command=='sync': sync_character(c); result='synced'
            elif args.command=='import': result=str(import_animation(c,args.action,args.source,args.layout,individual=args.individual))
            elif args.command=='review': review(c,args.action,args.note); result='review recorded'
            elif args.command=='register': register(c); result='registered'
            elif args.command=='auto':
                from character_autogen import provider_from_config, run
                result=run(c,provider=provider_from_config(args.config),max_retries=args.max_retries,
                           cost_limit=args.cost_limit,actions=args.actions,auto_register=not args.no_register)
                print(json.dumps({'mode':result['mode'],'registered':result['registered'],
                    'reserved_usd':result['reserved_usd'],'actions':{k:v['status'] for k,v in result['actions'].items()}},indent=2))
            elif args.command=='approve':
                from character_autogen import approve_frames
                approve_frames(c,args.action,args.frames,args.note); result='approved'
            elif args.command=='candidate':
                from character_autogen import ingest_candidate
                ingest_candidate(c,args.action,args.source); result='staged for validation'
        # Detailed reports are files; do not flood the terminal with pixel metadata.
        print(f'OK: {args.command}'+(f' -> {args.output}' if hasattr(args,'output') and args.output else ''))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as error:
        parser.exit(2,f'ERROR: {error}\n')


if __name__=='__main__': raise SystemExit(main())
