"""RM3: map of DCS commands -> context, from the route receipts (build/native/mk3-m2/routes/<route>.json, events.dcs).

events.dcs is the Original/native sound-port write stream, [[TMS cycle, value], ...] from reset. Each write carries one
byte; a command is a consecutive pair (high byte, then low byte; its cycle is the low byte's), as the Original's
0xffaa88b0 / 0xffaa8920 writes paired in tools/mk3/test_fight.py observe. Every command gets its route and the phase it
was heard in: the last project mark (MARKS) written before it, a mark opening its own phase.

The class (musica / fala / efeito) comes only from EVIDENCE, each entry citing its ROM caller or DCS code; every other
command is "sem classe". No track or asset is associated here (plan RM3: only with the user's assets and confirmation).

    python tools/mk3/music_map.py                 # reads build/native/mk3-m2/routes/*.json, prints the map as JSON
    python tools/mk3/music_map.py --routes DIR    # another receipt directory
"""
from pathlib import Path
import argparse,json,sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.mk3 import explore
ROUTES=ROOT/'build/native/mk3-m2/routes'
UNCLASSIFIED='sem classe'
# Marks already used by the project's routes (tools/mk3/test_attract.py, test_fight.py; docs/MK3_DEVELOPMENT.md J2/J3).
MARKS={0x0451:'rodada demo do attract (primeiro comando de cada rodada)',0x2341:'"Round" 1',0x2346:'"Round" 2',
       0x233d:'round start',0x0038:'tela de continue',0x0021:'fim da partida'}
# Class only with a cited caller in the ROM or the DCS code.
EVIDENCE={0x233d:dict(classe='fala',evidencia='chamada de fala (som 10h) em 0xff80ec30-0xff80ec50, que chega '
                                               'ao emissor 0xffaa87c0 (docs/MK3_DEVELOPMENT.md J3; tools/mk3/test_fight.py)')}


def commands(writes):
    """(commands [(cycle, command)], unpaired tail write or None) from the byte writes of one route."""
    rows=[]
    for n,w in enumerate(writes):
        if not (isinstance(w,(list,tuple)) and len(w)==2 and all(isinstance(v,int) and not isinstance(v,bool) for v in w)):
            raise ValueError(f'events.dcs[{n}] is not [cycle, value]: {w!r}')
        if not 0<=w[1]<=0xff:raise ValueError(f'events.dcs[{n}] value {w[1]:#x} is not one sound-port byte')
        if w[0]<0 or (rows and w[0]<rows[-1][0]):raise ValueError(f'events.dcs[{n}] cycle {w[0]} goes back')
        rows.append(tuple(w))
    pairs=[(lo[0],(hi[1]<<8)|lo[1]) for hi,lo in zip(rows[0::2],rows[1::2])]
    return pairs,(list(rows[-1]) if len(rows)%2 else None)


def build(receipts):
    """The map from {route: events.dcs}: per command its class, evidence, mark and, per route, count, first cycle and phases."""
    table,routes={},{}
    for route in sorted(receipts):
        pairs,tail=commands(receipts[route]);phase='antes da primeira marca'
        routes[route]=dict(writes=len(receipts[route]),commands=len(pairs),unpaired_tail=tail)
        for cycle,command in pairs:
            if command in MARKS:phase=f'{command:04x} {MARKS[command]}'
            key=f'{command:04x}';known=EVIDENCE.get(command,{})
            row=table.setdefault(key,dict(classe=known.get('classe',UNCLASSIFIED),evidencia=known.get('evidencia'),marca=MARKS.get(command),contexts={}))
            ctx=row['contexts'].setdefault(route,dict(count=0,first_cycle=cycle,phases={}))
            ctx['count']+=1;ctx['phases'][phase]=ctx['phases'].get(phase,0)+1
    classes={}
    for row in table.values():classes[row['classe']]=classes.get(row['classe'],0)+1
    return dict(routes=routes,commands=dict(sorted(table.items())),classes=classes,tracks_associated=0,assets=0)


def load(directory=ROUTES):
    """{route: events.dcs} of every receipt in directory (route = file stem)."""
    receipts={}
    for path in sorted(Path(directory).glob('*.json')):
        data=json.loads(path.read_text('utf-8'))
        try:dcs=explore.dcs_rows(data)   # a list, or packed in the /2 receipts (K3)
        except (KeyError,TypeError,AttributeError,ValueError):dcs=None
        if not isinstance(dcs,list):raise ValueError(f'{path.name}: no events.dcs list')
        receipts[path.stem]=dcs
    return receipts


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--routes',type=Path,default=ROUTES);a=p.parse_args()
    if not a.routes.is_dir():
        print(json.dumps(dict(routes={},commands={},note=f'no receipt directory {a.routes}')));return 1
    print(json.dumps(build(load(a.routes)),indent=1,ensure_ascii=False));return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');raise SystemExit(main())
