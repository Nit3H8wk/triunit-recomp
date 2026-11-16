"""M2 PIXBLT lot: native PIXBLT B,XY (native/mk3/mk3_pixblt.hpp) vs the pinned Original at 0xffae8690.

Instruction-level differential test: each instruction starts from the Original's entry checkpoint (31 registers,
ST, totalcycles, 32 TMS I/O words, video control, DMA_PALETTE) and the VRAM words it reads that no earlier PIXBLT
wrote; the per-execution timeslice budgets come from the Original's consecutive checkpoints (scheduler fact, not
modeled natively). The end-to-end run from reset belongs to the main M2 session.
Compared: state after every execution (restarts with ST.P included), ordered VRAM writes and VRAM/ROM reads
(address, value, cycle); a single-execution run (unbounded budget) against the completions; explicit rejections.
"""
import copy,json,os,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,reference_pixblt as rp

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/pixblt.json'
P=1<<25

def groups(ref):
    out=[]
    for run in ref['executions']:
        if run['entry']['status']&P:out[-1].append(run)
        else:out.append([run])
    assert len(out)==len(ref['completions']),'executions/completions mismatch'
    for g,done in zip(out,ref['completions']):
        assert done['pc']==rp.INSIDE and not done['status']&P
        assert all(not r['reads'] and not r['writes'] for r in g[1:]),'restart touched the bus'
    return out

def native_input(gs,ref,mutate=None):
    written,seeded,lines=set(),set(),[str(len(gs))]
    for n,(g,done) in enumerate(zip(gs,ref['completions'])):
        e=copy.deepcopy(g[0])
        if mutate:mutate(n,e)
        after=[r['entry']['cycles'] for r in g[1:]]+[done['cycles']]
        budgets=[b-r['entry']['cycles'] for b,r in zip(after,g)]
        if mutate and getattr(mutate,'budgets',None):budgets=mutate.budgets(n,budgets)
        seeds=[]
        for address,value,_ in e['reads']:
            if address<0x400000 and address not in written and address not in seeded:seeds.append(f'{address} {value}');seeded.add(address)
        written|={a for a,_,_ in e['writes']}
        x=e['entry'];lines.append(' '.join(map(str,[x['pc'],x['status'],x['cycles'],*x['registers'],*e['io'],e['video_control'],e['dma_palette'],
                                               len(budgets),*budgets,len(seeds)]+seeds)))
    return '\n'.join(lines)+'\n'

def native(inputs):
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    outputs=[]
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-pixblt.exe'
        build=q.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-municode','-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),
                         ROOT/'native/tests/mk3_pixblt_tests.cpp',ROOT/'native/mk3/mk3_program.cpp',ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],
                        temp,cwd=ROOT,env=env,timeout=180)
        assert build['passed'],q.compact(build)
        exe_sha,run_s=q.sha(exe),0.0
        for i,text in enumerate(inputs):
            (temp/f'in{i}.txt').write_text(text,encoding='ascii')
            run=q.command([exe,ROOT/'roms/mk3',temp/f'in{i}.txt',temp/f'out{i}.json'],temp,cwd=ROOT,env=env,timeout=60)
            assert run['passed'],q.compact(run)
            outputs.append(json.loads((temp/f'out{i}.json').read_text('ascii')));run_s+=run['wall_seconds']
    assert not cleanup['exists_after']
    return outputs,dict(native_build=build['wall_seconds'],native_runs=run_s),exe_sha,cleanup

def point(p):return [p['pc'],p['status'],p['cycles'],p['registers']]

def compare(data,gs,ref):
    """First difference between the native PIXBLT runs and the Original, or None."""
    for n,(g,done,nat) in enumerate(zip(gs,ref['completions'],data['scheduled'])):
        after=[r['entry'] for r in g[1:]]+[done]
        if len(nat['steps'])!=len(g):return f'#{n} executions: native {len(nat["steps"])} reference {len(g)}'
        for i,(step,exp) in enumerate(zip(nat['steps'],after)):
            if point(step)!=point(exp):return f'#{n} execution {i}: native {point(step)} reference {point(exp)}'
            if step['consumed']!=exp['cycles']-g[i]['entry']['cycles'] or step['completed']!=(i==len(g)-1):return f'#{n} execution {i} progress {step}'
        for key in ('writes','reads'):
            if nat[key]!=g[0][key]:
                first=next((i for i,(a,b) in enumerate(zip(nat[key],g[0][key])) if a!=b),min(len(nat[key]),len(g[0][key])))
                return f'#{n} {key} #{first}: native {nat[key][first:first+2]} reference {g[0][key][first:first+2]} (counts {len(nat[key])}/{len(g[0][key])})'
    if len(data['scheduled'])!=len(gs):return 'instruction count'
    for n,(g,done,nat) in enumerate(zip(gs,ref['completions'],data['single'])):
        step=nat['steps'][0]
        if point(step)!=point(done) or not step['completed']:return f'single #{n}: native {point(step)} reference {point(done)}'
        if nat['writes']!=g[0]['writes'] or nat['reads']!=g[0]['reads']:return f'single #{n} bus'
    return None

class PixbltLot(unittest.TestCase):
    def test_native_pixblt_equals_original(self):
        started=time.perf_counter()
        ref=rp.capture()
        gs=groups(ref)
        def colour(n,e):
            if n==0:e['entry']['registers'][25]^=0x100  # COLOR1
        def short(n,e):pass
        short.budgets=lambda n,b:b[:-1]+[b[-1]-1] if n==len(gs)-1 else b
        (data,bad_colour,bad_budget),timings,exe_sha,cleanup=native([native_input(gs,ref),native_input(gs,ref,colour),native_input(gs,ref,short)])
        self.assertEqual(data['opcode']&0xfff0,0x0fa0,'PIXBLT B,XY opcode at 0xffae8690')
        self.assertIsNone(compare(data,gs,ref))
        self.assertTrue(all(data['rejections'].values()),data['rejections'])
        negatives={'colour1_input':compare(bad_colour,gs,ref) is not None,'final_budget_minus_one':compare(bad_budget,gs,ref) is not None}
        last_restart=next(n for n in range(len(gs)-1,-1,-1) if len(gs[n])>1)
        for label,mutate in {'register':lambda d:d['scheduled'][0]['steps'][-1]['registers'].__setitem__(16,0),
                             'restart_p_flag':lambda d:d['scheduled'][last_restart]['steps'][0].__setitem__('status',8),
                             'restart_cycles':lambda d:d['scheduled'][last_restart]['steps'][0].__setitem__('cycles',d['scheduled'][last_restart]['steps'][0]['cycles']+1),
                             'completion_cycles':lambda d:d['scheduled'][3]['steps'][-1].__setitem__('cycles',d['scheduled'][3]['steps'][-1]['cycles']-1),
                             'write_value':lambda d:d['scheduled'][5]['writes'][3].__setitem__(1,d['scheduled'][5]['writes'][3][1]^0x0500),
                             'write_order':lambda d:d['scheduled'][2]['writes'].insert(0,d['scheduled'][2]['writes'].pop(1)),
                             'write_missing':lambda d:d['scheduled'][-1]['writes'].pop(),
                             'write_cycle':lambda d:d['scheduled'][1]['writes'][0].__setitem__(2,0),
                             'read_address':lambda d:d['scheduled'][4]['reads'][0].__setitem__(0,d['scheduled'][4]['reads'][0][0]+16),
                             'single_register':lambda d:d['single'][7]['steps'][0]['registers'].__setitem__(18,0)}.items():
            changed=copy.deepcopy(data);mutate(changed);negatives[label]=compare(changed,gs,ref) is not None
        self.assertTrue(all(negatives.values()),negatives)
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            scope='instruction-level differential test of PIXBLT B,XY at 0xffae8690: inputs from the Original entry checkpoints; end-to-end from reset pending in the main M2 session',
            program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],seed_sha256=ref['seed_sha256'],debugger=ref['debugger'],
            native=dict(helper_sha256=q.sha(ROOT/'native/mk3/mk3_pixblt.hpp'),driver_sha256=q.sha(ROOT/'native/tests/mk3_pixblt_tests.cpp'),exe_sha256=exe_sha),
            bound_cycles=ref['bound'],first_divergence=None,
            instructions=[dict(entry_cycle=g[0]['entry']['cycles'],exit_cycle=done['cycles'],executions=len(g),
                               budgets=[s['consumed'] for s in nat['steps']],width_height=[g[0]['entry']['registers'][23]&0xffff,g[0]['entry']['registers'][23]>>16],
                               writes=len(g[0]['writes']),reads=len(g[0]['reads'])) for g,done,nat in zip(gs,ref['completions'],data['scheduled'])],
            totals=dict(instructions=len(gs),executions=sum(map(len,gs)),writes=sum(len(g[0]['writes']) for g in gs),reads=sum(len(g[0]['reads']) for g in gs),
                        checkpoints_compared=sum(map(len,gs))+len(gs)),
            checkpoint_fields='PC, ST, totalcycles, A0-A14, SP, B0-B14 after every execution; single-execution run vs completions',
            supported='PSIZE 8, CONTROL rop 0 + T, window 0, DPYCTL.SRT 0, PMASK 0; source in program ROM, destination in VRAM',
            rejections=data['rejections'],negative_controls=negatives,
            timings_seconds=dict(timings,reference=ref['wall_seconds'],total=round(time.perf_counter()-started,3)),
            cleanup=dict(reference=ref['cleanup'],native=cleanup)),indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':unittest.main()
