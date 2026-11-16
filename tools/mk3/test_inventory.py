"""K1 front A: the inventory of forms and paths that still rejected (plan 2026-11-10-mk3-cobertura-em-ondas.md, change 4).

Each family runs the C++ that tools/mk3/generate.py emits for a real candidate PC (or the mk3::Ops path it calls) against a
Python model of the pinned sources (docs/investigation/decoder-research/upstream: 34010tbl.hxx, 34010ops.hxx,
34010gfx.hxx, tms34010.cpp; docs/investigation/sources/dcs.cpp; diexec.h eat_cycles at the same commit), with one mutated
expectation per family that must be detected. The model shares the author's reading of the source with the C++: every
family here stays "translated, not verified" until a route reaches it (none of the graphics/arithmetic sites is reachable
from the vectors or the measured PCs; all come from pointer candidates).
Also: the route-promotion mechanism (tools/mk3/route_verified.json -> generate.py states and RouteVerifiedSet, Strict
acceptance in mk3::Ops) with a synthetic file in a scratch tree, and its refusals.
"""
import copy,json,math,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import generate,roms
from tools.mk3.test_families import State,s16,s32,M,N,C,Z,V,RAM,CONTROL,PSIZE,CONVSP,CONVDP,DPYCTL

ROOT=Path(__file__).resolve().parents[2]
P=1<<25;IE=1<<21;INTENB,INTPEND=17,18
LOOKUP=[0,0,1,1,2,2,2,2,3,3,3,3,3,3,3,3]+[4]*16
CC=q.DEFAULT_CC;ENV={'PATH':str(CC.parent)+os.pathsep+os.environ['PATH']}

def run_cpp(test,source,name):
    with q.scratch_tree() as (temp,cleanup):
        (temp/f'{name}.cpp').write_text(source,encoding='utf-8');exe=temp/f'{name}.exe'
        build=q.command([CC,'-std=c++17','-O1','-Wall','-Wextra','-Werror','-Wno-unused-variable','-static','-I'+str(ROOT/'native/mk3'),
                         '-I'+str(ROOT/'native/include'),temp/f'{name}.cpp',ROOT/'native/mk3/mk3_program.cpp',ROOT/'native/src/mk5_program.cpp',
                         '-lbcrypt','-o',exe],temp,env=ENV,timeout=300)
        test.assertTrue(build['passed'],q.compact(build)['output_tail'])
        run=q.command([exe],temp,env=ENV,timeout=60);test.assertTrue(run['passed'],q.compact(run)['output_tail'])
        lines=run['stdout'].splitlines()
    test.assertFalse(cleanup['exists_after'])
    return lines

# ---- Python model of the pinned graphics ops (34010gfx.hxx op0 / op0_trans, memory_r/memory_w, window mode 0) ----
def bpp(s):return 1<<LOOKUP[s.io.get(PSIZE,0)&0x1f]
def word(s,a):return s.mem.get(a&~15,0)
def setw(s,a,v):s.mem[a&~15]=v&0xffff
def split(daddr,dx,b):
    per=16//b;left=(per-((daddr&15)//b))&(per-1);right=((daddr+dx*b)&15)//b;full=dx-left-right
    if full<0:left,right,full=dx,0,0
    else:full//=per
    return left,right,full,full+(left!=0)+(right!=0)
def addy(xy,d):return (xy&0xffff)|((((xy>>16)+(d>>16))&0xffff)<<16)
def rows(s):return s16(s.b[7]>>16)
def m_fill(s,linear):
    b=bpp(s);trans=s.io.get(CONTROL,0)&0x20;dx,dy=s16(s.b[7]),s16(s.b[7]>>16)
    gfx=4 if linear else 6;daddr=(s.b[2] if linear else s.xy(s.b[2],False))&~(b-1)&M
    if dx<=0 or dy<=0:return 0
    left,right,full,words=split(daddr,dx,b);gfx+=2;mask=(1<<b)-1;color=s.b[9]&0xffff
    for _ in range(dy):
        w=daddr>>4;gfx+=words*(4 if trans else 2)
        def put(count,dm,read):
            nonlocal w
            d=word(s,w<<4) if read else 0
            for _ in range(count):
                px=color&dm
                if not trans or px:d=(d&~dm)|px
                dm=(dm<<b)&0xffff
            setw(s,w<<4,d);w+=1
        if left:put(left,(mask<<(daddr&15))&0xffff,True)
        for _ in range(full):put(16//b,mask,trans)
        if right:put(right,mask,True)
        daddr=(daddr+s.b[3])&M
    s.b[2]=(s.b[2]+s32(rows(s))*s.b[3])&M if linear else addy(s.b[2],s.b[7]);return gfx
def m_blit_b(s,linear):
    b=bpp(s);trans=s.io.get(CONTROL,0)&0x20;saddr=s.b[0];dx,dy=s16(s.b[7]),s16(s.b[7]>>16)
    gfx=4 if linear else 6;daddr=(s.b[2] if linear else s.xy(s.b[2],False))&~(b-1)&M
    if dx<=0 or dy<=0:return 0
    left,right,full,words=split(daddr,dx,b);gfx+=(words*(4 if trans else 2)+words*b//16*2)*dy+2;mask=(1<<b)-1
    for _ in range(dy):
        sw,dw=saddr>>4,daddr>>4;src=word(s,sw<<4);sw+=1;sm=1<<(saddr&15)
        def put(count,dm,read):
            nonlocal dw,src,sw,sm
            d=word(s,dw<<4) if read else 0
            for _ in range(count):
                px=(s.b[9] if src&sm else s.b[8])&dm
                if not trans or px:d=(d&~dm)|px
                sm=(sm<<1)&0xffff
                if not sm:src=word(s,sw<<4);sw+=1;sm=1
                dm=(dm<<b)&0xffff
            setw(s,dw<<4,d);dw+=1
        if left:put(left,(mask<<(daddr&15))&0xffff,True)
        for _ in range(full):put(16//b,mask,trans)
        if right:put(right,mask,True)
        saddr=(saddr+s.b[1])&M;daddr=(daddr+s.b[3])&M
    s.b[0]=(s.b[0]+rows(s)*s.b[1])&M
    s.b[2]=(s.b[2]+rows(s)*s.b[3])&M if linear else addy(s.b[2],s.b[7]);return gfx
def m_blit(s,sl,dl):
    b=bpp(s);ctl=s.io.get(CONTROL,0);trans=ctl&0x20;yrev=(ctl>>9)&1
    saddr=s.b[0] if sl else s.xy(s.b[0],True);dx,dy=s16(s.b[7]),s16(s.b[7]>>16)
    gfx=7+(0 if sl else 2)+(0 if dl else 2+(not sl));daddr=(s.b[2] if dl else s.xy(s.b[2],False))&~(b-1)&M
    if dx<=0 or dy<=0:return 0
    conv=lambda reg:1<<(~s.io[reg]&31)
    if (not sl or not dl) and yrev:saddr=(saddr+(dy-1)*conv(CONVSP))&M;daddr=(daddr+(dy-1)*conv(CONVDP))&M
    mask=(1<<b)-1;rw=0
    for _ in range(dy):
        sw,dw,sb,db=saddr>>4,daddr>>4,saddr&15,daddr&15;d=0
        src=word(s,sw<<4);sw+=1;rw+=1
        if trans or daddr&15:d=word(s,dw<<4);rw+=1
        for _ in range(dx):
            if sb+b>16:src|=word(s,sw<<4)<<16;sw+=1;rw+=1
            px=(src>>sb)&mask;sb+=b
            if sb>16:sb-=16;src>>=16
            if trans and db+b>16:d|=word(s,(dw+1)<<4)<<16;rw+=1
            px<<=db;dm=mask<<db
            if not trans or px:d=(d&~dm)|px
            db+=b
            if db>16:setw(s,dw<<4,d);dw+=1;rw+=1;db-=16;d>>=16
        if db>0:
            if db!=16:keep=(0xffff<<db)&0xffff;d=(d&~keep)|(word(s,dw<<4)&keep);rw+=1
            setw(s,dw<<4,d);dw+=1;rw+=1
        step=-1 if yrev else 1;saddr=(saddr+step*s.b[1])&M;daddr=(daddr+step*s.b[3])&M
    s.b[0]=(s.b[0]+rows(s)*s.b[1])&M if sl else addy(s.b[0],s.b[7])
    s.b[2]=(s.b[2]+rows(s)*s.b[3])&M if dl else addy(s.b[2],s.b[7])
    return gfx+rw*2+dx*dy*(2 if trans else 0)
def m_line(s,alg1):   # whole LINE: returns (cycles, executions)
    s.b[14]=1 if alg1 else 0;n=0;cyc=0;mode=(s.io.get(CONTROL,0)>>6)&3
    while s32(s.b[10])>0:
        s.b[10]-=1;x,y=s16(s.b[2]),s16(s.b[2]>>16)
        if mode!=3 or (s16(s.b[5])<=x<=s16(s.b[6]) and s16(s.b[5]>>16)<=y<=s16(s.b[6]>>16)):s.wpixel(s.xy(s.b[2],False),s.b[9])
        dyy,dxx=s16(s.b[7]>>16),s16(s.b[7])
        if s32(s.b[0])>=s32(s.b[14]):s.b[0]=(s.b[0]+dyy*2-dxx*2)&M;inc=s.b[11]
        else:s.b[0]=(s.b[0]+dyy*2)&M;inc=s.b[12]
        s.b[2]=((x+s16(inc))&0xffff)|(((y+s16(inc>>16))&0xffff)<<16);n+=1;cyc+=2
    return cyc,n+1

def io8(**kw):d={CONTROL:0,PSIZE:8,CONVSP:0x13,CONVDP:0x13,DPYCTL:0xf010};d.update({int(k):v for k,v in kw.items()});return d
SRC=RAM+0x2000;DST=RAM+0x8000
SEED={SRC+16*i:(0x1357*i+0x9a1)&0xffff for i in range(64)}|{SRC+0x400+16*i:(i*0x0f0f)&0xffff for i in range(64)}|{DST+16*i:0xa5a5 for i in range(80)}
WATCH=tuple(range(DST-0x40,DST+0x6000,16))
XYB={'B4':DST,'B1':0x400,'B3':0x1000}   # OFFSET = DST, 0x1000-bit destination rows (CONVDP 0x13: 4096)
GRAPHICS={   # name: (handler, model, [(registers, io, budget)])
 'FILL L':('fill_l',lambda s:m_fill(s,True),[({'B2':DST+0x18,'B3':0x400,'B7':0x00020005,'B9':0x5a},io8(**{str(CONTROL):0x20}),0),
                                           ({'B2':DST+0x14,'B3':0x400,'B7':0x00030009,'B9':0x0c},io8(**{str(PSIZE):4}),0),
                                           ({'B2':DST,'B3':0x400,'B7':0x00040004,'B9':0x77},io8(),9)]),
 'PIXBLT B,L':('pixblt_b_l',lambda s:m_blit_b(s,True),[({'B0':SRC+3,'B1':0x40,'B2':DST+0x08,'B3':0x400,'B7':0x00030007,'B8':0,'B9':0x33},io8(**{str(CONTROL):0x20}),0),
                                                     ({'B0':SRC,'B1':0x20,'B2':DST+0x06,'B3':0x400,'B7':0x0002000b,'B8':1,'B9':2},io8(**{str(PSIZE):2}),0),
                                                     ({'B0':SRC,'B1':0x40,'B2':DST,'B3':0x400,'B7':0x00040010,'B8':4,'B9':9},io8(),7)]),
 'PIXBLT B,XY':('pixblt_b_xy',lambda s:m_blit_b(s,False),[(dict(XYB,B0=SRC+5,B2=0x00010003,B7=0x00030006,B8=0,B9=0x44),io8(**{str(CONTROL):0x20}),0)]),
 'PIXBLT L,L':('pixblt_l_l',lambda s:m_blit(s,True,True),[({'B0':SRC+8,'B1':0x80,'B2':DST+0x18,'B3':0x400,'B7':0x00030005},io8(),0),
                                                        ({'B0':SRC,'B1':0x80,'B2':DST+0x08,'B3':0x400,'B7':0x00020004},io8(**{str(CONTROL):0x20}),0),
                                                        ({'B0':SRC+0x10,'B1':0x40,'B2':DST+0x10,'B3':0x400,'B7':0x00020003},io8(**{str(PSIZE):16}),0),
                                                        ({'B0':SRC+4,'B1':0x40,'B2':DST+0x0c,'B3':0x400,'B7':0x00020007},io8(**{str(PSIZE):4}),11)]),
 'PIXBLT L,XY':('pixblt_l_xy',lambda s:m_blit(s,True,False),[(dict(XYB,B0=SRC+8,B2=0x00010002,B7=0x00020005),io8(),0)]),
 'PIXBLT XY,XY':('pixblt_xy_xy',lambda s:m_blit(s,False,False),[(dict(XYB,B0=0x00000001,B2=0x00020001,B7=0x00030004),io8(**{str(CONVSP):0x15}),0),
                                                             (dict(XYB,B0=0x00010000,B2=0x00010003,B7=0x00030002),io8(**{str(CONVSP):0x15,str(CONTROL):0x220}),0)]),
}

class Inventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom=roms.program_image(ROOT/'roms/mk3',roms.definition());cls.rows,_=generate.scan(cls.rom)
        owner=generate.verified();cls.measured=set(owner)|generate.EXTERNAL_PCS
        (cls.static,_),(graph,_),_=generate.closures(cls.rom,cls.rows,cls.measured)
        cls.candidate=set(graph)|cls.measured;cls.unverified=sorted(cls.candidate-cls.measured)
    def emitted(self,pc):
        size,_,raw,asm=self.rows[pc];return generate.emit_unverified(pc,size,asm,raw,self.candidate,self.rom)
    def site(self,predicate):
        return next(pc for pc in self.unverified if predicate(self.rows[pc]))

    def native(self,cases):
        """cases: dicts pc, code, st, regs (State), io, budget, watch -> one JSON line each (final state, passes)."""
        body=[]
        for c in cases:
            b=c['state'];setup=[f's.a[{n}]={v}u;' for n,v in enumerate(b.a) if v]+[f's.b[{n}]={v}u;' for n,v in enumerate(b.b) if v]
            setup+=[f'o.video.io[{k}]={v}; o.io_written|=1u<<{k};' for k,v in b.io.items()]+[f'o.ram[{(k-RAM)//16}]={v};' for k,v in b.mem.items()]
            budget=c.get('budget',0)
            loop=(f'unsigned passes=0; do {{ o.slice_end={"s.cycles+"+str(budget) if budget else "~0ull"}; o.Begin(); {c["code"]} ++passes; }} '
                  f'while (s.pc==0x{c["pc"]:x}u && passes<100000);')
            body.append(f'{{ mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); s.pc=0x{c["pc"]:x}u; s.status={b.st}u; '
                        +' '.join(setup)+f' try {{ {loop} Dump(o,passes,{{{",".join(f"{w}u" for w in c["watch"]) or "0u"}}},{len(c["watch"])}); }} '
                        'catch (const std::exception& e) { std::printf("reject %s\\n", e.what()); } }')
        source=('#include "mk3_cpu.hpp"\n#include <cstdio>\n#include <initializer_list>\nnamespace {\n'
                'void Dump(mk3::Ops& o,unsigned passes,std::initializer_list<uint32_t> watch,size_t count){ auto& s=o.s; std::printf("{\\"a\\":[");\n'
                ' for(int i=0;i<16;++i){std::printf("%s%u",i?",":"",s.a[i]);} std::printf("],\\"b\\":[");\n'
                ' for(int i=0;i<15;++i){std::printf("%s%u",i?",":"",s.b[i]);}\n'
                ' std::printf("],\\"st\\":%u,\\"cycles\\":%llu,\\"pc\\":%u,\\"passes\\":%u,\\"mem\\":{",s.status,(unsigned long long)s.cycles,s.pc,passes);\n'
                ' size_t n=0; for(auto w:watch){ if(n>=count)break; const unsigned v=o.ram[(w-0x01000000u)/16]; if(v) std::printf("%s\\"%u\\":%u",n++?",":"",w,v); } std::printf("}}\\n"); }\n}\n'
                'int main(){ mk3::Program program; program.bytes.resize(0x100000);\n'+'\n'.join(body)+'\nreturn 0; }\n')
        lines=run_cpp(self,source,'inventory')
        self.assertEqual(len(lines),len(cases))
        return [json.loads(x) if x.startswith('{') else x for x in lines]

    def test_families_against_the_pinned_sources(self):
        cases=[];kinds={}
        def add(name,pc,state,expected_fn,budget=0,watch=WATCH,code=None):
            before=copy.deepcopy(state);cycles,passes=expected_fn(state)
            res=state.result(watch);res['cycles']=cycles;res['passes']=passes
            cases.append(dict(name=name,pc=pc,code=code or self.emitted(pc),state=before,budget=budget,watch=watch,expected=res))
            kinds.setdefault(name,[]).append(f'{pc:08x}')
        # graphics: the real candidate PCs whose pinned handler is the op
        for name,(h,model,inputs) in GRAPHICS.items():
            pc=self.site(lambda row,h=h:row[0]==16 and generate.handler(row[2])==h)
            for regs,io,budget in inputs:
                st=State(regs,0x10,io,SEED)
                def fn(s,model=model,budget=budget,pc=pc):
                    gfx=model(s);s.pc=pc+16;s.st&=~P
                    return gfx,(1 if not budget or gfx<=budget else math.ceil(gfx/budget))
                add(name,pc,st,fn,budget)
        for h,alg in (('line',False),('line',True)):
            pc=self.site(lambda row:generate.handler(row[2])=='line')   # the candidate's LINE sites are all LINE 0 (0xdf10)
            code=self.emitted(pc) if not alg else generate.family(pc,16,'LINE   1',(0xdf90,),self.candidate)   # LINE 1 form, same PC
            for mode in (0,3):
                st=State({'B0':0xfffffffe,'B2':0x00010001,'B4':DST,'B5':0x00000000,'B6':0x00020003,'B7':0x00020005,'B9':0x66,'B10':5,
                          'B11':0x00010001,'B12':0x00000001},0x10,io8(**{str(CONTROL):mode<<6}),{})
                def fn(s,alg=alg,pc=pc):cyc,n=m_line(s,alg);s.pc=pc+16;return cyc,n
                add('LINE 1' if alg else 'LINE 0',pc,st,fn,watch=tuple(range(DST,DST+0x8000,0x200)),code=code)
        # reserved opcodes (unimpl): one site per decoded mnemonic kind
        for mnem in ('PIXBLT','FILL','LINE','EINT','RETI','CALLR'):
            pc=self.site(lambda row,m=mnem:generate.reserved(row) and row[3].startswith(m))
            def fn(s,pc=pc):s.pc=pc+16;return 1,1
            add('reserved '+mnem,pc,State({'B2':0x10,'B7':0x00010001,'B10':3},0x40000010,io8(),{}),fn,watch=())
        # MPYS/MPYU/DIVU with Rd = SP (register 15 of both files) and MPYS/DIVS with Rd = A14 (low half / remainder in SP)
        for form,regs,st in (('MPYS R,R',{'A2':0xfffffffd,'SP':0x01000040},0x10),('MPYS R,R',{'A2':0x00000007,'SP':0x80000000},0x10),
                             ('MPYU R,R',{'A13':0x00010001,'SP':0x00020000},0x10),('DIVU R,R',{'A12':7,'SP':100},0x10),('DIVU R,R',{'A12':0,'SP':100},0x10)):
            pc=self.site(lambda row,f=form:generate.form(row[3])==f and row[3].endswith(',SP'))
            op,args=self.rows[pc][3].split(None,1);rs=args.split(',')[0]
            def fn(s,op=op,rs=rs,pc=pc):
                m,d=s[rs],s['SP'];s.pc=pc+16
                if op=='MPYS':
                    p=s32(m)*s32(d);s.st=(s.st&~(N|Z))|(Z if p==0 else 0)|(N if p<0 else 0);s['SP']=p&M;return 20,1
                if op=='MPYU':p=m*d;s.st=(s.st&~Z)|(Z if p==0 else 0);s['SP']=p&M;return 21,1
                s.st&=~(Z|V)
                if not m:s.st|=V
                else:s['SP']=d//m;s.st|=0 if s['SP'] else Z
                return 37,1
            add(op+' SP',pc,State(regs,st),fn,watch=())
        pc=self.site(lambda row:generate.form(row[3])=='MPYS R,R' and row[3].endswith(',A14') and row[3].split()[1].startswith('A'))
        rs=self.rows[pc][3].split()[1].split(',')[0]
        def fn(s,pc=pc,rs=rs):
            p=s32(s[rs])*s32(s['A14']);s.st=(s.st&~(N|Z))|(N if p<0 else 0)|(Z if p==0 else 0);s['A14']=(p>>32)&M;s['SP']=p&M;s.pc=pc+16;return 20,1
        add('MPYS A14',pc,State({rs:0x12345,'A14':0x89abcdef,'SP':0x01000100},0x10),fn,watch=())
        results=self.native(cases)
        failures=[(c['name'],hex(c['pc']),r,c['expected']) for c,r in zip(cases,results) if r!=c['expected']]
        self.assertFalse(failures,failures[:2])
        negatives={}
        for c,r in zip(cases,results):
            if c['name'] in negatives:continue
            bad=copy.deepcopy(c['expected'])
            if bad['mem'] and any(bad['mem'].values()):k=next(k for k,v in bad['mem'].items() if v);bad['mem'][k]^=1
            else:bad['cycles']+=1
            negatives[c['name']]=bad!=r
        self.assertTrue(all(negatives.values()),negatives)
        # CALLA/JA to destinations outside the program image: explicit boundary before the branch, PC in the message
        sites=[pc for pc in self.unverified if self.rows[pc][3].split()[0] in ('CALLA','JA') and self.rows[pc][0]==48
               and generate.emitter.transfer_target(self.rows[pc][3].split()[0],self.rows[pc][3].split()[1])<generate.BASE]
        self.assertEqual(len(sites),3,sites)
        for pc in sites:self.assertEqual(self.emitted(pc),f'o.Reject("branch outside the static candidate",0x{pc:08x}u);')
        Inventory.receipt=dict(cases=len(cases),sites=kinds,negatives=negatives,boundary_sites=[f'{pc:08x}' for pc in sites])

    def test_dcs_empty_latch_intenb_and_route_profiles(self):
        vector,handler,at=0xfffffea0,0xff812340,0xff9000a0   # DI vector; a qualified MOVE A0,@C0000110h,1 at `at` (0x0780)
        put=lambda a,w:f'program.bytes[{(a-generate.BASE)//8}]={w&0xff}; program.bytes[{(a-generate.BASE)//8+1}]={w>>8};'
        source=('#include "mk3_cpu.hpp"\n#include <cstdio>\n#include <string>\nint main(){ mk3::Program program; program.bytes.resize(0x100000);\n'
                +put(at,0x0780)+put(vector,handler&0xffff)+put(vector+16,handler>>16)+put(at+48,0x0000)+'\n'
                # 1. dcs data_r on an empty output latch: eat_cycles(4444) clamped to m_icount (slice_end - start)
                ' { mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); o.cosim=true; s.pc=0xff900000u; s.cycles=1000;\n'
                '   for (uint64_t end : {3000ull, 100000ull}) { s.dcs_control=0x0c00; o.slice_end=end; uint64_t c0=s.cycles; o.Begin(); o.Read16(0x01680000u); std::printf("eat %llu\\n",(unsigned long long)(s.cycles-c0)); }\n'
                '   s.dcs_control=0x0800; uint64_t c0=s.cycles; o.Begin(); o.Read16(0x01680000u); std::printf("full %llu %u\\n",(unsigned long long)(s.cycles-c0),unsigned(o.empty_reads)); }\n'
                # 2. INTENB write taking DI: Game takes it inside the instruction and notes IrqPath; Strict rejects; with a route key it runs
                ' for (int mode=0; mode<3; ++mode) { mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); mk3::FirstExecution log; mk3::RouteVerified keys;\n'
                f'   keys.keys.insert({{uint8_t(mk3::Unverified::IrqPath),{vector}u,{at}u}});\n'
                '   if (mode==0) { o.profile=mk3::Profile::Game; o.first=&log; } else if (mode==2) o.routes=&keys;\n'
                f'   s.pc={at}u; s.status=0x00200010u; s.a[15]=0x01010000u; o.video.io[mk3::VideoTiming::INTPEND]=mk3::VideoTiming::DI; s.cycles=500; o.Begin();\n'
                '   try { o.Write32(0xc0000110u,0x04000400u); o.Finish(s.pc+48,5);\n'
                '     std::printf("intenb %u %u %llu %u %u %u %zu\\n", s.pc, s.status, (unsigned long long)s.cycles, o.Read32(s.a[15]), o.Read32(s.a[15]+32), unsigned(o.interrupts.back().entry), log.order.size()); }\n'
                '   catch (const std::exception& e) { std::printf("intenb reject %s\\n", e.what()); } }\n'
                # 3. unqualified form taking it: rejects in Game
                f' {{ mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); o.profile=mk3::Profile::Game; s.pc={at+48}u; s.status=0x00200010u; s.a[15]=0x01010000u;\n'
                '   o.video.io[mk3::VideoTiming::INTPEND]=mk3::VideoTiming::DI; o.Begin(); try { o.Write16(0xc0000110u,0x0400u); std::printf("unqualified ran\\n"); } catch (const std::exception& e) { std::printf("unqualified reject\\n"); } }\n'
                # 4. RETI taking a pending DI: Strict rejects (not compared), Game notes IrqPath {vector, RETI pc}
                ' for (int game=0; game<2; ++game) { mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); mk3::FirstExecution log; if (game) { o.profile=mk3::Profile::Game; o.first=&log; }\n'
                '   s.pc=0xff900200u; s.a[15]=0x01010000u; o.Write32(0x01010000u,0x00200010u); o.Write32(0x01010020u,0xff900400u); o.video.io[mk3::VideoTiming::INTPEND]=mk3::VideoTiming::DI; o.video.io[mk3::VideoTiming::INTENB]=mk3::VideoTiming::DI; o.Begin();\n'
                '   try { o.ReturnInterrupt(); std::printf("reti %u %llu %zu %u\\n", s.pc, (unsigned long long)s.cycles, log.order.size(), log.order.empty()?0u:log.order[0].from); } catch (const std::exception& e) { std::printf("reti reject %s\\n", e.what()); } }\n'
                # 5. Strict with a route set: a route-verified block and edge run, others reject with their PC
                ' { mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); mk3::RouteVerified keys; o.routes=&keys;\n'
                '   keys.keys.insert({uint8_t(mk3::Unverified::TmsBlock),0xff9253c0u,0u}); keys.keys.insert({uint8_t(mk3::Unverified::TmsEdge),0xff9253d0u,0xff9253c0u});\n'
                '   s.pc=0xff9253c0u; o.Begin(); o.Block(0xff9253c0u); o.Edge(0xff9253d0u,0xff9253c0u,true); std::printf("route ok\\n");\n'
                '   s.pc=0xff9253e0u; o.Begin(); try { o.Block(0xff9253e0u); } catch (const std::exception& e) { std::printf("%s\\n", e.what()); }\n'
                '   o.routes=nullptr; s.pc=0xff9253c0u; o.Begin(); try { o.Block(0xff9253c0u); } catch (const std::exception& e) { std::printf("lot only: %s\\n", e.what()); } }\n'
                'return 0; }\n')
        got=run_cpp(self,source,'paths')
        DI_ST=0x00200010
        expected=['eat 2000','eat 4444','full 0 2',
                  f'intenb {handler} 16 521 {DI_ST} {at+48} 521 1',f'intenb reject MK3 interrupt taken inside POPST/PUTST/RETI/INTENB is not compared with the Original; PC {at}; address {vector}',
                  f'intenb {handler} 16 521 {DI_ST} {at+48} 521 0','unqualified reject',
                  f'reti reject MK3 interrupt taken inside POPST/PUTST/RETI/INTENB is not compared with the Original; PC {0xff900200}; address {vector}',
                  f'reti {handler} 27 1 {0xff900200}','route ok',f'MK3 PC outside the authenticated fixed translation; PC {0xff9253e0}; address {0xff9253e0}',
                  f'lot only: MK3 PC outside the authenticated fixed translation; PC {0xff9253c0}; address {0xff9253c0}']
        self.assertEqual(got,expected)
        self.assertNotEqual(got,[e.replace('eat 4444','eat 4443') for e in expected])   # negative: one cycle less is detected
        self.assertNotEqual(got,[e.replace(' 521 1',' 505 1') for e in expected])        # negative: the 16 interrupt cycles

    def test_route_verified_file(self):
        """Synthetic route_verified.json in a scratch tree (the real file belongs to front B): counted apart, compiled into
        RouteVerifiedSet, deterministic; refused for another program, a receipt digest mismatch, a malformed key or a block
        outside the candidate."""
        import hashlib
        pc=next(pc for pc in self.unverified if not self.rows[pc][3].startswith(('DW','EMU')))
        with q.scratch_tree() as (temp,cleanup):
            receipt=temp/'route.json';receipt.write_text('{"route":"synthetic"}',encoding='utf-8')
            rel=receipt.relative_to(ROOT).as_posix()
            good=dict(schema='mk3-route-verified/1',program_sha256=generate.PROGRAM['sha256'],
                      routes=[dict(name='synthetic',receipt=rel,receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest())],
                      TmsBlock=[[pc,0]],TmsEdge=[],AdspBlock=[[0x10020,0x123456]],AdspEdge=[],DmaPath=[[7,0]],IrqPath=[[0xfffffea0,0]],DevicePath=[])
            path=temp/'route_verified.json';path.write_text(json.dumps(good),encoding='utf-8')
            sources,rec=generate.units(self.rom,self.rows,routes=path)
            again,_=generate.units(self.rom,self.rows,routes=path)
            refusals={}
            for name,change in dict(program=dict(program_sha256='0'*64),receipt=dict(routes=[dict(good['routes'][0],receipt_sha256='0'*64)]),
                                    malformed=dict(DmaPath=[[7]]),schema=dict(schema='x')).items():
                path.write_text(json.dumps(dict(good,**change)),encoding='utf-8')
                with self.assertRaises(ValueError) as e:generate.route_keys(path)
                refusals[name]=str(e.exception)
            path.write_text(json.dumps(dict(good,TmsBlock=[[next(a for a in range(generate.BASE,generate.END,16) if a not in self.candidate),0]])),encoding='utf-8')
            with self.assertRaises(ValueError) as e:generate.units(self.rom,self.rows,routes=path)
            refusals['outside']=str(e.exception)
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(rec['cases']['verified_route'],1)
        self.assertEqual(rec['route_verified']['keys']['TmsBlock'],1);self.assertEqual(rec['route_verified']['receipts_present'],1)
        self.assertEqual(sources,again)   # deterministic for one file
        text=sources['mk3_tms_dispatch.cpp']
        for entry in (f'{{0,0x{pc:08x}u,0x00000000u}}','{2,0x00010020u,0x00123456u}','{4,0x00000007u,0x00000000u}','{5,0xfffffea0u,0x00000000u}'):
            self.assertIn(entry,text)
        self.assertIn('outside the static candidate',refusals['outside'])
        Inventory.route_receipt=dict(verified_route=1,refusals=refusals)

if __name__=='__main__':unittest.main()
