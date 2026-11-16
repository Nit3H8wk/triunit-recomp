"""K4 front A, item 1 (plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md, M5 matrix): every route
receipt of build/native/mk3-m2/routes replayed natively from reset with its own tape in mk3::Profile::Strict with the
route-verified keys (spec `profile strict-routes`: lot-verified + tools/mk3/route_verified.json compiled in).

Per route: the first strict stop (message, PC, END cycle; TMS frontier and DCS frontier) or "runs to the end", and the
receipt digest check of that strict run (explore.regress: chained record digests, END regions, event streams). The
digest check is native only: NOT a new integral comparison with the Original. Stops are grouped by cause.

Usage: python tools/mk3/strict_matrix.py [--names ...] [--processes 6] [--report build/native/mk3-m2/k4-a-strict.json]
       python tools/mk3/strict_matrix.py residue [--report build/native/mk3-m2/k4-residue.json]

Residue (K4 item 4): the static closure from the vectors and the lot-measured PCs (tools/mk3/generate.py closures, the
pointer candidates excluded: they enter no count) minus every PC executed on a passing route receipt or measured by the
lot. Each never-executed PC is assigned to the first entry edge (executed PC -> never-executed successor) that reaches
it inside the residue; the entry's guard (the executed instruction) and the nearest preceding memory operand in its
executed fall-through predecessors (the reader) classify it: input port, CMOS, sound, DMA, RAM game state, or register/indirect state.
K10: closure roots without a static edge get one from their site (GETPC+ADDI software-stack returns, inline-parameter calls, trap
vectors); PCs first reached through a return pushed inside an entry's residue are its `inherited` count, apart from `pcs`. Unclassified
guards claim first, so a reviewed class owns only the PCs that no open entry reaches; other_guards / entered_from list what else enters.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,collections,datetime,hashlib,json,re,sys,threading,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,replay

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'build/native/mk3-m2/k4-a-strict.json'
# Strict-only rejections (mk3_cpu.hpp Block/Edge/io paths, mk3_board.hpp DeferredInterrupt, mk3_dma.hpp, mk3_adsp.cpp
# Unverified / timer) -> the FirstExecution kind a route would have to verify. Any other message is a real stop.
KIND=(('PC outside the authenticated fixed translation','TmsBlock'),('unobserved branch','TmsEdge'),
      ('interrupt taken inside POPST/PUTST/RETI/INTENB is not compared','IrqPath'),('interrupt pending at an instruction boundary','IrqPath'),
      ('DMA command','DmaPath'),('DMA source outside the graphics region is not verified','DmaPath'),
      ('read outside translated Wolf-Unit map','DevicePath'),('opcode differs from the translated block','AdspBlock'),
      ('PC outside the fixed translation','AdspBlock'))


def kind(message):
    if not message or message=='none':return None
    return next((k for m,k in KIND if m in message),'other')


def cause(frontier):
    """(message, pc, address) of a frontier text 'MK3 why; PC n; address m' (ADSP texts keep their own form)."""
    if not frontier or frontier=='none':return None
    pc=re.search(r'PC (\d+)',frontier);ad=re.search(r'address (\d+)',frontier)
    return dict(message=frontier.split('; PC')[0],pc=pc and hex(int(pc.group(1))),address=ad and hex(int(ad.group(1))),kind=kind(frontier))


class Keep:
    """A replay.Native seen by explore.regress; keeps that run's output (one per route thread)."""
    def __init__(self,native,gate):self.n,self.gate,self.out=native,gate,None
    def run(self,*a,**k):
        with self.gate:self.out=self.n.run(*a,**k)
        return self.out


def one(native,gate,name):
    receipt=explore.load(name);keep=Keep(native,gate);t=time.perf_counter()
    reg=explore.regress(keep,receipt);s=keep.out['summary'];end=keep.out['records'][-1]['cycle']
    tms,dcs=cause(s['frontier']),cause(s['dcs_frontier'])
    return dict(name=name,horizon=receipt['horizon'],end_cycle=end,profile=s.get('profile'),
                runs_to_end=tms is None and dcs is None and end>=receipt['horizon'],
                first_stop=tms or dcs,tms_frontier=tms,dcs_frontier=dcs,
                digest=dict(passed=reg['passed'],first_differing_block=reg['first_differing_block'],end_regions_differing=reg['end_regions_differing'],
                            streams_differing=reg['streams_differing'],recapture_needed=reg['recapture_needed'],
                            integral_comparison_at=reg['integral_comparison_at']),
                receipt_sha256=hashlib.sha256((explore.ROUTES/f'{name}.json').read_bytes()).hexdigest(),seconds=round(time.perf_counter()-t,1))


def group(rows):
    """Stops grouped by (kind, message, pc), with the routes and the earliest stop cycle."""
    out={}
    for r in rows:
        c=r['first_stop']
        if not c:continue
        g=out.setdefault((c['kind'],c['message'],c['pc']),dict(**c,routes=[],earliest=None))
        g['routes'].append(r['name']);g['earliest']=min(g['earliest'] or r['end_cycle'],r['end_cycle'])
    return sorted(out.values(),key=lambda g:(-len(g['routes']),g['kind'],g['pc'] or ''))


def matrix(names,processes):
    gate=threading.Semaphore(processes);t=time.perf_counter()
    with replay.Native(profile='strict-routes') as native:
        with ThreadPoolExecutor(len(names)) as ex:rows=list(ex.map(lambda n:one(native,gate,n),names))
        ident,build=native.source_identity,native.build_seconds
    cleanup=native.cleanup
    return dict(schema='mk3-k4-strict-matrix/1',front='K4 A',at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                profile='strict-routes (Profile::Strict, lot-verified + route_verified.json keys)',
                route_verified_sha256=hashlib.sha256(explore.VERIFIED.read_bytes()).hexdigest(),executor=ident,build_seconds=build,
                routes=len(rows),runs_to_end=sum(r['runs_to_end'] for r in rows),digest_equal=sum(r['digest']['passed'] for r in rows),
                stops=group(rows),per_route=rows,wall_seconds=round(time.perf_counter()-t,1),native_cleanup=cleanup,
                note='native only: the digest check reuses each receipt\'s integral comparison; it is not a new comparison with the Original')


COND=re.compile(r'^(J[RA](?!UC)[A-Z]+|DSJ[A-Z]*) ')
def reader_class(address):
    if address is None:return 'register/indirect state'
    if 0x01800000<=address<=0x0187ffff:   # io offset (midwunit io_r, identity shuffle): 0 IN0, 1 IN1, 2 DSW, 3 IN2
        return {0:'input port IN0 (players)',1:'input port IN1 (players)',2:'DIP switches DSW (default settings fixed by the route contract)',
                3:'input port IN2 (coins, starts, test, service)'}.get(((address-0x01800000)>>4)%16%8,'io default offset')
    for lo,hi,name in ((0x01800000,0x0187ffff,'input port'),(0x01400000,0x0145ffff,'CMOS'),(0x01680000,0x0168001f,'sound port'),
                       (0x01a00000,0x01a800ff,'DMA registers'),(0x01000000,0x013fffff,'RAM game state'),(0xff800000,0xffffffff,'program ROM table')):
        if lo<=address<=hi:return name
    return 'other device'


# Hand-reviewed classes (K5-K10): removed for publication (plan 2026-11-15-conformidade-legal.md, 5.1, 16/11/2026). Their
# evidence was prose about the game's routines and data; every residue entry now stays unclassified (never a count either way).
REVIEWED={}            # guard PC -> (class, evidence)
DATA_AFTER_RETURN={}   # guard PC -> (bits,): entries checked by the data-after-return rule
NOT_AN_EDGE={}         # executed PCs whose static edge is not an entry



def residue(report=None,largest=60):
    from tools.mk3 import generate,versus
    rom=versus.image();rows,_=generate.scan(rom)
    measured=set(generate.verified())|generate.EXTERNAL_PCS
    executed={i for k,i,f in explore.receipt_keys() if k=='TmsBlock'}|measured
    (static,_),(full,_),pointers=generate.closures(rom,rows,executed)   # roots: vectors, the lot and every route-executed PC
    left=set(static)-executed
    def before(pc,n=4):   # up to n executed instructions falling through into pc (scan rows; the same decode as the emitter)
        out,q=[],pc-16
        while q>=pc-0x200 and len(out)<n:
            r=rows.get(q)
            if q in executed and r and r[0] and q+r[0]==(out[0][0] if out else pc):out.insert(0,(q,r[3]))   # executed PCs: real instruction starts
            q-=16
        return out
    # K10 A: closure roots without a static edge get one from their site, followed only after the static flood: software-stack
    # returns (generate.continuations: GETPC Rd; ADDI K,Rd), inline-parameter calls (generate.INLINE_CALLS) and the trap vectors.
    soft=collections.defaultdict(set)
    for pc in static:
        if rows[pc][3].startswith('GETPC'):soft[pc]|=generate.continuations(rows,(pc,))
        soft[pc]|={pc+rows[pc][0]+skip for routine,(skip,_,_) in generate.INLINE_CALLS.items() if re.fullmatch(rf'CALL[AR] +{routine:X}h',rows[pc][3])}
    vectors={v:int.from_bytes(rom[(v-generate.BASE)//8:][:4],'little')&~15 for v in range(0xffffffe0,0xfffffbe0,-32)}   # trap 0 first
    owner={};comps={};inherited=collections.Counter()
    def claim(key,t,succ):
        todo=[t];owner[t]=key;n=0
        while todo:
            x=todo.pop();n+=1
            for y in succ(x):
                if y in left and y not in owner:owner[y]=key;todo.append(y)
        return n
    both=lambda x:(*static.get(x,()),*soft.get(x,()))
    for done in (False,True):   # open guards claim first: a class covers only the PCs that no unclassified entry reaches
        for p,t in sorted((p,t) for p in set(static)&executed-NOT_AN_EDGE.keys() if (p in REVIEWED)==done for t in static[p] if t in left):
            if t not in owner:comps[(p,t)]=claim((p,t),t,lambda x:static.get(x,()))
        for p,t in sorted((p,t) for p in soft if p in executed and (p in REVIEWED)==done for t in soft[p] if t in left):   # the site ran, its return address never did
            if t not in owner:comps[(p,t)]=claim((p,t),t,both)
        for p,t in sorted((p,t) for p in soft if p in owner for t in soft[p] if t in left):   # pushed inside an entry's residue: inherited, counted apart
            if t not in owner:inherited[owner[p]]+=claim(owner[p],t,both)
    for v,t in vectors.items():
        if t in left and t not in owner:comps[(v,t)]=claim((v,t),t,both)
    unreached=left-owner.keys()
    assert len(left)==sum(comps.values())+sum(inherited.values())+len(unreached)
    fullpred=collections.defaultdict(set)
    for q,ts in full.items():
        for x in ts:fullpred[x].add(q)
    longs=collections.defaultdict(list)   # aligned ROM long -> its addresses
    for n in range(0,len(rom)-3,2):
        if rom[n+3]==0xff:longs[int.from_bytes(rom[n:n+4],'little')].append(generate.BASE+8*n)
    returns=collections.defaultdict(set)   # software-stack return -> its sites
    for q,ts in soft.items():
        for x in ts:returns[x].add(q)
    def island(p,t,bits=0):
        """The rule "only the fall-through of its return EXGPC reaches this entry": failures ([] = holds) and the sites naming it.
        bits: the entry is data of that size, named only as an immediate or from data; 0: no aligned ROM long may name it."""
        mine={x for x,k in owner.items() if k==(p,t)};span=range(t,t+bits,16) if bits else sorted(mine);bad=[];sites=[]
        if not rows[p][3].startswith('EXGPC') or t!=p+rows[p][0]:bad.append('the guard is not an EXGPC falling into the entry')
        if bits and not all(t<=x<t+bits for x in mine):bad.append('the component leaves the declared data')
        bad+=[f'static predecessor {q:08x} of {x:08x}' for x in sorted(mine) for q in sorted(fullpred[x]-mine-{p})]
        bad+=[f'software-stack return {x:08x}' for x in span if returns.get(x,set())-mine]
        for x in span:
            for at in longs.get(x,()):
                pc=next((q for q in range(at-16,at-80,-16) if q in full and q+rows[q][0]>=at+32),None)
                if pc is None:sites.append(f'long at {at:08x} outside every closure instruction')
                elif re.match(r'(MOVI|ADDI|CMPI|SUBI) ',rows[pc][3]):sites.append(f'{pc:08x} {" ".join(rows[pc][3].split())} ({"executed" if pc in executed else "residue"})')
                else:bad.append(f'named by {pc:08x} {rows[pc][3]}')
        return bad+([] if bits else ['named by '+x for x in sites]),sites
    others=collections.defaultdict(set)   # entry -> executed instructions, other than its guard, with an edge into its PCs
    for q in set(static)&executed-NOT_AN_EDGE.keys():
        for x in (*static[q],*soft.get(q,())):
            if x in owner and owner[x]!=(q,x):others[owner[x]].add(q)
    cross=collections.defaultdict(set)   # entry -> other entries whose residue has an edge into its PCs
    for q,k in owner.items():
        for x in both(q):
            if x in owner and owner[x]!=k:cross[owner[x]].add(k)
    reviewed=dict(REVIEWED);checks={}
    for p,t in comps:
        if p in DATA_AFTER_RETURN or REVIEWED.get(p,('',))[0]=='no reference':
            bad,sites=island(p,t,DATA_AFTER_RETURN.get(p,(0,))[0]);checks[hex(p)]=dict(entry=hex(t),failures=bad,named_by=sites)
            if bad and p in DATA_AFTER_RETURN:del reviewed[p]   # the rule gates the K10 class; the K5-K9 reviews stay and their failures are listed
    rowsout=[]
    for (p,t),n in comps.items():
        if p in vectors:
            rowsout.append(dict(guard=hex(p),guard_asm='trap vector '+', '.join(str((0xffffffe0-v)//32) for v,x in vectors.items() if x==t),entry=hex(t),pcs=n,
                                inherited=inherited[(p,t)],kind='vector',reader=None,callee=None,cls='vector',context=[]));continue
        asm=rows[p][3];prev=before(p)
        ctx=[a for q,a in prev+[(p,asm)]]
        m=next((re.search(r'@([0-9A-F]+)h',a) for a in reversed(ctx) if re.search(r'@([0-9A-F]+)h',a)),None)
        address=int(m.group(1),16) if m else None
        call=next((re.search(r'CALL[AR] +([0-9A-F]+)h',a) for a in reversed(ctx) if re.search(r'CALL[AR] +([0-9A-F]+)h',a)),None)
        kind='software-stack return' if t in soft.get(p,()) and t not in static[p] else 'conditional branch' if COND.match(asm) else 'call/return continuation' if asm.startswith(('CALL','TRAP')) else 'other transfer'
        cls=reader_class(address) if address is not None else 'callee result' if call else 'object field (indirect)' if any(re.search(r'\*[AB]\d+\(',a) for a in ctx) else 'status/register only'
        rowsout.append(dict(guard=hex(p),guard_asm=asm,entry=hex(t),pcs=n,inherited=inherited[(p,t)],other_guards=[hex(q) for q in sorted(others[(p,t)])],entered_from=[hex(k[1]) for k in sorted(cross[(p,t)])],kind=kind,reader=address and hex(address),callee=call and '0x'+call.group(1).lower(),cls=cls,
                            context=[f'{q:08x} {a}' for q,a in prev]))
    rowsout.sort(key=lambda r:-r['pcs'])
    by=collections.defaultdict(lambda:[0,0])
    for r in rowsout:by[(r['cls'],r['kind'])][0]+=1;by[(r['cls'],r['kind'])][1]+=r['pcs']
    out=dict(schema='mk3-k4-residue/1',front='K5 A',at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
             method=__doc__.split('Residue (K4 item 4): ')[1].strip(),
             route_receipts=len(list(explore.ROUTES.glob('*.json'))),roots='interrupt/trap vectors, the lot-measured PCs and every TmsBlock of the passing receipts',
             denominators=dict(static_closure_pcs=len(static),lot_measured_pcs=len(measured),executed_on_receipts_or_lot=len(executed&set(static)),
                               residue_pcs=len(left),entries=len(comps),residue_pcs_in_entries=sum(comps.values()),
                               residue_pcs_inherited_through_software_returns=sum(inherited.values()),residue_pcs_without_entry_from_executed=len(unreached),
                               classified_pcs=sum(n for (p,t),n in comps.items() if p in reviewed),classified_inherited_pcs=sum(n for k,n in inherited.items() if k[0] in reviewed),
                               classified_entries=sum(p in reviewed for p,t in comps),
                               classified_entries_with_another_guard_outside_their_class=sum(p in reviewed and any(reviewed.get(q,(None,))[0]!=reviewed[p][0] for q in others[(p,t)]) for p,t in comps),
                               inherited_note='PCs first reached through a software-stack return address or inline-parameter continuation pushed inside the residue of an entry; they follow the class of that entry and are counted apart from its pcs',
                               
                               pointer_candidate_only_pcs=len(set(full)-set(static)-measured),note='pointer-candidate-only PCs are outside every count'),
             classes=[dict(cls=c,kind=k,entries=v[0],pcs=v[1]) for (c,k),v in sorted(by.items(),key=lambda x:-x[1][1])],
             classified={d:dict(evidence=' || '.join(sorted({e for c,e in reviewed.values() if c==d})),
                                entries=[dict(guard=hex(p),entry=hex(t),pcs=comps[(p,t)],inherited=inherited[(p,t)],other_guards_not_in_this_class=[hex(q) for q in sorted(others[(p,t)]) if reviewed.get(q,(None,))[0]!=d],
                                              entered_from_entries_not_in_this_class=[hex(k[1]) for k in sorted(cross[(p,t)]) if reviewed.get(k[0],(None,))[0]!=d]) for (p,t) in comps if reviewed.get(p,(None,))[0]==d],
                                pcs=sum(n for (p,t),n in comps.items() if reviewed.get(p,(None,))[0]==d),
                                inherited_pcs=sum(n for k,n in inherited.items() if reviewed.get(k[0],(None,))[0]==d)) for d in sorted({c for c,e in reviewed.values()})},
             rule_checks=checks,
             largest=rowsout[:largest],
             counting='reader/caller evidence (static guard and its preceding memory operand), not route acceptance; nothing here counts as verified')
    if report:report.write_text(json.dumps(out,indent=1)+'\n',encoding='utf-8')
    return out


def main():
    if sys.argv[1:2]==['residue']:
        out=residue(Path(sys.argv[3]) if sys.argv[2:3]==['--report'] else ROOT/'build/native/mk3-m2/k4-residue.json');print(json.dumps({k:v for k,v in out.items() if k!='largest'},indent=1));return 0
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--names',nargs='*',default=sorted(p.stem for p in explore.ROUTES.glob('*.json')))
    ap.add_argument('--processes',type=int,default=6);ap.add_argument('--report',type=Path,default=REPORT)
    a=ap.parse_args()
    out=matrix(a.names,a.processes);text=json.dumps(out,indent=1)
    a.report.write_text(text+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in out.items() if k!='per_route'},indent=1)[:6000])
    return 0


if __name__=='__main__':raise SystemExit(main())
