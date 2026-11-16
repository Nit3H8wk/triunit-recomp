"""Per-instruction oracle of the MK3 2.1 translator (tools/mk3/generate.py) against the pinned MAME 0.280 (mame_step).

Evidence label (decision D9): "tradução igual ao Original por instrução, estado sintético". Translator evidence, not
route acceptance: no PC becomes verified, no route receipt is written, the product receives no state.

For each translated site chosen (every site of a form with <= 30, else 30 stratified by operand registers), the C++
case body the generator emits for that PC (the same text as the unit) runs in a native harness against
native/mk3/mk3_cpu.hpp (Profile::Game, no first-execution log), and the same instruction runs once in MAME through
mame_step from the same synthetic state. Compared: the 31 registers, ST, next PC, cycles, the watched memory words
and the number of main-CPU write accesses; the native writes must also stay inside the watched words.

Vectors (about 8 per site): zero, sign bits, carry/borrow/overflow edges, random; ST flags and field sizes vary; a
register shift/field count takes 0, 1, 15, 16, 31, -1, -16, -31. Address registers point into a RAM window seeded
with random words; the stack pointer points into a separate seeded RAM window. FILL/PIXBLT/LINE run with RAM
destinations and sources, no window or raster op, to completion through their restarts (graphics()). Absolute
operands outside RAM and program ROM are "operando de dispositivo": listed, not tested. Reserved opcodes (o.Reserved)
have no operand access and are always tested. Mismatches reduced to a recorded MAME defect where the chip is the Original (D10)
are counted and labelled by known_class(); every other mismatch is "unexplained".

    python tools/oracle/mk3_oracle.py [--receipt build/native/day1/front-b.json] [--forms 'ADDC R,R;SRL K,R'] [--jobs 5]
    python tools/oracle/mk3_oracle.py --control      # self-validation: route-verified sites equal, mutated emitter differs
    python tools/oracle/mk3_oracle.py --reserved     # every reserved-opcode site
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,collections,json,os,random,re,sys,threading,time
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.quality import run as q
from tools.mk3 import generate,roms
from tools.oracle import mame_step

RAM_LO,RAM_HI=0x01000000,0x013fffff
DATA=0x01100000       # address-register window (bit address)
STACK=0x01300000      # stack window
PIXEL=0x01200000      # pixel base (B4) for XY forms
M=0xffffffff
CASE=re.compile(r'case 0x([0-9a-f]{8})u: \{ // (.*)\n    (.*)\n    break;\n\}')
REG=r'(?:[AB](?:1[0-5]|[0-9])|SP)'
GRAPHICS=('PIXBLT','FILL','LINE')
COUNT_FORMS={'SLA R,R','SLL R,R','SRA R,R','SRL R,R','RL R,R','BTST R,R'}
IO_CONTROL,IO_PSIZE,IO_CONVSP,IO_CONVDP,IO_DPYCTL=11,21,19,20,8

def load():
    """rows, rom and {pc: (asm, size, raw, code)} of every case the generator emits (translated or not)."""
    rom=roms.program_image(ROOT/'roms/mk3',roms.definition());rows,_=generate.scan(rom)
    text,_=generate.units(rom,rows);cases={}
    for name,src in text.items():
        for m in CASE.finditer(src):
            pc=int(m[1],16);size,_,raw,asm=rows[pc];cases[pc]=(m[2].strip(),size,raw,m[3])
    return rom,rows,cases

def translated(code):return not any(r in code for r in ('o.Reject(','throw std::runtime_error','untranslated'))

def operands(asm):
    op,*rest=asm.split(None,1);return op,(rest[0].split(',') if rest else [])

def regs_of(arg):
    """Registers named by one operand (ranges A0-A14 expanded)."""
    m=re.fullmatch(rf'({REG})-({REG})',arg)
    if m:
        a,b=(('A15' if x=='SP' else x) for x in m.groups())
        return [f'{a[0]}{i}' if not (i==15) else 'SP' for i in range(int(a[1:]),int(b[1:])+1)]
    return re.findall(rf'\b{REG}\b',arg)

def name(r):return 'sp' if r in ('SP','A15','B15') else r.lower()

def classify(asm,rom,code=''):
    """None if testable here, else the reason it is an operando de dispositivo. A reserved opcode (34010tbl.hxx unimpl,
    emitted as o.Reserved) has no operand access at all: always testable."""
    op,args=operands(asm)
    if 'o.Reserved(' in code:return None
    for a in args:
        if a.startswith('@'):
            x=int(a[1:-1],16)
            if not (RAM_LO<=x<=RAM_HI-64 or x>=0xff800000):return f'absolute operand {x:08x} outside RAM/ROM'
            if x>=0xff800000 and op in ('MOVE','MOVB') and args.index(a)==len(args)-1-(1 if args[-1] in '01' else 0):
                return f'write to program ROM {x:08x}'
    return None

def graphics(pc,handler,rng,count):
    """FILL/PIXBLT/LINE vectors (34010gfx.hxx): destination and source in seeded RAM windows, window checking and raster
    ops off (CONTROL 0 or 0x20 transparency), PSIZE 16/8/4, pitches 256 bits (CONVSP/CONVDP 0x17), small DYDX; run to
    completion through the restarts (restart=True in MAME, the same loop in the native harness)."""
    out=[];pix=list(range(PIXEL,PIXEL+16*160,16));src=list(range(DATA,DATA+16*96,16))   # LINE: up to 8 rows of 256 bits
    for k in range(count):
        psize=[16,8,4,16,8,16,8,4][k];regs={name(f'{b}{i}'):rng.getrandbits(32) for b in 'AB' for i in range(15)}
        regs['sp']=STACK
        xy=lambda:(rng.randrange(0,3)<<16)|rng.randrange(0,8)
        lin=lambda base:base+psize*rng.randrange(0,8)
        regs.update(b1=256,b3=256,b4=PIXEL,b7=(rng.randrange(1,4)<<16)|rng.randrange(1,13),b5=0,b6=0x00400040)
        regs['b2']=lin(PIXEL) if handler in ('fill_l','pixblt_l_l','pixblt_xy_l','pixblt_b_l') else xy()
        regs['b0']=lin(DATA) if handler in ('pixblt_l_l','pixblt_l_xy','pixblt_b_l','pixblt_b_xy') else xy()
        if handler=='line':
            regs.update(b0=rng.randrange(-4,4)&M,b10=rng.randrange(0,7),b11=rng.choice([0x00010000,0x00000001,0x00010001]),
                        b12=rng.choice([0x00000001,0x00010000]),b7=(rng.randrange(0,4)<<16)|rng.randrange(0,8))
        if k==0:regs['b7']=0   # zero extent: returns before ST.P
        io={IO_CONTROL:[0,0x20][k%2],IO_PSIZE:psize,IO_CONVSP:0x17,IO_CONVDP:0x17,IO_DPYCTL:0}
        mem={w:rng.getrandbits(16) for w in pix+src}
        out.append(dict(id=f'{pc:08x}_{k}',pc=pc,st=[0x10,0x20000010][k%2],regs=regs,mem=mem,watch=pix+src,io=io,restart=True))
    return out

def vectors(pc,asm,size,rng,count=8,raw=None):
    """Synthetic inputs for one site (module docstring). Returns a list of mame_step vectors (watch words included)."""
    op,args=operands(asm);form=generate.form(asm)
    h=generate.handler(raw) if raw else None
    if h in ('fill_l','fill_xy','line') or (h or '').startswith('pixblt'):return graphics(pc,h,rng,count)
    mem_args=[a for a in args if '*' in a]
    addr_regs={name(regs_of(a)[0]) for a in mem_args}
    if op in ('MMTM','MMFM'):addr_regs={name(args[0])}
    data_regs=[name(r) for a in args if '*' not in a and not a.startswith('@') for r in regs_of(a)]
    if op in ('MMTM','MMFM'):data_regs=[name(r) for a in args[1:] for r in regs_of(a)]
    pixel='PIXT' in op or op in ('DRAV','CVXYL','CVSXYL','CPW','LINE')
    xy=pixel and ('XY' in args or op in ('DRAV','CVXYL'))
    edges=[(0,0),(0x80000000,0x80000000),(0xffffffff,0x80000000),(0x7fffffff,0xffffffff),(1,0x7fffffff)]
    counts=[0,1,15,16,31,M,(-16)&M,(-31)&M]
    sts=[0x10,0xf0000010,0x40000010,0x20000810]
    out=[]
    for k in range(count):
        regs={name(f'{b}{i}'):rng.getrandbits(32) for b in 'AB' for i in range(15)}
        regs['sp']=STACK+16*rng.randrange(-8,8)
        for j,r in enumerate(data_regs):
            if r in addr_regs:continue
            regs[r]=edges[k][j%2] if k<len(edges) else rng.choice([rng.getrandbits(32),rng.getrandbits(5),rng.getrandbits(16)])
        if form in COUNT_FORMS:regs[data_regs[0]]=counts[k%len(counts)]
        if op in ('DSJ','DSJS','DSJEQ','DSJNE') and k<3:regs[data_regs[0]]=k
        if op in ('DIVS','MODS') and len(data_regs)>1 and regs[data_regs[0]]==M and regs[data_regs[1]]==0x80000000:
            # MAME 0.280 has no result for INT_MIN / -1 (the host division faults and the process hangs): no oracle there
            regs[data_regs[1]]=0x80000001
        for r in addr_regs:   # bit address in the data window: aligned words, bit offsets for field/byte moves
            field=op in ('MOVE','MOVB')
            off=rng.randrange(0,256) if field and k>=4 else 16*rng.randrange(0,16)
            if r=='sp' or op in ('MMTM','MMFM'):off=16*rng.randrange(0,8)
            base=(STACK if r=='sp' else DATA)+off
            disp=[a for a in mem_args if name(regs_of(a)[0])==r and '(' in a]
            if disp:   # *R(K): the effective address lands at base
                d=int(re.search(r'\(([0-9A-F]+)h\)',disp[0])[1],16);d=d-0x10000 if d&0x8000 else d
                base=(base-d)&M
            regs[r]=base
        st=sts[k] if k<len(sts) else (rng.getrandbits(32)&0xf0000fff)|0x10*rng.randrange(2)
        io={}
        if pixel:
            io={IO_CONTROL:[0x20,0x00,0xa0,0x20,0x60,0xe0,0x20,0x80][k],IO_PSIZE:[8,16,8,4,8,16,2,8][k],
                IO_CONVSP:0x17,IO_CONVDP:0x17,IO_DPYCTL:0}
            regs['b4']=PIXEL;regs['b5']=rng.choice([0,0x00010002]);regs['b6']=rng.choice([0x00030010,0x00100020,0x00020004])
            if xy:
                for a in args:
                    for r in regs_of(a):
                        if name(r) not in ('b4','b5','b6') and (('*' in a) or name(r) in data_regs):
                            regs[name(r)]=(rng.randrange(0,4)<<16)|rng.randrange(0,16) if k else 0
            for r in addr_regs:
                if not xy:regs[r]=PIXEL+8*rng.randrange(0,32)
        # memory: random words around every address register, the stack and RAM absolute operands; all watched
        words=set()
        for r in addr_regs|{'sp'}:
            v=regs[r]
            if not (RAM_LO<=v<=RAM_HI):continue
            span=(576 if op in ('MMTM','MMFM') else 160)
            lo=max(RAM_LO,(v-span)&~15);words|=set(range(lo,min(RAM_HI,v+span)&~15,16))
        for a in args:
            if a.startswith('@'):
                x=int(a[1:-1],16)
                if RAM_LO<=x<=RAM_HI:words|=set(range((x-64)&~15,(x+96)&~15,16))
        disp_words=set()
        for a in mem_args:   # *R(K): the base register itself also gets a seeded window
            r=name(regs_of(a)[0])
            if '(' in a:
                d=int(re.search(r'\(([0-9A-F]+)h\)',a)[1],16);d=d-0x10000 if d&0x8000 else d
                ea=(regs[r]+d)&M
                if RAM_LO<=ea<=RAM_HI:disp_words|=set(range((ea-96)&~15,(ea+128)&~15,16))
        words|=disp_words
        if xy or pixel:words|=set(range(PIXEL,PIXEL+16*80,16))
        mem={w:rng.getrandbits(16) for w in words}
        if pixel:mem.update({w:rng.choice([0,rng.getrandbits(16)]) for w in range(PIXEL,PIXEL+16*80,16)})
        out.append(dict(id=f'{pc:08x}_{k}',pc=pc,st=st,regs=regs,mem=mem,watch=sorted(words),io=io))
    return out

def select(sites,limit=30):
    """All sites up to `limit`, else round-robin over the operand-register signature groups (stratified)."""
    if len(sites)<=limit:return list(sites)
    groups=collections.defaultdict(list)
    for pc,asm in sites:groups[tuple(re.findall(rf'\b{REG}\b',asm))].append((pc,asm))
    keys=sorted(groups);picked=[]
    while len(picked)<limit:
        for key in keys:
            if groups[key] and len(picked)<limit:picked.append(groups[key].pop(len(groups[key])//2))
    return sorted(picked)

HARNESS=r'''#include "mk3_cpu.hpp"
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
namespace {
using Site = void(*)(mk3::Ops&);
SITES
}
int main(int argc, char** argv) {
    mk3::Program program = mk3::LoadProgram(argv[2]);
    std::ifstream in(argv[1]); std::string line;
    while (std::getline(in, line)) {
        std::istringstream v(line); std::string id; unsigned site, restart; uint32_t pc, st; v >> id >> site >> restart >> std::hex >> pc >> st;
        mk3::ResetTrace s; mk3::Ops o(program, s, std::vector<uint16_t>(0x6000));
        o.profile = mk3::Profile::Game;
        for (int i = 0; i < 16; ++i) v >> s.a[i];
        for (int i = 0; i < 15; ++i) v >> s.b[i];
        unsigned n; v >> std::dec >> n;
        for (unsigned i = 0; i < n; ++i) { unsigned k, x; v >> std::dec >> k >> std::hex >> x; o.video.io[k] = uint16_t(x); o.io_written |= 1u << k; }
        v >> std::dec >> n;
        for (unsigned i = 0; i < n; ++i) { uint32_t a, x; v >> std::hex >> a >> x; o.ram.at((a - 0x01000000u) / 16) = uint16_t(x); }
        v >> std::dec >> n; std::vector<uint32_t> watch(n);
        for (auto& a : watch) v >> std::hex >> a;
        s.pc = pc; s.status = st; std::string error;
        o.Begin();
        try {   // restartable graphics ops: re-execute at the same PC while ST.P is set, as MAME does (bounded)
            kSites[site](o);
            for (int n = 0; restart && s.pc == pc && (s.status & (1u << 25)) && n < 100000; ++n) kSites[site](o);
        } catch (const std::exception& e) { error = e.what(); }
        for (auto& c : error) if (c == '"' || c == '\\') c = '\'';
        std::printf("{\"id\":\"%s\",\"pc\":%u,\"st\":%u,\"cycles\":%llu,\"writes\":%zu,\"error\":%s%s%s,\"regs\":[", id.c_str(), s.pc, s.status,
                    (unsigned long long)s.cycles, s.writes.size(), error.empty() ? "" : "\"", error.empty() ? "null" : error.c_str(), error.empty() ? "" : "\"");
        for (int i = 0; i < 15; ++i) std::printf("%u,", s.a[i]);
        std::printf("%u", s.a[15]);
        for (int i = 0; i < 15; ++i) std::printf(",%u", s.b[i]);
        std::printf("],\"mem\":[");
        for (size_t i = 0; i < watch.size(); ++i) std::printf("%s%u", i ? "," : "", unsigned(o.ram.at((watch[i] - 0x01000000u) / 16)));
        std::printf("],\"outside\":[");
        size_t k = 0;
        for (const auto& w : s.writes) if (std::find(watch.begin(), watch.end(), w.address_bit) == watch.end()) std::printf("%s%u", k++ ? "," : "", w.address_bit);
        std::printf("]}\n");
    }
    return 0;
}
'''
NATIVE_ORDER=[f'a{i}' for i in range(15)]+['sp']+[f'b{i}' for i in range(15)]

def native(sites,vecs,label='n'):
    """sites: {pc: code}; vecs: mame_step vectors of those sites. Returns {id: result} in mame_step's result shape."""
    index={pc:i for i,pc in enumerate(sorted(sites))}
    fns='\n'.join(f'void S{i}(mk3::Ops& o) {{ [[maybe_unused]] auto& s = o.s; switch (0) {{ default: {{ {sites[pc]} }} }} }}' for pc,i in index.items())
    table='const Site kSites[] = {'+','.join(f'S{i}' for i in range(len(index)))+'};'
    source=HARNESS.replace('SITES',fns+'\n'+table)
    lines=[]
    for v in vecs:
        r=v['regs'];a=[r.get(x,0)&M for x in NATIVE_ORDER]
        regs=' '.join(f'{x:x}' for x in a[:16])+' '+' '.join(f'{x:x}' for x in a[16:])
        io=' '.join(f'{k} {x:x}' for k,x in sorted(v.get('io',{}).items()))
        mem=' '.join(f'{k:x} {x:x}' for k,x in sorted(v['mem'].items()))
        lines.append(f"{v['id']} {index[v['pc']]} {int(bool(v.get('restart')))} {v['pc']:x} {v['st']&M&~mame_step.P_BIT&~mame_step.IE_MASK:x} {regs} {len(v.get('io',{}))} {io} {len(v['mem'])} {mem} {len(v['watch'])} {' '.join(f'{w:x}' for w in v['watch'])}")
    cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        (temp/'h.cpp').write_text(source,encoding='utf-8');(temp/'v.txt').write_text('\n'.join(lines)+'\n',encoding='ascii');exe=temp/'h.exe'
        t=time.perf_counter()
        build=q.command([cc,'-std=c++17','-O1','-w','-static','-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/include'),temp/'h.cpp',
                         ROOT/'native/mk3/mk3_program.cpp',ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],temp,env=env,timeout=1800,parallel_cpp=False)
        if not build['passed']:raise RuntimeError('native harness build failed: '+q.compact(build)['output_tail'][-2000:])
        compile_s=time.perf_counter()-t
        run=q.command([exe,temp/'v.txt',ROOT/'roms/mk3'],temp,env=env,timeout=1800,output_limit=512*1024*1024)
        if not run['passed']:raise RuntimeError('native harness run failed: '+q.compact(run)['output_tail'][-2000:])
        out={}
        for line in run['stdout'].splitlines():
            if line.startswith('{'):d=json.loads(line);out[d['id']]=d
    if cleanup['exists_after']:raise RuntimeError('native scratch retained')
    for v in vecs:
        d=out.get(v['id'])
        if d is None:continue
        d['regs']=dict(zip(NATIVE_ORDER,d['regs']));d['mem']=dict(zip(v['watch'],d['mem']))
    return out,dict(compile_seconds=round(compile_s,1),run_seconds=run.get('wall_seconds'))

def compare(v,n,m):
    """None if equal, else (field, expected (MAME), got (native))."""
    if m.get('error'):return ('mame',m['error'],None)
    if n is None:return ('native','no result',None)
    if n['error']:return ('native_reject',None,n['error'])
    for f in ('pc','st','cycles','writes'):
        if n[f]!=m[f]:return (f,m[f],n[f])
    for r in NATIVE_ORDER:
        if n['regs'][r]!=m['regs'][r]:return (r,m['regs'][r],n['regs'][r])
    for a in v['watch']:
        if n['mem'][a]!=m['mem'][a]:return (f'mem {a:08x}',m['mem'][a],n['mem'][a])
    if n['outside']:return ('native write outside watch',None,n['outside'][:4])
    return None

def known_class(v,n,m,asm,diff):
    """Label of a mismatch fully reduced to a recorded MAME 0.280 defect where D10 (15/11, "Siga o hardware") makes the
    chip the Original, else None. Exact per-vector conditions: every compared field outside the defect must be equal."""
    if n is None or n.get('error') or m.get('error'):return None
    op,args=operands(asm);r=v['regs'];st=v['st']
    same=lambda skip:all(n[f]==m[f] for f in ('pc','cycles','writes') if f not in skip) and n['regs']==m['regs'] and not n['outside']
    if op=='ABS' and r[name(args[0])]==0x80000000:   # pinned binary V=0; 34010ops.hxx:327 text and the TI manual V=1
        return 'abs-v' if same(()) and n['mem']==m['mem'] and n['st']^m['st']==0x10000000 and n['st']&0x10000000 else None
    if op!='MOVE' or args[-1] not in '01' or not diff[0].startswith(('writes','mem')):return None
    f=int(args[-1]);w=(st>>(6*f))&31 or 32
    if not 18<=w<=31:return None
    def ea(a,bump):
        reg=name(regs_of(a)[0]) if regs_of(a) else None
        if a.startswith('@'):return int(a[1:-1],16)
        x=(r[reg]+bump.get(reg,0))&M
        if a.startswith('-*'):return (x-w)&M
        if '(' in a:d=int(re.search(r'\(([0-9A-F]+)h\)',a)[1],16);return (x+(d-0x10000 if d&0x8000 else d))&M
        return x
    def bits(a):   # the w-bit field at bit address a of the input words (TI field definition)
        b=a&~15;return sum(v['mem'].get(b+16*k,0)<<(16*k) for k in range(3))>>(a&15)&((1<<w)-1)
    bump={}
    if '*' in args[0]:   # source side effect on a shared register before the destination access
        reg=name(regs_of(args[0])[0])
        if args[0].endswith('+'):bump[reg]=w
        elif args[0].startswith('-*'):bump[reg]=-w
    dst=args[1]
    if '*' not in dst and not dst.startswith('@'):return None
    a=ea(dst,bump);sh=a&15
    if sh+w<=32:return None
    value=bits(ea(args[0],{})) if '*' in args[0] or args[0].startswith('@') else r[name(args[0])]
    if dst.startswith('-*') and regs_of(dst)==[args[0]]:value=(value-w)&M   # MOVE Rs,-*Rs: Rs is read after the decrement
    w0,w2=a&~15,(a&~15)+32
    if w0 not in v['watch'] or w2 not in v['watch'] or not same(()) or n['st']!=m['st']:return None
    # MAME's third write lands on w0: it carries the chip's w2; MAME leaves w2 as input; native w0 is the field's low part
    ok=(all(n['mem'][x]==m['mem'][x] for x in v['watch'] if x not in (w0,w2)) and m['mem'][w0]==n['mem'][w2]
        and m['mem'][w2]==v['mem'][w2] and n['mem'][w0]==(v['mem'][w0]&((1<<sh)-1))|((value<<sh)&0xffff&~((1<<sh)-1)))
    return 'wfieldmac-big' if ok else None

def run_sites(cases,chosen,rng,label,mutate=None,count=8):
    """chosen: [(pc, asm)]. Returns per-vector rows (vector, native, mame, diff) and timings."""
    vecs=[];codes={}
    for pc,asm in chosen:
        asm_,size,raw,code=cases[pc];codes[pc]=mutate(pc,code) if mutate else code
        vecs+=vectors(pc,asm,size,rng,count,raw)
    t=time.perf_counter();nat,nt=native(codes,vecs,label);t1=time.perf_counter()
    mres,mrec=mame_step.run('mk3',vecs,timeout=900);t2=time.perf_counter()
    rows=[(v,nat.get(v['id']),m,compare(v,nat.get(v['id']),m)) for v,m in zip(vecs,mres)]
    return rows,dict(native_seconds=round(t1-t,1),mame_seconds=round(t2-t1,1),**nt,mame_cleanup=mrec['cleanup']['exists_after'],
                     mame_missing=mrec['missing'],identity=mrec['identity']['program_sha256'],mame_log_tail=[l[:300] for l in mrec.get('log_tail',[])])

def summarize(form,rows,cases,sites_n):
    labels=collections.Counter(known_class(r[0],r[1],r[2],cases[r[0]['pc']][0],r[3]) for r in rows if r[3] and r[3][0]!='native_reject')
    bad=[r for r in rows if r[3] and r[3][0]!='native_reject' and not known_class(r[0],r[1],r[2],cases[r[0]['pc']][0],r[3])]
    rej=[r for r in rows if r[3] and r[3][0]=='native_reject']
    first=None
    if bad:
        v,n,m,d=bad[0]
        first=dict(pc=f"{v['pc']:08x}",asm=cases[v['pc']][0],code=cases[v['pc']][3],field=d[0],expected=d[1],got=d[2],
                   inputs=dict(st=v['st'],regs={k:x for k,x in v['regs'].items()},io=v['io'],mem_words=len(v['mem'])),
                   mame=dict(pc=m.get('pc'),st=m.get('st'),cycles=m.get('cycles'),writes=m.get('writes')),
                   native=dict(pc=n and n['pc'],st=n and n['st'],cycles=n and n['cycles'],writes=n and n['writes']))
    known={k:n for k,n in labels.items() if k}
    return dict(sites=sites_n,vectors=len(rows),mismatches=len(bad)+sum(known.values()),unexplained=len(bad),known_open=known,
                unexplained_sites=len({r[0]['pc'] for r in bad}),
                native_rejects=len(rej),native_reject_example=rej and rej[0][3][2],first_mismatch=first)

CONTROL_FORMS=('MOVE R,R','MOVI K,R','ADD R,R','SUB R,R','CMP R,R','ADDI K,R','SLA K,R','SRL K,R','SLL K,R','ANDN R,R',
               'OR R,R','CLR R','MOVK K,R','MOVE *R(K),R,0','MOVE R,*R(K),1','MOVE R,-*R,1','MMFM R,R','JREQ K','DSJS R,K','RETS',
               'CALLR K','ADDC R,R')
# negative controls: one deliberately mutated emitted body per form (a shift count, a subtract flag); each must be detected
MUTATIONS={'SRL K,R':lambda code:re.sub(r'o\.Shift\((s\.[ab]\[\d+\]),(\d+),',lambda m:f'o.Shift({m[1]},{(int(m[2])+1)&31},',code,count=1),
           'SUB R,R':lambda code:code.replace(',true,',',false,',1)}

def control(cases,by,receipt,save,seed):
    """Self-validation: route-verified sites (tools/mk3/route_verified.json TmsBlock, read only) of CONTROL_FORMS must
    give native == MAME; the MUTATIONS must give mismatches on every site."""
    rv={a for a,b in generate.route_keys()['keys']['TmsBlock']}
    chosen=[];per={}
    for form in CONTROL_FORMS:
        sites=[(pc,asm) for pc,asm in by.get(form,[]) if pc in rv and not classify(asm,None)][:5]
        per[form]=sites;chosen+=sites
    rows_,timing=run_sites(cases,chosen,random.Random(seed),'control')
    out={}
    for form,sites in per.items():
        pcs={pc for pc,_ in sites};out[form]=summarize(form,[r for r in rows_ if r[0]['pc'] in pcs],cases,len(sites))
    neg={}
    for form,mut in MUTATIONS.items():
        sites=per[form]
        rows_n,_=run_sites(cases,sites,random.Random(seed),'negative',mutate=lambda pc,code,mut=mut:mut(code))
        changed=sum(1 for pc,_ in sites if mut(cases[pc][3])!=cases[pc][3])
        det={pc for pc,_ in sites if any(r[3] and r[3][0]!='native_reject' for r in rows_n if r[0]['pc']==pc)}
        neg[form]=dict(sites=len(sites),mutated_sites=changed,detected_sites=len(det),vectors=len(rows_n),
                       mismatching_vectors=sum(1 for r in rows_n if r[3]),example=MUTATIONS[form](sites[0] and cases[sites[0][0]][3]))
    receipt['control']=dict(route_verified_forms=len([f for f in per if per[f]]),sites=len(chosen),vectors=len(rows_),
                            mismatches=sum(x['mismatches'] for x in out.values()),unexplained=sum(x['unexplained'] for x in out.values()),
                            known_open=dict(sum((collections.Counter(x['known_open']) for x in out.values()),collections.Counter())),
                            native_rejects=sum(x['native_rejects'] for x in out.values()),
                            forms=out,negatives=neg,timing=timing,
                            passed=all(x['unexplained']==0 and x['native_rejects']==0 for x in out.values())
                                   and all(n['detected_sites']==n['sites']==n['mutated_sites']>0 for n in neg.values()))
    save();print(json.dumps({k:v for k,v in receipt['control'].items() if k not in('forms',)},indent=1,default=str))

# Divergences from the pinned binary where the chip is the Original (D10, user, 15/11/2026: "Siga o hardware"). The native
# follows the hardware; known_class() accepts a vector only when every other compared field equals MAME.
D10={
 'abs-v':dict(pc='ff87f550',asm='ABS B0',inputs='B0=0x80000000, ST=0x10',mame='ST=0x80000010 (V clear), B0 unchanged, 1 cycle',
              native='ST=0x90000010 (V set, as 34010ops.hxx:327 SET_V_LOG(r == INT_MIN) and the TI manual)',
              cause='pinned MAME 0.280 binary: 0 - INT_MIN is signed-overflow UB in ABS(R); the compiled check never sets V'),
 'wfieldmac-big':dict(pc='ff801a90',asm='MOVE A0,*A7,0',inputs='ST=0x18 (FS0=24), A0=0xABCDEF, A7=0x0110000C, words 1111 2222 3333 4444',
              mame='words 333A BCDE 3333 4444 (34010ops.h WFIELDMAC_BIG writes the third word to WORD(offset), not offset+0x20)',
              native='words F111 BCDE 333A 4444, 3 write accesses (mk3_cpu.hpp WriteField, widths 18-31 past the dword)',
              cause='MAME addressing defect; reachability: no real MK3 site shown to reach it (SETF 18h sites read at shift 0 and 8)')}
# Divergences left open, with their negative and next probe.
OPEN={
 'divs-mods-int-min':dict(asm='DIVS/MODS Rs,Rd with Rd=0x80000000, Rs=0xFFFFFFFF',mame='no result: the pinned process hangs (host division fault)',
              native='not compared',next_probe='none with this oracle; vectors avoid the pair (vectors())')}

def reserved(cases,rows,receipt,save,seed):
    """Every site whose opcode 34010tbl.hxx dispatches to unimpl (generate.reserved): 4 vectors each against MAME."""
    sites=[(pc,cases[pc][0]) for pc in sorted(cases) if generate.reserved(rows[pc]) and translated(cases[pc][3])]
    rows_,timing=run_sites(cases,sites,random.Random(seed),'reserved',count=4)
    receipt['reserved_sites']=dict(sites=len(sites),all_reserved=sum(1 for pc in cases if generate.reserved(rows[pc])),vectors=len(rows_),
        mismatches=sum(1 for r in rows_ if r[3]),next_pc_plus_16=all(r[2]['pc']==r[0]['pc']+16 for r in rows_),
        cycles=sorted({r[2]['cycles'] for r in rows_}),forms=dict(collections.Counter(generate.form(a) for _,a in sites).most_common()),timing=timing)
    save();print(json.dumps({k:v for k,v in receipt['reserved_sites'].items() if k!='forms'},indent=1,default=str))

def main():
    a=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument('--control',action='store_true',help='self-validation only (route-verified sites, mutated emitter)')
    a.add_argument('--reserved',action='store_true',help='every reserved-opcode site (34010tbl.hxx unimpl) only')
    a.add_argument('--receipt',default=str(ROOT/'build/native/day1/front-b.json'))
    a.add_argument('--forms',help='form keys separated by ; (default: all translated forms)')
    a.add_argument('--jobs',type=int,default=5);a.add_argument('--chunk',type=int,default=12,help='forms per MAME/native batch')
    a.add_argument('--seed',type=int,default=20261114)
    args=a.parse_args();started=time.perf_counter()
    rom,rows,cases=load();loaded=time.perf_counter()
    by=collections.defaultdict(list)
    for pc,(asm,size,raw,code) in sorted(cases.items()):
        if translated(code):by[generate.form(asm)].append((pc,asm))
    wanted=args.forms.split(';') if args.forms else sorted(by)
    receipt_path=Path(args.receipt)
    receipt=json.loads(receipt_path.read_text('utf-8')) if receipt_path.is_file() else {}
    receipt.update(schema='day1-front-b/1',label='tradução igual ao Original por instrução, estado sintético (D9); não é aceitação de rota',
                   core_sha256=mame_step.CORE_SHA,program_sha256=generate.PROGRAM['sha256'],
                   translated_forms=len(by),translated_sites=sum(map(len,by.values())))
    receipt.setdefault('forms',{});receipt.setdefault('device_operands',{})
    lock=threading.Lock()
    def save():
        receipt_path.parent.mkdir(parents=True,exist_ok=True);tmp=receipt_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(receipt,indent=1,default=str)+'\n',encoding='utf-8');os.replace(tmp,receipt_path)
    receipt['open']=OPEN;receipt['d10']=D10
    if args.control:control(cases,by,receipt,save,args.seed);return
    if args.reserved:reserved(cases,rows,receipt,save,args.seed);return
    if not args.forms:receipt['forms']={};receipt['device_operands']={};receipt['batches']={}
    receipt['untranslated_forms']=sorted({generate.form(asm) for asm,_,_,code in cases.values()}-set(by))
    plan=[]
    for form in wanted:
        sites=by.get(form,[])
        device={pc:why for pc,asm in sites if (why:=classify(asm,rom,cases[pc][3]))}
        test=[(pc,asm) for pc,asm in sites if pc not in device]
        if device:receipt['device_operands'][form]=dict(sites=len(device),reason=sorted(set(device.values()))[:3],examples=[f'{pc:08x}' for pc in list(device)[:3]])
        if test:plan.append((form,select(test),len(sites)))
    save()
    chunks=[plan[i:i+args.chunk] for i in range(0,len(plan),args.chunk)]
    def work(ci):
        chunk=chunks[ci];rng=random.Random(args.seed+ci)
        chosen=[s for _,sel,_ in chunk for s in sel]
        try:rows_,timing=run_sites(cases,chosen,rng,f'c{ci}')
        except Exception as e:
            with lock:
                for form,_,_ in chunk:receipt['forms'][form]=dict(error=str(e)[:500])
                save()
            return
        with lock:
            for form,sel,total in chunk:
                pcs={pc for pc,_ in sel}
                s=summarize(form,[r for r in rows_ if r[0]['pc'] in pcs],cases,len(sel));s['translated_sites']=total;s['batch']=ci
                receipt['forms'][form]=s
            receipt.setdefault('batches',{})[str(ci)]=timing
            save()
        print(f'batch {ci}: {len(chosen)} sites, {sum(1 for r in rows_ if r[3] and r[3][0]!="native_reject")} mismatches',flush=True)
    with ThreadPoolExecutor(args.jobs) as pool:list(pool.map(work,range(len(chunks))))
    f=receipt['forms']
    receipt['totals']=dict(forms_compared=sum(1 for x in f.values() if 'vectors' in x),sites=sum(x.get('sites',0) for x in f.values()),
                           vectors=sum(x.get('vectors',0) for x in f.values()),mismatches=sum(x.get('mismatches',0) for x in f.values()),
                           unexplained=sum(x.get('unexplained',0) for x in f.values()),
                           known_open=dict(sum((collections.Counter(x.get('known_open',{})) for x in f.values()),collections.Counter())),
                           forms_with_mismatch=sorted(k for k,x in f.items() if x.get('mismatches')),
                           forms_with_unexplained=sorted(k for k,x in f.items() if x.get('unexplained')),
                           native_rejects=sum(x.get('native_rejects',0) for x in f.values()),
                           errors=sorted(k for k,x in f.items() if 'error' in x),
                           device_operand_forms=len(receipt['device_operands']),
                           device_operand_sites=sum(x['sites'] for x in receipt['device_operands'].values()),
                           forms_without_any_compared_site=sorted(set(receipt['device_operands'])-{k for k,x in f.items() if x.get('vectors')}),
                           wall_seconds=round(time.perf_counter()-started,1),load_seconds=round(loaded-started,1))
    save();print(json.dumps(receipt['totals'],indent=1))

if __name__=='__main__':main()
