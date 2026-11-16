"""MK3 wave engine (K1, plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md, changes 1, 2, 3 and 5).

Exploration (native only, never acceptance): legal input tapes from reset generated from a recorded seed (the
tools/mk3/replay.py tape format and limits), run by N native processes of ONE build of the replay executor in
Profile::Game; of each tape only its first-execution set (mk3::FirstExecution keys) and its stop are kept. A greedy cover
picks the fewest tapes that add the most new keys; native stops are grouped by cause (message + PC), each with the
shortest tape that reproduces it. What only ran natively is "explored natively, not yet compared".

Routes (acceptance): replay.route from reset with the event streams, compared with the Original (pinned MAME) at every
checkpoint, whole regions at END, whole dcs/input/cmos streams and per-record digests of all four streams; localized
negative controls; sampled fine bus windows. The compact receipt (build/native/mk3-m2/routes/<name>.json, 1 MB in
total for the directory) keeps the identities, the integral result and its date, a digest chained every 64 checkpoints,
the counters, the first-execution set and the event streams. Regression mode checks a native run against that digest
in seconds, without the Original: it is NOT a new integral comparison (integral.at changes only when the Original is
recaptured), and a changed Original-side identity (core, program, seed, tape, observer) requires a recapture.

Usage:
  python tools/mk3/explore.py pilot --tapes 48 --processes 12 --seconds 90 --seed 1 --report OUT.json
  python tools/mk3/explore.py routes [--names attract fight match] [--original-processes 3] [--audit 4]
  python tools/mk3/explore.py regress [--names ...]          # digest only, native only
  python tools/mk3/explore.py verified                        # tools/mk3/route_verified.json from passing receipts
  python tools/mk3/explore.py measure --report OUT.json        # parallel throughput, native and Original
  python tools/mk3/explore.py rename                          # local receipts under ids renamed on 16/11/2026
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,base64,copy,datetime,hashlib,json,random,re,sys,threading,time,zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,replay,replay_reference,replay_state,roms,specials,tower,versus

ROOT=Path(__file__).resolve().parents[2]
ROUTES=ROOT/'build/native/mk3-m2/routes'
ROUTES_LIMIT=4_000_000                 # bytes for every receipt of ROUTES together (user decision of 11/11/2026: 4 MB)
VERIFIED=ROOT/'tools/mk3/route_verified.json'
KINDS=('TmsBlock','TmsEdge','AdspBlock','AdspEdge','DmaPath','IrqPath','DevicePath')   # mk3::Unverified order
CHAIN=64
TMS_HZ=6250000
FRAME=TMS_HZ//60
FIGHT_TAPE=tuple(replay.read_tape(ROOT/'tools/mk3/fight_route.tape'))
# The three routes of J2/J3 (horizons and expected ends: build/native/mk3-m2/j2-attract.json, j3-fight.json).
ROUTE_SPECS={
 'attract':dict(tape=(),horizon=1476055509,criterion='second DCS 0x0451 (first command of each demo round), low byte at 1,476,055,509',
                mutation=(0x30000,1,80000000),input_negative=dict(native=((20000000,1,0xfffe),(20300000,1,0xffff)),reference=())),
 'fight':dict(tape=FIGHT_TAPE,horizon=283339366,criterion='DCS 0x233D (round start), low byte at 283,339,365',
              mutation=(0x30000,1,160000000),input_negative=dict(native=FIGHT_TAPE[:6],reference=FIGHT_TAPE)),
 'match':dict(tape=FIGHT_TAPE,horizon=635092423,criterion='DCS 0x0021 (game over, 0xff8109e0), low byte at 635,092,422',
              mutation=(0x30000,1,400000000),input_negative=dict(native=FIGHT_TAPE+((400000000,1,0xfffe),(400625000,1,0xffff)),reference=FIGHT_TAPE)),
}
ROUTE_SPECS.update(versus.route_specs())   # K2 (R1): 2-player versus routes of tools/mk3/r1_routes.json
R3_SPECS=ROOT/'tools/mk3/r3_routes.json'

# Legal inputs, INPUT_PORTS(mk3) (docs/investigation/sources/midwunit.cpp:136-232), active low. 8-way sticks: never two
# opposite directions. Operator switches (test, service, tilt, door, volume, bill) are left for the R4 wave.
STICK=dict(up=1,down=2,left=4,right=8)
DIRECTIONS=(0,1,2,4,8,1|4,1|8,2|4,2|8)
P1=dict(in0_buttons=(0x10,0x20,0x40),in1_buttons=(0x1,0x2,0x4),shift=0)    # HP Block HK / LP LK Run
P2=dict(in0_buttons=(0x1000,0x2000,0x4000),in1_buttons=(0x10,0x20,0x40),shift=8)
COIN1,START1,START2=0x1,0x4,0x20
MAX_EVENTS=512


def tape_text(tape):return ''.join(f'{c} {p} {v}\n' for c,p,v in tape)
def tape_sha(tape):return hashlib.sha256(tape_text(tape).encode('ascii')).hexdigest()


def random_tape(seed,horizon,two_players=None):
    """A legal tape from reset: the J3 prelude (2 coins, Start P1, a select press; 2P: 2 more coins and Start P2), then
    random stick/button states held 2-30 frames for each playing side, until the horizon or MAX_EVENTS."""
    rng=random.Random(seed)
    two=rng.random()<0.5 if two_players is None else two_players
    rows=list(FIGHT_TAPE[:6])
    if two:rows+=[(137500000,3,0xffff^COIN1),(138125000,3,0xffff),(140625000,3,0xffff^COIN1),(141250000,3,0xffff),
                  (150000000,3,0xffff^START2),(150625000,3,0xffff)]
    rows+=[FIGHT_TAPE[6],FIGHT_TAPE[7]] if rng.random()<0.5 else [(187500000,0,0xffff^rng.choice(P1['in0_buttons'])),(188125000,0,0xffff)]
    rows.sort()
    c=200000000+rng.randrange(0,30*FRAME);state={0:0xffff,1:0xffff}
    while c<horizon:
        in0=in1=0
        for side in ((P1,P2) if two else (P1,)):
            in0|=rng.choice(DIRECTIONS)<<side['shift']
            for b in side['in0_buttons']:in0|=b if rng.random()<0.15 else 0
            for b in side['in1_buttons']:in1|=b if rng.random()<0.15 else 0
        for port,value in ((0,0xffff^in0),(1,0xffff^in1)):
            if value!=state[port]:
                if len(rows)>=MAX_EVENTS:return dict(seed=seed,two_players=two,tape=tuple(rows))
                rows.append((c,port,value));state[port]=value
        c+=rng.randint(2,30)*FRAME
    return dict(seed=seed,two_players=two,tape=tuple(rows))


SESSION_EVENTS=2000
JOIN_EVERY=20*TMS_HZ   # mean cycles between coin-ins of a random session


def random_session(seed,horizon,max_events=SESSION_EVENTS):
    """R3 legal tape from reset: the J3 prelude (2 coins, Start P1), then random stick/button states of BOTH sides held
    2-30 frames (only the playing sides read them), and every ~JOIN_EVERY cycles on average a coin-in burst (two COIN1
    pulses, then Start of a random side): continues, the 2P challenger and the select screen again."""
    rng=random.Random(seed);rows=list(FIGHT_TAPE[:6]);state={0:0xffff,1:0xffff}
    c=170000000+rng.randrange(0,30*FRAME);join=c+int(rng.expovariate(1/JOIN_EVERY))
    while c<horizon and len(rows)<max_events-8:
        in0=in1=0
        for side in (P1,P2):
            in0|=rng.choice(DIRECTIONS)<<side['shift']
            for b in side['in0_buttons']:in0|=b if rng.random()<0.15 else 0
            for b in side['in1_buttons']:in1|=b if rng.random()<0.15 else 0
        for port,value in ((0,0xffff^in0),(1,0xffff^in1)):
            if value!=state[port]:rows.append((c,port,value));state[port]=value
        h=rng.randint(2,30)*FRAME
        if join<c+h-3750000:   # the burst fits before the next stick change: 2 coins and a Start, 0.1 s pulses
            j=max(join,c+FRAME);start=rng.choice((START1,START2))
            rows+=[(j,3,0xffff^COIN1),(j+625000,3,0xffff),(j+1250000,3,0xffff^COIN1),(j+1875000,3,0xffff),(j+2500000,3,0xffff^start),(j+3125000,3,0xffff)]
            join=c+h+int(rng.expovariate(1/JOIN_EVERY))
        c+=h
    return dict(seed=seed,two_players=None,tape=tuple(sorted(rows)))


def r3_specs(path=R3_SPECS):
    """ROUTE_SPECS entries of the R3 routes (tools/mk3/r3_routes.json): random_session(seed, generated horizon) cut at
    the route horizon; the negatives flip a RAM bit at 160,000,000 and drop the first stick/button row (native only)."""
    if not path.is_file():return {}
    out={}
    for r in json.loads(path.read_text('utf-8'))['routes']:
        tape=tuple(e for e in random_session(r['seed'],r['generated_horizon'])['tape'] if e[0]<r['horizon'])
        if tape_sha(tape)!=r['tape_sha256']:raise ValueError(f'{r["name"]}: tape differs from r3_routes.json')
        k=next(i for i,e in enumerate(tape) if e[1] in (0,1) and e[0]>=170000000)
        out[r['name']]=dict(tape=tape,horizon=r['horizon'],criterion=f"R3 random legal session (random_session seed {r['seed']}): "
                            f"{r['horizon']/TMS_HZ:.0f} s from reset, both sides random, coin-in bursts",
                            mutation=(0x30000,1,160000000),input_negative=dict(native=tape[:k]+tape[k+1:],reference=tape),
                            wave=dict(family='R3',seed=r['seed'],pilot=r.get('pilot')))
    return out


def legal(tape):
    """The tape parses back through replay.read_tape and touches only legal bits."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        (Path(d)/'t.tape').write_text(tape_text(tape),encoding='ascii');back=replay.read_tape(Path(d)/'t.tape')
    used={0:0x7f7f,1:0x77,3:COIN1|START1|START2|0x2}
    for c,p,v in back:
        pressed=0xffff^v
        if p not in used or pressed&~used[p]:return False
        if p==0:
            for s in (0,8):
                if (pressed>>s)&3==3 or (pressed>>s)&12==12:return False
    return tuple(back)==tuple(tape)


# ---- first-execution sets ----
def first_set(summary):
    """{kind: sorted [[id, from], ...]} and {kind: {key: first cycle}} from a native summary (spec `first all`)."""
    pairs={k:set() for k in KINDS};cycles={}
    for kind,i,f,c in summary['first_set']:
        pairs[KINDS[kind]].add((i,f));cycles.setdefault((kind,i,f),c)
    return {k:sorted(map(list,v)) for k,v in pairs.items()},cycles


def keys(sets):return {(k,i,f) for k,v in sets.items() for i,f in v}


def pack(rows,width=2):
    """[[id, ...]] of `width` columns (sorted ids or cycles) -> zlib/base64 of the delta-encoded first column and the
    others (lossless)."""
    flat,prev=[],0
    for r in rows:
        assert len(r)==width,r
        flat+=[r[0]-prev,*r[1:]];prev=r[0]
    return base64.b64encode(zlib.compress(json.dumps(flat,separators=(',',':')).encode(),9)).decode()


def unpack(text,width=2):
    flat=json.loads(zlib.decompress(base64.b64decode(text)));out,prev=[],0
    for k in range(0,len(flat),width):prev+=flat[k];out.append([prev,*flat[k+1:k+width]])
    return out


def pairs_sha(pairs):return hashlib.sha256(json.dumps(pairs,separators=(',',':')).encode()).hexdigest()


def greedy(results,base=frozenset()):
    """Greedy cover: repeatedly the tape adding the most first-execution keys new over `base` and the tapes already
    picked (ties: the lower index)."""
    left={k:keys(r['sets'])-base for k,r in enumerate(results) if r.get('sets')}
    covered,order=set(),[]
    while left:
        k=max(left,key=lambda j:(len(left[j]-covered),-j))
        gain=left.pop(k)-covered
        if not gain:break
        covered|=gain;order.append(dict(index=k,seed=results[k]['seed'],new=len(gain),
                                        new_by_kind={n:sum(1 for g in gain if g[0]==n) for n in KINDS}))
    return dict(tapes=order,keys=len(covered),by_kind={n:sum(1 for g in covered if g[0]==n) for n in KINDS})


def stop_cause(frontier):
    """(message, pc) of a native stop: the frontier text up to '; PC', and that PC."""
    if not frontier or frontier=='none':return None
    m=re.search(r'PC (\d+)',frontier)
    return (frontier.split('; PC')[0],int(m.group(1)) if m else None)


def group_stops(results):
    """Native stops grouped by cause (message + PC), each with the tape that reproduces it soonest."""
    groups={}
    for r in results:
        for side in ('frontier','dcs_frontier'):
            cause=stop_cause(r.get(side))
            if cause is None:continue
            g=groups.setdefault((side,)+cause,dict(side=side,message=cause[0],pc=cause[1] and hex(cause[1]),tapes=0,reproducer=None))
            g['tapes']+=1
            if g['reproducer'] is None or r['end_cycle']<g['reproducer']['end_cycle']:
                g['reproducer']=dict(seed=r['seed'],end_cycle=r['end_cycle'],tape=[list(e) for e in r['tape']])
    return sorted(groups.values(),key=lambda g:(-g['tapes'],g['message'],g['pc'] or ''))


class Pool:
    """Process ceilings shared by every thread: native runs and Original captures."""
    def __init__(self,native=12,original=3):self.native,self.original=threading.Semaphore(native),threading.Semaphore(original)


class Original(replay.Original):
    """replay.Original shared by the route threads: one capture per distinct argument set (concurrent requests for the
    same one wait for it), each waiting for an Original slot of the pool."""
    def __init__(self,pool):super().__init__();self.pool=pool;self.lock=threading.Lock();self.pending={}
    def capture(self,*args,**kw):
        key=json.dumps([args,kw],sort_keys=True,default=list)
        with self.lock:
            if key in self.cache:return self.cache[key]
            first=key not in self.pending
            if first:self.pending[key]=threading.Event()
            done=self.pending[key]
        if not first:
            done.wait()
            with self.lock:
                if key in self.cache:return self.cache[key]
            raise RuntimeError('shared Original capture failed')
        try:
            with self.pool.original:out=replay_reference.capture(*args,**kw)
            with self.lock:self.cache[key]=out;self.runs.append(out['wall_seconds'])
            return out
        finally:done.set()


class Native:
    """A replay.Native build shared by threads; each run waits for a native slot of the pool."""
    def __init__(self,native,pool):self.n,self.pool=native,pool
    def run(self,*a,**k):
        with self.pool.native:return self.n.run(*a,**k)
    def __getattr__(self,name):return getattr(self.n,name)


def explore_one(native,item,horizon):
    out=native.run(0,0,0,horizon,item['tape'],first_all=True)
    s=out['summary'];sets,cycles=first_set(s)
    return dict(seed=item['seed'],two_players=item['two_players'],tape=item['tape'],sets=sets,end_cycle=out['records'][-1]['cycle'],
                frontier=s['frontier'],dcs_frontier=s['dcs_frontier'],wall_seconds=out['wall_seconds'],
                peak_working_set_bytes=out['metrics'].get('peak_working_set_bytes'),counts={k:len(v) for k,v in sets.items()})


def verified_keys(path=VERIFIED):
    """The keys of route_verified.json (every route compared with the Original so far)."""
    d=json.loads(path.read_text('utf-8'));return {(k,i,f) for k in KINDS for i,f in d.get(k,())}


def receipt_keys(directory=ROUTES):
    """The keys of every receipt in ROUTES (compared with the Original, listed in route_verified.json or not yet)."""
    out=set()
    for p in directory.glob('*.json'):
        r=json.loads(p.read_text('utf-8'))
        if r.get('passed'):out|={(k,i,f) for k in KINDS for i,f in unpack(r['first_executions'][k]['packed'])}
    return out


def pilot(native,pool,tapes,seconds,seed,processes,make=random_tape,base=frozenset()):
    """Exploration pilot: `tapes` random tapes (seeds seed*100000+k) to `seconds` of game time, `processes` at a time.
    make: the tape generator (random_tape; versus.random_versus for the R1 wave; random_session for R3).
    base: keys already known (verified_keys); the curve and the cover count only keys new over it."""
    horizon=int(seconds*TMS_HZ)
    items=[make(seed*100000+k,horizon) for k in range(tapes)]
    for it in items:assert legal(it['tape']),it['seed']
    t0=time.perf_counter()
    with ThreadPoolExecutor(processes) as ex:results=list(ex.map(lambda it:explore_one(native,it,horizon),items))
    wall=time.perf_counter()-t0
    union,curve,machine=set(base),[],0.0
    for k,r in enumerate(results):   # saturation in tape order (seed order), machine time = summed process wall time
        machine+=r['wall_seconds'];new=keys(r['sets'])-union;union|=new
        curve.append(dict(tape=k,machine_seconds=round(machine,2),new=len(new),new_tms_blocks=sum(1 for n in new if n[0]=='TmsBlock'),
                          union=len(union),union_tms_blocks=sum(1 for n in union if n[0]=='TmsBlock')))
    explored=union-base
    def rate(points):   # new TmsBlock per 600 s of machine time over the given curve points
        secs=sum(results[p['tape']]['wall_seconds'] for p in points)
        return round(600*sum(p['new_tms_blocks'] for p in points)/secs,2) if secs else None
    tenth=max(1,len(curve)//10)
    return dict(tapes=tapes,seconds=seconds,horizon=horizon,seed=seed,processes=processes,wall_seconds=round(wall,2),
                machine_seconds=round(machine,2),aggregate_realtime=round(tapes*seconds/wall,2),
                greedy=greedy(results,base),stops=group_stops(results),curve=curve,base_keys=len(base),
                union={k:pack(sorted([i,f] for n,i,f in union if n==k)) for k in KINDS},
                explored_not_compared={k:sum(1 for n in explored if n[0]==k) for k in KINDS},
                rate_first_tenth=rate(curve[:tenth]),rate_last_tenth=rate(curve[-tenth:]),rate_last_10=rate(curve[-10:]),
                per_tape=[dict(seed=r['seed'],two_players=r['two_players'],events=len(r['tape']),end_cycle=r['end_cycle'],frontier=r['frontier'],
                               wall_seconds=r['wall_seconds'],peak_working_set_bytes=r['peak_working_set_bytes'],counts=r['counts']) for r in results],
                class_note='explored natively, not yet compared with the Original: no count of verified')


# ---- route receipts ----
def canonical(record,fields,masks):
    """The compared content of a native record (replay_state.difference), in a fixed order."""
    a=record['adsp']
    adsp=None if a['frozen'] else [v&m for n,v,m in zip(fields,a['fields'],masks) if n!='totalcycles']
    return [record['spec'],record['cycle'],record['pc'],record['status'],record['registers'],[record['hash'][n] for n in replay_state.REGIONS],
            record['dma'],record['io'],record['control'],adsp,[record['pcm']['segment'],record['pcm']['hash']],
            [record['events'][n] for n in replay_state.STREAMS] if 'events' in record else None]


def chain(records,fields):
    """sha256 chained every CHAIN records: link_k = sha256(link_{k-1} | record digests of block k). Returns the links."""
    masks=replay.masks(fields);link=b'';links=[]
    for k in range(0,len(records),CHAIN):
        h=hashlib.sha256(link)
        for r in records[k:k+CHAIN]:h.update(hashlib.sha256(json.dumps(canonical(r,fields,masks),separators=(',',':')).encode()).digest())
        link=h.digest();links.append(link.hex())
    return links


def observer_sha():
    # Line endings normalized to CRLF (the form the recorded receipts hashed): a fresh clone with LF files keeps the identity.
    crlf=lambda data:data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    return hashlib.sha256(b''.join(crlf((ROOT/'tools/mk3'/n).read_bytes()) for n in ('replay_reference.py','replay_state.py'))).hexdigest()


def original_identities(tape):
    """The identities the Original's result depends on; a change requires a recapture."""
    return dict(core_sha256=q.sha(reference.CORE),program_sha256=roms.verify(ROOT/'roms/mk3')['program_sha256'],seed_sha256=q.sha(reference.SEED),
                tape_sha256=tape_sha(tape),observer_sha256=observer_sha())


def needs_recapture(receipt,current=None):
    """Original-side identities that changed since the integral comparison (empty: the digest stands)."""
    current=current or original_identities(receipt_tape(receipt))
    return sorted(k for k,v in current.items() if receipt['identities'].get(k)!=v)


def compact_stream(events,rows=True):
    """{count, sha256 of the JSON list[, packed [cycle, a, b] rows]} (schema /2; /1 kept the list itself up to 48 KB).
    The input stream (tens of thousands of port reads) keeps only count and sha256, as every /1 receipt did."""
    text=json.dumps(events,separators=(',',':'))
    return dict(count=len(events),sha256=hashlib.sha256(text.encode()).hexdigest(),**({'packed':pack(events,3)} if rows else {}))


def stream_rows(stream):return unpack(stream['packed'],3) if 'packed' in stream else stream.get('events')


def packed_dcs(writes):
    """events.dcs of /2: {count, sha256 of the JSON list, packed [cycle, value] rows} (lossless; the list itself before K3)."""
    return dict(count=len(writes),sha256=hashlib.sha256(json.dumps(writes,separators=(',',':')).encode()).hexdigest(),packed=pack(writes,2))


def dcs_rows(receipt):
    """The whole sound-port write list [[cycle, value], ...] of a receipt (packed or a list)."""
    d=receipt['events']['dcs'];return unpack(d['packed'],2) if isinstance(d,dict) else d


def receipt_tape(receipt):
    t=receipt['tape'];return [tuple(e) for e in (unpack(t['packed'],3) if isinstance(t,dict) else t)]


def packed_tape(tape):return dict(count=len(tape),sha256=tape_sha(tape),packed=pack([list(e) for e in tape],3))


SCHEMA='mk3-route-receipt/2'


def upgrade_receipt(old,raw):
    """Lossless re-encoding of a mk3-route-receipt/1 (K3, 1 MB ceiling): the tape and the cmos list packed;
    everything else (integral result and date, digest chain, first executions, dcs list, negatives, audit) unchanged.
    raw: the /1 file bytes, whose sha256 is recorded. Refuses when a packed field does not unpack to the original."""
    if old.get('schema')!='mk3-route-receipt/1':raise ValueError(f'{old.get("name")}: not a /1 receipt')
    new=copy.deepcopy(old);new['schema']=SCHEMA
    new['tape']=packed_tape([tuple(e) for e in old['tape']]);new['events']['dcs']=packed_dcs(old['events']['dcs'])
    for n in ('input','cmos'):
        s=old['events'][n]
        if 'events' not in s:continue   # /1 kept count and sha256 only (input always; cmos above 48 KB)
        new['events'][n]=compact_stream(s['events'],n=='cmos')
        if new['events'][n]['sha256']!=s['sha256'] or (n=='cmos' and stream_rows(new['events'][n])!=s['events']):raise ValueError(f'{old["name"]}: {n} not lossless')
    if receipt_tape(new)!=[tuple(e) for e in old['tape']] or new['tape']['sha256']!=old['identities']['tape_sha256']:
        raise ValueError(f'{old["name"]}: tape not lossless')
    new['reencoded']=dict(from_schema=old['schema'],from_sha256=hashlib.sha256(raw).hexdigest(),
                          at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                          note='lossless re-encoding of the /1 receipt (tape and cmos list packed); not a new comparison')
    return new


def build_receipt(name,spec,result,nat,identities,executor,negatives,audit,timings):
    fields=nat['fields'];links=chain(nat['records'],fields);sets,_=first_set(nat['summary'])
    ev=nat['events']
    return dict(schema=SCHEMA,name=name,profile='game',criterion=spec['criterion'],horizon=spec['horizon'],
        tape=packed_tape(spec['tape']),identities=identities,executor=executor,
        integral=dict(at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            note='the only integral comparison of this receipt: native and Original (pinned MAME) from reset with this tape',
            checkpoints=result['records'],step_cycles=replay.STEP,end=result['end'],first_difference=result['first_record_difference'],
            end_integral={n:None if d is None else d for n,d in result['end_integral'].items()},
            end_region_sha256={n:hashlib.sha256(nat['dumps'][(n,0)]).hexdigest() for n in replay_state.REGIONS},
            streams=result['streams'],frontier=result['summary']['frontier'],dcs_frontier=result['summary']['dcs_frontier']),
        digest=dict(every=CHAIN,links=[l[:16] for l in links],final=links[-1],
            note='sha256 chain of the native records the integral comparison found equal to the Original; checking it is not a new '
                 'integral comparison'),
        counters={k:len(v) for k,v in sets.items()},
        first_executions={k:dict(count=len(v),sha256=pairs_sha(v),packed=pack(v)) for k,v in sets.items()},
        events=dict(dcs=packed_dcs(ev['events_full']['dcs']),totals=ev['events_total'],input=compact_stream(ev['events_full']['input'],False),
                    cmos=compact_stream(ev['events_full']['cmos']),dma=dict(count=ev['events_total']['dma'][0],fnv=ev['events_total']['dma'][1]),
                    note='dcs: every write to the sound port 0x01680000 [cycle, value] (a command is two writes, high byte then low '
                         'byte); input [cycle, port, value]; cmos [cycle, address, value]; cycle = TMS cycle of the instruction start'),
        negatives=negatives,audit=audit,timings=timings,**{k:spec[k] for k in ('versus','wave') if k in spec},
        passed=passed(result,negatives,audit))


def passed(result,negatives,audit):
    return (result['first_record_difference'] is None and all(v is None for v in (result['end_integral'] or {'x':1}).values())
            and all(v is None for v in (result['streams'] or {'x':1}).values()) and bool(negatives) and all(n.get('detected') for n in negatives.values())
            and (audit is None or audit.get('passed')))


def write_receipt(receipt,directory=ROUTES,limit=ROUTES_LIMIT):
    """Writes <name>.json; refuses when the directory would exceed `limit` bytes in total."""
    text=json.dumps(receipt,separators=(',',':'))+'\n'
    directory.mkdir(parents=True,exist_ok=True);path=directory/f'{receipt["name"]}.json'
    others=sum(p.stat().st_size for p in directory.glob('*.json') if p!=path)
    if others+len(text.encode())>limit:raise ValueError(f'route receipts would take {others+len(text.encode())} bytes (limit {limit})')
    path.write_text(text,encoding='utf-8');return path


def regress(native,receipt):
    """Native run against the receipt digest (seconds, no Original). Not an integral comparison."""
    t0=time.perf_counter();tape=receipt_tape(receipt)
    nat=native.run(replay.STEP,replay.STEP,replay.NEVER,receipt['horizon'],tape,[(r,0) for r in replay_state.REGIONS],events=True,first_all=True)
    links=chain(nat['records'],nat['fields']);want=receipt['digest']
    first=next((k for k,(a,b) in enumerate(zip(links,want['links'])) if a[:16]!=b),None)
    if first is None and len(links)!=len(want['links']):first=min(len(links),len(want['links']))
    regions=[n for n in replay_state.REGIONS if hashlib.sha256(nat['dumps'][(n,0)]).hexdigest()!=receipt['integral']['end_region_sha256'][n]]
    ev=nat['events'];streams=[n for n in replay_state.STREAMS if ev['events_total'][n]!=receipt['events']['totals'][n]]
    if ev['events_full']['dcs']!=dcs_rows(receipt):streams.append('dcs list')
    sets,_=first_set(nat['summary'])
    changed=[k for k in KINDS if pairs_sha(sets[k])!=receipt['first_executions'][k]['sha256']]
    ok=first is None and not regions and not streams and links[-1]==want['final']
    return dict(name=receipt['name'],passed=ok,records=len(nat['records']),first_differing_block=first,
                first_differing_cycles=None if first is None else [nat['records'][min(first*CHAIN,len(nat['records'])-1)]['cycle'],
                                                                  nat['records'][min(first*CHAIN+CHAIN-1,len(nat['records'])-1)]['cycle']],
                end_regions_differing=regions,streams_differing=streams,first_executions_changed=changed,
                recapture_needed=needs_recapture(receipt),integral_comparison_at=receipt['integral']['at'],seconds=round(time.perf_counter()-t0,2),
                note='digest check of the native run only; not a new integral comparison with the Original')


# ---- negatives, event-stream negative, sampled fine windows ----
def located(r):
    b=r.get('bisection') or {};return b.get('first_difference') or {},b.get('instruction') or {},b.get('window') or {},len(b.get('rounds',()))


NEGATIVE_SPAN=40000000   # negatives end 40M cycles (6.4 s) after their event: localization needs no more of the route


def negatives_for(native,original,name,spec):
    out={};tape=spec['tape']
    word,mask,m=spec['mutation'];end=min(spec['horizon'],m+NEGATIVE_SPAN)
    expect=native.run(m,1,m,m,tape)['records'][0]
    t=time.perf_counter();r,_,_=replay.route(native,original,tape,[spec['mutation']],horizon=end,events=True)
    d,i,w,rounds=located(r)
    out['ram_bit']=dict(detected=d.get('region')=='ram' and d.get('boundary_cycle')==expect['cycle'] and (w.get('region_bytes') or {}).get('offset')==2*word,
                        mutation=list(spec['mutation']),boundary=d.get('boundary_cycle'),expected_boundary=expect['cycle'],region=d.get('region'),
                        byte=(w.get('region_bytes') or {}).get('offset'),rounds=rounds,seconds=round(time.perf_counter()-t,1))
    neg=spec['input_negative'];nt,rt=tuple(neg['native']),tuple(neg['reference'])
    diff=sorted(set(nt)^set(rt));at=diff[0][0];port=diff[0][1];end=min(spec['horizon'],at+NEGATIVE_SPAN)
    reads=native.run(0,0,0,at+700000,nt if len(nt)>len(rt) else rt,(),(at,at+700000))['window']['reads']
    first_read=next(x for x in reads if 0x01800000<=x[1]<=0x0187fff0 and ((x[1]-0x01800000)>>4)%16%8==port)
    t=time.perf_counter();r,_,_=replay.route(native,original,nt,horizon=end,reference_tape=rt,events=True)
    d,i,w,rounds=located(r)
    out['input_one_tape']=dict(detected=(i.get('cycle'),i.get('pc'))==(first_read[3],first_read[0]),only_on='native' if len(nt)>len(rt) else 'original',
                               event=list(diff[0]),instruction=i,expected_read=first_read,region=d.get('region'),rounds=rounds,seconds=round(time.perf_counter()-t,1))
    return out


def stream_negative(nat,ref):
    """A DCS write shifted by one cycle in a copy of the Original's streams: found at the first record after it (events.dcs,
    cumulative count and hash recomputed from the shifted stream) and at its index in the whole-stream comparison."""
    dcs=ref['events']['events_full']['dcs']
    if not dcs:return dict(detected=False,reason='no DCS write on the route')
    k=len(dcs)//2;cycle,value=dcs[k]
    recs=ref['records'];j=next(x for x,r in enumerate(recs) if r['cycle']>cycle+1)
    h=lambda evs:[len(evs),f'{replay_state.fnv(v for c,val in evs for v in (0x01680000,val,c&0xffffffff,c>>32)):x}']
    before=[e for e in dcs if e[0]<recs[j]['cycle']]
    if h(before)!=recs[j]['events']['dcs']:return dict(detected=False,reason='cumulative hash not reproduced from the stream')
    shifted=[[c+1,v] if i==k else [c,v] for i,(c,v) in enumerate(dcs)]
    changed=dict(ref,records=copy.deepcopy(recs),events=copy.deepcopy(ref['events']))
    changed['records'][j]['events']['dcs']=h([e for e in shifted if e[0]<recs[j]['cycle']]);changed['events']['events_full']['dcs']=shifted
    got=replay.compare_records(nat,changed);whole=replay_state.stream_difference(nat,changed)['dcs']
    return dict(detected=got is not None and got[:2]==(j,'events.dcs') and whole is not None and whole.get('index')==k,
                event=[cycle,value],index=k,record=j,found=got and list(got[:2]),whole=whole and {x:whole.get(x) for x in ('index','native','reference')})


def audit(native,original,tape,end,seed,count,width=20000):
    """Fine bus comparison (replay.window's comparator) of `count` windows of `width` cycles drawn from `seed`."""
    rng=random.Random(seed);spans=sorted((c,c+width) for c in (rng.randrange(2000000,end-width-1) for _ in range(count)))
    hi=spans[-1][1]+1;t=time.perf_counter()
    nat=native.run(0,0,0,hi,tape,windows=spans);ref=original.capture(1000,0,0,hi,tape,windows=tuple(spans))
    rows=[]
    for lo,h in spans:
        inside=lambda xs:[x[1:] for x in xs if lo<=x[3]<=h]
        nw,rw=inside(nat['window']['window']),inside(ref['window']['writes'])
        nr,rr=inside(nat['window']['reads']),inside(ref['window']['reads'])
        row=dict(span=[lo,h],writes=len(nw),reads=len(nr),writes_equal=nw==rw,reads_equal=nr==rr)
        for tag,a,b in (('write',nw,rw),('read',nr,rr)):
            if a!=b:
                k=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
                row[f'first_{tag}_difference']=dict(index=k,native=a[k] if k<len(a) else None,reference=b[k] if k<len(b) else None,
                                                    native_count=len(a),reference_count=len(b))
        rows.append(row)
    return dict(seed=seed,width=width,windows=rows,passed=all(r['writes_equal'] and r['reads_equal'] for r in rows),
                seconds=round(time.perf_counter()-t,1),original_seconds=ref['wall_seconds'])


def run_route(native,pool,name,audit_windows=4,seed=20261110,original=None):
    spec=ROUTE_SPECS[name];original=original or Original(pool);tape=spec['tape']
    t0=time.perf_counter()
    result,nat,ref=replay.route(native,original,tape,horizon=spec['horizon'],events=True)
    t1=time.perf_counter()
    negatives=negatives_for(native,original,name,spec)
    negatives['stream_shift']=stream_negative(nat,ref)
    t2=time.perf_counter()
    au=audit(native,original,tape,result['end']['cycle'],seed+sum(map(ord,name)),audit_windows) if audit_windows else None
    timings=dict(native_route=result['timings']['native'],original_route=ref['wall_seconds'],comparison=result['timings']['compare'],
                 route_total=round(t1-t0,1),negatives=round(t2-t1,1),audit=au and au['seconds'],original_captures=len(original.runs),
                 original_capture_seconds=round(sum(original.runs),1),original_peak_working_set_bytes=ref.get('metrics',{}).get('peak_working_set_bytes'))
    identities=dict(original_identities(tape),core_sha256=ref['core_sha256'],program_sha256=ref['program_sha256'],seed_sha256=ref['seed_sha256'],
                    debugger=ref['debugger'])
    receipt=build_receipt(name,spec,result,nat,identities,native.source_identity,negatives,au,timings)
    return receipt


def verified_text(receipts,receipt_bytes=None):
    """(text, data) of route_verified.json (schema mk3-route-verified/1) from the receipts that passed everything.
    receipt_bytes: {name: bytes} for receipts not yet on disk (default: ROUTES/<name>.json)."""
    ok=[r for r in receipts if r.get('passed')]
    if not ok:raise ValueError('no passing route receipt')
    prog={r['identities']['program_sha256'] for r in ok}
    if len(prog)!=1:raise ValueError('receipts of different programs')
    raw=lambda n:(receipt_bytes or {}).get(n) or (ROUTES/f'{n}.json').read_bytes()
    data=dict(schema='mk3-route-verified/1',program_sha256=prog.pop(),
              routes=[dict(name=r['name'],receipt=f'build/native/mk3-m2/routes/{r["name"]}.json',
                           receipt_sha256=hashlib.sha256(raw(r['name'])).hexdigest()) for r in sorted(ok,key=lambda r:r['name'])])
    for k in KINDS:data[k]=sorted({tuple(p) for r in ok for p in unpack(r['first_executions'][k]['packed'])})
    return '{'+',\n'.join(json.dumps(k)+':'+json.dumps(v,separators=(',',':')) for k,v in data.items())+'}\n',data


def write_verified(receipts,path=VERIFIED):
    text,data=verified_text(receipts);path.write_text(text,encoding='utf-8');return data


def union(receipts):
    """Distinct keys per kind over the routes, the intersection of all, and the keys only one route has."""
    sets={r['name']:{k:{tuple(p) for p in unpack(r['first_executions'][k]['packed'])} for k in KINDS} for r in receipts}
    out={}
    for k in KINDS:
        each=[s[k] for s in sets.values()];u=set().union(*each);i=set(each[0]).intersection(*each[1:]) if each else set()
        out[k]=dict(union=len(u),intersection=len(i),per_route={n:len(s[k]) for n,s in sets.items()},
                    only={n:len(s[k]-set().union(*(t[k] for m,t in sets.items() if m!=n))) for n,s in sets.items()})
    return out


def measure(native,pool,report):
    """Parallel throughput: native N processes on one tape (fight prelude, 50 s); Original N captures (route config, 20 s)."""
    out=dict(native=[],original=[]);H=50*TMS_HZ;item=random_tape(7,H,two_players=False)
    for n in (1,2,4,8,12):
        t=time.perf_counter()
        with ThreadPoolExecutor(n) as ex:runs=list(ex.map(lambda _:native.n.run(0,0,0,H,item['tape']),range(n)))
        wall=time.perf_counter()-t
        out['native'].append(dict(processes=n,wall_seconds=round(wall,2),aggregate_realtime=round(n*50/wall,2),
                                  per_process_realtime=[round(50/r['wall_seconds'],2) for r in runs],
                                  peak_working_set_bytes=max(r['metrics'].get('peak_working_set_bytes',0) for r in runs)))
    E=20*TMS_HZ
    for n in (1,2,4):
        t=time.perf_counter()
        with ThreadPoolExecutor(n) as ex:runs=list(ex.map(lambda _:replay_reference.capture(replay.STEP,replay.STEP,E,E,FIGHT_TAPE,events=True),range(n)))
        wall=time.perf_counter()-t
        out['original'].append(dict(processes=n,wall_seconds=round(wall,2),aggregate_realtime=round(n*20/wall,2),
                                    per_process_realtime=[round(20/r['wall_seconds'],2) for r in runs],
                                    peak_working_set_bytes=max(r['metrics'].get('peak_working_set_bytes',0) for r in runs),
                                    cleanup_ok=all(not r['cleanup'].get('exists_after') for r in runs)))
    return out


def load(name):return json.loads((ROUTES/f'{name}.json').read_text('utf-8'))


ACCEPTANCE_FIELDS=('name','profile','criterion','horizon','identities','executor','integral','digest','counters','first_executions',
                   'negatives','audit','timings','passed','versus')


def lossless(old,new):
    """Field-by-field equality of a /1 receipt and its /2 expansion over what acceptance, regression and route_verified
    use: [] or the differing fields."""
    bad=[k for k in ACCEPTANCE_FIELDS if old.get(k)!=new.get(k)]
    if receipt_tape(new)!=receipt_tape(old):bad.append('tape')
    oe,ne=old['events'],new['events']
    if dcs_rows(old)!=dcs_rows(new) or (isinstance(ne['dcs'],dict) and (ne['dcs']['count'],ne['dcs']['sha256'])!=(len(dcs_rows(old)),hashlib.sha256(json.dumps(dcs_rows(old),separators=(',',':')).encode()).hexdigest())):bad.append('events.dcs')
    for k in ('totals','dma'):
        if oe[k]!=ne[k]:bad.append('events.'+k)
    for k in ('input','cmos'):
        if (oe[k]['count'],oe[k]['sha256'])!=(ne[k]['count'],ne[k]['sha256']) or stream_rows(oe[k])!=stream_rows(ne[k]):bad.append('events.'+k)
    return bad


def compact(names,write,directory=ROUTES,limit=ROUTES_LIMIT,verified=VERIFIED):
    """/1 receipts -> /2 (upgrade_receipt). Every one is converted and proven lossless (lossless) before anything is
    written; route_verified.json regenerated from the /2 receipts must keep exactly its keys and routes (only the
    receipt_sha256 change); the directory must stay within `limit`. Writing: every new file to <name>.tmp first, then
    os.replace one after the other (the receipts, then route_verified.json)."""
    import os
    rows,new,receipts={},{},[]
    for n in names:
        raw=(directory/f'{n}.json').read_bytes();old=json.loads(raw)
        if old.get('schema')==SCHEMA and isinstance(old['events']['dcs'],dict):rows[n]=dict(bytes=len(raw),schema=SCHEMA);receipts.append(old);continue
        r=upgrade_receipt(old,raw) if old.get('schema')!=SCHEMA else dict(old,events=dict(old['events'],dcs=packed_dcs(old['events']['dcs'])),
            reencoded=dict(old.get('reencoded') or {},dcs_from_sha256=hashlib.sha256(raw).hexdigest(),dcs_note='events.dcs list packed (K3); not a new comparison'));text=json.dumps(r,separators=(',',':'))+'\n';back=json.loads(text)
        diff=lossless(old,back)
        if diff:raise ValueError(f'{n}: not lossless: {diff}')
        new[n]=text.encode();receipts.append(back)
        rows[n]=dict(bytes=len(raw),compact_bytes=len(new[n]),from_sha256=hashlib.sha256(raw).hexdigest(),sha256=hashlib.sha256(new[n]).hexdigest(),lossless=True)
    cur=json.loads(verified.read_text('utf-8'));listed={r['name'] for r in cur['routes']}   # route_verified keeps its routes; others are only re-encoded
    vtext,vdata=verified_text([r for r in receipts if r['name'] in listed]+[json.loads((directory/f'{n}.json').read_text('utf-8')) for n in sorted(listed-{r['name'] for r in receipts})],new)
    same=dict(program=cur['program_sha256']==vdata['program_sha256'],routes=[r['name'] for r in cur['routes']]==[r['name'] for r in vdata['routes']],
              **{k:[list(x) for x in vdata[k]]==cur.get(k) for k in KINDS})
    if not all(same.values()):raise ValueError(f'route_verified.json keys would change: {same}')
    after=sum(p.stat().st_size for p in directory.glob('*.json') if p.stem not in new)+sum(len(t) for t in new.values())
    if after>limit:raise ValueError(f'route receipts would take {after} bytes (limit {limit})')
    out=dict(routes=rows,total_after=after,limit=limit,written=write,verified_same_keys=same,
             verified_sha256_before=hashlib.sha256(verified.read_bytes()).hexdigest(),verified_sha256_after=hashlib.sha256(vtext.encode()).hexdigest())
    if write:
        tmp={directory/f'{n}.json':t for n,t in new.items()};tmp[verified]=vtext.encode()
        for p,t in tmp.items():p.with_suffix('.tmp').write_bytes(t)
        for p in tmp:os.replace(p.with_suffix('.tmp'),p)
    return out


def rename_local(directory=ROUTES,verified=VERIFIED):
    """Route ids were renamed to neutral ones on 16/11/2026 (plan 2026-11-15-conformidade-legal.md, 5.1). A local receipt
    under an id that route_verified.json no longer lists is rewritten under the listed id whose receipt_sha256 it then
    matches with only `name` changed (digests, streams and first executions untouched); nothing else is written."""
    listed={r['name']:r['receipt_sha256'] for r in json.loads(verified.read_text('utf-8'))['routes']}
    missing={n:s for n,s in listed.items() if not (directory/f'{n}.json').is_file()};done=[]
    for p in sorted(directory.glob('*.json')):
        if p.stem in listed or not missing:continue
        r=json.loads(p.read_text('utf-8'))
        for n,s in list(missing.items()):
            text=json.dumps(dict(r,name=n),separators=(',',':'))+'\n'
            if hashlib.sha256(text.encode()).hexdigest()==s:
                (directory/f'{n}.json').write_bytes(text.encode());p.unlink();del missing[n];done.append([p.stem,n]);break
    return dict(renamed=done,still_missing=sorted(missing))


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode',choices=('pilot','routes','regress','verified','measure','compact','rename'))
    ap.add_argument('--write',action='store_true',help='compact: rewrite the /1 receipts (default: report the sizes only)')
    ap.add_argument('--names',nargs='*',default=list(ROUTE_SPECS))
    ap.add_argument('--tapes',type=int,default=48);ap.add_argument('--seconds',type=float,default=90);ap.add_argument('--seed',type=int,default=1)
    ap.add_argument('--processes',type=int,default=12);ap.add_argument('--original-processes',type=int,default=3)
    ap.add_argument('--audit',type=int,default=4);ap.add_argument('--report',type=Path)
    ap.add_argument('--wave',choices=('random','versus','session'),default='random',help='pilot tape generator (versus: R1, tools/mk3/versus.py; session: R3)')
    ap.add_argument('--base',choices=('none','verified','receipts'),default='none',help='pilot: count only keys new over route_verified.json (verified) or over every receipt of ROUTES (receipts)')
    a=ap.parse_args()
    if a.mode in ('regress','verified','compact') and a.names==list(ROUTE_SPECS):a.names=[n for n in ROUTE_SPECS if (ROUTES/f'{n}.json').is_file()]   # planned routes without a receipt yet are skipped
    if a.mode=='rename':print(json.dumps(rename_local()));return 0
    if a.mode=='compact':
        out=compact(a.names,a.write);print(json.dumps(out,indent=1));return 0
    if a.mode=='verified':
        data=write_verified([load(n) for n in a.names]);print(json.dumps({k:len(v) if isinstance(v,list) else v for k,v in data.items()},indent=1));return 0
    if a.report and a.report.exists():ap.error('Preserve the existing report; choose another --report')
    pool=Pool(a.processes,a.original_processes);out={}
    with replay.Native(profile='game') as built:
        native=Native(built,pool);out['executor']=built.source_identity;out['build_seconds']=built.build_seconds
        if a.mode=='pilot':
            make=dict(random=random_tape,versus=versus.random_versus,session=random_session)[a.wave]
            out['pilot']=pilot(native,pool,a.tapes,a.seconds,a.seed,a.processes,make,dict(none=lambda:frozenset(),verified=verified_keys,receipts=receipt_keys)[a.base]());out['wave']=a.wave;out['base']=a.base
        elif a.mode=='measure':out['measure']=measure(native,pool,a.report)
        elif a.mode=='regress':
            t=time.perf_counter()
            with ThreadPoolExecutor(len(a.names)) as ex:out['regress']=list(ex.map(lambda n:regress(native,load(n)),a.names))
            out['seconds']=round(time.perf_counter()-t,2)
        else:
            t=time.perf_counter()
            shared=Original(pool)
            def one(n):   # each receipt is written as soon as its route ends; a failing route is reported, the others kept
                try:r=run_route(native,pool,n,a.audit,original=shared);return r,write_receipt(r),None
                except Exception as e:return None,None,dict(name=n,error=repr(e)[:3000])
            with ThreadPoolExecutor(len(a.names)) as ex:done=list(ex.map(one,a.names))
            receipts=[r for r,_,_ in done if r];out['failed']=[f for _,_,f in done if f]
            out['seconds']=round(time.perf_counter()-t,1);out['routes']={}
            for r,path,_ in done:
                if not r:continue
                out['routes'][r['name']]=dict(passed=r['passed'],bytes=path.stat().st_size,checkpoints=r['integral']['checkpoints'],
                                                                     end=r['integral']['end'],streams=r['integral']['streams'],negatives=r['negatives'],
                                                                     audit=r['audit'] and {k:v for k,v in r['audit'].items() if k!='windows'},timings=r['timings'],counters=r['counters'])
            out['union']=union(receipts) if receipts else None
    out['native_cleanup']=built.cleanup
    text=json.dumps(out,indent=1)
    if a.report:a.report.write_text(text+'\n',encoding='utf-8')
    print(text[:6000])
    return 0


ROUTE_SPECS.update(r3_specs())   # K3 (R3)
ROUTE_SPECS.update(specials.route_specs())   # K3 (R1 special moves)
ROUTE_SPECS.update(tower.route_specs())   # K3 (R2)
from tools.mk3 import finishes
ROUTE_SPECS.update(finishes.route_specs())   # K5 (R1 finishing moves, tools/mk3/r1_finishes.json)
ROUTE_SPECS.update(finishes.route_specs(ROOT/'tools/mk3/r1_initials.json'))   # K10 A2 (initials grid, r1fin19)

if __name__=='__main__':raise SystemExit(main())
