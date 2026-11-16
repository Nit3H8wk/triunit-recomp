"""M2 DCS lot 2: the bank-1 program of the DCS 8K ADSP-2105 (boot 3) vs the pinned Original, from the reset.

Scope: the native executor (tools/mk3/generate_adsp.py fixed blocks + native/mk3/mk3_adsp.cpp devices) runs from
power-on through the bank-0 boots (tools.mk3.test_adsp) into the bank-1 program and on to the frame marker (PC 0x131)
at boot-3 totalcycles >= END. Host stimulus after TMS cycle 231: the Original's own io[1] / sound-port accesses
(declared, as in test_adsp). Compared, in order and in full:
- full stretches (entry to the first frame marker at boot-3 totalcycles >= SPARSE_FROM, and from the first marker
  at >= FULL_FROM to the end): the 84 debugger fields before every instruction (the two I7 wait loops only every
  1009 cycles or while IRQ1 is asserted) and every data / program-data access;
- always: the frame-marker row, every access to the autobuffer (CPU writes and the dcs_irq reads = the PCM handed
  to the DMADAC, with the cycle of each transfer), every access to DM 0x3000-0x37ff and 0x3fe0-0x3fff (bank select,
  latches, control registers);
- the PM/DM images and the state at the end, the DCS latch at the host's status reads and the value of its data read.
The PCM is compared in the DAC domain (16-bit samples in dmadac_transfer order); MAME's resampling is outside.
"""
import ast,json,os,sys,unittest
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.setup import mk3 as setup_mk3
from tools.mk3 import generate_adsp,reference_dcs,roms
from tools.mk3 import test_adsp
from tools.mk3.test_adsp import end_cycles,first,masks

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/dcs-bank1.json'
# Boot-3 totalcycles: init + the first three audio frames; the host command 0x03 0xE7 and its reply.
SPARSE_FROM,FULL_FROM,END=250000,19970000,20140000
SCHEDULE=((3,0,'F'),(3,SPARSE_FROM,'S'),(3,FULL_FROM,'F'),(3,END,'E'))   # reference_dcs.schedule_script switch points
# Boots 4-5, verified: boot 4 in full to the boot-5 entry (BOOTS_VERIFIED); boot 5 in full through its init (the
# commands 55 AA / 64 9B), the commands 00 00 / 00 3E (~78.83M, ~79.01M), the first non-zero sample (79,339,810) and the
# command 04 29 (~108.93M, handled at ~108.99M) in full windows, sparse in between and to the end (BOOTS_SCHEDULE).
# The native run past it, to PROBE_NS with the host events of that capture, stops at BOOTS_FRONTIER.
BOOTS_VERIFIED=((4,0,'F'),(5,0,'E'))
BOOTS_SCHEDULE=((4,0,'F'),(5,SPARSE_FROM,'S'),(5,78780000,'F'),(5,79060000,'S'),(5,79260000,'F'),(5,79420000,'S'),
                (5,108840000,'F'),(5,109060000,'S'),(5,127000000,'E'))
BOOTS_FRONTIER='none'   # no rejection: every executed pair to PROBE_NS is measured
BOOTS_SECONDS,PROBE_NS=16,16000000000   # generate_adsp.BANK1 pairs: -seconds_to_run 16 (an integer option)
RECEIPT_BOOTS=ROOT/'build/native/mk3-m2/dcs-boots.json'
TMS_NS,ADSP_NS=160,100


@contextmanager
def native_runner(status):
    """Builds the native harness once; yields run(events in ns) -> parsed observations, and the timing record."""
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']};times={}
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-adsp.exe'
        build=test_adsp.harness(temp,exe)
        assert build['passed'],q.compact(build)
        times['native_build']=build['wall_seconds']
        def run(events,schedule=SCHEDULE,probe_ns=0):
            (temp/'events.txt').write_text(''.join(f'{k} {w} {e} {v}\n' for k,w,e,v in events),encoding='ascii')
            result=q.command([exe,ROOT/'roms/mk3',temp/'native.txt',temp/'events.txt','_'.join(map(str,status)),'bank1',
                              ','.join(f'{b}:{c}:{m}' for b,c,m in schedule),str(probe_ns)],temp,cwd=ROOT,env=env,timeout=600)
            assert result['passed'],q.compact(result)
            times['native_run']=result['wall_seconds']
            return dict(parse_native((temp/'native.txt').read_text('ascii')),first_boot=schedule[0][0])
        yield run,times
    assert not cleanup['exists_after']


def boosted_slice_end(previous_end,write,starts,adsp_syncs,expire):
    """ADSP-side end (ns) of the timeslice in which the main CPU writes the sound port at `write`, under the 500 ns
    quantum added by the previous write (dcs.cpp dcs_delayed_data_w), after pinned schedule.cpp timeslice():
    target = base + quantum; the main CPU runs whole 160 ns cycles to it, finishing its instruction, and stops after a
    synchronizing one; the ADSP then runs whole 100 ns cycles and stops after a self-synchronizing instruction; each
    device that ran and ends short of the target lowers it (not below the base), so the next base is on the ADSP's
    100 ns grid. previous_end: end of the previous writing instruction (the ADSP ended that slice at its grid floor);
    starts: later main-CPU instruction starts (ns); adsp_syncs: starts (ns) of the ADSP instructions that synchronize;
    expire: the quantum's end (add_quantum at the first write's sync time + 5 us), dropped at the first timeslice()
    entry (after an ADSP synchronization) at or past it. Assumes no other timer expires in between (the interleaving
    is compared with the Original's). Returns the end and the slices as (main-CPU local time before, after, ADSP local
    time before).
    """
    bounds=[previous_end,*starts];tms=previous_end;base=adsp=previous_end//ADSP_NS*ADSP_NS;slices=[];boost=True
    while True:
        target=base+500 if boost else bounds[-1]+TMS_NS;written=synced=False;slices.append([tms,tms,adsp])
        if target-tms>=TMS_NS:
            budget=(target-tms)//TMS_NS
            while budget>0 and not written:
                start=tms;tms=bounds[bounds.index(tms)+1];budget-=(tms-start)//TMS_NS;written=start==write
            if tms<target:target=max(tms,base)
        slices[-1][1]=tms
        if target-adsp>=ADSP_NS:
            while adsp+ADSP_NS<=target and not synced:
                adsp+=ADSP_NS;synced=adsp-ADSP_NS in adsp_syncs
            if adsp<target:target=max(adsp,base)
        base=target
        if written:return base,slices
        if synced and base>=expire:boost=False


def interleave(model,order,starts):
    """Timeslice order around each boosted command: for every main-CPU instruction from the end of the first byte's
    writing instruction to the second byte's, (start ns, modeled ADSP time = its slice's ADSP time before, the
    Original's = its next ADSP instruction hook) from reference_dcs.capture_interleave rows."""
    following={};nxt=None
    for kind,_,c in reversed(order['rows']):
        if kind=='D':nxt=c
        elif kind=='M':following[c*TMS_NS]=nxt
    out=[]
    for first_end,write,slices in model.values():
        boot=max(b for b,ns in starts.items() if ns<=first_end)
        out+=[(t,adsp,starts[boot]+following[t]*ADSP_NS) for before,after,adsp in slices for t in sorted(following) if before<=t<after and first_end<=t<=write]
    return out

def parse_native(text):
    out=dict(rows=[],accesses=[],latch=[],resets=[],blocks=[],host_reads=[],status=[],executed=[])
    for line in text.splitlines():
        tag,_,rest=line.partition(' ');v=rest.split()
        if tag=='F':out['fields']=v
        elif tag=='B':out['rows'].append([int(x,16) for x in v])
        elif tag=='E':out['final']=[int(x,16) for x in v]
        elif tag=='A':out['accesses'].append([v[0],*(int(x,16) for x in v[1:])])   # kind, pc, cycle, address, value, boot
        elif tag=='L':out['latch'].append([int(v[0]),int(v[1])])
        elif tag=='R':out['resets'].append([int(x) for x in v])
        elif tag=='K':out['blocks'].append(dict(zip(('ns','boot','cycle','address','step','first','count','sample_ns','arm'),map(int,v))))
        elif tag=='P':out['blocks'][-1]['samples']=[int(x) for x in v]
        elif tag=='H':out['host_reads'].append([int(v[0]),int(v[1])])
        elif tag=='S':out['status'].append([int(v[0]),int(v[1])])
        elif tag=='M':out['pm']=[int(x,16) for x in v]
        elif tag=='N':out['dm']=[int(x,16) for x in v]
        elif tag=='X':out.update(zip(('local_ns','instructions','totalcycles','bank','executed_pairs','pcm_samples'),map(int,v)))
        elif tag=='Z':out['frontier']=rest
        elif tag=='C':out['executed'].append(int(v[0],16))
    return out


def reference_blocks(accesses):
    """dcs_irq transfers: runs of two or more data reads stamped with one (pc, totalcycles, boot); an instruction reads
    at most one. A transfer of no sample (after a DCS reset with the timer running) leaves no access."""
    blocks=[];n=0
    while n<len(accesses):
        m=n+1
        if accesses[n][0]=='r':
            while m<len(accesses) and accesses[m][:3]==accesses[n][:3] and accesses[m][5:]==accesses[n][5:]:m+=1
        if m-n>1:blocks.append(dict(boot=accesses[n][5],cycle=accesses[n][2],pc=accesses[n][1],addresses=[a[3] for a in accesses[n:m]],
                                    samples=[a[4]-0x10000 if a[4]&0x8000 else a[4] for a in accesses[n:m]]))
        n=m
    return blocks


def boot_starts(nat):return {boot:ns for ns,boot,_ in nat['resets']}


def expected_latch(ref,starts,start_ns):
    """Latch changes from start_ns implied by the Original's ordered latch accesses (dcs.cpp latch contract); ADSP
    access times from the boot starts."""
    events=[(h['totalcycles']*TMS_NS,2,'host_w' if h['kind']=='dcs_w' else 'host_r') for h in ref['host'] if h['kind'] in ('dcs_w','dcs_r')]
    events+=[(starts[a[5]]+a[2]*ADSP_NS,n,'adsp_'+a[0]) for n,a in enumerate(ref['accesses']) if 0x3400<=a[3]<0x3404]
    return [(ns,kind) for ns,_,kind in sorted(e for e in events if e[0]>=start_ns)]


def dac_observed(nat):
    """Native transfers that carry samples, from the first observed boot (a transfer of no sample leaves no access in
    the Original; its I0 rewind and IRQ1 pulse are in the field rows). arm: the m_reg_timer setting (TX1 write) the transfer
    follows, so the sample-period check spans one timer setting."""
    return [b for b in nat['blocks'] if b['count'] and b['boot']>=nat['first_boot']]


def dac_difference(nat,ref):
    """PCM in the DAC domain: every dcs_irq transfer, its boot and cycle, addresses, samples, time and period."""
    blocks=reference_blocks(ref['accesses']);starts=boot_starts(nat);observed=dac_observed(nat)
    if len(blocks)!=len(observed):return f'DAC blocks: native {len(observed)} reference {len(blocks)}'
    for n,(b,r) in enumerate(zip(observed,blocks)):
        if b['boot']!=r['boot'] or b['cycle']-1!=r['cycle']:return f'DAC block {n} cycle: native {b["boot"]}/{b["cycle"]-1} reference {r["boot"]}/{r["cycle"]}'
        if [b['address']+k*b['step'] for k in range(b['count'])]!=r['addresses']:return f'DAC block {n} addresses'
        if b['samples']!=r['samples']:return f'DAC block {n} samples: '+str(first(b['samples'],r['samples'],'sample'))
        if b['ns']!=starts[b['boot']]+b['cycle']*ADSP_NS:return f'DAC block {n} time {b["ns"]}'
        if n and blocks[n-1]['boot']==r['boot'] and observed[n-1]['arm']==b['arm']:
            # recompute_sample_rate: period = sample_period * size / (2 * step) = sample_ns * count; the Original's period is the cycle distance
            period=(r['cycle']-blocks[n-1]['cycle'])*ADSP_NS
            if period!=b['sample_ns']*b['count']:return f'DAC block {n} sample period: native {b["sample_ns"]} ns x {b["count"]}, reference period {period} ns'
    return None


def compare(nat,ref):
    """First difference between the native observations and the Original, or None."""
    if nat['fields']!=ref['fields']:return 'field order'
    m=masks(ref['fields']);norm=lambda row:[v&k for v,k in zip(row,m)]
    rows=ref.setdefault('normalized_rows',[norm(r) for r in ref['rows']])
    if len(nat['rows'])+1!=len(rows):return f'instruction: count native {len(nat["rows"])+1} reference {len(rows)}'
    for n,(x,y) in enumerate(zip(nat['rows'],rows)):
        if norm(x)!=y:return f'instruction #{n}: native {norm(x)} reference {y}'
    if (d:=first(norm(nat['final']),rows[-1],'last instruction')):return d
    if (d:=first(norm(nat['final']),norm(ref['end']),'end state')):return d
    if len(nat['accesses'])!=len(ref['accesses']):return f'access: count native {len(nat["accesses"])} reference {len(ref["accesses"])}'
    for n,(x,y) in enumerate(zip(nat['accesses'],ref['accesses'])):
        if x[1:]!=y[1:] or ('r' if x[0]=='d' else x[0])!=y[0]:return f'access #{n}: native {x} reference {y}'
    if (d:=dac_difference(nat,ref)):return d
    starts=boot_starts(nat)
    if (d:=first(nat['pm'],[v for a,v in enumerate(ref['end_pm']) if a<0x400 or a>=0x800],'end PM')):return d
    if (d:=first(nat['dm'],[v for a,v in enumerate(ref['end_dm']) if a<0x3000 or 0x3800<=a<0x3a00 or a>=0x3fe0],'end DM')):return d
    # Status reads: the main CPU runs first in a timeslice, so it sees the ADSP's latch changes of earlier slices only.
    # Inside the simulated boosted slices that cutoff is known; elsewhere plain time order (Dcs8k::LatchAt) is compared.
    start=starts[ref['first_boot']];changes=expected_latch(ref,starts,start)
    for (cycle,latch),h in zip(nat['status'],(h for h in ref['host'] if h['kind']=='status')):
        ns=cycle*TMS_NS;cutoff=next((adsp for before,after,adsp in ref.get('slices',()) if before<=ns<after),None)
        if cutoff is not None:
            latch=0x0c00
            for when,kind in changes:
                if when<(cutoff if kind.startswith('adsp') else ns):latch={'host_w':latch&~0x800,'adsp_r':latch|0x800,'adsp_w':latch&~0x400,'host_r':latch|0x400}[kind]
        if cycle!=h['totalcycles'] or latch!=h['value']&0x0fff:return f'status read at TMS {h["totalcycles"]}: native {latch:04x} reference {h["value"]:04x}'
    if len(nat['status'])!=sum(1 for h in ref['host'] if h['kind']=='status'):return 'status read count'
    if (d:=first([v&0xff for _,v in nat['host_reads']],[h['value']&0xff for h in ref['host'] if h['kind']=='dcs_r'],'host data read')):return d
    # Latch changes with time: host accesses at TMS cycles, ADSP accesses at boot-3 cycles.
    value=0x0c00;expected=[]
    for ns,kind in changes:
        new={'host_w':value&~0x800,'adsp_r':value|0x800,'adsp_w':value&~0x400,'host_r':value|0x400}[kind]
        if new!=value:expected.append([ns,new])
        value=new
    if (d:=first([c for c in nat['latch'] if c[0]>=start],expected,'latch change')):return d
    return None


class DcsBank1Lot(unittest.TestCase):
    def test_bank1_program_equals_original(self):
        u2=(ROOT/'roms/mk3'/generate_adsp.U2).read_bytes()
        self.assertEqual((setup_mk3.adsp_dir()/'mk3_adsp_bank1.inc').read_text('utf-8'),generate_adsp.generate_bank1(u2),'stale generated bank-1 blocks')
        pairs=generate_adsp.bank1_pairs(u2)
        ref=reference_dcs.capture_bank1(SCHEDULE);ref['first_boot']=SCHEDULE[0][0]
        program=roms.program_image(ROOT/'roms/mk3',roms.definition())
        hosts=[h for h in ref['host'] if h['kind']!='status']
        self.assertEqual([(h['value'],h['totalcycles']) for h in hosts[:2]],[(0x30,23),(0x20,231)],'native lot-1 host timeline')
        kind=lambda h:(0 if h['value']&0x10 else 1) if h['kind']=='io1' else 2 if h['kind']=='dcs_w' else 3
        events=[(kind(h),h['totalcycles']*TMS_NS,(h['totalcycles'] if h['kind']=='dcs_r' else end_cycles(program,h['pc'],h['totalcycles']))*TMS_NS,
                 h['value']&0xff) for h in hosts[2:]]
        self.assertEqual([k for k,*_ in events].count(3),1,'one host data read in scope')
        status=[h['totalcycles'] for h in ref['host'] if h['kind']=='status']
        command=next(n for n,x in enumerate(events) if x[0]==2 and x[3]==3)
        tms=reference_dcs.capture_tms_after_write(3)
        self.assertEqual(tms['write']*TMS_NS,events[command][1],'main-CPU boundary capture is anchored at the command byte')
        with native_runner(status) as (run,times):
            # The second command byte is written 5.28 us after the first, under its 500 ns quantum. The boot-3 start
            # does not depend on later events, so a first run gives the ADSP time base for the slice simulation.
            start=run(events)['resets'][3][0]
            syncs={start+a[2]*ADSP_NS for a in ref['accesses'] if 0x3400<=a[3]<0x3404}
            k,w,e,v=events[command+1]
            slice_end,ref['slices']=boosted_slice_end(events[command][2],w,[c*TMS_NS for c in tms['starts']],syncs,events[command][1]+5000)
            self.assertTrue(w<slice_end<e,'the boosted slice ends inside the second writing instruction')
            events[command+1]=(k,w,slice_end,v)
            nat=run(events)
            # Stimulus negatives: the command byte 0x03 ending one TMS cycle later; the second byte seen at its instruction end.
            late_nat=run([(k,w,e+TMS_NS,v) if n==command else (k,w,e,v) for n,(k,w,e,v) in enumerate(events)])
            unboosted_nat=run([(k,w,e,v) if n==command+1 else x for n,x in enumerate(events)])
        build_s,run_s=times['native_build'],times['native_run']
        self.assertIsNone(compare(nat,ref))
        self.assertEqual(set(nat['executed'])-{3<<48|pc<<24|op for pc,op,_ in pairs},set(),'executed code outside the measured pairs')
        blocks=reference_blocks(ref['accesses'])
        negatives={}
        def mutate(label,container,key,change):   # one element changed in place, compared, restored
            old=container[key];container[key]=change(old)
            negatives[label]=compare(nat,ref) is not None
            container[key]=old
        def dropped(label,items,index):
            item=items.pop(index);negatives[label]=compare(nat,ref) is not None;items.insert(index,item)
        field=lambda name:ref['fields'].index(name)
        access=lambda test:next(a for a in nat['accesses'] if test(a))
        mutate('register',nat['rows'][5000],field('ar'),lambda v:v^1)
        mutate('mac_overflow_flag',nat['rows'][20000],field('astat'),lambda v:v^0x40)
        dropped('row_dropped',nat['rows'],12345)
        mutate('i7_after_transfer',nat['final'],field('i7'),lambda v:v^0xf0)
        mutate('irq1_pulse',next(r for r in nat['rows'] if r[field('irq1')]),field('irq1'),lambda v:0)
        mutate('pcm_sample',nat['blocks'][7]['samples'],100,lambda v:v+1)
        mutate('pcm_block_cycle',nat['blocks'][7],'cycle',lambda v:v+1)
        mutate('pcm_block_time',nat['blocks'][7],'ns',lambda v:v+ADSP_NS)
        dropped('pcm_block_missing',nat['blocks'],40)
        mutate('sample_rate',nat['blocks'][7],'sample_ns',lambda v:v+1)
        mutate('transfer_read_cycle',access(lambda a:a[0]=='d'),2,lambda v:v+1)
        mutate('data_bank_word',access(lambda a:a[0]=='r' and 0x2000<=a[3]<0x3000),4,lambda v:v^1)
        mutate('data_bank_select',access(lambda a:a[0]=='w' and a[3]==0x3000 and a[4]==3),4,lambda v:2)
        mutate('autobuffer_control',access(lambda a:a[0]=='w' and a[3]==0x3fef),4,lambda v:0x0e80)
        mutate('command_read_cycle',access(lambda a:a[0]=='r' and a[3]==0x3400 and a[4]==3),2,lambda v:v+1)
        mutate('reply_value',access(lambda a:a[0]=='w' and a[3]==0x3400),4,lambda v:2)
        mutate('host_read_value',nat['host_reads'][0],1,lambda v:0)
        mutate('latch_change_time',nat['latch'][-1],0,lambda v:v+ADSP_NS)
        mutate('status_latch',nat['status'][-1],1,lambda v:v^0x400)
        mutate('end_pm_image',nat['pm'],0x400+0x280,lambda v:v^1)
        mutate('end_dm_image',nat['dm'],0x0c10,lambda v:v^1)
        self.assertIsNone(compare(nat,ref),'mutations restored')
        # Plain time order for the status read that the main CPU made before the ADSP ran that slice.
        negatives['status_read_without_slice_order']=compare(nat,{**ref,'slices':[]}) is not None
        negatives['command_write_end_plus_1']=compare(late_nat,ref) is not None
        negatives['second_byte_without_boosted_slice']=compare(unboosted_nat,ref) is not None
        self.assertTrue(all(negatives.values()),negatives)
        period=blocks[1]['cycle']-blocks[0]['cycle']
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            scope=dict(program='U2 bank-1 boot page (U2 0x1000, 1024 words) plus the external-PM code it copies at run time: '
                               'init from data bank 0 (U2 0x0800) and main from data bank 2 (U2 0x2000)',
                       boot=3,start_ns=start,end_cycle=nat['totalcycles'],end_ns=nat['local_ns'],
                       sparse_from=SPARSE_FROM,full_from=FULL_FROM,
                       fixed_blocks=len(pairs),identities={n:sum(1 for *_,i in pairs if i==n) for n in generate_adsp.BANK1},
                       executed_pairs=nat['executed_pairs'],native_instructions_from_reset=nat['instructions']),
            identities=dict(u2_sha256=generate_adsp.U2_SHA256,program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],
                            seed_sha256=ref['seed_sha256'],debugger=ref['debugger']),
            host_events=[dict(kind=['assert','release','data_write','data_read'][k],write_ns=w,slice_end_ns=e,value=v) for k,w,e,v in events],
            boosted_slice=dict(write_ns=events[command+1][1],slice_end_ns=slice_end,instruction_end_ns=e,
                               main_cpu_instruction_starts=len(tms['starts']),adsp_synchronizations=len(syncs)),
            compared=dict(instruction_rows=len(ref['rows']),fields_per_row=len(ref['fields']),accesses=len(ref['accesses']),
                          dac_blocks=len(blocks),pcm_samples=sum(len(b['samples']) for b in blocks),
                          nonzero_pcm_samples=sum(1 for b in blocks for s in b['samples'] if s),
                          dac_period_cycles=period,sample_ns=nat['blocks'][0]['sample_ns'],first_block_ns=nat['blocks'][0]['ns'],
                          latch_changes=[c for c in nat['latch'] if c[0]>=start],status_reads=nat['status'],
                          host_reads=nat['host_reads'],end_pm_words=len(nat['pm']),end_dm_words=len(nat['dm'])),
            first_divergence=None,negative_controls=negatives,frontier=nat['frontier'],
            timings_seconds=dict(native_build=build_s,native_run=run_s,reference=ref['wall_seconds'],reference_main_cpu_boundaries=tms['wall_seconds']),reference_log_bytes=ref['log_bytes'],
            assumptions='Host stimulus after TMS 231 is the Original main-CPU bus (as in test_adsp), plus its instruction starts for 1 ms '
                        'after the command byte 0x03, from which the slice end of the second byte is simulated; no other timer is '
                        'assumed to expire between the two bytes. The host data read is placed in a '
                        'scheduler slice of its own, after the ADSP reply (the value it returns is compared). Boot-3 start time comes '
                        'from the native model verified by test_adsp; the Original gives boot-relative cycles, tied to TMS time only by '
                        'the command reads, the status reads and the data read. Inside a timer callback the debugger shows the PC and '
                        'totalcycles of the last executed instruction. m_reg_timer is assumed never to be the scheduler head when armed '
                        '(the TMS scanline timer is always sooner), so the TX1 write does not end the ADSP timeslice.',
            cleanup=ref['cleanup']),indent=1)+'\n',encoding='utf-8')


    def host_scope(self,schedule,seconds):
        """Original capture for `schedule` plus the host events (TMS bus, ns) with the simulated boosted slice end of
        each command's second byte (boosted_slice_end over the Original's main-CPU instruction starts)."""
        ref=reference_dcs.capture_bank1(schedule,seconds=seconds);ref['first_boot']=schedule[0][0]
        program=roms.program_image(ROOT/'roms/mk3',roms.definition())
        hosts=[h for h in ref['host'] if h['kind']!='status']
        kind=lambda h:(0 if h['value']&0x10 else 1) if h['kind']=='io1' else 2 if h['kind']=='dcs_w' else 3
        events=[(kind(h),h['totalcycles']*TMS_NS,(h['totalcycles'] if h['kind']=='dcs_r' else end_cycles(program,h['pc'],h['totalcycles']))*TMS_NS,
                 h['value']&0xff) for h in hosts[2:]]
        reset=next(n for n,x in enumerate(events) if x[0]==0 and x[1]>=19000000*TMS_NS)
        self.assertEqual(events[reset][1],19398912*TMS_NS,'second host DCS reset')
        commands=[n for n in range(reset,len(events)-1) if events[n][0]==events[n+1][0]==2 and events[n+1][1]-events[n][1]<5500]
        return ref,events,reset,commands,[h['totalcycles'] for h in ref['host'] if h['kind']=='status']

    def boosted(self,run,ref,events,commands,schedule,order):
        """Host events with the simulated boosted slice end of each command's second byte (boosted_slice_end over the
        Original's main-CPU instruction starts in `order`, reference_dcs.capture_interleave), the boot starts and the
        modeled slices per second byte."""
        mains=[c*TMS_NS for kind,_,c in order['rows'] if kind=='M'];written={c*TMS_NS:v for kind,v,c in order['rows'] if kind=='W'}
        starts=boot_starts(run(events,schedule))
        syncs={starts[a[5]]+a[2]*ADSP_NS for a in ref['accesses'] if 0x3400<=a[3]<0x3404}
        ref['slices']=[];ends={};model={}
        for n in commands:   # the second byte under the first byte's 500 ns quantum
            k,w,e,v=events[n+1]
            self.assertEqual([written.get(events[n][1]),written.get(w)],[events[n][3],v],'interleaving capture anchors')
            slice_end,slices=boosted_slice_end(events[n][2],w,[c for c in mains if c>events[n][2]],syncs,events[n][1]+5000)
            self.assertTrue(w<slice_end<=e,f'boosted slice of command byte {n+1}')
            ends[n+1]=slice_end;ref['slices']+=slices;model[n+1]=(events[n][2],w,slices)
        return [(k,w,ends.get(n,e),v) for n,(k,w,e,v) in enumerate(events)],starts,model

    def test_boots_4_5_equal_original(self):
        """Verified: the host's second DCS reset with the autobuffer timer running, boot 4 (bank 0) in full (the timer
        is stopped before it expires again), the command 00 00 and the reboot to the boot-5 entry (BOOTS_VERIFIED, with
        the images there); boot 5 in full through its init (55 AA / 64 9B), the commands 00 00 / 00 3E and the first
        non-zero PCM sample, then sparse with the DAC stream (BOOTS_SCHEDULE). The timeslice order around every boosted
        command is compared with the Original's instruction hooks. The native probe past it stops at BOOTS_FRONTIER."""
        u2=(ROOT/'roms/mk3'/generate_adsp.U2).read_bytes()
        pairs=generate_adsp.bank1_pairs(u2)
        word=lambda pc:int.from_bytes(u2[4*generate_adsp.RUNTIME.get(pc,pc):][:3],'big')
        measured={b<<48|pc<<24|op for b in (3,5) for pc,op,_ in pairs}
        measured|={b<<48|pc<<24|word(pc) for b in (1,2,4) for pc in {*generate_adsp.PCS,*generate_adsp.RUNTIME}}
        ref,events,reset,commands,status=self.host_scope(BOOTS_VERIFIED,4)
        self.assertEqual([(events[n][3],events[n+1][3]) for n in commands],[(0,0)],'commands before the boot-5 entry')
        far,far_events,_,far_commands,far_status=self.host_scope(BOOTS_SCHEDULE,BOOTS_SECONDS)
        self.assertEqual([(far_events[n][3],far_events[n+1][3]) for n in far_commands],[(0,0),(0x55,0xaa),(0x64,0x9b),(0,0),(0,0x3e),(4,0x29)],'commands in scope')
        order=reference_dcs.capture_interleave([(far_events[n][1]//TMS_NS-2,far_events[n+1][1]//TMS_NS+4) for n in far_commands],
                                               far_events[far_commands[-1]+1][1]//10**9+1)
        with native_runner(status) as (run,times):
            events,starts,_=self.boosted(run,ref,events,commands,BOOTS_VERIFIED,order)
            nat=run(events,BOOTS_VERIFIED)
        with native_runner(far_status) as (run,_):
            far_events,far_starts,model=self.boosted(run,far,far_events,far_commands,BOOTS_SCHEDULE,order)
            far_nat=run(far_events,BOOTS_SCHEDULE,PROBE_NS)
            third=far_commands[4]+1   # stimulus negative: the command byte 0x3E applied one ADSP cycle later
            late_nat=run([(k,w,e+ADSP_NS*(n==third),v) for n,(k,w,e,v) in enumerate(far_events)],BOOTS_SCHEDULE)
        self.assertIsNone(compare(nat,ref))
        self.assertIsNone(compare(far_nat,far))
        self.assertEqual(far_nat['frontier'],BOOTS_FRONTIER)
        self.assertEqual(set(nat['executed'])-measured,set(),'executed code outside the measured pairs')
        self.assertEqual(set(far_nat['executed'])-measured,set(),'executed code outside the measured pairs (probe)')
        ordered=interleave(model,order,far_starts)
        self.assertEqual([x for x in ordered if x[1]!=x[2]],[],'timeslice order around the boosted commands')
        negatives={};field=lambda name:ref['fields'].index(name)
        def mutate(label,container,key,change,nat=nat,ref=ref):
            old=container[key];container[key]=change(old);negatives[label]=compare(nat,ref) is not None;container[key]=old
        mutate('boot4_i0',nat['rows'][100],field('i0'),lambda v:v^1)
        mutate('boot4_mstat',nat['rows'][-50],field('mstat'),lambda v:v^0x10)
        k=len(nat['rows'])//2;item=nat['rows'].pop(k);negatives['boot4_row_dropped']=compare(nat,ref) is not None;nat['rows'].insert(k,item)
        mutate('command_read_cycle',next(a for a in nat['accesses'] if a[0]=='r' and a[3]==0x3400),2,lambda v:v+1)
        mutate('latch_change_time',nat['latch'][-1],0,lambda v:v+ADSP_NS)
        mutate('end_dm_image',nat['dm'],0x0c10,lambda v:v^1)
        self.assertIsNone(compare(nat,ref),'mutations restored')
        # Boot 5: the IRQ2 entry of the byte 0xAA (row 22090, the former frontier), a row at the first non-zero sample.
        far_blocks=reference_blocks(far['accesses'])
        nonzero=next(n for n,b in enumerate(far_blocks) if any(b['samples']))
        entry=far_nat['rows'][22090];self.assertEqual(entry[field('pc')],4,'IRQ2 entry row of the byte 0xAA')
        mutate('boot5_aa_irq2_entry_cycle',entry,field('totalcycles'),lambda v:v+1,far_nat,far)
        mutate('boot5_register_at_first_nonzero',next(r for r in far_nat['rows'] if r[field('totalcycles')]>=far_blocks[nonzero]['cycle']),
               field('ar'),lambda v:v^1,far_nat,far)
        mutate('boot5_end_pm_image',far_nat['pm'],0x400+0x280,lambda v:v^1,far_nat,far)
        negatives['command_3e_one_adsp_cycle_late']=compare(late_nat,far) is not None
        slices=model[third][2];k=[n for n,(before,after,_) in enumerate(slices) if after>before][1];slices[k][2]+=ADSP_NS   # a slice where the main CPU ran
        negatives['timeslice_order_adsp_time']=any(x[1]!=x[2] for x in interleave(model,order,far_starts));slices[k][2]-=ADSP_NS
        self.assertIsNone(compare(far_nat,far),'mutations restored')
        far_obs=dac_observed(far_nat);nz=next(n for n,b in enumerate(far_obs) if any(b['samples']))
        def far_mutate(label,container,key,change):
            old=container[key];container[key]=change(old);negatives[label]=dac_difference(far_nat,far) is not None;container[key]=old
        far_mutate('pcm_first_nonzero_sample',far_obs[nz]['samples'],next(k for k,x in enumerate(far_obs[nz]['samples']) if x),lambda v:v+1)
        far_mutate('pcm_late_sample',far_obs[-1]['samples'],7,lambda v:v^0x100)
        far_mutate('dac_block_address',far_obs[nz],'address',lambda v:v+1)
        far_mutate('dac_block_cycle',far_obs[nz+5],'cycle',lambda v:v+1)
        far_mutate('dac_sample_rate',far_obs[-2],'sample_ns',lambda v:v+1)
        self.assertIsNone(dac_difference(far_nat,far),'mutations restored')
        self.assertTrue(all(negatives.values()),negatives)
        # The boot-3 timer survives the reset hold without expiring and the bank-0 code stops it (SYSCONTROL) before its
        # next expiry: boot 4 has no dcs_irq transfer, boot 5 re-arms it (TX1).
        last3=max((b for b in nat['blocks'] if b['boot']==3),key=lambda b:b['ns'])
        self.assertEqual([b for b in nat['blocks'] if b['boot']==4],[],'no transfer in boot 4')
        self.assertLess(last3['ns'],events[reset][1],'last boot-3 transfer before the reset')
        RECEIPT_BOOTS.write_text(json.dumps(dict(passed=True,
            scope=dict(schedule=BOOTS_VERIFIED,boot5_schedule=BOOTS_SCHEDULE,boot_start_ns={b:starts[b] for b in (4,5)},end_ns=nat['local_ns'],
                       boot5_end_ns=far_starts[5]+BOOTS_SCHEDULE[-1][1]*ADSP_NS,fixed_blocks=len(pairs),executed_pairs=nat['executed_pairs'],
                       probe_executed_pairs=far_nat['executed_pairs'],native_instructions_from_reset=nat['instructions']),
            identities=dict(u2_sha256=generate_adsp.U2_SHA256,program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],
                            seed_sha256=ref['seed_sha256'],debugger=ref['debugger']),
            host_events=[dict(kind=['assert','release','data_write','data_read'][k],write_ns=w,slice_end_ns=e,value=v) for k,w,e,v in far_events[reset:]],
            compared=dict(instruction_rows=len(ref['rows']),fields_per_row=len(ref['fields']),accesses=len(ref['accesses']),
                          last_boot3_transfer_ns=last3['ns'],boot4_transfers=0,latch_changes=len([c for c in nat['latch'] if c[0]>=starts[4]]),
                          status_reads=nat['status'],end_pm_words=len(nat['pm']),end_dm_words=len(nat['dm']),
                          boot5=dict(instruction_rows=len(far['rows']),accesses=len(far['accesses']),dac_blocks=len(far_blocks),
                                     pcm_samples=sum(len(b['samples']) for b in far_blocks),nonzero_pcm_samples=sum(1 for b in far_blocks for x in b['samples'] if x),
                                     first_nonzero_block_cycle=far_blocks[nonzero]['cycle'],blocks_after_first_nonzero=len(far_blocks)-1-nonzero,
                                     latch_changes=len([c for c in far_nat['latch'] if c[0]>=far_starts[5]]),status_reads=len(far_nat['status'])),
                          timeslice_order=dict(commands=[[far_events[n-1][3],far_events[n][3]] for n in model],main_cpu_instructions=len(ordered),
                                               second_byte_slice_end_ns=[far_events[n][2] for n in model])),
            first_divergence=None,negative_controls=negatives,
            frontier=dict(native_probe=far_nat['frontier'],probe_ns=PROBE_NS),
            timings_seconds=dict(native_build=times['native_build'],native_run=times['native_run'],reference=ref['wall_seconds'],
                                 reference_boot5=far['wall_seconds'],reference_interleave=order['wall_seconds']),
            reference_log_bytes=[ref['log_bytes'],far['log_bytes'],order['log_bytes']],
            assumptions='Host stimulus is the Original main-CPU bus, as in test_bank1_program_equals_original; the second byte of each '
                        'command gets the simulated boosted slice end from the main-CPU instruction starts after its first byte, and the '
                        'modeled ADSP time at every main-CPU instruction start between the two bytes equals the Original one. Boot starts '
                        'come from the native model. The timer keeps running through the reset hold but does not expire before the bank-0 '
                        'code stops it, so the dcs_irq path after dcs_reset (no sample, I0 rewind, IRQ1 pulse) is transcribed from dcs.cpp '
                        'without differential evidence. Boot 5 between its full windows is compared sparse (frame markers, autobuffer, '
                        'DM 0x3000-0x37ff, control registers) and in the DAC stream.',
            cleanup=[ref['cleanup'],far['cleanup'],order['cleanup']]),indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
