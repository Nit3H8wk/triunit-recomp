"""K2 (R1, plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md): 2-player versus tapes from the ROM tables.

ROM evidence (MK3 rev. 2.1 program image, TMS34010 bit addresses; readers seen in the Original by debugger read
watchpoints on the 2P select screen, build/native/mk3-m2/k2-versus.json):
- Select grid GRID 0xff9e9c50: 15 entries of 0x60 bits (long portrait, word x, word y, word character, word 0), 5 columns
  (instruction listing removed; derived locally from the ROM)
  `MOVE *A1(40h),A1,0` (new position -> character, stored at *A13(2D0h): P1 block 0x1060A10, P2 block 0x10615C0).
(instruction listing removed; derived locally from the ROM)
  (0xff9ec900) picks up/down/left/right by stick bits 0-3 of its port (P1 IN0 bits 0-3, P2 bits 8-11; FF81FA70) and
  waits 12 frames between moves (`MOVK Ch,A10`). Any of the three IN0 + three IN1 buttons of the side selects
  (masks 0x70070 / 0x707000 on the 32-bit IN0:IN1 read).
- Position HIDDEN (7, character 14): with RAM word 0x1062DE0 == 0 a move onto it jumps over it (0xff9ee5c0-0xff9ee7d0);
  it is an R5 (secrets) slot, not a K2 fighter.
(instruction listing removed; derived locally from the ROM)
- Arena: RAM word ARENA 0x1062210, read before each fight at 0xff80a8f0 and indexing the arena table ARENA_TABLE
  0xff910780 (longs, reader 0xff962790) and the arena music table MUSIC 0xff80fff0 (words, reader 0xff80ff50); after a
  match 0xff8125b0 adds 1 and wraps at ARENA_CYCLE (11). Characters 0xF, 0x10, 0x11 force arenas 4, 0xA, 0x12 and a
  locked character 14 forces 0xB (0xff80a980-0xff80ab90): not selectable on the grid, R5.
Tapes are legal (tools/mk3/explore.py legal): coins and starts, single stick directions, the side's own buttons.
"""
from pathlib import Path
import random,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import roms

ROOT=Path(__file__).resolve().parents[2]
BASE=0xff800000
GRID,GRID_ENTRY,GRID_CHAR,GRID_SIZE=0xff9e9c50,0x60,0x40,15
MOVES=dict(up=0xff9ee140,down=0xff9ee230,left=0xff9ee320,right=0xff9ee410)
HIDDEN,HIDDEN_FLAG=7,0x1062DE0
HIDDEN_JUMP=dict(up=2,down=12,left=6,right=8)          # 0xff9ee630-0xff9ee7d0 (flag clear)
START=dict(p1=0,p2=4)
PLAYER_BLOCK=dict(p1=0x1060A10,p2=0x10615C0)            # word 0: the character under the cursor (then the chosen one)
ARENA,ARENA_TABLE,MUSIC,ARENA_CYCLE=0x1062210,0xff910780,0xff80fff0,11
STICK=dict(up=1,down=2,left=4,right=8)
SIDE=dict(p1=dict(shift=0,in0=(0x10,0x20,0x40),in1=(0x1,0x2,0x4)),p2=dict(shift=8,in0=(0x1000,0x2000,0x4000),in1=(0x10,0x20,0x40)))
TMS_HZ=6250000
FRAME=TMS_HZ//60
COIN1,START1,START2=0x1,0x4,0x20
# Credits as tools/mk3/fight_route.tape (2 coins per credit with the seed CMOS), then the second credit and Start P2.
PRELUDE=((125000000,3,0xffff^COIN1),(125625000,3,0xffff),(131250000,3,0xffff^COIN1),(131875000,3,0xffff),
         (137500000,3,0xffff^COIN1),(138125000,3,0xffff),(140625000,3,0xffff^COIN1),(141250000,3,0xffff),
         (143750000,3,0xffff^START1),(144375000,3,0xffff),(150000000,3,0xffff^START2),(150625000,3,0xffff))
CURSOR_FROM=160000000                                  # first cursor tap (select screen up, both cursors running)
TAP,GAP=4*FRAME,16*FRAME                               # held 4 frames, one tap every 16 (> the 12-frame repeat)
_rom=None


def image():
    global _rom
    if _rom is None:_rom=roms.program_image(ROOT/'roms/mk3',roms.definition())
    return _rom


def word(a,rom=None):
    rom=rom or image();o=(a-BASE)//8;return int.from_bytes(rom[o:o+2],'little')


def grid(rom=None):
    """The 15 grid entries: position, character, x, y (words of GRID)."""
    out=[]
    for p in range(GRID_SIZE):
        e=GRID+p*GRID_ENTRY
        out.append(dict(position=p,character=word(e+GRID_CHAR,rom),x=word(e+0x20,rom),y=word(e+0x30,rom),portrait=word(e,rom)|word(e+16,rom)<<16))
    return out


def moves(rom=None):return {d:[word(t+16*p,rom) for p in range(GRID_SIZE)] for d,t in MOVES.items()}


def hop(table,pos,d):
    n=table[d][pos]
    return HIDDEN_JUMP[d] if n==HIDDEN else n


def path(src,dst,rom=None):
    """Shortest list of stick directions from position src to dst with the hidden slot locked (breadth first)."""
    table=moves(rom);seen={src:[]};todo=[src]
    for p in todo:
        for d in STICK:
            n=hop(table,p,d)
            if n not in seen:seen[n]=seen[p]+[d];todo.append(n)
    if dst not in seen:raise ValueError(f'position {dst} unreachable from {src}')
    return seen[dst]


def fighters(rom=None):
    """Characters selectable with the hidden slot locked, in grid order, and their positions."""
    return {e['character']:e['position'] for e in grid(rom) if e['position']!=HIDDEN}


def shifted(rows,shift):return tuple((c+shift,p,v) for c,p,v in rows)


def select_rows(p1,p2,shift=0,rom=None):
    """IN0 rows: both cursors walk to the positions of characters p1 and p2 (taps at the same time), then P1 High Punch
    and, 10 frames later, P2 High Punch select. Returns (rows, cycle of the P1 select press)."""
    f=fighters(rom);a,b=path(START['p1'],f[p1],rom),path(START['p2'],f[p2],rom)
    rows=[];c=CURSOR_FROM+shift
    for k in range(max(len(a),len(b))):
        v=0
        if k<len(a):v|=STICK[a[k]]
        if k<len(b):v|=STICK[b[k]]<<8
        rows+=[(c,0,0xffff^v),(c+TAP,0,0xffff)];c+=GAP
    sel=c+GAP
    rows+=[(sel,0,0xffff^SIDE['p1']['in0'][0]),(sel+TAP,0,0xffff),(sel+10*FRAME,0,0xffff^SIDE['p2']['in0'][0]),(sel+10*FRAME+TAP,0,0xffff)]
    return tuple(rows),sel


def fight_rows(seed,start,end,limit):
    """Basic moves on both sides from `start` to `end`: per side a random stick direction (never two opposite) and
    each of its six buttons with probability 0.15, held 2-30 frames; at most `limit` rows."""
    rng=random.Random(seed);rows=[];state={0:0xffff,1:0xffff};c=start
    dirs=(0,1,2,4,8,1|4,1|8,2|4,2|8)
    while c<end:
        in0=in1=0
        for s in SIDE.values():
            in0|=rng.choice(dirs)<<s['shift']
            for b in s['in0']:in0|=b if rng.random()<0.15 else 0
            for b in s['in1']:in1|=b if rng.random()<0.15 else 0
        for port,value in ((0,0xffff^in0),(1,0xffff^in1)):
            if value!=state[port]:
                if len(rows)>=limit:return tuple(rows)
                rows.append((c,port,value));state[port]=value
        c+=rng.randint(2,30)*FRAME
    if state[0]!=0xffff or state[1]!=0xffff:
        rows+=[(c,p,0xffff) for p in (0,1) if state[p]!=0xffff][:max(0,limit-len(rows))]
    return tuple(rows)


def versus_tape(p1,p2,shift=0,seed=0,fight_from=None,fight_to=None,limit=512,rom=None):
    """Legal 2P tape: prelude moved by `shift` cycles (the coin-in time picks the first arena), cursors to p1/p2,
    both selects, and basic moves of both sides in [fight_from, fight_to) (none if fight_from is None)."""
    sel,at=select_rows(p1,p2,shift,rom)
    rows=list(shifted(PRELUDE,shift))+list(sel)
    if fight_from is not None:rows+=list(fight_rows(seed,fight_from,fight_to,limit-len(rows)))
    return dict(tape=tuple(sorted(rows)),select_at=at)


# ---- R1 route plan (native, Profile::Game): the fight-start marker, horizon and arena of each route ----
FIGHT_SOUND=(0x233D,0x233E)   # sound 0x10 (speech call at 0xff80ec30): table FFAA3A60 entry 0x10 (base 0x233C), both seen
FIGHT_SECONDS=15
SPECS=ROOT/'tools/mk3/r1_routes.json'
# First-match arena by coin-in shift (measured natively with the 12/13 default picks, then per route): 14 small shifts
# whose first arenas cover 1-9 (the first versus arena is never 0 or 10, see k2-versus.json).
SHIFTS=(0,781250,2343750,3125000,3906250,5468750,6250000,7031250,8593750,9375000,10156250,11718750,12500000,13281250)


def commands(events):
    d=events['events_full']['dcs'];return [(d[i][0],d[i][1]<<8|d[i+1][1]) for i in range(0,len(d)-1,2)]


def ram_word(dump,address):k=2*((address-0x1000000)>>4);return dump[k]|dump[k+1]<<8


def cyclic_pairs(rom=None):
    f=sorted(fighters(rom));return [(f[i],f[(i+1)%len(f)]) for i in range(len(f))]


def plan_one(native,name,p1,p2,shift,seed):
    """Native run to the fight-start marker, then the full tape (basic moves for FIGHT_SECONDS) to its horizon."""
    probe=versus_tape(p1,p2,shift)['tape'];o=native.run(0,0,0,360000000+shift,probe,events=True)
    fight=next((c for c,v in commands(o['events']) if v in FIGHT_SOUND),None)
    if fight is None:return dict(name=name,p1=p1,p2=p2,shift=shift,seed=seed,fight=None,frontier=o['summary']['frontier'])
    command=next(v for c,v in commands(o["events"]) if c==fight)
    end=fight+FIGHT_SECONDS*TMS_HZ;tape=versus_tape(p1,p2,shift,seed,fight+FRAME,end)['tape'];horizon=end+FRAME
    o=native.run(0,0,0,horizon,tape,[('ram',0)],events=True)
    d=o['dumps'][('ram',0)]
    return dict(name=name,p1=p1,p2=p2,shift=shift,seed=seed,fight=fight,fight_command=command,horizon=horizon,events=len(tape),
                chars=[ram_word(d,PLAYER_BLOCK['p1']),ram_word(d,PLAYER_BLOCK['p2'])],arena=ram_word(d,ARENA),
                frontier=o['summary']['frontier'],end_cycle=o['records'][-1]['cycle'])


def route_tape(spec):
    end=spec['fight']+FIGHT_SECONDS*TMS_HZ
    return versus_tape(spec['p1'],spec['p2'],spec['shift'],spec['seed'],spec['fight']+FRAME,end)


def route_specs(path=SPECS):
    """explore.py ROUTE_SPECS entries of the planned versus routes (tools/mk3/r1_routes.json)."""
    import json
    if not path.is_file():return {}
    out={}
    for s in json.loads(path.read_text('utf-8'))['routes']:
        chain='joins' in s
        t=chain_tape(s) if chain else route_tape(s);tape=t['tape'];sel=t['select_at']
        no_p1_select=tuple(r for r in tape if not (r[0] in (sel,sel+TAP) and r[1]==0))
        if chain:
            criterion=(f"{len(s['arenas'])} consecutive versus matches (the loser buys back in), arenas {s['arenas']} read at 0xff80a8f0; "
                       f"round start of each round at {s['fights']}; ends 1 s after the last round start")
            meta=dict(p1=s['p1'],p2=s['p2'],arena=s['arenas'][0],arenas=s['arenas'],chars=s['chars'],shift=s['shift'],fight=s['fights'][0],
                      fights=s['fights'],wins=s['wins'],joins=s['joins'],attackers=s['attackers'])
        else:
            criterion=(f"versus P1 {s['p1']} x P2 {s['p2']}, arena {s['arena']}: round start (DCS {s['fight_command']:#06x}, sound 0x10) at {s['fight']:,}, "
                       f"then {FIGHT_SECONDS} s of basic moves of both sides")
            meta=dict(p1=s['p1'],p2=s['p2'],arena=s['arena'],shift=s['shift'],seed=s['seed'],fight=s['fight'])
        out[s['name']]=dict(tape=tape,horizon=s['horizon'],criterion=criterion,mutation=(0x30000,1,CURSOR_FROM+s['shift']),
                            input_negative=dict(native=no_p1_select,reference=tape),versus=meta)
    return out


def random_versus(seed,horizon):
    """Exploration tape (explore.py pilot --wave versus): random fighters and coin-in shift, both cursors and selects,
    then basic moves of both sides from 30 frames after the P1 select to the horizon (VS-screen presses included)."""
    rng=random.Random(seed);f=sorted(fighters())
    p1,p2=rng.choice(f),rng.choice(f);shift=rng.randrange(0,80)*781250
    sel,at=select_rows(p1,p2,shift)
    rows=list(shifted(PRELUDE,shift))+list(sel)
    rows+=list(fight_rows(rng.randrange(1<<30),at+30*FRAME,horizon,512-len(rows)))
    return dict(seed=seed,two_players=True,tape=tuple(sorted(rows)),p1=p1,p2=p2,shift=shift)


# ---- reader evidence in the Original (read-only debugger watchpoints; probe, not a route comparison) ----
EVIDENCE_RANGES=((GRID,GRID_SIZE*GRID_ENTRY//8),(0xff9ee140,4*GRID_SIZE*2),(ARENA_TABLE,19*4),(MUSIC,21*2),(PLAYER_BLOCK['p1'],2),
                 (PLAYER_BLOCK['p2'],2),(ARENA,2))


def readers(tape,end,lo,ranges=EVIDENCE_RANGES,fetches=False):
    """Original from reset with `tape` to `end`: every data read of `ranges` (bit address, bytes) in [lo, end] with its PC,
    as {(pc, address): [count, first value, first cycle, first 8 [value, cycle]]}. Uses replay_reference.capture with its global write window
    replaced by read watchpoints on the ranges only (instruction fetches excluded unless `fetches`: an executed PC)."""
    from tools.mk3 import replay_reference as rr
    def script(first,window=None,windows=(),events=False,_orig=rr.script):
        text=_orig(first,window,windows,events).splitlines()
        cond=f'(totalcycles>={lo:#x}&&totalcycles<={end:#x})'
        keep=[l for l in text if not l.startswith('wpset 0,ffffffff,w') and not (l.startswith('wpset') and ',r,' in l and 'MK3_R' in l)]
        reads=[f'wpset {b:x},{n*8:x},r,{cond},{{printf "MK3_R %X %X %X %d %d{rr.NL}",pc,wpaddr,wpdata,totalcycles,wpsize;g}}' for b,n in ranges]
        return '\n'.join(keep[:-1]+reads+keep[-1:])+'\n'
    saved=rr.script;rr.script=script
    try:out=rr.capture(0,0,0,end,tape,window=(lo,end))
    finally:rr.script=saved
    rows={}
    for pc,a,v,c in out['window']['reads']:
        if pc-80<=a<pc and not fetches:continue   # an opcode fetch of the instruction itself (MAME reports the PC after the fetch)
        r=rows.setdefault((pc,a),[0,v,c,[]]);r[0]+=1
        if len(r[3])<8:r[3].append([v,c])   # the first reads one by one (one per match for the arena)
    return dict(rows=rows,wall_seconds=out['wall_seconds'],cleanup=out['cleanup'],core_sha256=out['core_sha256'],program_sha256=out['program_sha256'])


# ---- K2: consecutive versus matches (the arena cycle: first arena 9 -> 10 -> 0) ----
ATTACK_WALK,ATTACK_EVERY=100*FRAME,8*FRAME
ATTACK=dict(p1=(STICK['right'],0x10,0x40),p2=(STICK['left']<<8,0x1000,0x4000))   # walk toward the other side, then HP/HK forward
WIN_SOUND=0x2337   # first DCS command after each round's KO in the probes (the attacks of that round stop there)


def attack_rows(fights,wins,attackers,end):
    """Per round from its round start: the attacker walks ATTACK_WALK, then alternates forward+HP and forward+HK every
    ATTACK_EVERY until the round's win sound (or the next round start/end); the other side is idle; release at the stop."""
    rows=[]
    for i,f in enumerate(fights):
        stop=min([w for w in wins if w>f][:1]+[fights[i+1] if i+1<len(fights) else end,end])
        walk,a,b=ATTACK[attackers[min(i,len(attackers)-1)]]
        rows.append((f+FRAME,0,0xffff^walk));c=f+FRAME+ATTACK_WALK;k=0
        while c<stop-2*FRAME:rows.append((c,0,0xffff^walk^(a if k%2==0 else b)));k+=1;c+=ATTACK_EVERY
        rows.append((min(c,stop-FRAME),0,0xffff))
    return rows


def join_rows(cycle,side,select_after):
    """The loser buys back in: two COIN1 pulses (one credit), its Start, then High Punch on the select screen."""
    start=START1 if side=='p1' else START2
    return [(cycle,3,0xffff^COIN1),(cycle+625000,3,0xffff),(cycle+3125000,3,0xffff^COIN1),(cycle+3750000,3,0xffff),
            (cycle+6250000,3,0xffff^start),(cycle+6875000,3,0xffff),
            (cycle+select_after,0,0xffff^SIDE[side]['in0'][0]),(cycle+select_after+TAP,0,0xffff)]


def chain_tape(spec):
    t=versus_tape(spec['p1'],spec['p2'],spec['shift'])
    rows=list(t['tape'])+attack_rows(spec['fights'],spec['wins'],spec['attackers'],spec['horizon'])
    for j in spec['joins']:rows+=join_rows(j['cycle'],j['side'],j['select_after'])
    return dict(tape=tuple(sorted(rows)),select_at=t['select_at'])


def plan_chain(native,spec,rounds=10):
    """Iterates the native run until the round start and win cycles the tape depends on are stable; returns the spec with
    fights, wins, horizon (1 s after the last round start), per-match arena reads and the native end."""
    spec=dict(spec,fights=list(spec.get('fights',())),wins=list(spec.get('wins',())))
    for _ in range(rounds):
        o=native.run(0,0,0,spec['horizon'],chain_tape(spec)['tape'],events=True)
        ev=commands(o['events']);first=spec['first_fight']
        fights=[c for c,v in ev if v in FIGHT_SOUND and c>=first];wins=[c for c,v in ev if v==WIN_SOUND and c>=first]
        if (fights,wins)==(spec['fights'],spec['wins']):break
        spec['fights'],spec['wins']=fights,wins
    else:raise ValueError('chain plan did not settle')
    return dict(spec,frontier=o['summary']['frontier'],end_cycle=o['records'][-1]['cycle'],
                fight_commands=[v for c,v in ev if c in spec['fights']])
