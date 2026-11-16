"""MK2 L3.1 per-instruction oracle: each emitted MK2 site against one TMS34010 step in the pinned MAME 0.280.

Evidence class (one-day plan, decision D9): "traduÃ§Ã£o igual ao Original por instruÃ§Ã£o, estado sintÃ©tico". Translator
evidence only, never route acceptance: nothing here marks a PC verified, injects state into the product or changes it.

Native side: the emitted case body of a site (native/mk2/*.inc, or `git show <rev>:` of them) is compiled against the
runtime ops the product uses (native/mk2/mk2_boot_ops.hpp BootOps), with the authentic program lanes, and run from the
vector's synthetic state. MAME side: tools/oracle/mame_step.py (front B) on driver mk2, through a rompath of hard links
named as the pinned driver expects (tools/mk2/roms-l31.json), removed with its scratch tree.
Compared: next PC, ST, the 31 registers, cycles and the watched RAM words. A native explicit rejection (throw) is
reported apart from a value mismatch. Device operands (absolute addresses outside main RAM) have no single-instruction
oracle and are listed, not run.

    python tools/oracle/mk2_oracle.py srl [--rev HEAD]          # the 42 SRL Rs,Rd sites
    python tools/oracle/mk2_oracle.py sweep --report build/native/day1/front-c.json [--forms "ADD R,R,SUB R,R"]
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,collections,hashlib,json,os,random,re,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.quality import run as q
from tools.oracle import inventory
from tools.mk2 import generate_video_irq as emitter
from tools.mk3.generate import form as form_of

RAM_LO,RAM_HI=0x01000000,0x013ffff0
WINDOW=0x01200000          # one fixed RAM window keeps mame_step's re-zeroed word set bounded
WORDS=96                   # 0x600 bits: data EAs in [W+0x100,W+0x480), SP at W+0x300 (MMTM/MMFM 16x32 bits fit)
SP0=WINDOW+0x300
NOP_PC=0xff80de70      # NOP (0x0300) in the L3.1 program ROM; mame_step checks the opcode
REGS=[f'a{i}' for i in range(15)]+['sp']+[f'b{i}' for i in range(15)]
WIDTHS=(0,1,6,8,16)        # FieldWidth() translated scope (mk2_boot_ops.hpp); others are an explicit native rejection
REJECT=inventory.REJECT
SITE_RE=re.compile(r'^case 0x([0-9a-f]{8})u: \{ // (.+?)\s*$')

# ---------------------------------------------------------------- sites
def texts(rev=None):
    for path in inventory.sources('mk2'):
        rel=path.relative_to(ROOT).as_posix()
        if rev:
            text=subprocess.run(['git','show',f'{rev}:{rel}'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8','replace')
        else:text=path.read_text('utf-8',errors='replace')
        yield path.name,text

def sites(rev=None):
    """pc -> dict(asm, form, code, files). code is the emitted statement line(s) between the case header and break."""
    found={}
    for name,text in texts(rev):
        lines=text.splitlines()
        for i,l in enumerate(lines):
            m=SITE_RE.match(l)
            if not m:continue
            body=[]
            for j in range(i+1,min(i+12,len(lines))):
                if lines[j]=='    break;':break
                body.append(lines[j])
            else:body=None
            pc=int(m.group(1),16);asm=m.group(2)
            code='\n'.join(body) if body is not None else None
            site=found.setdefault(pc,dict(pc=pc,asm=asm,form=form_of(asm),code=code,files=[]))
            site['files'].append(name)
            if site['code']!=code:site.setdefault('variants',set()).add(code)
    return found

def translated(site):
    return site['code'] is not None and not any(r in site['code'] for r in REJECT)

def git_rev():
    return subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True).stdout.strip()

# ---------------------------------------------------------------- operands
def sext16(v):return (v&0xffff)-((v&0x8000)<<1)

def parse(asm):
    op,*tail=asm.split(None,1)
    return op,(tail[0].split(',') if tail else [])

def reg_key(name):
    if name in ('SP','A15','B15'):return 'sp'
    return name.lower()

REG_NAME=re.compile(r'^(?:[AB](?:1[0-5]|[0-9])|SP)$')
MEM=re.compile(r'^(-?)\*([AB]\d+|SP)(?:\(([0-9A-F]+h)\))?(\+?)$')

def classify(site):
    """None (runnable) or the reason a site has no single-instruction oracle here."""
    op,args=parse(site['asm'])
    nop=site['code'] and re.fullmatch(r'\s*o\.Finish\(0x[0-9a-f]{8}u,1\);',site['code'])   # reserved dispatch (MAME no-op)
    if nop:return None
    for a in args:
        if a.startswith('@'):
            k=emitter.immediate(a[1:])
            if not RAM_LO<=k<=RAM_HI-64:return f'device operand @{k:08X} (outside main RAM)'
    if op in ('PIXBLT','FILL','LINE','PIXT','DRAV','CVXYL') and not nop:return 'graphics/pixel operand'
    if site['code'] and re.search(r'o\.(Record|DrawBitmapText|WriteXYPixel|FillXY|PixelRead)\(',site['code']):return 'device operation'
    return None

STACK_OPS=('CALL','CALLA','CALLR','RETS','RETI','TRAP','PUSHST','POPST','MMTM','MMFM')

def uses_memory(site):
    op,args=parse(site['asm'])
    return op in STACK_OPS or any(a.startswith(('*','-*','@')) for a in args)

EDGE=[(0,0),(0x80000000,0x7fffffff),(0xffffffff,1),(0x7fffffff,1),(0x80000000,0x80000000),(1,0xffffffff),(0x8000,0xffff8000),(0x10000,0xffff)]
COUNTS=[0,1,15,16,31,0xffffffff,0xfffffff1,0xfffffff0,0xffffffe1,32,33,0x80000010]

def vectors(site,n=8,seed=0,counts=None):
    """n synthetic states for one site; deterministic in (pc, seed)."""
    op,args=parse(site['asm'])
    rnd=random.Random(f"{site['pc']:08x}:{seed}")
    memory=uses_memory(site)
    out=[]
    for i in range(n):
        regs={r:rnd.getrandbits(32) for r in REGS}
        fs=[rnd.choice(WIDTHS),rnd.choice(WIDTHS)]
        st=(rnd.getrandbits(4)<<28)|fs[0]|(rnd.getrandbits(1)<<5)|(fs[1]<<6)|(rnd.getrandbits(1)<<11)
        direct=[a for a in args if REG_NAME.match(a)]
        if i<len(EDGE)-2 and direct:          # zero, sign, carry/borrow, overflow edges on the register operands
            x,y=EDGE[i]
            if len(direct)>=2:regs[reg_key(direct[0])],regs[reg_key(direct[-1])]=y,x
            else:regs[reg_key(direct[0])]=x
        if direct and (op in ('SLL','SRL','SRA','SLA','RL','BTST') and len(direct)==2 or op.startswith('DSJ')):
            pool=counts or COUNTS
            regs[reg_key(direct[0])]=pool[(i+seed*n)%len(pool)] if op[:3]!='DSJ' else (0,1,2,0xffffffff,0x80000000,3,0x7fffffff,rnd.getrandbits(32))[i%8]
        if op in ('DIVS','MODS') and len(direct)==2 and regs[reg_key(direct[0])]==0xffffffff and regs[reg_key(direct[-1])]==0x80000000:
            regs[reg_key(direct[0])]=1   # pinned MAME process hangs on INT_MIN/-1 (front B)
        mem={};watch=[]
        if memory:
            regs['sp']=SP0
            if op in ('MMTM','MMFM') and args[0]!='SP':regs[reg_key(args[0])]=SP0
            if op in ('RETS','RETI','POPST'):pass
            eas=[]
            for k,a in enumerate(args):
                m=MEM.match(a)
                if not m:continue
                pre,name,off,post=m.groups()
                field=int(args[2]) if op=='MOVE' and len(args)==3 else 0
                width=32 if op=='MOVB' else ((st>>(6*field))&31) or 32
                ea=WINDOW+0x100+16*rnd.randrange(0,48)+(rnd.randrange(16) if i==n-1 and op!='MOVB' else 0)
                if op=='MOVB' and i==n-1:ea+=rnd.randrange(16)
                if off:regs[reg_key(name)]=(ea-sext16(emitter.immediate(off)))&0xffffffff
                elif pre:regs[reg_key(name)]=(ea+width)&0xffffffff
                else:regs[reg_key(name)]=ea
                eas.append(ea)
            for w in range(WORDS):mem[WINDOW+16*w]=rnd.getrandbits(16)
            for a in args:
                if a.startswith('@'):
                    k=emitter.immediate(a[1:])&~15
                    if RAM_LO+32<=k<=RAM_HI-96:   # device addresses only reach here as reserved no-ops, never read
                        for w in range(-2,6):mem[k+16*w]=rnd.getrandbits(16)
            if op in ('RETS','RETI'):           # popped PC: aligned ROM-like target on even vectors, raw on odd
                t=(NOP_PC if op=='RETI' else 0xff800000|(rnd.getrandbits(23)<<4)) if i%2==0 else rnd.getrandbits(32)
                base=SP0+(32 if op=='RETI' else 0)
                mem[base]=t&0xffff;mem[base+16]=t>>16
            watch=sorted(mem)
        out.append(dict(id=f"s{site['pc']:08x}v{seed}_{i}",pc=site['pc'],st=st,regs=regs,mem=mem,watch=watch))
    return out

# ---------------------------------------------------------------- native harness
HARNESS=r'''
#include "native/mk2/mk2_boot_ops.hpp"
#include <cstdio>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
@SITES@
static void (*const kSites[])(mk2::BootOps&)={@TABLE@};
int main(int argc,char** argv){
    if(argc!=5)return 2;
    mk2::Program program;program.bytes.resize(0x100000);
    {std::ifstream e(argv[1],std::ios::binary),d(argv[2],std::ios::binary);
     std::vector<char> even(0x80000),odd(0x80000);e.read(even.data(),even.size());d.read(odd.data(),odd.size());
     if(!e||!d)return 3;
     for(size_t n=0;n<0x80000;++n){program.bytes[2*n]=uint8_t(even[n]);program.bytes[2*n+1]=uint8_t(odd[n]);}}
    std::vector<uint16_t> ram(262144);   // persists across vectors, as MAME's RAM does
    std::ifstream in(argv[3]);std::ofstream res(argv[4]);std::string line;
    while(std::getline(in,line)){
        // Fresh board per vector: one instruction from a synthetic state; the DCS side never reaches its program.
        auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        machine->link.HostWrite(0x01d01020,0);machine->link.Synchronize();
        auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.swap(ram);out->observe_history=false;
        auto& s=out->ready;s.board.io[8]=0x2000;
        mk2::BootOps o(program,*machine,*out);
        struct Back{std::vector<uint16_t>& a;std::vector<uint16_t>& b;~Back(){a.swap(b);}} back{ram,out->main_ram};
        std::istringstream ls(line);std::string id;unsigned site,count;uint32_t pc,st,r[31];
        ls>>id>>std::hex>>site>>pc>>st;for(auto& v:r)ls>>v;
        for(unsigned n=0;n<15;++n){s.a[n]=r[n];s.b[n]=r[16+n];}
        s.a[15]=r[15];
        ls>>count;
        for(unsigned n=0;n<count;++n){uint32_t a,v;ls>>a>>v;out->main_ram.at((a-0x01000000)/16)=uint16_t(v);}
        std::vector<uint32_t> watch;ls>>count;watch.resize(count);for(auto& a:watch)ls>>a;
        if(!ls){res<<"E "<<id<<" parse\n";continue;}
        s.status=st;s.next_pc=pc;const auto cycles=s.cycles;
        try{kSites[site](o);}
        catch(const std::exception& error){std::string m=error.what();for(auto& c:m)if(c=='\n')c=' ';res<<"E "<<id<<' '<<m<<"\n";continue;}
        res<<"R "<<id<<std::hex<<' '<<s.next_pc<<' '<<s.status<<std::dec<<' '<<(s.cycles-cycles)<<std::hex;
        for(unsigned n=0;n<15;++n)res<<' '<<s.a[n];
        res<<' '<<s.a[15];
        for(unsigned n=0;n<15;++n)res<<' '<<s.b[n];
        for(auto a:watch)res<<' '<<out->main_ram.at((a-0x01000000)/16);
        res<<std::dec<<"\n";
    }
    return 0;
}
'''

def zero_plan(chunk):
    """Exactly mame_step._setup's writes: unseeded watched words are written 0, then the seeded words; other words keep
    their value (vectors here seed every word their instruction can read)."""
    plans=[]
    for v in chunk:
        mem={a:w&0xffff for a,w in v['mem'].items()}
        plans.append([(a,0) for a in sorted(set(v['watch'])-set(mem))]+sorted(mem.items()))
    return plans

def native(bodies,chunks,scratch_note=None):
    """bodies: list of C++ statement strings (site index = position); chunks: lists of (site index, vector).
    Returns {vector id: result}. One compile, one process per chunk, in one scratch tree."""
    fns=''.join(f'static void site_{n}(mk2::BootOps& o){{auto& s=o.s;(void)s;\n{b}\n}}\n' for n,b in enumerate(bodies))
    source=HARNESS.replace('@SITES@',fns).replace('@TABLE@',','.join(f'site_{n}' for n in range(len(bodies))))
    results={};timing={}
    with q.scratch_tree() as (scratch,cleanup):
        cpp=scratch/'oracle.cpp';cpp.write_text(source,encoding='utf-8')
        exe=scratch/'oracle.exe'
        env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
        t=time.perf_counter()
        build=q.command([q.DEFAULT_CC,'-std=c++17','-O0','-w','-I'+str(ROOT),'-I'+str(ROOT/'native/include'),cpp,
                         ROOT/'native/mk2/mk2_adsp.cpp',ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp',
                         '-lbcrypt','-o',exe],scratch,env=env,timeout=3600)
        timing['native_build_s']=round(time.perf_counter()-t,1)
        if not build['passed']:raise RuntimeError('native harness build failed: '+build.get('stdout','')[-3000:])
        t=time.perf_counter()
        for c,chunk in enumerate(chunks):
            plans=zero_plan([v for _,v in chunk])
            lines=[]
            for (index,v),writes in zip(chunk,plans):
                r=' '.join(f"{v['regs'].get(k,0)&0xffffffff:x}" for k in REGS)
                lines.append(f"{v['id']} {index:x} {v['pc']:x} {v['st']&0xffffffff:x} {r} {len(writes):x} "+
                             ' '.join(f'{a:x} {w:x}' for a,w in writes)+f" {len(v['watch']):x} "+' '.join(f'{a:x}' for a in v['watch']))
            (scratch/'in.txt').write_text('\n'.join(lines)+'\n',encoding='ascii')
            run=q.command([exe,ROOT/'roms/mk2/uj12.l31',ROOT/'roms/mk2/ug12.l31',scratch/'in.txt',scratch/'out.txt'],scratch,env=env,timeout=3600)
            if not run['passed']:raise RuntimeError('native harness failed: '+str(run)[-2000:])
            watch={v['id']:v['watch'] for _,v in chunk}
            for line in (scratch/'out.txt').read_text('ascii').splitlines():
                kind,vid,*rest=line.split(' ',2) if line.startswith('E ') else line.split()
                if kind=='E':results[vid]=dict(id=vid,error='native: '+(rest[0] if rest else ''));continue
                pc,st,cycles,*vals=rest
                regs=dict(zip(REGS,(int(x,16) for x in vals[:31])))
                mem=dict(zip(watch[vid],(int(x,16) for x in vals[31:])))
                results[vid]=dict(id=vid,pc=int(pc,16),st=int(st,16),cycles=int(cycles),regs=regs,mem=mem,error=None)
        timing['native_run_s']=round(time.perf_counter()-t,1)
    timing['native_cleanup']=cleanup
    if cleanup.get('exists_after'):raise RuntimeError('native scratch retained')
    return results,timing

# ---------------------------------------------------------------- MAME adapter (mk2 rompath and identity only)
def mk2_identity():
    rom=emitter.load_program(ROOT/'roms/mk2')
    sha=hashlib.sha256(rom).hexdigest()
    if sha!=emitter.PROGRAM_SHA256:raise ValueError('MK2 L3.1 program identity changed')
    manifest=json.loads((ROOT/'tools/mk2/roms-l31.json').read_text('utf-8'))
    return dict(program_sha256=sha,roms=len(manifest['roms']))

def mame(chunks,workers=6,timeout=900):
    """chunks: lists of vectors; one mame_step.run per chunk, in parallel. Returns ({id: result}, receipts)."""
    from tools.oracle import mame_step
    manifest=json.loads((ROOT/'tools/mk2/roms-l31.json').read_text('utf-8'))
    identity=mk2_identity()
    results={};receipts=[]
    with q.scratch_tree() as (scratch,cleanup):
        roms=scratch/'mk2';roms.mkdir()
        for rom in manifest['roms']:
            name=rom['upstream_name']
            if Path(name).name!=name:raise ValueError('ROM name')
            os.link(ROOT/'roms/mk2'/rom['path'],roms/name)   # same-volume hard links: removal keeps the sources
        def one(chunk):return mame_step.run('mk2',chunk,rompath=scratch,nvram=None,verify=lambda:identity,nop_pc=NOP_PC,timeout=timeout)
        with ThreadPoolExecutor(workers) as pool:
            for res,receipt in pool.map(one,chunks):
                receipts.append(receipt)
                for r in res:results[r['id']]=r
    if cleanup.get('exists_after'):raise RuntimeError('rompath scratch retained')
    return results,receipts,cleanup

# ---------------------------------------------------------------- compare
def diff(v,exp,got):
    if exp.get('error') or got.get('error'):
        if exp.get('error')==got.get('error'):return None
        return dict(kind='native_reject' if (got.get('error') or '').startswith('native:') and not exp.get('error') else 'error',
                    expected_error=exp.get('error'),got_error=got.get('error'))
    d={}
    for k in ('pc','st','cycles'):
        if exp[k]!=got[k]:d[k]=(f'{exp[k]:x}',f'{got[k]:x}')
    for r in REGS:
        if exp['regs'][r]!=got['regs'][r]:d[r]=(f"{exp['regs'][r]:08x}",f"{got['regs'][r]:08x}")
    for a in v['watch']:
        if exp['mem'].get(a)!=got['mem'].get(a):d[f'mem{a:08x}']=(f"{exp['mem'].get(a,-1):04x}",f"{got['mem'].get(a,-1):04x}")
    if exp.get('writes') and not v['watch']:d['mame_writes']=exp['writes']
    return dict(kind='mismatch',fields=d) if d else None

def chunked(items,limit):
    """Split (index, vector) items keeping each chunk's union of seeded/watched words small."""
    chunks=[];cur=[];words=set()
    for item in items:
        w=set(item[1]['mem'])|set(item[1]['watch'])
        if cur and (len(cur)>=limit or len(words|w)>WORDS+64):chunks.append(cur);cur=[];words=set()
        cur.append(item);words|=w
    if cur:chunks.append(cur)
    return chunks

def compare(selected,*,n=8,seed=0,counts=None,limit=400,mutate=None,workers=6):
    """selected: list of sites. Runs native and MAME on the same vectors. Returns per-site records and timings."""
    bodies=[];items=[]
    for index,site in enumerate(selected):
        body=site['code'] if mutate is None else mutate(site)
        bodies.append(body)
        for v in vectors(site,n,seed,counts):items.append((index,v))
    chunks=chunked(items,limit)
    t=time.perf_counter()
    exp,receipts,mame_cleanup=mame([[v for _,v in c] for c in chunks],workers)
    mame_s=round(time.perf_counter()-t,1)
    got,timing=native(bodies,chunks)
    timing.update(mame_s=mame_s,mame_processes=len(receipts),mame_cleanup=mame_cleanup,
                  mame_receipt=dict(core_sha256=receipts[0]['core_sha256'],identity=receipts[0]['identity'],
                                    all_exit_passed=all(r['exit_passed'] for r in receipts),
                                    all_cleanup=all(not r['cleanup'].get('exists_after') for r in receipts)) if receipts else None)
    records=[]
    for index,site in enumerate(selected):
        rec=dict(pc=f"{site['pc']:08x}",asm=site['asm'],form=site['form'],vectors=0,mismatches=0,native_rejects=0,first=None)
        for i,v in items:
            if i!=index:continue
            rec['vectors']+=1
            e=exp.get(v['id'],dict(error='no MAME result'));g=got.get(v['id'],dict(error='no native result'))
            d=diff(v,e,g)
            if d is None:continue
            if d['kind']=='native_reject':rec['native_rejects']+=1
            else:rec['mismatches']+=1
            if rec['first'] is None or (rec['first']['diff']['kind']=='native_reject' and d['kind']!='native_reject'):
                rec['first']=dict(vector=v['id'],code=bodies[index],
                                  inputs=dict(st=f"{v['st']:08x}",regs={k:f'{x:08x}' for k,x in v['regs'].items()},
                                              mem_words=len(v['mem'])),diff=d)
        records.append(rec)
    return records,timing

# ---------------------------------------------------------------- selection
def stratified(form_sites,k=30,seed=0):
    if len(form_sites)<=k:return list(form_sites)
    rnd=random.Random(f'{form_sites[0]["form"]}:{seed}')
    groups=collections.defaultdict(list)
    for s in form_sites:groups[(s['files'][0],re.sub(r'[0-9A-F]+h','K',s['asm'].split(None,1)[-1]))].append(s)
    for g in groups.values():rnd.shuffle(g)
    keys=sorted(groups);rnd.shuffle(keys);out=[]
    while len(out)<k:
        for key in keys:
            if groups[key] and len(out)<k:out.append(groups[key].pop())
    return sorted(out,key=lambda s:s['pc'])

def srl_sites(rev=None):
    return [s for s in sites(rev).values() if s['form']=='SRL R,R']

SRL_COUNTS=[1,2,3,5,7,8,15,17,24,31,0,16]

def srl_check(rev=None):
    """Counts as the ROM idiom produces them (NEG then SRL): Rs=-n, plus Rs=+n; n with 32-n != n, n=0/16 controls."""
    sel=srl_sites(rev)
    counts=[(-n)&0xffffffff for n in SRL_COUNTS]+SRL_COUNTS
    return compare(sel,n=len(counts),counts=counts)

def abs_check(report_path):
    """ABS Rd=80000000h: V from the pinned binary on other sites/registers, read both from ST and through JRV/JRNV
    executed in MAME with the ST that MAME's ABS produced. Native results alongside, nothing changed."""
    S=sites()
    abs_sites=[S[pc] for pc in (0xff94aa80,0xff835a80,0xff8d90c0) if pc in S]
    jumps=[s for s in S.values() if s['form'] in ('JRV K','JRNV K') and translated(s)]
    jrv=min((s for s in jumps if s['form']=='JRV K'),key=lambda s:s['pc']);jrnv=min((s for s in jumps if s['form']=='JRNV K'),key=lambda s:s['pc'])
    vs=[]
    for site in abs_sites:
        reg=reg_key(parse(site['asm'])[1][0])
        for k,(value,st) in enumerate(((0x80000000,0x10),(0x80000000,0x10000010),(0x7fffffff,0x10000010),(0xffffffff,0x10))):
            vs.append(dict(id=f"abs{site['pc']:08x}_{k}",pc=site['pc'],st=st,regs={reg:value,'sp':SP0},mem={},watch=[]))
    exp,receipts,cleanup=mame([vs],1)
    got,_=native([s['code'] for s in abs_sites],[[(i//4,v) for i,v in enumerate(vs)]])
    follow=[]
    for v in vs:
        st=exp[v['id']]['st']
        for j in (jrv,jrnv):follow.append(dict(id=f"{v['id']}_{j['form'][:4].strip()}",pc=j['pc'],st=st,regs={'sp':SP0},mem={},watch=[]))
    exp2,_,cleanup2=mame([follow],1)
    rows=[]
    for v in vs:
        e,g=exp[v['id']],got[v['id']]
        reg=next(k for k in v['regs'] if k!='sp')
        taken={}
        for j in (jrv,jrnv):
            r=exp2[f"{v['id']}_{j['form'][:4].strip()}"]
            taken[j['form'].split()[0]]=r['pc']!=j['pc']+16 and r['pc']!=j['pc']+32
        rows.append(dict(vector=v['id'],asm=next(s['asm'] for s in abs_sites if s['pc']==v['pc']),input=f"{v['regs'][reg]:08x}",st_in=f"{v['st']:08x}",
                         mame_st=f"{e['st']:08x}",mame_V=(e['st']>>28)&1,mame_reg=f"{e['regs'][reg]:08x}",
                         mame_JRV_taken=taken['JRV'],mame_JRNV_taken=taken['JRNV'],
                         native_st=f"{g['st']:08x}" if not g.get('error') else g['error'],native_V=(g['st']>>28)&1 if not g.get('error') else None))
    out=dict(jrv_site=f"{jrv['pc']:08x} {jrv['asm']}",jrnv_site=f"{jrnv['pc']:08x} {jrnv['asm']}",rows=rows,
             note='34010ops.hxx ABS: r=0-*rd (int32, overflows for 80000000h); SET_V_LOG(r==(int32_t)0x80000000). TI manual: V=1 on overflow.',
             status='open: user decision (pinned binary vs TI manual/source text); native unchanged',cleanup=[cleanup,cleanup2])
    state=json.loads(report_path.read_text('utf-8')) if report_path.is_file() else {}
    state.setdefault('checks',{})['abs_v']=out;save(report_path,state)
    print(json.dumps(out,indent=1,default=str))

def field_probe(report_path):
    """Front B's MK3 field cases measured on MK2: FS0=24 reads/writes crossing a dword ('wfieldmac-big')."""
    S=sites()
    rd=next(s for s in sorted(S.values(),key=lambda s:s['pc']) if s['form']=='MOVE *R,R,0' and translated(s))
    wr=next(s for s in sorted(S.values(),key=lambda s:s['pc']) if s['form']=='MOVE R,*R,0' and translated(s))
    a_rd,d_rd=[reg_key(x) for x in parse(rd['asm'])[1][:2]];d_rd=reg_key(parse(rd['asm'])[1][1]);a_rd=reg_key(parse(rd['asm'])[1][0][1:])
    src_wr=reg_key(parse(wr['asm'])[1][0]);a_wr=reg_key(parse(wr['asm'])[1][1][1:])
    words={0x01100000:0x1111,0x01100010:0x2222,0x01100020:0x3333,0x01100030:0x4444}
    vs=[dict(id='field_read',pc=rd['pc'],st=0x18,regs={a_rd:0x0110000c,'sp':SP0},mem=dict(words),watch=sorted(words)),
        dict(id='field_write',pc=wr['pc'],st=0x18,regs={src_wr:0xabcdef,a_wr:0x0110000c,'sp':SP0},mem=dict(words),watch=sorted(words))]
    exp,_,c1=mame([vs],1)
    got,_=native([rd['code'],wr['code']],[[(0,vs[0]),(1,vs[1])]])
    def show(r,reg):
        if r.get('error'):return dict(error=r['error'])
        return dict(reg=f"{r['regs'][reg]:08x}",words=[f"{r['mem'][a]:04x}" for a in sorted(words)])
    out=dict(read=dict(site=f"{rd['pc']:08x} {rd['asm']}",mame=show(exp['field_read'],d_rd),native=show(got['field_read'],d_rd)),
             write=dict(site=f"{wr['pc']:08x} {wr['asm']}",label='wfieldmac-big',mame=show(exp['field_write'],src_wr),
                        native=show(got['field_write'],src_wr),hardware_expected=['f111','bcde','333a','4444']),
             cleanup=c1)
    state=json.loads(report_path.read_text('utf-8')) if report_path.is_file() else {}
    state.setdefault('checks',{})['field_fs24']=out;save(report_path,state)
    print(json.dumps(out,indent=1,default=str))

def mutated(site):
    """Negative control: flip the first boolean of the emitted call, else bump the next-PC constant."""
    code=site['code']
    for x,y in (('false','true'),('true','false')):
        if x in code:return code.replace(x,y,1)
    nxt=f"0x{(site['pc']+16)&0xffffffff:08x}u"
    return code.replace(nxt,f"0x{(site['pc']+32)&0xffffffff:08x}u",1) if nxt in code else code+' s.a[0]^=1;'

NEGATIVE_FORMS=('ADD R,R','SUB R,R','SRL K,R','MOVE R,*R(K),1','JRNE K','MMTM R,R-R','SLL R,R','RL K,R')

def negative(report_path):
    all_sites=sites();by=collections.defaultdict(list)
    for s in all_sites.values():
        if translated(s) and classify(s) is None:by[s['form']].append(s)
    sel=[sorted(by[f],key=lambda s:s['pc'])[0] for f in NEGATIVE_FORMS if by[f]]
    records,timing=compare(sel,n=8,mutate=mutated)
    out=dict(forms=list(NEGATIVE_FORMS),sites=[dict(pc=r['pc'],asm=r['asm'],vectors=r['vectors'],detected=r['mismatches'],
                                                    mutated=r['first']['code'] if r['first'] else mutated(s))
                                               for r,s in zip(records,sel)],
             all_detected=all(r['mismatches'] for r in records),timing=timing)
    state=json.loads(report_path.read_text('utf-8')) if report_path.is_file() else {}
    state['negative_control']=out
    report_path.write_text(json.dumps(state,indent=1,default=str)+'\n',encoding='utf-8')
    print(json.dumps(out,indent=1,default=str))

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=a.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('srl');s.add_argument('--rev');s.add_argument('--report')
    ng=sub.add_parser('negative');ng.add_argument('--report',required=True)
    ab=sub.add_parser('abs');ab.add_argument('--report',required=True)
    fp=sub.add_parser('field');fp.add_argument('--report',required=True)
    w=sub.add_parser('sweep');w.add_argument('--report',required=True);w.add_argument('--forms');w.add_argument('--per-form',type=int,default=30)
    w.add_argument('--vectors',type=int,default=8);w.add_argument('--workers',type=int,default=6);w.add_argument('--batch',type=int,default=20)
    w.add_argument('--batch-sites',type=int,default=4000)
    w.add_argument('--key',default='forms',help="receipt section; 'all_sites' with a large --per-form runs every site")
    c=sub.add_parser('pcs');c.add_argument('--pcs',required=True);c.add_argument('--rev');c.add_argument('--vectors',type=int,default=8)
    c.add_argument('--report');c.add_argument('--name',default='pcs')
    args=a.parse_args()
    if args.cmd=='srl':
        records,timing=srl_check(args.rev)
        if args.report:
            report=Path(args.report);state=json.loads(report.read_text('utf-8')) if report.is_file() else {}
            state.setdefault('srl',{})[args.rev or 'worktree']=dict(summarize(records,timing),sites=len(records),
                counts=[f'{c:08x}' for c in [(-n)&0xffffffff for n in SRL_COUNTS]+SRL_COUNTS],
                per_site=[dict(pc=r['pc'],asm=r['asm'],vectors=r['vectors'],mismatches=r['mismatches']) for r in records])
            save(report,state)
        print(json.dumps(dict(rev=args.rev or 'worktree',sites=len(records),vectors=sum(r['vectors'] for r in records),
                              mismatching_sites=sum(1 for r in records if r['mismatches']),
                              mismatches=sum(r['mismatches'] for r in records),first=next((r for r in records if r['first']),None),
                              timing=timing),indent=1,default=str))
        return
    if args.cmd=='negative':return negative(Path(args.report))
    if args.cmd=='abs':return abs_check(Path(args.report))
    if args.cmd=='field':return field_probe(Path(args.report))
    if args.cmd=='pcs':return pcs_check(args)
    sweep(args)

def summarize(records,timing=None):
    e=dict(vectors=sum(r['vectors'] for r in records),mismatches=sum(r['mismatches'] for r in records),
           native_rejects=sum(r['native_rejects'] for r in records),
           mismatching_sites=sum(1 for r in records if r['mismatches']),
           mismatching_pcs=[r['pc'] for r in records if r['mismatches']][:40],
           rejecting_pcs=[r['pc'] for r in records if r['native_rejects']][:40],
           first_mismatch=next((r for r in records if r['mismatches']),None) or next((r for r in records if r['first']),None))
    if timing:e['timing']=timing
    return e

def save(report,state):
    state.update(schema='day1-front-c/1',evidence='tradução igual ao Original por instrução, estado sintético',
                 scope='translator evidence only (D9): synthetic state, one instruction; never route acceptance or verified',
                 game='mk2',git_head=git_rev())
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(state,indent=1,default=str)+'\n',encoding='utf-8')

def sweep(args):
    report=Path(args.report)
    started=time.perf_counter()
    all_sites=sites()
    by_form=collections.defaultdict(list)
    for site in all_sites.values():by_form[site['form']].append(site)
    wanted=[f.strip() for f in args.forms.split(';')] if args.forms else sorted(by_form)
    state=json.loads(report.read_text('utf-8')) if report.is_file() else {}
    forms=state.setdefault(args.key,{})
    pending=[]
    for name in wanted:
        group=sorted(by_form[name],key=lambda s:s['pc'])
        ok=[s for s in group if translated(s)]
        if not ok:
            forms[name]=dict(status='untranslated guard (left as is)',sites=len(group),translated=0);continue
        devices=[(s,classify(s)) for s in ok]
        runnable=[s for s,c in devices if c is None]
        listed=[dict(pc=f"{s['pc']:08x}",asm=s['asm'],reason=c) for s,c in devices if c]
        sel=stratified(runnable,args.per_form)
        forms[name]=dict(sites=len(group),translated=len(ok),device_sites=len(listed),device_examples=listed[:5],
                         selected=len(sel),status='device operands only' if not sel else 'pending')
        if sel:pending.append((name,sel))
    save(report,state)
    groups=[];cur=[]
    for item in pending:   # at most --batch forms and about --batch-sites sites per compile
        if cur and (len(cur)>=args.batch or sum(len(x[1]) for x in cur)+len(item[1])>args.batch_sites):groups.append(cur);cur=[]
        cur.append(item)
    if cur:groups.append(cur)
    for batch in groups:
        t=time.perf_counter()
        flat=[s for _,sel in batch for s in sel]
        records,timing=compare(flat,n=args.vectors,workers=args.workers)
        state.setdefault(args.key+'_batches',[]).append(dict(forms=len(batch),sites=len(flat),seconds=round(time.perf_counter()-t,1),
                                                    timing=timing))
        for name,sel in batch:
            mine=[r for r in records if r['form']==name]
            e=forms[name];e.update(summarize(mine))
            e['status']=('match' if not e['mismatches'] and not e['native_rejects'] else
                         'mismatch' if e['mismatches'] else 'native rejections')
            print(name,e['status'],e['vectors'],e['mismatches'],e['native_rejects'],flush=True)
        save(report,state)
    state[args.key+'_seconds']=round(time.perf_counter()-started,1);save(report,state)
    print('sweep seconds',state[args.key+'_seconds'])

def pcs_check(args):
    all_sites=sites(args.rev)
    wanted=[int(x,16) for x in args.pcs.split(',')]
    sel=[all_sites[pc] for pc in wanted if pc in all_sites]
    records,timing=compare(sel,n=args.vectors)
    out=summarize(records,timing)
    out['absent_pcs']=[f'{pc:08x}' for pc in wanted if pc not in all_sites]
    out['records']=[dict(pc=r['pc'],asm=r['asm'],vectors=r['vectors'],mismatches=r['mismatches'],native_rejects=r['native_rejects'])
                    for r in records]
    if args.report:
        report=Path(args.report);state=json.loads(report.read_text('utf-8')) if report.is_file() else {}
        state.setdefault('checks',{})[args.name]=dict(rev=args.rev or 'worktree',**out);save(report,state)
    print(json.dumps(out,indent=1,default=str))

if __name__=='__main__':main()
