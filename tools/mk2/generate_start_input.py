"""Authenticate measured Start input against the existing fixed L3.1 translation."""
from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_prestart_wait as pair,generate_video_irq as shared

PATH=Path(__file__).with_name('start_input_path.json')
measured=json.loads(PATH.read_text(encoding='utf-8'))
START,END,END_PC=22081952,23108559,0xff80dd30
CPU_ROWS,PHYSICAL_ROWS=439431,813947
if (measured['start'],measured['end'],measured['cpu_rows'],measured['physical_rows'])!=(START,END,CPU_ROWS,PHYSICAL_ROWS):
    raise ValueError('Start input manifest differs from the measured endpoint')
if measured['start_cpu34_sha256']!=pair.WINDOWS[-1]['end_cpu34_sha256']:
    raise ValueError('Start input requires the last measured waiting CPU34 boundary')
OUTPUT=pair.OUTPUT
PCS=tuple(sorted(set(pair.PCS)|{int(pc,16) for pc in measured['new_pcs']}))
SUCCESSORS=dict(pair.SUCCESSORS)
for source,targets in measured['successors'].items():
    pc=int(source,16)
    SUCCESSORS[pc]=tuple(sorted(set(SUCCESSORS.get(pc,()))|{int(p,16) for p in targets}))


def generate(rom):
    fixed=pair.generate(rom)
    from tools.mk2.offline_decode import decode
    rows,_=decode(rom,PCS)
    previous=set(pair.PCS);qualified=set(PCS)
    for pc in PCS:
        size,flags,raw,asm=rows[pc]
        code=shared.emit_instruction(pc,size,asm,raw,qualified,SUCCESSORS,end=END_PC)
        if pc not in previous or code!=shared.emit_instruction(pc,size,asm,raw,previous,pair.SUCCESSORS,end=END_PC):
            raise ValueError('Start input requires an additional authenticated fixed translation')
    return fixed


if __name__=='__main__':
    generate(shared.load_program(shared.ROOT/'roms/mk2'))
    print(f'Existing {len(PCS)} fixed blocks cover the measured Start input')
