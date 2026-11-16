"""M2 DCS lot: native DCS 8K ADSP-2105 (fixed translation of the U2 boot page) vs the pinned Original.

Clock/reset contract (sources in docs/investigation): TMS34010 cycle = 160 ns (50 MHz, tms34010.h clocks/8);
ADSP-2105 cycle = 100 ns (dcs.cpp XTAL 10 MHz, 1 cycle per clock). io[1] bit 4 drives dcs reset_w(~bit4):
dcs_reset + RESET assert / RESET clear, both synchronized at the TMS write; the main CPU aborts its timeslice at
the end of the writing instruction and the ADSP then runs whole cycles to that time (schedule.cpp timeslice),
unless one of its own line changes (input_latch_r auto-ack) aborts it first. A RESET clear runs device_reset,
which restarts totalcycles (diexec interface_pre_reset).

Window (required): power-on boot 0 and boot 1 up to TMS cycle 1961, host timeline from the native lot-1 TMS
translation; every ADSP instruction's 84 debugger fields, ordered PM/DM accesses, PM/DM images and the DCS latch
at the three TMS status reads. Extension: the same executor continues through the Original's later host
timeline (reset at TMS 504984/524990 and two sound-port writes, taken from the Original's main-CPU bus as a
declared stimulus) until the bank-1 software reboot; compared at every non-NOP instruction, sampled NOPs, all
accesses and the final images. Negative controls mutate one field each and must be detected.
"""
import copy,json,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.setup import mk3 as setup_mk3
from tools.mk3 import generate_adsp,reference_dcs,roms

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/dcs-adsp.json'
PROGRAM_BASE=0xff800000
# Debugger state masks (adsp2100.cpp state_add): 16 bits unless listed.
MASKS={'se':0xff,'sb':0x1f,'mr2':0xff,'se_sec':0xff,'sb_sec':0x1f,'mr2_sec':0xff,'cntr':0x3fff,'mstat':0x7f,'imask':0x7f,
       **{f'{g}{k}':0x3fff for g in 'ilm' for k in range(8)},'astat':0xff,'sstat':0xff,'px':0xff,'pcsp':0xff,
       **{n:0xf for n in ('cntrsp','statsp','loopsp')},'icntl':0x1f,**{f'irq{k}':1 for k in range(4)},
       **{n:1 for n in ('flagin','flagout','fl0','fl1','fl2')}}


def masks(fields):return [MASKS.get(name,0xffff) if name not in ('totalcycles',) else (1<<64)-1 for name in fields]


def end_cycles(program,pc,cycle):
    """End of the main instruction whose bus write the watchpoint saw at pc (after its fetch)."""
    word=lambda bit:int.from_bytes(program[(bit-PROGRAM_BASE)//8:(bit-PROGRAM_BASE)//8+2],'little')
    if word(pc-48)&0xffe0==0x0580:return cycle+3   # MOVE Rs,@abs,0 (34010ops.hxx MOVE_RA: COUNT_CYCLES(3))
    if word(pc-16)&0xfe00==0x8000:return cycle+1   # MOVE Rs,*Rd,0 (MOVE_RN: COUNT_CYCLES(1))
    raise ValueError(f'Host write from an unqualified instruction at {pc:08x}')


def harness(temp,exe):
    """native/tests/mk3_adsp_tests.cpp with the whole-image TMS units (the host timeline comes from the generated reset)."""
    from tools.mk3 import generate
    return generate.build(temp,[ROOT/'native/tests/mk3_adsp_tests.cpp',ROOT/'native/mk3/mk3_adsp.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),
                                ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp'],exe)


def native(variants,reads):
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-adsp.exe'
        build=harness(temp,exe)
        assert build['passed'],q.compact(build)
        data=[]
        for events in variants:   # one build, one run per host-event variant
            (temp/'events.txt').write_text(''.join(f'{k} {w} {e} {v}\n' for k,w,e,v in events),encoding='ascii')
            run=q.command([exe,ROOT/'roms/mk3',temp/'native.json',temp/'events.txt','_'.join(map(str,reads))],temp,cwd=ROOT,env=env,timeout=120)
            assert run['passed'],q.compact(run)
            data.append(json.loads((temp/'native.json').read_text('utf-8')))
    assert not cleanup['exists_after']
    return data,build['wall_seconds'],run['wall_seconds']


def first(a,b,label):
    if len(a)!=len(b):return f'{label}: count native {len(a)} reference {len(b)}'
    for n,(x,y) in enumerate(zip(a,b)):
        if x!=y:return f'{label} #{n}: native {x} reference {y}'
    return None


def boots(accesses):
    """Reference accesses carry no core-reset index: totalcycles restarts at each reset."""
    out,boot,last=[],0,-1
    for kind,pc,cycle,address,value in accesses:
        if cycle<last:boot+=1
        last=cycle;out.append([boot,cycle,pc,kind,address,value])
    return out


def compare(nat,ref):
    """First difference between the native observations and the Original, or None."""
    m=masks(ref['fields'])
    norm=lambda row:[v&k for v,k in zip(row,m)]
    w,e=nat['window'],nat['extension']
    if nat['fields']!=ref['fields']:return 'field order'
    # Window: the reference trace starts after the boot-0 PC-0 hook (debugger initial stop).
    native_trace=[norm(r[1:]) for r in w['rows'][1:]]+[norm(w['final'])]
    if (d:=first(native_trace,[norm(r) for r in ref['trace']],'window instruction')):return d
    window_pm=[v for a,v in enumerate(ref['win_pm']) if a<0x400 or a>=0x800]
    window_dm=[v for a,v in enumerate(ref['win_dm']) if a<0x3000 or 0x3800<=a<0x3a00 or a>=0x3fe0]
    if (d:=first(w['pm'],window_pm,'window PM')):return d
    if (d:=first(w['dm'],window_dm,'window DM')):return d
    accesses=boots(ref['accesses'])
    in_window=[a for a in accesses if a[0]==0 or (a[0]==1 and a[1]<w['totalcycles'])]
    if (d:=first([[a[0],a[1],a[2],a[3],a[4],a[5]] for a in w['accesses']],in_window,'window access')):return d
    for cycle,latch in nat['latch_at']:
        read=next(h for h in ref['host'] if h['kind']=='status' and h['totalcycles']==cycle)
        if read['value']&0x0fff!=latch:return f'latch at TMS {cycle}: native {latch:04x} reference {read["value"]:04x}'
    # Extension to the bank-1 reboot.
    # Breakpoints are armed after the debugger's initial stop at the boot-0 PC-0 hook.
    if e['rows'][0][:3]!=[0,0,0]:return 'extension rows do not start at the boot-0 entry'
    if (d:=first([norm(r[1:]) for r in e['rows'][1:]],[norm(r) for r in ref['rows']],'extension instruction')):return d
    if (d:=first(e['accesses'],accesses,'extension access')):return d
    if (d:=first(norm(e['final']),norm(ref['end']),'bank-1 entry state')):return d
    if (d:=first(e['pm'],[v for a,v in enumerate(ref['end_pm']) if a<0x400 or a>=0x800],'bank-1 entry PM')):return d
    if (d:=first(e['dm'],[v for a,v in enumerate(ref['end_dm']) if a<0x3000 or 0x3800<=a<0x3a00 or a>=0x3fe0],'bank-1 entry DM')):return d
    return None


FORMS_RECEIPT=ROOT/'build/native/mk3-m2/adsp-forms.json'


class DcsAdspLot(unittest.TestCase):
    def test_sweep_forms_and_profiles(self):
        """Linear PM sweep (generate_adsp.images): every swept word translates; the measured pairs keep their exact
        blocks. The forms closed by the sweep (shift_op/shift_op_imm, DIVS/DIVQ, flag out) against a separate
        transcription of 2100ops.hxx with six one-rule mutations that must all be detected; strict vs game on an
        unmeasured block; the busy-loop slice (jump to self) of execute_run."""
        u2=(ROOT/'roms/mk3'/generate_adsp.U2).read_bytes()
        census=generate_adsp.census(u2)
        self.assertEqual((census['boot']['verified'],census['bank1']['verified']),(63,1711),'verified blocks = measured pairs')
        self.assertEqual(census['boot']['untranslated']+census['bank1']['untranslated'],0,census)
        self.assertEqual((setup_mk3.adsp_dir()/'mk3_adsp_bank1.inc').read_text('utf-8'),generate_adsp.generate_bank1(u2),'stale generated bank-1 blocks')
        # dual-read form: operation on the old registers, then the DAG1 data read, then the DAG2 program read (op >> 4)
        self.assertEqual(generate_adsp.emit(0xc2e60f),'Alu(0, 7, 6, 0); WriteReg0(0, DataReadDag1(0xc2e60fu)); WriteReg0(4, PgmReadDag2(0x0c2e60u));')
        self.assertEqual(generate_adsp.emit(0x1815bf,0x15b),'if (Condition(15)) { pc = 0x015b; EatSlice(); }')
        self.assertEqual(generate_adsp.emit(0x1815bf,0x15c),'if (Condition(15)) { pc = 0x015b; }')
        cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
        with q.scratch_tree() as (temp,cleanup):
            exe=temp/'mk3-adsp.exe'
            build=harness(temp,exe)
            self.assertTrue(build['passed'],q.compact(build))
            run=q.command([exe,'forms',ROOT/'roms/mk3'],temp,cwd=ROOT,env=env,timeout=120)
            self.assertTrue(run['passed'],q.compact(run))
            result=json.loads(run['stdout'].strip().splitlines()[-1])
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(result['failures'],0)
        self.assertEqual(result['negatives'],0b1111110,'every mutation of the transcription is detected')
        self.assertEqual(result['profiles'],'strict:MK3 ADSP PC outside the fixed translation (boot 0, PC 1, cycle 0);'
                         'game:3,2:1:5074802:0,3:1:0:0,2:2:6384672:1;busy:1100:11:1:347')
        FORMS_RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        FORMS_RECEIPT.write_text(json.dumps(dict(passed=True,census=census,form_cases=result['cases'],negatives_detected=6,
            profiles=result['profiles'],timings_seconds=dict(build=build['wall_seconds'],run=run['wall_seconds']),
            verified_scope='per-form helpers vs a transcription of the pinned 2100ops.hxx (not the Original); swept blocks '
                           'without a measured pair stay unverified',cleanup=dict(exists_after=cleanup['exists_after'])),indent=1)+'\n',encoding='utf-8')

    def test_native_adsp_equals_original(self):
        u2=(ROOT/'roms/mk3'/generate_adsp.U2).read_bytes()
        self.assertEqual((setup_mk3.adsp_dir()/'mk3_adsp_boot.inc').read_text('utf-8'),generate_adsp.generate(u2),'stale generated ADSP blocks')
        ref=reference_dcs.capture()
        program=roms.program_image(ROOT/'roms/mk3',roms.definition())
        hosts=[h for h in ref['host'] if h['kind']!='status']
        prefix=[h for h in hosts if h['totalcycles']<=231]
        self.assertEqual([(h['value'],h['totalcycles']) for h in prefix],[(0x30,23),(0x20,231)],'native lot-1 host timeline')
        events=[(0 if h['value']&0x10 else 1,h['totalcycles'],end_cycles(program,h['pc'],h['totalcycles']),0) if h['kind']=='io1' else
                (2,h['totalcycles'],end_cycles(program,h['pc'],h['totalcycles']),h['value']&0xff) for h in hosts if h['totalcycles']>231]
        if any(h['kind']=='dcs_r' for h in hosts):self.fail('host DCS reads are not modeled in this lot')
        reads=[h['totalcycles'] for h in ref['host'] if h['kind']=='status']
        self.assertEqual(len(reads),3)
        # Stimulus negatives: the first sound-port write ending one TMS cycle later; the reset assert one earlier.
        first_data=next(n for n,x in enumerate(events) if x[0]==2)
        late=[(k,w,e+1,v) if n==first_data else (k,w,e,v) for n,(k,w,e,v) in enumerate(events)]
        early=[(k,w,e-1,v) if k==0 else (k,w,e,v) for k,w,e,v in events]
        (nat,late_nat,early_nat),build_s,run_s=native([events,late,early],reads)
        self.assertTrue(nat['u2_rejected'])
        self.assertEqual(nat['frontier'],'none')   # the bank-1 entry now executes: continued by tools.mk3.test_adsp_bank1
        self.assertIsNone(compare(nat,ref))
        negatives={}
        def mutate(label,f):
            changed=copy.deepcopy(nat);f(changed);negatives[label]=compare(changed,ref) is not None
        mutate('window_register',lambda n:n['window']['rows'][100].__setitem__(7,n['window']['rows'][100][7]^1))
        mutate('window_cntr',lambda n:n['window']['rows'][-1].__setitem__(ref['fields'].index('cntr')+1,n['window']['rows'][-1][ref['fields'].index('cntr')+1]+1))
        mutate('boot0_length',lambda n:n['window']['rows'].pop(36))
        mutate('reset_point',lambda n:n['window']['rows'].insert(37,n['window']['rows'][36]))
        mutate('pm_write_value',lambda n:n['window']['accesses'][5].__setitem__(5,n['window']['accesses'][5][5]^0x100))
        mutate('access_cycle',lambda n:n['window']['accesses'][-1].__setitem__(1,n['window']['accesses'][-1][1]+1))
        mutate('latch_read',lambda n:n['window']['accesses'][16].__setitem__(4,0x3401))
        mutate('window_pm_image',lambda n:n['window']['pm'].__setitem__(4,n['window']['pm'][4]^1))
        mutate('window_dm_image',lambda n:n['window']['dm'].__setitem__(0x2000,n['window']['dm'][0x2000]^0x100))
        mutate('latch_at_234',lambda n:n['latch_at'][0].__setitem__(1,0x0400))
        mutate('irq_entry',lambda n:n['extension']['rows'][next(i for i,r in enumerate(n['extension']['rows']) if r[1]==0x176)].__setitem__(2,1))
        mutate('reboot_bank',lambda n:n['extension']['accesses'][-2].__setitem__(5,2))
        mutate('bank1_pm',lambda n:n['extension']['pm'].__setitem__(0,0x18022f))
        mutate('end_state',lambda n:n['extension']['final'].__setitem__(ref['fields'].index('mstat'),1))
        negatives['data_write_end_plus_1']=compare(late_nat,ref) is not None
        negatives['reset_assert_end_minus_1']=compare(early_nat,ref) is not None
        self.assertTrue(all(negatives.values()),negatives)
        w,e=nat['window'],nat['extension']
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            scope=dict(window='power-on boot 0 (37 instructions) and boot 1 cycles 0..2763 (TMS cycles 0..1961)',
                       extension='boot 1 to the TMS 504984 reset, boot 2 from the 524990 release through IRQ2, its handler, '
                                 'the 0xF5 clear and the SYSCONTROL 0x0208 reboot into the U2 bank-1 page (stopped before its first instruction)',
                       translated_pcs=sorted({*generate_adsp.PCS,*generate_adsp.RUNTIME}),fixed_blocks=generate_adsp.generate(u2).count('Fetch(')),
            identities=dict(u2_sha256=generate_adsp.U2_SHA256,program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],
                            seed_sha256=ref['seed_sha256'],debugger=ref['debugger']),
            clock=dict(tms_cycle_ns=160,adsp_cycle_ns=100,boot1_start_ns=w['core_resets'][1][0],
                       boot1_cycle_at_tms='(160*tms - 37400) / 100',boot2_start_ns=e['core_resets'][2][0],boot3_start_ns=e['core_resets'][3][0]),
            host_events=[dict(kind=['assert','release','data'][k],tms_write=wc,tms_end=ec,value=v) for k,wc,ec,v in events],
            compared=dict(window_instructions=len(ref['trace']),fields_per_instruction=len(ref['fields']),
                          window_accesses=len(w['accesses']),window_pm_words=len(w['pm']),window_dm_words=len(w['dm']),
                          extension_instruction_rows=len(ref['rows']),extension_accesses=len(e['accesses']),
                          end_pm_words=len(e['pm']),end_dm_words=len(e['dm']),
                          instructions_per_boot=[b[2]-a[2] for a,b in zip(e['core_resets'],e['core_resets'][1:])],
                          native_instructions_executed=dict(window=len(w['rows']),extension_to_reboot=e['core_resets'][-1][2]),
                          status_reads=[dict(tms_cycle=c,dcs_latch=f'0x{v:04x}') for c,v in nat['latch_at']]),
            latch_changes=nat['extension']['latch_changes'],first_divergence=None,negative_controls=negatives,
            frontier=nat['frontier'],
            timings_seconds=dict(native_build=build_s,native_run=run_s,reference=ref['wall_seconds']),
            assumptions='Host events up to TMS 231 come from the native lot-1 translation; later ones are the Original main-CPU '
                        'bus writes (declared stimulus, instruction ends from the MOVE cycle costs). Slice starts: t = 0 for the '
                        'power-on slice; otherwise within one 63.25 us scanline-timer line or a 500 ns boosted quantum before the '
                        'write; an ADSP self-synchronization inside that range rejects. The boot-0 PC-0 instruction precedes the '
                        'debugger hooks and is compared only through its effects. DCS latch values at TMS reads assume no ADSP '
                        'latch change inside the reading TMS slice (none occurs before TMS 545051).',
            cleanup=ref['cleanup']),indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
