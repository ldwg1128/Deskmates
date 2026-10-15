"""Run project checks in isolated processes and save a reproducible JSON report."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from PySide6.QtCore import qVersion


def main():
    root=Path(__file__).resolve().parent
    scripts=['verify_resource_regression.py','verify_pet.py','verify_edge.py',
             'verify_feeding.py','verify_appetite.py','verify_tools.py','verify_settings.py',
             'verify_character_pipeline.py','verify_autogen.py']
    if sys.platform=='win32': scripts.append('verify_rendering.py')
    report={'python':platform.python_version(),'qt':qVersion(),'platform':platform.platform(),'checks':[]}
    env={**os.environ,'PYTHONUTF8':'1'}
    for script in scripts:
        start=time.monotonic()
        result=subprocess.run([sys.executable,str(root/script)],cwd=root,env=env,
                              text=True,encoding='utf-8',errors='replace',capture_output=True)
        report['checks'].append({'script':script,'exit_code':result.returncode,
            'seconds':round(time.monotonic()-start,2),'stdout':result.stdout,'stderr':result.stderr})
        print(f'{"PASS" if result.returncode==0 else "FAIL"}: {script}',flush=True)
        if result.returncode: print(result.stdout+result.stderr,flush=True)
    output=root/'artifacts/resource-refactor/regression-results.json'; output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 1 if any(r['exit_code'] for r in report['checks']) else 0


if __name__=='__main__': raise SystemExit(main())
