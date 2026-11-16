"""M2 PIC serial lot: native serial PIC simulation (native/mk3/mk3_pic.*) vs the pinned Original.

RNG contract: running_machine::rand() is an LCG from the constructor seed 0x9d14abd7 (machine.cpp,
mame0280), never reseeded; the serial PIC's device_reset draws m_data[12..13]. Evidence: two independent
headless runs without the debugger (different wall-clock base times) and one debugger run with a Lua soft
reset; each reports m_data and the LCG position of m_rand_seed. The debugger run's ordered security
reads/writes and io_w offset-1 writes are replayed into the native model: every returned byte, every
post-read PIC state (Lua saved items) and the final state must match. Negative controls must be detected.
"""
import json,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference_pic

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/pic-serial.json'
SECURITY,IO_BASE,IO_END=0x01600000,0x01800000,0x0187fff0

def events(bus):
    """Reference rows -> native events. totalcycles restarts after a soft reset, which marks device_reset."""
    out,last=['P'],-1
    for kind,pc,address,value,cycles,size in bus:
        if size!=16:raise ValueError('non-16-bit PIC access')
        if cycles<last:out.append('S')
        last=cycles
        if SECURITY<=address<SECURITY+0x20:out.append('R' if kind=='R' else (f'W {value&0xff}' if address==SECURITY else None))
        elif kind=='W' and IO_BASE<=address<=IO_END and (address-IO_BASE)>>4&7==1:out.append(f'L {value}')
        else:raise ValueError(f'unexpected row {address:x}')
    return [e for e in out if e]

def native(build,event_lists):
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    results=[]
    with q.scratch_tree() as (temp,cleanup):
        exe=temp/'mk3-pic.exe'
        made=q.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/mk3'),
                        ROOT/'native/tests/mk3_pic_tests.cpp',ROOT/'native/mk3/mk3_pic.cpp','-o',exe],temp,cwd=ROOT,env=env,timeout=180)
        assert made['passed'],q.compact(made);build['seconds']=made['wall_seconds']
        for i,ev in enumerate(event_lists):
            (temp/f'e{i}.txt').write_text('\n'.join(ev)+'\n',encoding='ascii')
            run=q.command([exe,temp/f'e{i}.txt'],temp,cwd=ROOT,env=env,timeout=30);assert run['passed'],q.compact(run)
            results.append(json.loads(run['stdout'].strip()))
    assert not cleanup['exists_after']
    return results

def compare(got,ref):
    """First difference between a native replay and the reference observation, or None."""
    resets=[r['data'] for r in ref['pic'] if r['tag'] in ('boot','reset')]
    if got['resets']!=resets:return f'm_data: native {got["resets"]} reference {resets}'
    if got['draws']!=ref['pic'][-1]['rand_draws']:return f'draws: native {got["draws"]} reference {ref["pic"][-1]["rand_draws"]}'
    values=[row[3] for row in ref['bus'] if row[0]=='R']
    states=[[r['buff'],r['idx'],r['buff'],r['status']] for r in ref['pic'] if r['tag']=='read']
    if len(got['reads'])!=len(values) or len(values)!=len(states):return f'read counts {len(got["reads"])}/{len(values)}/{len(states)}'
    for i,(g,v,s) in enumerate(zip(got['reads'],values,states)):
        if g[0]!=v or g!=s:return f'read #{i}: native {g} reference value {v} state {s}'
    stop=ref['pic'][-1]
    if got['final']!=[stop['idx'],stop['buff'],stop['status']]:return f'final: native {got["final"]} reference {stop}'
    return None

class PicSerial(unittest.TestCase):
    def test_native_pic_equals_original(self):
        runs=[reference_pic.capture(30,debug=False),reference_pic.capture(30,debug=False)]
        ref=reference_pic.capture(2,debug=True,soft_reset_ns=1e9)
        for r in runs:
            self.assertEqual([(p['tag'],p['data'],p['rand_draws']) for p in r['pic'] if p['tag']!='read'],
                             [('boot',runs[0]['pic'][0]['data'],2),('stop',runs[0]['pic'][0]['data'],2)],'run-to-run m_data and draws')
        self.assertEqual(ref['pic'][0]['data'],runs[0]['pic'][0]['data'],'debugger does not change the draws')
        ev=events(ref['bus'])
        controls={'extra_draw':[x for e in ev for x in (['D',e] if e=='S' else [e])],  # one rand() call before the soft reset
                  'reseeded_soft_reset':['P' if e=='S' else e for e in ev],
                  'missing_clock':ev[:ev.index('W 0')]+ev[ev.index('W 0')+1:],
                  'nibble_clock':[('W 15' if e=='W 0' else e) for e in ev][:ev.index('W 0')+1]+ev[ev.index('W 0')+1:],
                  'ignored_reset_line':[e for e in ev if not e.startswith('L')]}
        build={}
        got,*bad=native(build,[ev]+list(controls.values()))
        self.assertIsNone(compare(got,ref))
        negatives={name:compare(result,ref) is not None for name,result in zip(controls,bad)}
        changed=json.loads(json.dumps(ref));[r for r in changed['bus'] if r[0]=='R'][1][3]^=1
        negatives['reference_value']=compare(got,changed) is not None
        self.assertTrue(all(negatives.values()),negatives)
        clocks=[(row[1],row[4]) for row in ref['bus'] if row[0]=='W' and row[2]==SECURITY and not row[3]&0x1f]
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,
            scope='serial PIC simulation (the serial PIC device of midwayic.cpp) data, read/write/status/reset_w; no CPU translation',
            program_sha256=ref['program_sha256'],core_sha256=ref['core_sha256'],seed_sha256=ref['seed_sha256'],
            rand_contract='machine.cpp mame0280: seed 0x9d14abd7 (l.73), rand l.850-857, saved item l.190; no reseed; PIC device_reset draws 1-2, soft reset draws 3-4',
            m_data={r['tag']:r['data'] for r in ref['pic'] if r['tag'] in ('boot','reset')},
            run_to_run=[dict(data=r['pic'][0]['data'],draws_at_stop=r['pic'][-1]['rand_draws'],seconds=r['seconds']) for r in runs],
            first_zero_nibble_clock=dict(pc=hex(clocks[0][0]),cycles=clocks[0][1]),zero_nibble_clocks=len(clocks),
            compared=dict(events=len(ev),reads=len(got['reads']),bytes_clocked=sum(1 for e in ev if e=='W 0'),resets=len(got['resets'])),
            negative_controls=negatives,
            timings_seconds=dict(native_build=build['seconds'],reference=[r['wall_seconds'] for r in runs+[ref]]),
            cleanup=[r['cleanup']['exists_after'] for r in runs+[ref]]),indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':unittest.main()
