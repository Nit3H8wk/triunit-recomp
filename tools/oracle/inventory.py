"""Inventory of the TMS34010 forms the three translators emit (one-day plan, docs/superpowers/plans/2026-11-14-plano-um-dia.md).

MK1: native/src/*_graph.inc (labels `pc_XXXXXXXX: { // ASM`). MK2: native/mk2/*.inc|*.hpp|*.cpp (`case 0x...u: { // ASM`).
MK3: the units tools/mk3/generate.py emits in memory (`case 0x...u: { // ASM`). A form is the mnemonic and the operand shape
(tools/mk3/generate.py form(): registers -> R, constants -> K). For each form: emitted sites, translated sites (not a
rejection/throw) and up to 3 example PCs. Nothing is written but the report.

    python tools/oracle/inventory.py --report build/native/day1/forms.json
"""
import argparse,collections,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.mk3 import generate,roms

SITE=re.compile(r'^(?:case 0x([0-9a-f]{8})u?:|pc_([0-9a-f]{8}):) \{ // (.+?)\s*$')
REJECT=('o.Reject(','throw std::runtime_error','untranslated')

def sites(text):
    """(pc, asm, body) for each commented site of a generated source."""
    lines=text.splitlines();out=[]
    for i,l in enumerate(lines):
        m=SITE.match(l)
        if not m:continue
        body=[]
        for j in range(i+1,min(i+12,len(lines))):
            if SITE.match(lines[j]):break
            body.append(lines[j])
        out.append((int(m.group(1) or m.group(2),16),m.group(3),'\n'.join(body)))
    return out

def sources(game):
    if game=='mk1':return sorted((ROOT/'native/src').glob('*_graph.inc'))
    if game=='mk2':return sorted(p for p in (ROOT/'native/mk2').iterdir() if p.suffix in ('.inc','.hpp','.cpp'))
    raise ValueError(game)

def collect(game):
    found={}
    if game=='mk3':
        rom=roms.program_image(ROOT/'roms/mk3',roms.definition());rows,_=generate.scan(rom)
        text,_=generate.units(rom,rows)
        for name,source in text.items():
            for pc,asm,body in sites(source):found[pc]=(asm,body,name)
    else:
        for path in sources(game):
            for pc,asm,body in sites(path.read_text('utf-8',errors='replace')):found.setdefault(pc,(asm,body,path.name))
    forms=collections.defaultdict(lambda:dict(sites=0,translated=0,examples=[],files=set()))
    for pc,(asm,body,name) in sorted(found.items()):
        f=forms[generate.form(asm)];f['sites']+=1;f['files'].add(name)
        if not any(r in body for r in REJECT):
            f['translated']+=1
            if len(f['examples'])<3:f['examples'].append(f'{pc:08x} {asm}')
    return {k:dict(v,files=sorted(v['files'])) for k,v in sorted(forms.items())}

def main():
    a=argparse.ArgumentParser();a.add_argument('--report',required=True);a.add_argument('--games',default='mk1,mk2,mk3')
    args=a.parse_args();report={}
    for game in args.games.split(','):
        forms=collect(game)
        report[game]=dict(forms=len(forms),translated_forms=sum(1 for f in forms.values() if f['translated']),
                          sites=sum(f['sites'] for f in forms.values()),translated_sites=sum(f['translated'] for f in forms.values()),
                          by_form=forms)
        print(game,{k:v for k,v in report[game].items() if k!='by_form'})
    out=Path(args.report);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(dict(schema='day1-forms/1',games=report),indent=1)+'\n',encoding='utf-8')

if __name__=='__main__':main()
