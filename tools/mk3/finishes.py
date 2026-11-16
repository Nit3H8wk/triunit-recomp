"""K5 front B (R1, plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md): finishing moves from reset.

Facts used (program image rev. 2.1, TMS34010 bit addresses): the finish state word STATE (== FINISH when a finishing
entry may run), the kind table KIND_TABLE of the list walker (tools/mk3/specials.py entries), the stage condition
STAGE_CONDITION and the action routines of CLASSES, keyed by kind: kind2 (two actions), kind3, kind45 (kinds 4 and 5),
stage, kind6, kind7. Button tokens (< 6): HP 0, LP 1, BL 2, HK 3, LK 4, RUN 5; stick tokens 6 up, 7 down, 8 left, 9
right; sequences are newest first. The evidence prose of rounds K5-K7 (readers, conditions, game rules) was removed for
publication (plan 2026-11-15-conformidade-legal.md, 5.1); the addresses are the facts the specs need.
The match is won by a native search over legal P1 macros (tools/mk3/tower.chunk_rows on copies of an exploration
snapshot, replay.Explorer: search only) until STATE == 3; P1 is released at the cut, then walks and taps the entry's
tokens. Success is the first execution of the action routine after the cut (native Profile::Game), then the whole route
from reset is compared with the Original (explore.run_route).

Usage: python tools/mk3/finishes.py capture --names r1fin00 ...   # explore.run_route + write_receipt (4 MB)
"""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import specials,tower,versus

ROOT=Path(__file__).resolve().parents[2]
SPECS=ROOT/'tools/mk3/r1_finishes.json'
FRAME=versus.FRAME
STATE,MERCY,ARENA=0x1062250,0x1062AE0,0x1062210
KIND_TABLE,FINISH=0xff992160,3
STAGE_CONDITION=0xff992670
CLASSES={0xff998750:'kind2',0xff9987e0:'kind2',0xff9ba8c0:'stage',0xff993c10:'kind3',0xff9be6a0:'kind45',0xff9ccce0:'kind6',0xff97f390:'kind7'}
BUTTON_TOKEN=dict(zip(range(6),specials.BUTTONS))
LIMIT=4_000_000
TAP=6   # frames per token: 3 down, 3 up (a token repeated after a 1-frame release is not recorded: native history dumps)


def side_bits(side,token):
    """(port, active mask) of a token for the side: stick 6-9 on IN0, a button by BUTTON_BITS."""
    shift=8 if side=='p2' else 0
    if token in specials.TOKEN_STICK:return 0,specials.TOKEN_STICK[token]<<shift
    port,bit=specials.BUTTON_BITS[BUTTON_TOKEN[token]];return port,bit<<(shift if port==0 else (4 if side=='p2' else 0))


def attempt_rows(entry,side,variant,at,walk=0,direction='left',hold=12,tap=TAP,gap=None):
    """Legal taps for one entry from `at`: walk `walk` frames toward `direction`, then (release table) the button pressed
    and held `hold` frames, the tokens oldest first (each 3 frames down, 3 up), the trigger: press table its button for
    4 frames unless the newest token is that button; release table the release. gap: frames from the previous token's
    press to the newest one's (K6: the check 0xff9825b0 wants *(*A13(290h))(210h) & 0x1C == 0, nonzero while the move
    of an earlier button token runs). Returns (rows, trigger cycle)."""
    rows=[];c=at;shift=8 if side=='p2' else 0;seq=entry['seq'][variant]
    if walk:rows+=[(c,0,0xffff^(versus.STICK[direction]<<shift)),(c+walk*FRAME,0,0xffff)];c+=(walk+2)*FRAME
    port,bit=specials.BUTTON_BITS[entry['button']];bit=bit<<(shift if port==0 else (4 if side=='p2' else 0))
    held={0:0,1:0}
    if entry['table']=='release':held[port]=bit;rows.append((c,port,0xffff^bit));c+=max(hold-tap*len(seq),1)*FRAME
    for i,tok in enumerate(reversed(seq)):
        if gap and i==len(seq)-1:c+=(gap-tap)*FRAME
        p,b=side_bits(side,tok);rows+=[(c,p,0xffff^(b|held[p])),(c+3*FRAME,p,0xffff^held[p])];c+=tap*FRAME
    if entry['table']=='release':rows.append((c,port,0xffff));return rows,c
    if seq and seq[0]<6 and BUTTON_TOKEN[seq[0]]==entry['button']:return rows,c-tap*FRAME
    rows+=[(c,port,0xffff^bit),(c+4*FRAME,port,0xffff)];return rows,c


def side_rows(rows,side):
    """P1 macro rows (tower.chunk_rows) moved to the side's own bits: P2 stick and IN0 buttons << 8, IN1 buttons << 4."""
    if side=='p1':return rows
    move=lambda p,x:(((x&0x7f)<<8) if p==0 else (x&0x7)<<4)
    return [(c,p,0xffff^move(p,0xffff^v)) for c,p,v in rows]


def held(rows,port,mask,start,end):
    """rows with the active-low `mask` also held on `port` in [start, end): the port's own rows there keep their other bits."""
    mine=sorted(r for r in rows if r[1]==port)
    level=lambda c:next((v for x,_,v in reversed(mine) if x<=c),0xffff)
    out=[r for r in rows if not(r[1]==port and start<=r[0]<end)]
    out+=[(start,port,level(start)&~mask)]+[(c,p,v&~mask) for c,p,v in mine if start<c<end]
    if not any(r[0]==end for r in mine):out.append((end,port,level(end)))
    return out


def chunk_tape(spec):
    """versus_tape of the pair, the KO chunks (tower.chunk_rows, macros spec['macros'], on the chunk's side) cut at
    spec['cut'] (or the chunk's own 'cut': a KO before an earlier attempt, e.g. a kind-3 entry before a kind-4/5 one), both ports
    released at every cut. spec['tower']: a 1P tower route of tools/mk3/r2_routes.json instead, its fights up to
    spec['fight'] with P1 released at spec['cut'] (the deciding KO) in the last one. spec['chain']: a chained versus
    route of tools/mk3/r1_routes.json (versus.chain_tape, its fields overridden by spec['chain_fields']) cut at
    spec['cut'], both ports released there (the later matches' arenas 0xA and 0: the first versus arena is never 0/0xA)."""
    if 'rows' in spec:   # K9: a whole tape set by a closed-loop native bot (tower.bot_run; search only), "cycle port value ..." in one string
        v=list(map(int,spec['rows'].split()));return list(zip(v[0::3],v[1::3],v[2::3]))
    if 'secret' in spec:   # K8: a tools/mk3/secrets.py route tape (e.g. r5x05), every row moved by spec['secret_shift']
        from tools.mk3 import secrets
        rows=[(c+spec.get('secret_shift',0),p,v) for c,p,v in secrets.route_specs()[spec['secret']]['tape']]
        if 'fight_of' in spec:   # K9: plus the fight rows (from its round start) of a tools/mk3/r1_routes.json versus route
            r=next(x for x in json.loads(versus.SPECS.read_text('utf-8'))['routes'] if x['name']==spec['fight_of']);rows+=[x for x in versus.route_tape(r)['tape'] if x[0]>=r['fight']]
        return rows
    if 'chain' in spec:
        r=next(x for x in json.loads(versus.SPECS.read_text('utf-8'))['routes'] if x['name']==spec['chain'])
        rows=[x for x in versus.chain_tape(dict(r,**spec.get('chain_fields',{})))['tape'] if x[0]<spec['cut']]
        return rows+[(spec['cut'],p,0xffff) for p in (0,1)]
    if 'tower' in spec:
        r=next(x for x in json.loads(tower.SPECS.read_text('utf-8'))['routes'] if x['name']==spec['tower']);n=spec['fight']
        return list(tower.tape_of(dict(r,fights=r['fights'][:n-1]+[dict(r['fights'][n-1],cut=spec['cut'])],tail=None)))
    rows=list(versus.versus_tape(spec['p1'],spec['p2'],spec['shift'])['tape'])
    for ch in spec['chunks']:rows+=[r for r in side_rows(tower.chunk_rows(ch['seed'],ch['start'],ch['end'],spec.get('macros')),ch.get('side','p1')) if r[0]<ch.get('cut',spec['cut'])]
    return rows+[(c,p,0xffff) for c in sorted({ch.get('cut',spec['cut']) for ch in spec['chunks']}) for p in (0,1)]


def tape_of(spec):
    byentry={e['entry']:e for e in specials.entries()};rows=chunk_tape(spec)
    for a in spec.get('attempts',()):rows+=attempt_rows(a if 'seq' in a else byentry[a['entry']],a['side'],a['variant'],a['at'],a.get('walk',0),a.get('direction','left'),a.get('hold',12),a.get('tap',TAP),a.get('gap'))[0]
    out={}
    for r in rows:out[(r[0],r[1])]=r   # one row per (cycle, port): the last one set at that cycle
    rows=list(out.values())
    for t in spec.get('taps',()):   # K8: a button or stick held into the tape (`held`) for `hold` frames every `every` frames
        c=t['from']
        while c<t['to']:rows=held(rows,t['port'],t['mask'],c,c+t['hold']*FRAME);c+=t['every']*FRAME
    return tuple(sorted(rows))


BOT_WORDS=(0x1060A40,0x10615F0,f'{0x10609B0}:{0x90}',f'{0x1061560}:{0x90}',0x1060980,0x1061530,0x10622A0,0x10622B0)   # health, x, state, streak
BOT_NEAR=0x60


class VersusBot:
    """K9 closed-loop versus chain for tower.bot_run (reads only): from each round start the match's attacker (spec['plan'])
    walks toward the other side and, within BOT_NEAR, alternates toward+HP / toward+HK every 8 frames until the
    defender's health word is 0; the other side is idle. Match end: the loser's state word 1 -> 2 (FF80F480); the loser
    buys back in (versus.join_rows) join_delay after its streak word reads 0 (a broken streak first runs FFAB1710)."""
    def __init__(s,spec):
        s.plan,s.join_delay,s.select_after=spec['plan'],spec['join_delay'],spec['select_after']
        s.bytes=[];s.fighting=s.release=False;s.match=s.k=s.t=0;s.queue=[];s.prev={};s.pending=None;s.events=[]
    def __call__(s,c,w,dcs):
        h1,h2,x1,x2,s1,s2,k1,k2=w;v=dict(h1=h1,h2=h2,s1=s1,s2=s2,k1=k1,k2=k2)
        for b in dcs:
            s.bytes.append(b)
            if len(s.bytes)%2==0 and (s.bytes[-2]<<8|s.bytes[-1]) in versus.FIGHT_SOUND and s.match<len(s.plan):s.fighting=True;s.t=c;s.events.append((c,'fight',s.match))
        if s.fighting and c-s.t>FRAME and v['h2' if s.plan[s.match]=='p1' else 'h1']==0:s.fighting=False;s.release=True;s.events.append((c,'ko',s.match))
        if s.match<len(s.plan):
            loser='p2' if s.plan[s.match]=='p1' else 'p1';k='s'+loser[1]
            if v[k]==2 and s.prev.get(k)==1:s.match+=1;s.fighting=False;s.release=True;s.pending=loser;s.events.append((c,'end',s.match-1))
        if s.pending and v['k'+s.pending[1]]==0:s.queue+=list(versus.join_rows(c+s.join_delay,s.pending,s.select_after));s.events.append((c,'join',s.pending));s.pending=None
        s.prev=dict(s1=s1,s2=s2);out={}
        while s.queue and min(s.queue)[0]<=c:r=min(s.queue);s.queue.remove(r);out[r[1]]=r[2]
        if s.release:s.release=False;out.setdefault(0,0xffff);out.setdefault(1,0xffff)
        if not s.fighting:return out
        att=s.plan[s.match];sh=0 if att=='p1' else 8;xa,xd=(x1,x2) if att=='p1' else (x2,x1)
        dx=((xd-xa+0x8000)&0xffff)-0x8000;toward=(8 if dx>0 else 4)<<sh;hp,hk=(0x10<<sh,0x40<<sh)
        if c-s.t<FRAME:val=0
        elif abs(dx)<=BOT_NEAR:s.k+=1;val=toward|(hp if (s.k//8)%2==0 else hk)
        else:val=toward
        out[0]=0xffff^val;out[1]=0xffff;return out


def bot_tape(native,spec):
    """The whole legal tape of a VersusBot run from reset (versus_tape prefix of p1/p2/shift; search only) and its events."""
    b=VersusBot(spec);r=tower.bot_run(native,versus.versus_tape(spec['p1'],spec['p2'],spec['shift'])['tape'],spec['bot_horizon'],BOT_WORDS,b)
    return r['tape'],b.events


def route_specs(path=SPECS):
    """explore.py ROUTE_SPECS entries; input negative: the native tape without the last attempt's trigger row (a route
    without attempts, K8: without its row at spec['drop'] = [cycle, port], the first press of its residue condition)."""
    if not path.is_file():return {}
    out={};byentry={e['entry']:e for e in specials.entries()}
    for s in json.loads(path.read_text('utf-8'))['routes']:
        if 'bot' in s and not ('rows' in s and s.get('drop')):continue   # a bot route before its tape (`finishes.py bot`) and drop row are stored
        tape=tape_of(s)
        if 'attempts' not in s:
            drop=next(r for r in tape if list(r[:2])==s['drop'])
            out[s['name']]=dict(tape=tape,horizon=s['horizon'],mutation=(0x30000,1,versus.CURSOR_FROM+s['shift']),
                                input_negative=dict(native=tuple(r for r in tape if r!=drop),reference=tape),criterion=s['criterion'],
                                wave=dict(family='R1',kind='route',residue=s['residue'],base=s.get('secret') or s.get('chain') or s.get('base')))
            continue
        a=s['attempts'][-1];e=a if 'seq' in a else byentry[a['entry']]   # K8: a hand-coded handler's own table (seq, button, table)
        rows,trigger=attempt_rows(e,a['side'],a['variant'],a['at'],a.get('walk',0),a.get('direction','left'),a.get('hold',12),a.get('tap',TAP),a.get('gap'))
        drop=next(r for r in rows if r[0]==trigger)
        out[s['name']]=dict(tape=tape,horizon=s['horizon'],mutation=(0x30000,1,versus.CURSOR_FROM+s['shift']),
                            input_negative=dict(native=tuple(r for r in tape if r!=drop),reference=tape),criterion=s['criterion'],
                            wave=dict(family='R1',kind='finishes',p1=s['p1'],p2=s['p2'],classes=[x['class'] for x in s['attempts']],
                                      attempts=[{k:x[k] for k in ('entry','side','button','table','kind','variant','at','walk','class')} for x in s['attempts']]))
    return out


def capture(names,processes=2,original_processes=2,audit=4):
    """Receipts for `names` by explore.run_route (the K1-K4 acceptance), written under the 4 MB ceiling."""
    from concurrent.futures import ThreadPoolExecutor
    from tools.mk3 import explore,replay
    explore.ROUTE_SPECS.update(route_specs())
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


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode',choices=('capture','bot'));ap.add_argument('--names',nargs='+',required=True);ap.add_argument('--report',type=Path)
    a=ap.parse_args()
    if a.mode=='bot':   # regenerate spec['bot'] tapes natively: store them as spec['rows'] if absent, else compare
        from tools.mk3 import replay
        d=json.loads(SPECS.read_text('utf-8'));out={}
        with replay.Native(profile='game') as built:
            for s in d['routes']:
                if s['name'] not in a.names:continue
                tape,events=bot_tape(built,s['bot']);rows=' '.join(f'{c} {p} {v}' for c,p,v in tape)
                out[s['name']]=dict(rows=len(tape),stored_equal=s.get('rows',rows)==rows,events=events)
                s.setdefault('rows',rows)
        SPECS.write_text(json.dumps(d,indent=1,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n');out['native_cleanup']=built.cleanup
    else:out=capture(a.names)
    text=json.dumps(out,indent=1)
    if a.report:a.report.write_text(text+'\n',encoding='utf-8')
    print(text[:8000]);return 0


if __name__=='__main__':raise SystemExit(main())
