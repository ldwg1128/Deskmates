"""Offline demo: intentionally broken generation -> frame repair -> registration."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from character_autogen import prepare, run
from character_pipeline import open_character, preview, write_json
from examples.create_dummy import pose
from verify_autogen import FaultyModel


def main():
    app=QApplication([])
    root=Path('artifacts/autogen-demo'); root.mkdir(parents=True,exist_ok=True)
    folder=root/'characters'/'auto_dummy'
    if (folder/'character.json').exists(): c=open_character(folder)
    else:
        refs={}
        for role in ('front','side','back'):
            path=root/f'{role}.png'; pose('idle',0,1).save(path); refs[role]=path
        c=prepare(folder,'auto_dummy','자동 생성 더미 (Auto Dummy)',refs,cell=(96,128),anchor=(48,124))
    provider=FaultyModel()
    result=run(c,provider=provider,max_retries=2,cost_limit='1')
    preview(c,root/'preview')
    write_json(root/'result.json',{'registered':result['registered'],'mode':'deterministic test fixture; no paid API calls',
        'reserved_test_usd':result['reserved_usd'],'repairs':[
            {'action':r.action,'selected_frames':r.selected_frames,'same_design':True} for r in provider.requests if r.previous]})
    print(f'Auto dummy registered={result["registered"]}; report: {folder}/production/review.html')


if __name__=='__main__': main()
