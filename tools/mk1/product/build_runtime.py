"""Build the MK1 engine for the local product folder (build/native/manual-temporary-8-20261025/product).

    python tools/mk1/product/build_runtime.py build

The engine is compiled by tools/mk1/build.py from the source tree and the includes the setup generates from the user's
ROMs (generated/mk1/<sha>/); the result is copied into the product folder and recorded in build.json (identities only).
"""
from pathlib import Path
import argparse,hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
STAGE=ROOT/'build/native/manual-temporary-8-20261025';PRODUCT=STAGE/'product'


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['build']);p.parse_args()
    from tools.mk1 import build
    from tools.quality import run as q
    from tools.setup import mk1,paths
    for part in (STAGE,*STAGE.parents):
        if part.is_symlink() or part.is_junction():raise RuntimeError('Linked build path: '+str(part))
    mk1.inc_dir();out=paths.output('mk1');rec={'passed':False,'mode':'build'}
    try:
        built=build.engine(out)
        if not built['passed']:raise RuntimeError(built.get('output_tail',''))
        PRODUCT.mkdir(parents=True,exist_ok=True);shutil.copy2(out/'mk5-native-audio',PRODUCT/'mk5-native-audio')
        rec.update(passed=True,sha256=sha(PRODUCT/'mk5-native-audio'),compiler_sha256=sha(q.DEFAULT_CC),generated=mk1.files(),
                   game_rules_changed=False)
    except BaseException as e:
        rec['error']=str(e)[-4000:];raise
    finally:
        STAGE.mkdir(parents=True,exist_ok=True);(STAGE/'build.json').write_text(json.dumps(rec,indent=2)+'\n')
    print(json.dumps({k:v for k,v in rec.items() if k!='generated'},indent=2))


if __name__=='__main__':main()
