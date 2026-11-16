"""K2 front A: the ADSP-2105 internal timer of the DCS 8K (mk3::Dcs8k) against a Python transcription of the pinned
dcs.cpp timer management (docs/investigation/sources/dcs.cpp: timer_enable_callback, update_timer_count, reset_timer,
internal_timer_callback, adsp_control_r/w TIMER_*_REG, dcs_reset; member types from upstream/dcs.h), the MSTAT_TIMER
callback of upstream/2100ops.hxx update_mstat and adsp2100.cpp device_reset, the edge-triggered ADSP2105_TIMER input
(adsp21xx execute_set_input) and the list-head abort of schedule.cpp emu_timer::adjust.

Scripted and seeded-random sequences (MSTAT writes, TSCALE/TCOUNT/TPERIOD writes, TCOUNT reads, cycles, core and DCS
resets, the DRAM refresh stub at PM 0x18) run on the real Dcs8k private paths (friend AdspTimerTest) and on the model;
state, expiries, interrupt latches, timeslice aborts and rejections must be equal. Negative controls: each mutated
model (period, enable, scale, count read, reload rule, head abort, stub check) must differ. Profiles: Strict rejects the
path unless route-verified, Game notes DevicePath keys.
The model shares the author's reading of the source with the C++: no MK3 route enables the timer (see
build/native/mk3-m2/k2-devices.json), so the path stays "translated, not verified".
"""
import json,os,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.setup import mk3 as setup_mk3

ROOT=Path(__file__).resolve().parents[2]
U32,U64,NEVER=(1<<32)-1,(1<<64)-1,(1<<64)-1
STUB=(0x0c0030,0x804828,0x904828,0x0c0020,0x0a001f)
PATH=0x21050000
RUN,MSTAT,WRITE,READ,CORE,DCS,STUBOP,HOST=range(8)


class Model:
    """dcs.cpp timer management with the dcs.h types (u32 members, u64 start cycles), ADSP time in 100 ns cycles."""
    def __init__(s,mutation=None):
        s.mut=mutation;s.total=s.local=0;s.mstat=0;s.stub=False;s.host=0;s.latch=0;s.notes=[]
        s.enable=0;s.ignore=False;s.start_cycles=0;s.start_count=0;s.scale=1;s.period=0;s.fired=0;s.next=NEVER
        s.ctl={0x1b:0,0x1c:0,0x1d:0}
    def note(s,n,frm):
        key=(PATH|n,frm)
        if key not in s.notes:s.notes.append(key)
    def update_count(s):
        if not s.enable:return
        elapsed=((s.total-s.start_cycles)&U64)//s.scale
        if elapsed<((s.start_count+1)&U32):s.start_count=(s.start_count-elapsed)&U32
        else:
            elapsed-=(s.start_count+1)&U32
            elapsed-=(elapsed//((s.period+1)&U32))*((s.period+1)&U32)
            s.start_count=(s.period-elapsed)&U32
        s.ctl[0x1c]=s.start_count&0xffff
    def reset_timer(s):
        if not s.enable:return False
        s.start_cycles=s.total;s.fired=0
        if not s.ignore and s.stub and s.mut!='stub':s.ignore=True
        if s.ignore:return False
        s.next=s.local+((s.scale*(s.start_count+1))&U32)*100
        if not s.host:raise ValueError('MK3 ADSP internal timer armed without the host scheduler\'s next timer')
        return s.next<s.host and s.mut!='abort'   # DAC and IRQ1 pulse timers stay unarmed here
    def enable_cb(s,state):
        s.note(1,int(state))
        if state:s.enable=1;return s.reset_timer()
        s.update_count();s.enable=0
        if s.mut!='enable':s.next=NEVER
        return False
    def callback(s):
        s.note(4,0);now=s.next;s.next=NEVER;s.fired=(s.fired+1)&U32
        period=s.period if s.mut=='period' else (s.period+1)&U32
        target=(s.start_cycles+s.scale*(((s.start_count+1)&U32)+s.fired*period))&U64
        target=(target-s.total)&U64
        if target>=1<<63:target-=1<<64
        if not s.ignore and (s.period>10 or s.scale>1 or s.mut=='reload'):
            if target<0:raise ValueError('MK3 ADSP internal timer target before the current cycle')
            s.next=now+target*100
        s.latch=1
    def op(s,code,a,b):
        sync=False;value=0
        if code==RUN:
            for _ in range(a):
                fired=False
                while s.next<s.local+100:s.callback();fired=True
                if s.latch:s.out.append(f'F {s.local} {s.total}');s.latch=0
                s.total+=1;s.local+=100
        elif code==MSTAT:
            new=a&0x7f
            if (new^s.mstat)&0x20:s.mstat=new;sync=s.enable_cb(bool(new&0x20))
            s.mstat=new
        elif code==WRITE:
            s.note(2,a);s.ctl[a]=b
            if a==0x1b:
                data=b+1 if s.mut=='scale' else (b&0xff)+1
                if data!=s.scale:s.update_count();s.scale=data;sync=s.reset_timer()
            elif a==0x1c:s.start_count=b;sync=s.reset_timer()
            elif b!=s.period:s.update_count();s.period=b;sync=s.reset_timer()
        elif code==READ:
            s.note(3,a)
            if a==0x1c and s.mut!='count':s.update_count()
            value=s.ctl[a]
        elif code==CORE:
            s.total=0
            if s.mstat&0x20:s.enable_cb(False)
            s.mstat=0
        elif code==DCS:   # memset(m_control_regs), dcs_boot reloads PM (the stub goes), timers reset; count/period kept
            s.ctl={k:0 for k in s.ctl};s.stub=False;s.ignore=False;s.enable=0;s.scale=1;s.next=NEVER
        elif code==STUBOP:s.stub=bool(a)
        elif code==HOST:s.host=a
        return sync,value
    def run(s,ops):
        s.out=[]
        for code,a,b in ops:
            try:sync,value=s.op(code,a,b)
            except ValueError as e:s.out.append('reject '+str(e));break
            s.out.append(' '.join(map(str,('S',s.enable,int(s.ignore),s.start_cycles,s.start_count,s.scale,s.period,s.fired,
                                            s.next,s.next,s.ctl[0x1b],s.ctl[0x1c],s.ctl[0x1d],s.latch,int(sync),s.total,s.local,value))))
        s.out.append('N '+' '.join(f'{i}:{f}' for i,f in s.notes))
        return s.out


HARNESS=r'''#include "mk3_adsp.hpp"
#include "mk3_dcs.hpp"
#include <cstdio>
#include <stdexcept>
namespace mk3 {
struct AdspTimerTest {
    static void Run(const std::vector<uint8_t>& u2, const std::vector<std::array<uint64_t, 3>>& ops) {
        Dcs8k d(u2);
        FirstExecution log;
        d.profile = Profile::Game; d.first = &log;
        const std::array<uint32_t, 5> original = {d.pm_[0x18], d.pm_[0x19], d.pm_[0x1a], d.pm_[0x1b], d.pm_[0x1c]};
        static constexpr uint32_t stub[5] = {0x0c0030, 0x804828, 0x904828, 0x0c0020, 0x0a001f};
        try {
            for (const auto& [code, a, b] : ops) {
                d.sync_ = false;
                uint64_t value = 0;
                switch (code) {
                case 0: for (uint64_t k = 0; k < a; ++k) {
                            d.FireTimers();
                            if (d.irq_latch_[5]) { std::printf("F %llu %llu\n", (unsigned long long)d.local_ns, (unsigned long long)d.totalcycles); d.irq_latch_[5] = 0; }
                            ++d.totalcycles; d.local_ns += 100;
                        } break;
                case 1: d.WriteReg3(1, int32_t(a)); break;
                case 2: d.DataWrite(uint16_t(0x3fe0 + a), uint16_t(b)); break;
                case 3: value = d.DataRead(uint16_t(0x3fe0 + a)); break;
                case 4: d.CoreReset(); break;
                case 5: d.DcsReset(d.local_ns); break;
                case 6: for (int k = 0; k < 5; ++k) d.pm_[0x18 + k] = a ? stub[k] : original[k]; break;
                case 7: d.host_next_ns = a; break;
                }
                std::printf("S %u %u %llu %u %u %u %u %llu %llu %u %u %u %u %u %llu %llu %llu\n", d.timer_enable_, unsigned(d.timer_ignore_),
                            (unsigned long long)d.timer_start_cycles_, d.timer_start_count_, d.timer_scale_, d.timer_period_, d.timers_fired_,
                            (unsigned long long)d.int_next_ns_, (unsigned long long)d.NextTimerNs(), d.control_[0x1b], d.control_[0x1c], d.control_[0x1d],
                            unsigned(d.irq_latch_[5]), unsigned(d.sync_), (unsigned long long)d.totalcycles, (unsigned long long)d.local_ns,
                            (unsigned long long)value);
            }
        } catch (const std::runtime_error& e) {
            std::string what = e.what();
            std::printf("reject %s\n", what.substr(0, what.find(" (boot")).c_str());
        }
        std::printf("N");
        for (const auto& e : log.order) if (e.kind == Unverified::DevicePath) std::printf(" %u:%u", e.id, e.from);
        std::printf("\n");
    }
    // Strict: the lot-only build rejects the enable; a route-verified key accepts it.
    static std::string Strict(const std::vector<uint8_t>& u2) {
        std::string out;
        for (int routed = 0; routed < 2; ++routed) {
            Dcs8k d(u2);
            RouteVerified keys;
            keys.keys.insert(std::make_tuple(uint8_t(Unverified::DevicePath), Dcs8k::kTimerPath | 1u, 1u));
            if (routed) d.routes = &keys;
            d.host_next_ns = ~0ull;
            try { d.WriteReg3(1, 0x20); out += "run;"; } catch (const std::runtime_error& e) { out += e.what(); out += ";"; }
        }
        return out;
    }
};
}
int main(int, char** argv) {
    const auto u2 = mk3::LoadDcsU2(argv[1]);
    @SCRIPTS@
    std::printf("strict %s\n", mk3::AdspTimerTest::Strict(u2).c_str());
    return 0;
}
'''


def scripts():
    H=(HOST,NEVER,0)
    fixed={
        'periodic, count read, disable/enable':[H,(WRITE,0x1d,99),(WRITE,0x1c,49),(MSTAT,0x20,0),(RUN,130,0),(READ,0x1c,0),(RUN,30,0),
            (READ,0x1c,0),(RUN,200,0),(MSTAT,0,0),(RUN,300,0),(READ,0x1c,0),(MSTAT,0x20,0),(RUN,420,0),(READ,0x1d,0)],
        'scale while enabled':[H,(WRITE,0x1d,20),(MSTAT,0x20,0),(RUN,37,0),(WRITE,0x1b,0x103),(RUN,250,0),(WRITE,0x1b,3),(RUN,5,0),
            (WRITE,0x1d,20),(WRITE,0x1d,7),(RUN,300,0),(READ,0x1b,0),(READ,0x1c,0)],
        'one-shot without reload':[H,(WRITE,0x1d,5),(WRITE,0x1c,3),(MSTAT,0x20,0),(RUN,60,0),(WRITE,0x1b,1),(RUN,90,0),(WRITE,0x1d,10),(RUN,100,0)],
        'refresh stub and DCS reset':[H,(STUBOP,1,0),(WRITE,0x1d,50),(MSTAT,0x20,0),(RUN,120,0),(STUBOP,0,0),(MSTAT,0,0),(MSTAT,0x20,0),
            (RUN,120,0),(DCS,0,0),(RUN,80,0),(MSTAT,0,0),(MSTAT,0x20,0),(RUN,160,0)],
        'core reset while enabled':[H,(WRITE,0x1d,30),(WRITE,0x1c,12),(MSTAT,0x20,0),(RUN,77,0),(CORE,0,0),(READ,0x1c,0),(RUN,60,0),
            (MSTAT,0x20,0),(RUN,90,0)],
        'not the list head':[(HOST,500,0),(WRITE,0x1c,40),(WRITE,0x1d,40),(MSTAT,0x20,0),(RUN,10,0),H,(WRITE,0x1c,0),(RUN,60,0)],
        'unknown host timer':[(WRITE,0x1d,40),(MSTAT,0x20,0)],
        'count moved before the target':[H,(WRITE,0x1d,20),(WRITE,0x1c,1000),(MSTAT,0x20,0),*[(x,y,0) for _ in range(30) for x,y in ((RUN,30),(READ,0x1c))],(RUN,200,0)],
    }
    rng=random.Random(20261110);rand={}
    for n in range(24):
        ops=[H]
        for _ in range(40):
            k=rng.random()
            if k<0.30:ops.append((RUN,rng.choice((1,2,5,17,40,120)),0))
            elif k<0.45:ops.append((MSTAT,rng.choice((0,0x20,0x30,0x10)),0))
            elif k<0.75:ops.append((WRITE,rng.choice((0x1b,0x1c,0x1d)),rng.choice((0,1,3,9,11,15,40,0xff,0x1ff,rng.randrange(0x10000)))))
            elif k<0.88:ops.append((READ,rng.choice((0x1b,0x1c,0x1c,0x1d)),0))
            elif k<0.92:ops.append((CORE,0,0))
            elif k<0.95:ops.append((DCS,0,0))
            else:ops.append((STUBOP,rng.randrange(2),0))
        rand[f'random {n}']=ops
    return {**fixed,**rand}


def native(scripts_):
    calls='\n    '.join('{ std::printf("@ %s\\n", "'+name+'"); mk3::AdspTimerTest::Run(u2, {'+','.join(f'{{{c}ull,{a}ull,{b}ull}}' for c,a,b in ops)+'}); }'
                       for name,ops in scripts_.items())
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        (temp/'timer.cpp').write_text(HARNESS.replace('@SCRIPTS@',calls),encoding='utf-8');exe=temp/'timer.exe'
        build=q.command([cc,'-std=c++17','-O1','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),
                         '-I'+str(ROOT/'native/mk2'),setup_mk3.include(),temp/'timer.cpp',*(ROOT/'native/mk3'/n for n in ('mk3_adsp.cpp','mk3_dcs.cpp')),
                         ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],temp,env=env,timeout=300)
        assert build['passed'],q.compact(build)['output_tail']
        run=q.command([exe,ROOT/'roms/mk3'],temp,env=env,timeout=120)
        assert run['passed'],q.compact(run)['output_tail']
        out={};name=None
        for line in run['stdout'].splitlines():
            if line.startswith('@ '):name=line[2:];out[name]=[]
            elif line.startswith('strict '):out['strict']=line[7:]
            else:out[name].append(line)
    assert not cleanup['exists_after']
    return out,build['wall_seconds'],run['wall_seconds']


class AdspTimer(unittest.TestCase):
    def test_internal_timer_against_the_pinned_dcs_cpp(self):
        cases=scripts();got,build,run=native(cases)
        expires=0
        for name,ops in cases.items():
            want=Model().run(ops)
            self.assertEqual(got[name],want,name)
            expires+=sum(line.startswith('F ') for line in want)
        self.assertGreater(expires,40)
        self.assertTrue(any(l.startswith('reject MK3 ADSP internal timer target before') for l in got['count moved before the target']))
        self.assertTrue(got['unknown host timer'][-2].startswith('reject MK3 ADSP internal timer armed without'))
        sync=[line.split()[14] for line in got['not the list head'] if line.startswith('S ')]
        self.assertEqual((sync[3],sync[6]),('0','1'),'arming after the host timer does not abort; as the list head it does')
        # negative controls: every mutation of the transcription is detected
        for mutation in ('period','enable','scale','count','reload','abort','stub'):
            self.assertTrue(any(Model(mutation).run(ops)!=got[name] for name,ops in cases.items()),mutation)
        self.assertEqual(got['strict'],'MK3 ADSP internal timer path not compared with the Original (boot 0, PC 0, cycle 0);run;')
        print(json.dumps(dict(scripts=len(cases),expiries=expires,build_seconds=build,run_seconds=run)))


if __name__=='__main__':unittest.main()
