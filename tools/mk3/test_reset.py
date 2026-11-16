"""M2 lots 1-2 and reserve: native MK3 reset path vs the pinned Original, each from its own reset.

Lot 1: reset 0xff8148b0 -> before the first device read (0xff814aa0).
Lot 2: status read, BTST/JRNE, MOVI, CALLA -> CMOS routine entry 0xffadaf40.
At each frontier: PC, ST, cycles and 31 registers; every ordered main-CPU write and device read before it
(address, value, cycle; the watchpoint PC is after the fetch, and every access in these slices comes from a
48-bit instruction). Reserve: the ADSP-2105 boot page word by word against the Original's internal PM.
Negative controls mutate one field each and must be detected.
"""
import copy,json,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference

ROOT=Path(__file__).resolve().parents[2]
SLICES={'prefix':0xff814aa0,'cmos':0xffadaf40,'cmos_check':0xff814b40,'pic_check':0xffaeff00,'init_text':0xffae8690,'serial':0xffb096a0,'sound_wait':0xffaa8990}
FETCHED_BITS=48
# tms34010 CALLA pushes before fetching its 32-bit operand: the watchpoint PC is opcode + 16 bits.
CALLA_SITES={0xff814b10}
RECEIPT=ROOT/'build/native/mk3-m2/lot1-reset.json'

def native():
    """Strict profile of the whole-image units (tools/mk3/generate.py), generated and built in the scratch tree."""
    from tools.mk3 import generate
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-reset.exe'
        build=generate.build(temp,[ROOT/'native/tests/mk3_reset_tests.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),
                                   ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp'],exe)
        assert build['passed'],q.compact(build)
        out=temp/'native.json'
        run=q.command([exe,ROOT/'roms/mk3',reference.SEED,out],temp,cwd=ROOT,env=env,timeout=60);assert run['passed'],q.compact(run)
        data=json.loads(out.read_text('ascii'))
    assert not cleanup['exists_after']
    return data,build['wall_seconds'],run['wall_seconds']

def compare(trace,ref,name):
    """First difference between a native slice and the reference up to that slice's frontier, or None."""
    cpu=ref['cpu'][name]
    for key in ('pc','status','cycles','registers'):
        if trace[key]!=cpu[key]:return f'{name} {key}: native {trace[key]} reference {cpu[key]}'
    bus=[row for row in ref['bus'] if row[4]<cpu['cycles']]
    if any(row[5]!=16 for row in bus):return 'non-16-bit access in slice'
    for kind,key in (('W','writes'),('R','reads')):
        rows=[row for row in bus if row[0]==kind]
        if name in ('prefix','cmos'):
            expected=[[pc-16 if pc-16 in CALLA_SITES else pc-FETCHED_BITS,address,value,cycle] for k,pc,address,value,cycle,_ in rows]
            if trace[key]!=expected:return f'{name} {key}: native {trace[key]} reference {expected}'
            continue
        # Generated slices: exact ordered (address, value, cycle); the watchpoint PC lies inside the source instruction.
        if [r[1:] for r in trace[key]]!=[r[2:5] for r in rows]:
            first=next((i for i,(a,b) in enumerate(zip(trace[key],rows)) if a[1:]!=b[2:5]),min(len(trace[key]),len(rows)))
            return f'{name} {key} #{first}: native {trace[key][first:first+2]} reference {rows[first:first+2]} (counts {len(trace[key])}/{len(rows)})'
        if any(not 0<=r[1]-t[0]<=80 for t,r in zip(trace[key],rows)):return f'{name} {key}: watchpoint PC outside the source instruction'
    return None

class ResetLots(unittest.TestCase):
    def test_native_reset_path_equals_original(self):
        data,build_s,run_s=native()
        ref=reference.capture([(name,pc,'1') for name,pc in SLICES.items()],545036,pm_words=0x400)
        for name in SLICES:self.assertIsNone(compare(data[name],ref,name))
        frontier=[row for row in ref['bus'] if row[0]=='R' and row[4]<247]
        self.assertEqual([r[1:5] for r in frontier],[[0xff814aa0+FETCHED_BITS,0x0187ffc0,0x0c00,234]],'single device read at the lot 1 frontier')
        boot=data['dcs_boot'];self.assertEqual(len(boot),384);self.assertEqual(boot,ref['dsp_pm'][:len(boot)])
        negatives={}
        for label,(name,mutate) in {'register':('prefix',lambda t:t['registers'].__setitem__(5,1)),
                                    'status':('prefix',lambda t:t.__setitem__('status',t['status']^0x20000000)),
                                    'write_cycle':('prefix',lambda t:t['writes'][4].__setitem__(3,230)),
                                    'write_order':('prefix',lambda t:t['writes'].reverse()),
                                    'write_value':('prefix',lambda t:t['writes'][3].__setitem__(2,0x31)),
                                    'write_missing':('prefix',lambda t:t['writes'].pop()),
                                    'read_value':('cmos',lambda t:t['reads'][0].__setitem__(2,0x1c00)),
                                    'return_address':('cmos',lambda t:t['writes'][-2].__setitem__(2,0x4b30)),
                                    'entry_cycle':('cmos',lambda t:t.__setitem__('cycles',246)),
                                    'cmos_read':('cmos_check',lambda t:t['reads'][3].__setitem__(2,t['reads'][3][2]^1)),
                                    'cmos_write_cycle':('cmos_check',lambda t:t['writes'][-1].__setitem__(3,t['writes'][-1][3]+1)),
                                    'return_cycle':('cmos_check',lambda t:t.__setitem__('cycles',1869)),
                                    'pic_status':('pic_check',lambda t:t['reads'][-1].__setitem__(2,0x0c00)),
                                    'pic_write':('pic_check',lambda t:t['writes'][-1].__setitem__(2,0x0000)),
                                    'pic_cycles':('pic_check',lambda t:t.__setitem__('cycles',1960)),
                                    'dsw_read':('init_text',lambda t:next(r for r in t['reads'] if r[1]==0x0187ffa0).__setitem__(2,0xfd7c)),
                                    'tms_io_write':('init_text',lambda t:next(w for w in t['writes'] if w[1]==0xc00000b0).__setitem__(2,0x2d)),
                                    'vram_clear_write':('init_text',lambda t:[w for w in t['writes'] if w[1]<0x400000][-1].__setitem__(2,1)),
                                    'ram_clear_missing':('init_text',lambda t:t['writes'].pop(len(t['writes'])//2)),
                                    'text_registers':('init_text',lambda t:t['registers'].__setitem__(18,t['registers'][18]^1)),
                                    'pixblt_write':('serial',lambda t:[w for w in t['writes'] if w[0]==0xffae8690][-1].__setitem__(2,0x505^0x500)),
                                    'serial_byte':('sound_wait',lambda t:[r for r in t['reads'] if r[1]==0x01600000][3].__setitem__(2,0)),
                                    'serial_count':('sound_wait',lambda t:t['reads'].remove([r for r in t['reads'] if r[1]==0x01600000][-1])),
                                    'sound_cycles':('sound_wait',lambda t:t.__setitem__('cycles',545035))}.items():
            changed=copy.deepcopy(data[name]);mutate(changed);negatives[label]=compare(changed,ref,name) is not None
        boot_changed=list(boot);boot_changed[100]^=1;negatives['dcs_boot_word']=boot_changed!=ref['dsp_pm'][:len(boot)]
        self.assertTrue(all(negatives.values()),negatives)
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            lots={'1':'reset 0xff8148b0 -> before 0xff814aa0','2':'0xff814aa0 status read -> CMOS routine entry 0xffadaf40','3':'generated CMOS routine 0xffadaf40 -> return 0xff814b40','4':'generated watchdog/PIC handshake/JA -> first DMA write 0xffaeff00','5a':'generated DMA/second reset/RAM clear/TMS I/O/video/palette/VRAM clear/text setup -> first PIXBLT 0xffae8690','5b':'PIXBLT B,XY boot text (runtime helper) -> PIC serial clock 0xffb096a0','5c':'PIC serial number clock-out, checks, display setup -> first DCS wait 0xffaa8990',
                  'reserve':'ADSP-2105 boot page from U2'},
            program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],seed_sha256=ref['seed_sha256'],debugger=ref['debugger'],
            compared={name:dict(pc=hex(ref['cpu'][name]['pc']),cycles=ref['cpu'][name]['cycles'],writes=len(data[name]['writes']),
                                reads=len(data[name]['reads']),instructions=data[name]['instructions']) for name in SLICES},
            checkpoint_fields='PC, ST, totalcycles, A0-A14, SP, B0-B14',
            dcs_boot=dict(words_compared=len(boot),reference='ADSP internal PM 0..383 at the lot 1 frontier'),
            negative_controls=negatives,timings_seconds=dict(native_build=build_s,native_run=run_s,reference=ref['wall_seconds']),
            assumptions='DCS latch 0x0c00 until the first sound-port write (TMS 545051), shown by the native ADSP run in tools/mk3/test_adsp.py; PIXBLT run to completion (IE clear, scheduler timeslices change no state)',
            cleanup=ref['cleanup']),indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':unittest.main()
