"""K3 (R2, plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md): 1-player tower tapes from the ROM tables.

ROM evidence (MK3 rev. 2.1 program image, TMS34010 bit addresses; readers confirmed in the Original by debugger read
watchpoints, build/native/mk3-m2/k3-waves.json):
(instruction listing removed; derived locally from the ROM)
  stored in RAM long LADDER_PTR 0x1062D90. LADDERS 0xffa000f0: 6 longs, each a ladder of words.
- Each ladder: three towers of character words ended by 0xFFFF: words 0-7 (6 fighters, 0xF, 0x10), 9-18 (8 + 0xF,
  0x10), 20-31 (10 + 0xF, 0x10). 0xF and 0x10 are the two bosses that close every tower.
- Tower screen 0xff9fceb0: A11 starts at 2; stick left (bit 2) decrements to 0, right (bit 3) increments to 2, 10
  frames between moves; any side button (IN0:IN1 mask 0x70070 for P1) confirms, else it times out after 0x100 frames.
  0xff9fff80 stores the first opponent pointer (RAM long 0x1062260): A11 2 -> ladder + 0 (8 fights), 0 -> + 0x90
  (10 fights), 1 -> + 0x140 (12 fights). The display loops 0xff9fcc70/ca40/840 read the same words.
Fights are won by search in the native (Profile::Game): random legal P1 inputs per fight or per 4 s chunk, each
candidate a copy of an exploration snapshot at the chunk start (replay.Explorer, K4 decision 3: search only), kept when
the next fight's "Round 1" (DCS 0x2341) follows; the route is then run from reset and compared with the Original.
"""
from pathlib import Path
import json,os,random,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import versus

ROOT=Path(__file__).resolve().parents[2]
LADDERS,LADDER_COUNT,LADDER_PTR,OPPONENT_PTR=0xffa000f0,6,0x1062D90,0x1062260
TOWERS={2:(0,8),0:(9,10),1:(20,12)}      # A11 -> (first word, fights)
TOWER_SCREEN=197502609                   # first cycle of 0xff9fceb0 with the J3 prelude (native, game profile)
FRAME=versus.FRAME
ROUND1,FIGHT=(0x2341,0x2342),versus.FIGHT_SOUND   # both announcer variants seen natively (0x2342/0x233E after a continue)
P1_IN0,P1_IN1=(0x10,0x20,0x40),(0x1,0x2,0x4)
DIRS=(0,1,2,4,8,1|4,1|8,2|4,2|8)
SPECS=ROOT/'tools/mk3/r2_routes.json'
FIGHT_SECONDS=150


def ladders(rom=None):
    """The 6 ladders: {pointer, towers {A11: [character, ...]}} read from the ROM."""
    rom=rom or versus.image();W=lambda a:versus.word(a,rom)
    out=[]
    for k in range(LADDER_COUNT):
        p=W(LADDERS+32*k)|W(LADDERS+32*k+16)<<16
        towers={}
        for t,(w0,n) in TOWERS.items():
            row=[W(p+16*(w0+i)) for i in range(n)]
            if W(p+16*(w0+n))!=0xffff:raise ValueError(f'ladder {k} tower {t}: no 0xFFFF end')
            towers[t]=row
        out.append(dict(pointer=p,towers=towers))
    return out


# Operator menu (test switch IN2 0x10, then P1 stick down 0x2 / HP 0x10, one press per second from 200,000,000): Game
# Adjustment -> Computer Difficulty, two stick-downs (3 MEDIUM -> 1 VERY EASY, the game writes CMOS long 0x1408380 at each
# move), confirm, Return to main menu, Exit test menu (the game restarts). Screens read from native VRAM renders.
MENU_STEPS=((0,2),(0,2),(0,2),(0,16),(0,2),(0,2),(0,2),(0,2),(0,2),(0,16),(0,2),(0,2),(0,16),(0,2),(0,16),(0,2),(0,2),(0,2),(0,2),(0,16))
MENU_FROM,MENU_SHIFT=200000000,437500000   # prelude rows shifted by MENU_SHIFT: coins 30 s after the exit (attract)
DIFFICULTY=0x1408380                       # CMOS long of COMPUTER DIFFICULTY (seed 3)


def menu_rows(steps=MENU_STEPS):
    """The test-switch press (12 frames) and the menu presses (6 frames each, 1 s apart) from MENU_FROM."""
    T=versus.TMS_HZ;c=MENU_FROM;rows=[(c,3,0xffef),(c+12*FRAME,3,0xffff)];c+=8*T
    for port,mask in steps:rows+=[(c,port,0xffff^mask),(c+6*FRAME,port,0xffff)];c+=T
    return rows


def prelude(p1_character=None,tower=2,rom=None,menu=False):
    if menu:return tuple(sorted(menu_rows()+[(c+MENU_SHIFT,p,v) for c,p,v in prelude(p1_character,tower,rom)]))
    """J3 coins and Start P1, P1 cursor to the character (default: the start position), the select press of the J3
    tape, then stick-left taps on the tower screen from 2 down to `tower`; the screen times out to confirm."""
    from tools.mk3 import explore
    rows=list(explore.FIGHT_TAPE[:8])
    if p1_character is not None:
        c=versus.CURSOR_FROM
        for d in versus.path(versus.START['p1'],versus.fighters(rom)[p1_character],rom):
            rows+=[(c,0,0xffff^versus.STICK[d]),(c+versus.TAP,0,0xffff)];c+=versus.GAP
        if c>=explore.FIGHT_TAPE[6][0]:raise ValueError('cursor path overlaps the select press')
    c=TOWER_SCREEN+30*FRAME
    for _ in range(2-tower):rows+=[(c,0,0xffff^versus.STICK['left']),(c+4*FRAME,0,0xffff)];c+=16*FRAME
    return tuple(sorted(rows))


# Legal P1 input macros (IN0 stick/HP/BL/HK bits, IN1 LP/LK/RUN bits, frames held): press, then release 2 frames.
UP,DOWN,LEFT,RIGHT=1,2,4,8
MACROS=dict(walk_r=((RIGHT,0,12),),walk_l=((LEFT,0,12),),uppercut=((DOWN,0,3),(DOWN|0x10,0,4)),low_kick=((DOWN,0,2),(DOWN,0x2,4)),
            sweep_r=((LEFT,0,2),(LEFT|0x40,0,4)),sweep_l=((RIGHT,0,2),(RIGHT|0x40,0,4)),high_punch=((0x10,0,4),),high_kick=((0x40,0,4),),
            low_punch=((0,0x1,4),),jump_kick_r=((UP|RIGHT,0,10),(UP|RIGHT|0x40,0,4)),jump_kick_l=((UP|LEFT,0,10),(UP|LEFT|0x40,0,4)),
            block=((0x20,0,10),),crouch_block=((DOWN|0x20,0,10),),fwd_hp_r=((RIGHT|0x10,0,4),),fwd_hp_l=((LEFT|0x10,0,4),),run_r=((RIGHT,0x4,14),))


def p1_rows(seed,start,end):
    """Legal P1 inputs from `start` to `end`: a candidate draws its own weights over MACROS, then plays macros drawn
    with them (each step held as listed, then released 2 frames); released at `end`."""
    rng=random.Random(seed);names=sorted(MACROS);w=[rng.random()**2 for _ in names];rows=[];state={0:0xffff,1:0xffff};c=start
    def put(c,in0,in1):
        for port,value in ((0,0xffff^in0),(1,0xffff^in1)):
            if value!=state[port]:rows.append((c,port,value));state[port]=value
    while c<end:
        for in0,in1,n in MACROS[rng.choices(names,w)[0]]:
            if c>=end:break
            put(c,in0,in1);c+=n*FRAME
        if c<end:put(c,0,0);c+=2*FRAME
    kept=[r for r in rows if r[0]<end];last={p:next((r[2] for r in reversed(kept) if r[1]==p),0xffff) for p in (0,1)}
    return kept+[(end,p,0xffff) for p in (0,1) if last[p]!=0xffff]


def commands(o):return versus.commands(o['events'])


HEALTH=dict(p1=0x1060A40,p2=0x10615F0)   # word +0x30 of each player block: 166 (0xA6) full, 0 at the KO (native probe; Original readers in k3-waves.json)
# (instruction listing removed; derived locally from the ROM)
# accesses each); r2e2 tape natively: P2 0 -> 0 -> 1 across fight 1 (P1 won round 1, lost round 2), 0 after the match.
ROUNDS=dict(p1=0x1060A70,p2=0x1061620)
CHUNK=4*versus.TMS_HZ


def chunk_rows(seed,start,end,names=None):
    """Macro inputs of one search chunk [start, end): both ports set at `start`, then macros as p1_rows (only `names`
    if given); no release."""
    rng=random.Random(seed);names=sorted(names or MACROS);w=[rng.random()**2 for _ in names];rows=[(start,0,0xffff),(start,1,0xffff)];c=start
    state={0:0xffff,1:0xffff}
    def put(c,in0,in1):
        for port,value in ((0,0xffff^in0),(1,0xffff^in1)):
            if value!=state[port]:rows.append((c,port,value));state[port]=value
    while c<end:
        for in0,in1,n in MACROS[rng.choices(names,w)[0]]:
            if c>=end:break
            put(c,in0,in1);c+=n*FRAME
        if c<end:put(c,0,0);c+=2*FRAME
    rows=[r for r in rows if r[0]<end];out={}
    for r in rows:out[(r[0],r[1])]=r            # one row per (cycle, port): the last one set at that cycle
    return sorted(out.values())


def fight_rows(f):
    """Rows of a won fight: whole-fight candidate (seed) or guided chunks, cut at the next Round 1 and released there."""
    if 'chunks' not in f:return p1_rows(f['seed'],f['fight']+FRAME,f['cut'])
    rows=[r for ch in f['chunks'] for r in chunk_rows(ch['seed'],ch['start'],ch['end']) if r[0]<f.get('cut',ch['end'])]
    return rows+([(f['cut'],0,0xffff),(f['cut'],1,0xffff)] if 'cut' in f else [])


def plan_guided(native,spec,candidates=12,max_chunks=40,log=print,save=None,until=None,rounds=False):
    """Extends spec['fights'] fight by fight with a native search guided by the state of the native run: per CHUNK,
    `candidates` macro chunks continue copies of an exploration snapshot at the chunk start (replay.Explorer: search
    only; the route is captured from reset afterwards) and the one leaving the best health margin (HEALTH p1 - p2 at the
    chunk end; a lost match scores lowest) becomes the next snapshot. A fight is won at the next Round 1; the tape is cut
    there. Stops at a lost fight (spec['lost']) or when the tower is done. rounds (K9 A): the health margin resets at each
    round, so a lost round would score like a fresh one; with rounds the score adds 1000 * (ROUNDS p1 - p2) at the chunk end.
    The last fight has no next Round 1: it is won when ROUNDS p1 reaches 2 at a chunk end, cut at that chunk end."""
    from tools.mk3.replay import Explorer
    spec=dict(spec,fights=list(spec.get('fights',())));n=TOWERS[spec['tower']][1];T=versus.TMS_HZ
    partial=spec['fights'].pop() if spec['fights'] and 'cut' not in spec['fights'][-1] else None   # a fight saved chunk by chunk
    start=lambda:spec['fights'][-1]['cut'] if spec['fights'] else TOWER_SCREEN+(MENU_SHIFT if spec.get('menu') else 0)
    with Explorer(native,tape_of(spec),start()) as ex:
        pending=()   # rows of the tape from the snapshot on: the cut of the last won chunk
        while len(spec['fights'])<min(n,until or n):
            after=start();o=ex.run([dict(tape=pending,horizon=after+40*T)])[0]
            if spec['fights'] and not any((after,r) in commands(o) for r in ROUND1):raise ValueError(f'{spec["name"]}: the cut tape does not reproduce Round 1 at {after}')
            fight=next((c for c,v in commands(o) if v in FIGHT and c>after),None)
            if fight is None:spec['lost']=dict(fight=len(spec['fights']),reason='no round start after the last cut',frontier=o['summary']['frontier']);break
            f=dict(fight=fight,chunks=[]);spec['fights'].append(f);c=fight+FRAME;won=None
            if partial and partial['fight']==fight:f['chunks']=partial['chunks'];c=f['chunks'][-1]['end'] if f['chunks'] else c   # resume a saved fight
            partial=None
            ex.run([dict(tape=pending+tuple(r for ch in f['chunks'] for r in chunk_rows(ch['seed'],ch['start'],ch['end'])),horizon=c,keep=True)]);ex.adopt(0);pending=()
            for k in range(len(f['chunks']),max_chunks):
                seeds=[spec['seed']*100000+len(spec['fights'])*1000+k*candidates+j for j in range(candidates)]
                xs=ex.run([dict(tape=chunk_rows(sd,c,c+CHUNK),horizon=c+CHUNK,dumps=[('ram',0)],keep=True) for sd in seeds])
                res=[]
                for i,(sd,x) in enumerate(zip(seeds,xs)):
                    d=x['dumps'][('ram',0)];cs=commands(x)
                    r1=next((cc for cc,v in cs if v in ROUND1 and cc>fight),None);lost=any(v==LOSE and cc>fight for cc,v in cs)
                    score=-10**6 if lost else (10**6 if r1 else versus.ram_word(d,HEALTH['p1'])-versus.ram_word(d,HEALTH['p2']))
                    w=(versus.ram_word(d,ROUNDS['p1']),versus.ram_word(d,ROUNDS['p2']))
                    if rounds and abs(score)<10**6:score+=1000*(w[0]-w[1])
                    res.append((score,sd,r1,x['summary']['frontier'],i,w))
                res.sort(key=lambda r:(-r[0],r[1]))
                stops=[r for r in res if r[3]!='none']
                if stops:spec.setdefault('stops',[]).extend(dict(fight=len(spec['fights']),chunk=k,seed=r[1],frontier=r[3]) for r in stops)
                best=next((r for r in res if r[3]=='none'),None)
                if best is None or best[0]==-10**6:break
                f['chunks'].append(dict(seed=best[1],start=c,end=c+CHUNK,score=best[0]));log(f'  chunk {k} score {best[0]} worst {res[-1][0]} rounds {best[5][0]}-{best[5][1]} ({ex.seconds:.1f} s)')
                if len(spec['fights'])==n and best[5][0]>=2 and not best[2]:best=best[:2]+(c+CHUNK,)+best[3:]   # the last boss: no next Round 1
                if best[2]:
                    f['cut']=best[2];won=True
                    pending=tuple(r for r in chunk_rows(best[1],c,c+CHUNK) if r[0]<best[2])+((best[2],0,0xffff),(best[2],1,0xffff));break
                ex.adopt(best[4]);c+=CHUNK
                if save:save(spec)
            if not won:
                spec['fights'].pop();spec['lost']=dict(fight=len(spec['fights']),fight_cycle=fight,chunks=k+1,last_scores=[r[0] for r in res[:3]],tried=f['chunks']);break
            log(f"{spec['name']}: fight {len(spec['fights'])}/{n} won by {len(f['chunks'])} chunks, cut {f['cut']}")
            if save:save(spec)
    if save:save(spec)
    return spec


def bot_run(native,prefix,horizon,words,policy,period=FRAME):
    """Closed-loop native run (mk3_replay_main `bot`): `prefix` tape, then every `period` cycles policy(cycle, words,
    dcs) -> {port: value} reads the RAM `words` and new sound commands and sets inputs at that boundary. Returns the
    whole legal tape (prefix + the rows set) and the summary; the tape replays the same run from reset."""
    import subprocess
    from tools.quality import run as q
    from tools.mk3 import reference,replay_state
    spec=['profile game' if native.profile=='game' else 'profile strict',f'horizon {horizon}',f'bot {period} '+' '.join(map(str,words))]
    spec+=[f'tape {c} {p} {v}' for c,p,v in prefix]
    rows=list(prefix);state={p:0xffff for p in range(4)}
    for c,p,v in prefix:state[p]=v
    tail=[]
    with q.scratch_tree() as (temp,cleanup):
        (temp/'spec.txt').write_text('\n'.join(spec)+'\n',encoding='ascii')
        x=subprocess.Popen([str(native.exe),str(ROOT/'roms/mk3'),str(reference.SEED),str(native.temp/'gfx.txt'),str(temp/'spec.txt')],cwd=ROOT,
                           env={**os.environ,**native.env},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
        try:
            for line in x.stdout:
                if line.startswith('{"bot"'):
                    d=json.loads(line);out=[]
                    for p,v in (policy(d['bot'],d['w'],d['dcs']) or {}).items():
                        if state[p]!=v:state[p]=v;rows.append((d['bot'],p,v));out+=[p,v]
                    x.stdin.write(' '.join(map(str,out))+'\n')
                else:tail.append(line)
        finally:
            if x.poll() is None and not tail:x.kill()
            x.wait()
    if cleanup.get('exists_after'):raise RuntimeError('bot scratch retained')
    return dict(tape=tuple(rows),out=replay_state.parse_native(''.join(tail)),returncode=x.returncode)


OBJECT=dict(p1=0x10609B0,p2=0x1061560)   # long: the fighter object (RM2 front: written by FFA5E880/FFA5EA30)
OX,OY=0x90,0xB0                          # integer x and y words of the object (native probe: x moves with the stick)
BOT_WORDS=(HEALTH['p1'],HEALTH['p2'],f"{OBJECT['p1']}:{OX}",f"{OBJECT['p2']}:{OX}",f"{OBJECT['p1']}:{OY}",f"{OBJECT['p2']}:{OY}",
           OPPONENT_PTR,OPPONENT_PTR+16)
WIN_SOUND=versus.WIN_SOUND
COIN_START=((0,3,0xfffe),(625000,3,0xffff),(3125000,3,0xfffe),(3750000,3,0xffff),(6250000,3,0xfffb),(6875000,3,0xffff))


class Bot:
    """Closed-loop P1 player for bot_run: plays macros from round start until a lost match, choosing by the distance to the
    opponent and whether it is airborne (rng `seed`, weights `style`); after a lost match (LOSE) it continues (coin +
    Start, as coin_start) 2 s later. Only legal IN0/IN1/IN2 values; the game state is only read. `dealt`/`taken` sum
    the health drops of each side (HEALTH words) for the comparison of styles."""
    def __init__(self,seed,style=None):
        self.rng=random.Random(seed);self.bytes=[];self.cmds=[];self.fighting=False;self.queue=[];self.coins=[];self.ground=None
        self.style=dict(BOT_STYLE,**(style or {}));self.events=[];self.dealt=self.taken=0;self.last=None
    def plan(self,dx,air,dist):
        st,ch=self.style,self.rng.choices;tw,aw=(RIGHT,LEFT) if dx>0 else (LEFT,RIGHT)
        M=dict(upper=[(DOWN,0,3),(DOWN|0x10,0,5),(0,0,8)],sweep=[(aw,0,2),(aw,0x2,5),(0,0,8)],throw=[(tw,0x1,4),(0,0,4)],
               jab=[(0x10,0,3),(0,0,3),(0x10,0,3),(0,0,3)],low=[(DOWN,0,2),(DOWN,0x2,4),(0,0,3)],block=[(0x20,0,8)],
               cblock=[(DOWN|0x20,0,8)],jump=[(tw|UP,0,10),(tw|UP|0x40,0,4),(0,0,20)],walk=[(tw,0,6)],run=[(tw,0x4,10)],
               rh=[(aw,0,2),(aw|0x40,0,4),(0,0,6)],back=[(aw,0,8)])
        zone='air' if air>8 and dist<st['d_mid'] else 'near' if dist<st['d_near'] else 'mid' if dist<st['d_mid'] else 'far'
        names=list(st[zone]);return M[ch(names,[st[zone][n] for n in names])[0]]
    def __call__(self,c,w,dcs):
        for v in dcs:
            self.bytes.append(v)
            if len(self.bytes)%2==0:
                cmd=self.bytes[-2]<<8|self.bytes[-1];self.cmds.append((c,cmd))
                if cmd in FIGHT:self.fighting=True;self.queue=[];self.ground=None
                elif cmd==LOSE:self.fighting=False;self.coins=[(c+2*versus.TMS_HZ+d,p,v) for d,p,v in COIN_START];self.events.append(('lose',c))
                elif cmd==GAME_OVER:self.events.append(('game_over',c))
        out={}
        while self.coins and self.coins[0][0]<=c:_,p,v=self.coins.pop(0);out[p]=v
        h1,h2,x1,x2,y1,y2=w[:6]
        if self.last:self.taken+=max(0,self.last[0]-h1);self.dealt+=max(0,self.last[1]-h2)
        self.last=(h1,h2)
        if not self.fighting:return {**out,0:0xffff,1:0xffff}
        if self.ground is None:self.ground=y2
        dx=(x2-x1+0x8000&0xffff)-0x8000
        if not self.queue:
            for in0,in1,n in self.plan(dx,abs(((y2-self.ground+0x8000)&0xffff)-0x8000),abs(dx)):self.queue+=[(in0,in1)]*n
        in0,in1=self.queue.pop(0);return {**out,0:0xffff^in0,1:0xffff^in1}


BOT_STYLE=dict(d_near=55,d_mid=120,air=dict(upper=1),near=dict(upper=1,sweep=1,throw=1,jab=1,low=1,block=1),
               mid=dict(jump=1,walk=1,cblock=1,rh=1),far=dict(walk=4,run=4,jump=4,block=1))   # the K3 first bot (lost fight 3 x 192)


def coin_start(c):
    """One credit (two COIN1 pulses) and Start P1: the continue."""
    return [(c,3,0xfffe),(c+625000,3,0xffff),(c+3125000,3,0xfffe),(c+3750000,3,0xffff),(c+6250000,3,0xfffb),(c+6875000,3,0xffff)]


def tape_of(spec):
    """Prelude, the won fights (each candidate cut at the next Round 1), then the optional tail: candidate inputs of
    tail['seed']+k over each of tail['spans'] [from, to) and a continue (coin_start) at each of tail['continues']."""
    rows=list(prelude(spec.get('p1'),spec['tower'],menu=spec.get('menu',False)))
    for f in spec['fights']:rows+=fight_rows(f)
    t=spec.get('tail')
    if t:
        for k,(lo,hi) in enumerate(t['spans']):rows+=p1_rows(t['seed']+k,lo,hi)
        for c in t['continues']:rows+=coin_start(c)
    return tuple(sorted(rows))


def plan(native,spec,candidates=12,rounds=4,log=print,until=None):
    """Extends spec['fights'] (each {seed, fight, cut}) fight by fight: the round start after the last cut, then candidate
    seeds (copies of an exploration snapshot at round start + 1 frame, replay.Explorer) until one is followed by the next
    "Round 1"; that Round 1 cycle is the cut. Stops at the first fight no candidate wins (spec['lost'] with the seeds
    tried) or when the tower is done."""
    from tools.mk3.replay import Explorer
    spec=dict(spec,fights=list(spec.get('fights',())));n=TOWERS[spec['tower']][1];T=versus.TMS_HZ
    start=lambda:spec['fights'][-1]['cut'] if spec['fights'] else TOWER_SCREEN+(MENU_SHIFT if spec.get('menu') else 0)
    with Explorer(native,tape_of(spec),start()) as ex:
        pending=()
        while len(spec['fights'])<min(n,until or n):
            after=start();o=ex.run([dict(tape=pending,horizon=after+40*T)])[0]
            fight=next((c for c,v in commands(o) if v in FIGHT and c>after),None)
            if spec['fights'] and not any((after,r) in commands(o) for r in ROUND1):raise ValueError(f'{spec["name"]}: the cut tape does not reproduce Round 1 at {after}')
            if fight is None:spec['lost']=dict(fight=len(spec['fights']),reason='no round start after the last cut',frontier=o['summary']['frontier']);break
            ex.run([dict(tape=pending,horizon=fight+FRAME,keep=True)]);ex.adopt(0);pending=()
            end=fight+FIGHT_SECONDS*T;won=None;tried=[]
            for r in range(rounds):
                seeds=[spec['seed']*1000+len(spec['fights'])*100+r*candidates+k for k in range(candidates)]
                xs=ex.run([dict(tape=p1_rows(s,fight+FRAME,end),horizon=end) for s in seeds])
                res=[(s,next((c for c,v in commands(x) if v in ROUND1 and c>fight),None),x['summary']['frontier']) for s,x in zip(seeds,xs)]
                tried+=[dict(seed=s,next_round1=c,frontier=f) for s,c,f in res]
                stops=[t for t in tried if t['frontier']!='none']
                if stops:spec['stops']=stops
                won=next((x for x in res if x[1] is not None and x[2]=='none'),None)
                if won:break
            if not won:spec['lost']=dict(fight=len(spec['fights']),fight_cycle=fight,tried=len(tried));break
            spec['fights'].append(dict(seed=won[0],fight=fight,cut=won[1]));pending=tuple(p1_rows(won[0],fight+FRAME,won[1]))
            log(f"{spec['name']}: fight {len(spec['fights'])}/{n} won, seed {won[0]}, cut {won[1]}")
    return spec


def route_specs(path=SPECS):
    """explore.py ROUTE_SPECS entries of the planned tower routes (tools/mk3/r2_routes.json)."""
    if not path.is_file():return {}
    out={}
    for s in json.loads(path.read_text('utf-8'))['routes']:
        tape=tape_of(s)
        k=next(i for i,e in enumerate(tape) if e[0]>TOWER_SCREEN+(MENU_SHIFT if s.get('menu') else 0) and e[1] in (0,1))   # first row after the tower screen opens
        if 'drop' in s:k=tape.index(tuple(s['drop']))   # K9 A: chunked fights start with no-op rows; the spec names a lone press
        out[s['name']]=dict(tape=tape,horizon=s['horizon'],criterion=s['criterion'],mutation=(0x30000,1,160000000),
                            input_negative=dict(native=tape[:k]+tape[k+1:],reference=tape),
                            wave=dict(family='R2',tower=s['tower'],p1=s.get('p1'),fights=len(s['fights']),ladder=s.get('ladder'),
                                      opponents=s.get('opponents'),result=s.get('result'),**({'difficulty':'1 VERY EASY (operator menu, CMOS 0x1408380)'} if s.get('menu') else {})))
    return out


LOSE,GAME_OVER=0x38,0x21   # first DCS commands after a lost match (continue screen) and the game over, in native probes


def plan_tail(native,spec,seed):
    """After the last won fight: lose the next fight with candidate inputs, continue (coin_start 2 s after the lose
    command), lose the rematch, and end 40 s after the game over. Each cycle is read from a native run of the tape so far."""
    T=versus.TMS_HZ;f=spec['lost']['fight_cycle'];t=dict(seed=seed,spans=[[f+FRAME,f+70*T]],continues=[])
    spec=dict(spec,tail=t)
    def cmds(h):o=native.run(0,0,0,h,tape_of(spec),events=True);return commands(o),o['summary']['frontier']
    cs,fr=cmds(f+90*T);lose=next(c for c,v in cs if v==LOSE and c>f)
    t['continues']=[lose+2*T];cs,fr=cmds(lose+100*T)
    r1=next(c for c,v in cs if v in ROUND1 and c>lose);rematch=next(c for c,v in cs if v in FIGHT and c>r1)
    t['spans'].append([rematch+FRAME,rematch+70*T]);cs,fr=cmds(rematch+120*T)
    lose2=next(c for c,v in cs if v==LOSE and c>rematch);over=next(c for c,v in cs if v==GAME_OVER and c>lose2)
    spec.update(horizon=over+40*T,frontier=fr,result=dict(lose=lose,continue_round1=r1,rematch=rematch,lose2=lose2,game_over=over))
    return spec
