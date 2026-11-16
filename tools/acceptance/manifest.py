"""Acceptance reference for the local-setup migration (plan 2026-11-15-conformidade-legal.md, Fase 0).

SHA-256 of the generated translation units, the CMOS seeds and the route receipts as they are today.
The setup must reproduce these bytes before any of them leaves the repository.
  python tools/acceptance/manifest.py           write manifest.json
  python tools/acceptance/manifest.py --check   compare the working tree with manifest.json
"""
from pathlib import Path
import hashlib,json,subprocess,sys

ROOT=Path(__file__).resolve().parents[2]
TARGET=Path(__file__).with_name('manifest.json')
PATTERNS=['native/**/*.inc','native/runtime/*.bin','tools/mk3/route_verified.json','tools/mk2/flow_replays/*.json']


def current():
    names=subprocess.run(['git','ls-files','-z','--',*PATTERNS],cwd=ROOT,capture_output=True,check=True).stdout.decode().split('\0')
    return {n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n in sorted(filter(None,names)) for b in [(ROOT/n).read_bytes()]}


if __name__=='__main__':
    files=current()
    if sys.argv[1:]==['--check']:
        saved=json.loads(TARGET.read_text(encoding='utf8'))['files']
        changed=sorted(n for n in saved.keys()|files.keys() if saved.get(n)!=files.get(n))
        print(json.dumps({'files':len(saved),'changed':changed},indent=2));sys.exit(1 if changed else 0)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    TARGET.write_text(json.dumps({'commit':head,'files':files},indent=2)+'\n',encoding='utf8',newline='\n')
    print(len(files),'files')
