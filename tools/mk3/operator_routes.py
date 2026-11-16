"""K4 front A (R4, plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md): operator routes from reset.

Legal tapes only: the test switch (IN2 0x10) and the menu presses of tools/mk3/tower.py menu_rows (P1 stick up 0x1 /
down 0x2, HP 0x10 on IN0, one press of 6 frames per second from tower.MENU_FROM + 8 s), START1 (IN2 0x4) and COIN1
(IN2 0x1). A step (0, 0) is a one-second wait (a row that keeps IN0 at rest).

Facts used (program image rev. 2.1, TMS34010 bit addresses): the main test menu table MAIN_MENU (8 entries of 0x60 bits
{long text, long handler, long help}; menu item k is reached by k stick-downs) and the coin debounce table and states
(COIN_TABLE, COIN_STATE4, COIN_LONG). The menu and screen texts are not reproduced here (removed for publication, plan
2026-11-15-conformidade-legal.md, 5.1); a route is named by its index and its menu steps.

Usage: python tools/mk3/operator_routes.py plan            # native Game runs of every route (no Original)
       python tools/mk3/operator_routes.py capture --names r4util r5vs00 ...   # explore.run_route + write_receipt (4 MB), R4 and R5
"""
from pathlib import Path
import argparse,datetime,hashlib,json,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import tower

ROOT=Path(__file__).resolve().parents[2]
SPECS=ROOT/'tools/mk3/r4_routes.json'
T=6250000
FRAME=T//60
TEST_PRESS=(tower.MENU_FROM,3,0xffef)
D,U,HP,W,START=(0,2),(0,1),(0,16),(0,0),(3,4)
FIRST_STEP=tower.MENU_FROM+8*T          # menu_rows: first step 8 s after the test switch press
LIMIT=4_000_000                         # route receipts ceiling (user decision of 11/11/2026)
MAIN_MENU=0xffad1a80
COIN_TABLE,COIN_STATE4,COIN_LONG=0xffae4260,0xffae3f80,0xffae3d70


def util_steps():
    """Main item 4; each of its items 0-5 confirmed (stick up, button), continue; return; the last main item."""
    s=[D,D,D,D,HP]
    for k in range(6):s+=([D] if k else [])+[HP,U,HP,W,W,HP,W]
    return s+[D,HP,W,D,D,D,HP]


def steps_of(name):return ROUTES[name]['steps']()


def at(step):return FIRST_STEP+step*T   # cycle of menu step `step` (0-based)


ADJ=[D,D,D,HP,D,HP,D,HP,D,D,D,HP,D,HP,D,D,HP,D,D,D,D,HP]
DIAG24=[HP,W,(0,0x200),(0,8),(0,0x200),(0,0x20),U,(0,0x40),D,(0,0x20),(0,4),W,(0,0x200),(3,4),(0,4),(0,0x1000),(3,0x20),(0,0x100),HP,(0,8),D,
        (0,0x200),(0,0x100),U]
MON=[HP,D,D,D,D,HP]+[s for k in range(5) for s in ([D] if k else [])+[HP,W,HP]]+[D,HP]   # K8 A: the five pattern screens
FRAC=[D,D,D,HP,D,HP,U,U,U,HP,D,D,D,D,D,HP,D,D,D,D,HP]   # K9 C: pricing table FFCEEC40 entry 1 -> 4 (adj 0xA = 1, 2 units/credit)
PRICE=[D,D,D,HP,D,D,D,HP,D,HP,D,HP,U,HP,U,U,U,U,D,HP,D,HP,W,W]   # K8 A: a custom chute change (FFB042D0 bit 3: adj 0x15 = 0), then standard pricing
ROUTES=dict(
    r4util=dict(steps=util_steps,after=25,criterion='R4 operator route r4util: menu item 4, its six items confirmed, return, exit; 25 s after the last press'),
    r4adj=dict(steps=lambda:ADJ,after=40,extra=((at(len(ADJ)-1)+15*T,3,0xfffb),(at(len(ADJ)-1)+15*T+6*FRAME,3,0xffff)),
               criterion='R4 operator route r4adj: menu item 3 steps, return, exit, START1 15 s later; 40 s after the last menu press'),
    r4book=dict(steps=lambda:[D,HP,HP,HP,HP,HP,HP],after=4,criterion='R4 operator route r4book: menu item 1 and its pages (6 button presses); 4 s after the last press'),
    r4aud=dict(steps=lambda:[D,D,HP,HP,HP,HP,HP,HP,HP],after=4,criterion='R4 operator route r4aud: menu item 2 and its pages (7 button presses); 4 s after the last press'),
    r4hw=dict(steps=lambda:[D,D,D,D,D,HP,W,HP,W,D,HP,U,U,U,D,HP,W],after=4,criterion='R4 operator route r4hw: menu items 5 and 6 (stick up x3, down, button); 4 s after the last press'),
    r4cpu=dict(steps=lambda:[HP,D,D,HP],after=30,extra=((at(4)+6*T,3,0xfffb),(at(4)+8*T,3,0xffff)),
               criterion='R4 operator route r4cpu: menu item 0, sub-item 2; START1 held 2 s; 30 s after the last menu press'),
    r4snd=dict(steps=lambda:[HP,D,D,D,HP,HP,W,W,W,W,W,HP,W,D,HP,HP,W,HP,W,HP,W],after=4,
               criterion='R4 operator route r4snd: menu item 0, sub-items 3 and 4 and their pages; 4 s after the last press'),
    r4sw=dict(steps=lambda:[HP,HP,W,W,W,W,W,W,D,HP,W,W,HP,W],after=4,extra=((at(5),3,0xffdb),(at(5)+30*FRAME,3,0xffff)),
              criterion='R4 operator route r4sw: menu item 0, sub-items 0 and 1, START1+START2 held 0.5 s; 4 s after the last press'),
    r4sw60=dict(make=lambda:switch_presses(seconds=8),horizon=at(1)+11*T,criterion='R4 operator route r4sw60: menu item 0, sub-item 0 with 8 s of legal presses (switch_presses seed 5); 1 s after the presses'),
    r4diag24=dict(steps=lambda:DIAG24,after=4,criterion='R4 operator route r4diag24: menu item 0 with the first 24 steps of a legal exploration walk (seed 12); 4 s after the last press'),
    r4mon=dict(steps=lambda:MON,after=4,criterion='R4 operator route r4mon: menu item 0, sub-item 4 and its five pages; 4 s after the last press'),
    r4price=dict(steps=lambda:PRICE,after=4,criterion='R4 operator route r4price: menu item 3 steps (PRICE); 4 s after the last press'),
    r4hold=dict(steps=lambda:PRICE[:10],after=10,extra=((at(10),0,0xfffe),(at(10)+180*FRAME,0,0xffff),(at(14),0,0xffef),(at(14)+6*FRAME,0,0xffff),
                                                         (at(15),0,0xfffd),(at(15)+120*FRAME,0,0xffff)),
                criterion='R4 operator route r4hold: menu item 3, the first 10 PRICE steps, stick held up 3 s, button, stick held down 2 s; 10 s after the last menu press'),
    r4frac=dict(steps=lambda:FRAC,after=10,extra=((at(len(FRAC)-1)+5*T,3,0xfffe),(at(len(FRAC)-1)+5*T+6*FRAME,3,0xffff)),
                criterion='R4 operator route r4frac: menu item 3 steps (FRAC), return, exit, one COIN1 5 s later; 10 s after the last menu press'),
    r4coin=dict(extra=((100000000,3,0xfffe),(131250000,3,0xffff)),horizon=200000000,
                criterion='R4 operator route r4coin: attract, COIN1 held low 5 s from 100,000,000; 200,000,000'),
)


def switch_presses(seed=5,seconds=60):
    """SWITCH TEST held `seconds` with legal presses every 6-20 frames (single stick directions, P1 side buttons): the
    redraws run the PIXBLT B,XY 0xffae8690 with ST.IE set often enough for interrupts taken inside it (11 natively in 60 s;
    the route keeps 8 s: the switch test reads the ports ~10^5 times per 0.2 s and the whole input stream of 60 s
    overflows the native runner's 256 MB output limit)."""
    import random
    rng=random.Random(seed);rows=list(tower.menu_rows([HP,HP]));c=at(1)+2*T;end=c+seconds*T;state={0:0xffff,1:0xffff}
    while c<end:
        for p in (0,1):
            v=0xffff^(rng.choice((0,1,2,4,8))|rng.choice((0,0x10,0x20,0x40)) if p==0 else rng.choice((0,1,2,4)))
            if v!=state[p]:rows.append((c,p,v));state[p]=v
        c+=rng.randint(6,20)*FRAME
    return rows


def tape(name):
    """Menu rows from reset (tower.menu_rows), plus the route's extra rows (COIN1 holds)."""
    r=ROUTES[name]
    if r.get('make'):return tuple(sorted(r['make']()))
    rows=list(tower.menu_rows(r['steps']())) if r.get('steps') else []
    rows+=list(r.get('extra',()))
    return tuple(sorted(rows))


def horizon(name):
    r=ROUTES[name]
    if r.get('steps') and not r.get('make'):return FIRST_STEP+(len(r['steps']())-1)*T+r['after']*T
    return r['horizon']


def route_specs():
    """explore.py ROUTE_SPECS entries: RAM bit at 160,000,000 and the test-switch press (or first COIN1 row) dropped."""
    out={}
    for n,r in ROUTES.items():
        t=tape(n);drop=TEST_PRESS if TEST_PRESS in t else next(e for e in t if e[1]==3 and e[2]!=0xffff)
        out[n]=dict(tape=t,horizon=horizon(n),criterion=r['criterion'],mutation=(0x30000,1,160000000),
                    input_negative=dict(native=tuple(e for e in t if e!=drop),reference=t),wave=dict(family='R4',route=n))
    return out


def capture(names,processes=12,original_processes=4,audit=4):
    """Receipts for `names` by explore.run_route (the K1-K3 acceptance), written under the 4 MB ceiling."""
    from concurrent.futures import ThreadPoolExecutor
    from tools.mk3 import explore,replay,secrets
    explore.ROUTE_SPECS.update(route_specs());explore.ROUTE_SPECS.update(secrets.route_specs())   # R4 and R5 (tools/mk3/secrets.py)
    pool=explore.Pool(processes,original_processes);out=dict(routes={},failed=[])
    with replay.Native(profile='game') as built:
        native=explore.Native(built,pool);shared=explore.Original(pool)
        def one(n):
            try:r=explore.run_route(native,pool,n,audit,original=shared);p=explore.write_receipt(r,limit=LIMIT);return r,p,None
            except Exception as e:return None,None,dict(name=n,error=repr(e)[:3000])
        with ThreadPoolExecutor(len(names)) as ex:done=list(ex.map(one,names))
        out['executor']=built.source_identity
    for r,p,f in done:
        if f:out['failed'].append(f);continue
        out['routes'][r['name']]=dict(passed=r['passed'],bytes=p.stat().st_size,checkpoints=r['integral']['checkpoints'],end=r['integral']['end'],
                                     first_difference=r['integral']['first_difference'],streams=r['integral']['streams'],
                                     negatives={k:v.get('detected') for k,v in r['negatives'].items()},audit=r['audit'] and r['audit']['passed'],
                                     counters=r['counters'],timings=r['timings'])
    out['native_cleanup']=built.cleanup
    return out


def plan(names):
    """Native Game runs (no Original): end, frontier, DCS commands and first executions new over route_verified.json."""
    from concurrent.futures import ThreadPoolExecutor
    from tools.mk3 import explore,replay,versus
    known=explore.verified_keys();out={}
    with replay.Native(profile='game') as n:
        def one(name):
            o=n.run(0,0,0,horizon(name),tape(name),events=True,first_all=True);sets,_=explore.first_set(o['summary'])
            new={k:sum(1 for i,f in v if (k,i,f) not in known) for k,v in sets.items()};blocks={i for i,f in sets['TmsBlock']}
            return name,dict(end=o['records'][-1]['cycle'],frontier=o['summary']['frontier'],dcs_frontier=o['summary']['dcs_frontier'],
                             commands=len(versus.commands(o['events'])),cmos_writes=len(o['events']['events_full']['cmos']),
                             new_over_verified=new,new_tms_blocks=sorted({hex(i) for i,f in sets['TmsBlock'] if ('TmsBlock',i,f) not in known})[:60],tape_rows=len(tape(name)),tape_sha256=explore.tape_sha(tape(name)),wall_seconds=o['wall_seconds'],
                             coin_blocks={hex(p):p in blocks for p in (COIN_STATE4,COIN_LONG)})
        with ThreadPoolExecutor(min(12,len(names))) as ex:out=dict(ex.map(one,names))
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode',choices=('plan','capture'));ap.add_argument('--names',nargs='*',default=list(ROUTES))
    ap.add_argument('--report',type=Path);ap.add_argument('--original-processes',type=int,default=4)
    a=ap.parse_args()
    out=plan(a.names) if a.mode=='plan' else capture(a.names,original_processes=a.original_processes)
    text=json.dumps(out,indent=1)
    if a.report:a.report.write_text(text+'\n',encoding='utf-8')
    print(text[:8000]);return 0


if __name__=='__main__':raise SystemExit(main())
