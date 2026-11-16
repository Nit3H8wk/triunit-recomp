"""K4 front A (R5, plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md): VS-screen codes from the ROM table.

Facts used (program image rev. 2.1, TMS34010 bit addresses): the code table CODES (entries of 0x40 bits {long code, long
handler}, ended by code 0; a repeated code is never reached: first match wins), the six digit boxes at BOXES + 16*box (a
press of the box's button adds 1 mod 10), the mode words MODE and the mode tables MODE_TABLES. The codes are read from the
user's ROM by codes(); the evidence prose was removed for publication (plan 2026-11-15-conformidade-legal.md, 5.1).
Tapes: the versus00 prelude (tools/mk3/r1_routes.json: coins, both starts, cursors, select) cut before its fight rows,
then the code presses on the VS screen, then no input until the horizon (12 s after the round start of versus00).
"""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import versus

ROOT=Path(__file__).resolve().parents[2]
SPECS=ROOT/'tools/mk3/r5_routes.json'   # routes: R1-format versus specs (versus.route_specs), e.g. the 0x0C mirror match
CODES,BOXES,MODE=0xff814050,0x1062C60,0x1062AB0
MODE_TABLES=(0xff950940,0xff950bc0)
FRAME=versus.FRAME;T=versus.TMS_HZ
# box -> (port, mask): P1 LP, BL, LK, P2 LP, BL, LK (tools/mk3/versus.py SIDE / explore.P1, P2 buttons)
BUTTON=((1,0x1),(0,0x20),(1,0x2),(1,0x10),(0,0x2000),(1,0x20))
CODE_FROM,CODE_GAP,CODE_TAP=183000000,15*FRAME,4*FRAME   # VS screen of versus00: DCS 0x451 at 181,198,861; digits read at 205,993,099
HORIZON=290000000


def word(a,rom=None):return versus.word(a,rom)
def long(a,rom=None):return word(a,rom)|word(a+16,rom)<<16


def codes(rom=None):
    """[{index, code, digits, handler, mode, first}] of the table; first False: an earlier entry has the same code."""
    out,seen,a=[],set(),CODES
    while long(a,rom):
        c,h=long(a,rom),long(a+32,rom)
        w=word(h,rom);mode=(w>>5)&31 if (w&0xfc1f)==0x1800 else None   # MOVK k,A0: 0001 10kk kkk0 0000
        out.append(dict(index=len(out),code=f'{c:06x}',digits=[(c>>(20-4*k))&15 for k in range(6)],handler=hex(h),mode=mode,first=c not in seen))
        seen.add(c);a+=64
    return out


def code_rows(digits,start=CODE_FROM):
    """Press slots every CODE_GAP: at slot k every box whose digit > k is pressed (its own button, 4 frames)."""
    rows=[];c=start
    for k in range(max(digits)):
        v={0:0,1:0}
        for box,d in enumerate(digits):
            if d>k:p,m=BUTTON[box];v[p]|=m
        for p in (0,1):
            if v[p]:rows+=[(c,p,0xffff^v[p]),(c+CODE_TAP,p,0xffff)]
        c+=CODE_GAP
    return rows


def prelude():
    spec=json.loads((ROOT/'tools/mk3/r1_routes.json').read_text('utf-8'))['routes'][0]
    assert spec['name']=='versus00'
    return [r for r in versus.route_tape(spec)['tape'] if r[0]<spec['fight']],spec


# Hidden grid slot (flag 0x1062DE0): the 10-box entry after the game over (digits 0x1062C60 + 16*box, buttons HIDDEN_BUTTON)
# compared with the 10 words of the ROM table at 0xff93fe50.
HIDDEN_CODE=(1,0,9,0,2,2,2,2,3,4)
HIDDEN_BUTTON=((0,0x10),(1,0x1),(0,0x20),(1,0x2),(0,0x40),(0,0x1000),(1,0x10),(0,0x2000),(1,0x20),(0,0x4000))   # P1 HP LP BL LK HK, P2 the same
HIDDEN_CUT,HIDDEN_FROM,HIDDEN_COMPARE=2018000000,2021000000,2078935104   # r2t0: game over DCS 0x21 at 2,018,831,304; compare (native)
HIDDEN_HORIZON=2423310000


def hidden_tape():
    from tools.mk3 import explore,tower
    base=[e for e in explore.receipt_tape(explore.load('r2t0')) if e[0]<HIDDEN_CUT]
    rows=hidden_rows(HIDDEN_FROM)
    shift=HIDDEN_COMPARE+20*T-tower.MENU_FROM
    menu=[(c+shift,p,v) for c,p,v in tower.menu_rows([(0,2)]*7+[(0,16)])]   # test switch, 7 downs to the last menu item, button
    return tuple(sorted(base+rows+menu))


def hidden_rows(start):
    rows=[];c=start
    for k in range(max(HIDDEN_CODE)):
        v={0:0,1:0}
        for box,d in enumerate(HIDDEN_CODE):
            if d>k:p,m=HIDDEN_BUTTON[box];v[p]|=m
        for p in (0,1):
            if v[p]:rows+=[(c,p,0xffff^v[p]),(c+CODE_TAP,p,0xffff)]
        c+=CODE_GAP
    return rows


# Grid slot 14 from reset without the test menu: 1P game lost idle, the 10-box entry after the game over, 2 coins + Start 20 s
# after the compare, cursor down/right/right, HP. Cycles: game over, compare, round 2 round start (native).
HIDDEN14_OVER,HIDDEN14_COMPARE,HIDDEN14_ROUND2=604475016,671431671,1055530006


def one_player(shift=0):
    """2 coins, Start P1, P1 HP at grid position 0, from reset; every row moved by `shift` cycles (the coin-in time)."""
    S=versus.TAP
    return [(c+shift,p,v) for c,p,v in list(versus.PRELUDE[:4])+[(143750000,3,0xffff^versus.START1),(144375000,3,0xffff),(175000000,0,0xffef),(175000000+S,0,0xffff)]]


# Residue group 0xffa7f440/0xffa3f590: a 1P game lost idle with the coin-in ARENA7_SHIFT cycles later (arena 7).
ARENA7_SHIFT,ARENA7_HORIZON=7812500,560000000
# Residue 0xffa7f390: a 1P game, then every AUDIT24_PERIOD 2 coins, Start P1 and HP (continues and new games).
AUDIT24_PERIOD,AUDIT24_HORIZON=50000000,3500000000
# Residue 0xff9a4d50: the same tape to a later horizon (route r5x01).
LATE_HORIZON=3520000000


def continues_tape(period=AUDIT24_PERIOD,horizon=AUDIT24_HORIZON):
    rows=one_player();c=300000000;C,S=versus.COIN1,versus.START1
    while c<horizon-period:
        rows+=[(c,3,0xffff^C),(c+625000,3,0xffff),(c+3125000,3,0xffff^C),(c+3750000,3,0xffff),(c+6250000,3,0xffff^S),(c+6875000,3,0xffff),
               (c+9375000,0,0xffef),(c+9375000+versus.TAP,0,0xffff)]
        c+=period
    return tuple(sorted(rows))


def hidden14_tape(code=True):
    S=versus.TAP
    rows=one_player()
    rows+=hidden_rows(HIDDEN14_OVER+2170000) if code else []
    b=HIDDEN14_COMPARE+20*T
    rows+=[(b,3,0xffff^versus.COIN1),(b+625000,3,0xffff),(b+6250000,3,0xffff^versus.COIN1),(b+6875000,3,0xffff),
           (b+18750000,3,0xffff^versus.START1),(b+19375000,3,0xffff)]
    c=b+35000000
    for d in ('down','right','right'):rows+=[(c,0,0xffff^versus.STICK[d]),(c+S,0,0xffff)];c+=versus.GAP
    c+=versus.GAP;rows+=[(c,0,0xffef),(c+S,0,0xffff)]
    return tuple(sorted(rows))


# Residue 0xffa1c900: versus P1 3 x P2 7, a P2 special move (forward, down, back + HP) 120 frames after round start, then a P1 special
# move (back x3 + HK, 2 released frames between the taps) 45 frames later.
REACT_SHIFT,REACT_FIGHT,REACT_HORIZON=3125000,218224075,270000000   # round start of versus 3 x 7 (specials.fight_cycle)


def react_tape(react=True):
    from tools.mk3 import specials
    at=REACT_FIGHT+120*FRAME
    rows=list(versus.versus_tape(3,7,REACT_SHIFT)['tape'])
    rows+=specials.attempt_rows(dict(seq=([8,7,9],[9,7,8]),button='HP',table='press'),'p2',1,at)[0]   # P2 forward, down, back + HP
    c=at+45*FRAME
    if react:
        for _ in range(3):rows+=[(c,0,0xffff^4),(c+3*FRAME,0,0xffff)];c+=5*FRAME   # P1 back (left) held 3, released 2
        rows+=[(c+FRAME,0,0xffff^0x40),(c+5*FRAME,0,0xffff)]   # P1 HK
    return tuple(sorted(rows))


# Residue 0xffa150a0: versus P1 13 x P2 0, P2 idle: P1 forward tapped twice (held 3 frames, released 2) 62 frames after round start,
# HP 1 frame later.
TAP2_FIGHT,TAP2_HORIZON=213312184,231000000   # round start of versus 13 x 0 (specials.fight_cycle)


def tap2_tape(press=True):
    rows=list(versus.versus_tape(13,0)['tape']);c=TAP2_FIGHT+62*FRAME
    for _ in range(2):rows+=[(c,0,0xffff^8),(c+3*FRAME,0,0xffff)];c+=5*FRAME
    if press:rows+=[(c+FRAME,0,0xffef),(c+5*FRAME,0,0xffff)]
    return tuple(sorted(rows))


# Residue 0xffa36ed0: the mode of VS code 642468 (r5vs09) with random P1 left/right holds (seed SCREEN_SEED) from SCREEN_FROM.
SCREEN_SEED,SCREEN_FROM,SCREEN_HORIZON=1,215000000,300000000


def screen_tape(moves=True):
    import random
    rnd=random.Random(SCREEN_SEED);rows=list(tape(codes()[9]));c=SCREEN_FROM
    while moves and c<SCREEN_HORIZON:
        d=rnd.choice(('left','right'));h=rnd.randint(8,40)*FRAME
        rows+=[(c,0,0xffff^versus.STICK[d]),(c+h,0,0xffff)];c+=h+rnd.randint(1,10)*FRAME
    return tuple(sorted(rows))


def tape(entry):
    rows,_=prelude();return tuple(sorted(rows+code_rows(entry['digits'])))


def route_specs():
    """explore.py ROUTE_SPECS of the reachable codes: RAM bit at 160,000,000; the first code press dropped (native)."""
    out={}
    for e in codes():
        if not e['first']:continue
        t=tape(e);first=code_rows(e['digits'])[0]
        out[f"r5vs{e['index']:02d}"]=dict(tape=t,horizon=HORIZON,mutation=(0x30000,1,160000000),
            criterion=f"R5 route r5vs{e['index']:02d}: versus00 prelude, VS-screen code {e['code']} (table 0xff814050 entry {e['index']}); 290,000,000",
            input_negative=dict(native=tuple(r for r in t if r!=first),reference=t),wave=dict(family='R5',code=e['code'],entry=e['index'],handler=e['handler']))
    t=hidden_tape();first=next(e for e in t if e[0]>=HIDDEN_FROM)
    out['r5x03']=dict(tape=t,horizon=HIDDEN_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=tuple(r for r in t if r!=first),reference=t),
        criterion='R5 route r5x03: the r2t0 tape to its game over, the 10-box entry, test switch and last menu item; 20 s after the exit press',
        wave=dict(family='R5',hidden_slot=True,code=HIDDEN_CODE))
    t=hidden14_tape()
    out['r5x04']=dict(tape=t,horizon=HIDDEN14_ROUND2+T,mutation=(0x30000,1,160000000),input_negative=dict(native=hidden14_tape(False),reference=t),
        criterion='R5 route r5x04: 1P game lost idle, the 10-box entry, 2 coins, Start P1, grid position 7, HP; 1 s after the round 2 round start',
        wave=dict(family='R5',hidden_slot=True,character=14,code=HIDDEN_CODE))
    t=tuple(sorted(one_player(ARENA7_SHIFT)))
    out['r5arena7']=dict(tape=t,horizon=ARENA7_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=tuple(sorted(one_player())),reference=t),
        criterion='R5 route r5arena7: 1P game with the coin-in 7,812,500 cycles later, P1 idle and lost; 560,000,000',
        wave=dict(family='R5',residue='0xffa7f440/0xffa3f590',shift=ARENA7_SHIFT))
    t=continues_tape()
    out['r5audit24']=dict(tape=t,horizon=AUDIT24_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=tuple(sorted(one_player())),reference=t),
        criterion='R5 route r5audit24: 1P game, then every 8 s 2 coins, Start P1 and HP (P1 otherwise idle); 3,500,000,000',
        wave=dict(family='R5',residue='0xffa7f390',period=AUDIT24_PERIOD))
    t=continues_tape()   # the r5audit24 tape unchanged
    out['r5x01']=dict(tape=t,horizon=LATE_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=tuple(sorted(one_player())),reference=t),
        criterion=f'R5 route r5x01: the r5audit24 tape; {LATE_HORIZON:,}',
        wave=dict(family='R5',residue='0xff9a4d50',character=2,action='0xff9987e0'))
    t=screen_tape()
    out['r5x05']=dict(tape=t,horizon=SCREEN_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=screen_tape(False),reference=t),
        criterion='R5 route r5x05: r5vs09 with P1 left/right holds from 215,000,000 (random seed 1); 300,000,000',
        wave=dict(family='R5',residue='0xffa36ed0',code='642468',seed=SCREEN_SEED))
    t=react_tape()
    out['r5x02']=dict(tape=t,horizon=REACT_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=react_tape(False),reference=t),
        criterion='R5 route r5x02: versus P1 3 x P2 7, a P2 special move 120 frames after round start, a P1 special move 45 frames later; 270,000,000',
        wave=dict(family='R5',residue='0xffa1c900',p1=3,p2=7,shift=REACT_SHIFT))
    t=tap2_tape()
    out['r5x00']=dict(tape=t,horizon=TAP2_HORIZON,mutation=(0x30000,1,160000000),input_negative=dict(native=tap2_tape(False),reference=t),
        criterion='R5 route r5x00: versus P1 13 x P2 0, P2 idle, a P1 special move 62 frames after round start; 231,000,000',
        wave=dict(family='R5',residue='0xffa150a0',p1=13,p2=0))
    for n,v in versus.route_specs(SPECS).items():   # mirror 0x0C x 0x0C: guard ffa605b0..ffa606d0 -> ffa606f0 (k3-devices.json)
        out[n]=dict(v,wave=dict(family='R5',mirror=0x0C))
    return out


def plan():
    """Native Game runs: digits at the comparison, mode words, handler executed, frontier, keys new over route_verified."""
    from concurrent.futures import ThreadPoolExecutor
    from tools.mk3 import explore,replay
    known=explore.verified_keys();specs=route_specs()
    with replay.Native(profile='game') as n:
        def one(name):
            s=specs[name];o=n.run(0,0,0,s['horizon'],s['tape'],[('ram',205993000),('ram',0)],first_all=True)
            sets,_=explore.first_set(o['summary']);blocks={i for i,f in sets['TmsBlock']}
            d0,d1=o['dumps'][('ram',205993000)],o['dumps'][('ram',0)]
            return name,dict(digits=[versus.ram_word(d0,BOXES+16*k) for k in range(6)],mode=[versus.ram_word(d1,MODE),versus.ram_word(d1,MODE+16)],
                             handler=int(s['wave']['handler'],16) in blocks,end=o['records'][-1]['cycle'],frontier=o['summary']['frontier'],
                             new_over_verified={k:sum(1 for i,f in v if (k,i,f) not in known) for k,v in sets.items()},tape_rows=len(s['tape']))
        with ThreadPoolExecutor(12) as ex:return dict(ex.map(one,sorted(specs)))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter);ap.add_argument('mode',choices=('codes','plan'))
    a=ap.parse_args();print(json.dumps(codes() if a.mode=='codes' else plan(),indent=1))
