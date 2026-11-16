"""J1 instruction families of the MK3 2.1 whole-image candidate (tools/mk3/generate.py family() and the MK2 batch forms)
against an independent Python model of the pinned 34010ops.hxx / tms34010.cpp (docs/investigation/decoder-research,
commit in sources.json), plus the Strict/Game profile entry points (mk3::Ops::Block/Edge).

Each family runs the C++ that the generator emits for a real candidate PC of that form, with edge-case inputs (zero,
carry/borrow, overflow, count 0, sign, window inside/outside, transparency), and compares registers, ST, cycles, next
PC and the memory words it touches. Negative control per family: one mutated model value (a flag, a register, the cycle
count or a memory word) must be detected. Untranslated forms (DW, EMU: data) must emit an explicit rejection.
The model shares the author's reading of the pinned source with the C++, not an independent reference capture: these
families stay "emitted, not verified" until a route compares them with the Original.
"""
import copy,json,os,re,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import generate,roms

ROOT=Path(__file__).resolve().parents[2]
M=0xffffffff;N,C,Z,V=0x80000000,0x40000000,0x20000000,0x10000000
RAM=0x01000000
CONTROL,PSIZE,CONVSP,CONVDP,DPYCTL=11,21,19,20,8
s16=lambda x:((x&0xffff)^0x8000)-0x8000
s32=lambda x:((x&M)^0x80000000)-0x80000000
def tdiv(a,b):q=abs(a)//abs(b);return q if (a<0)==(b<0) else -q   # C++ truncating division
def nz(st,r):return (st&~(N|Z))|(r&N)|(0 if r&M else Z)

class State:
    def __init__(self,regs,st,io=(),mem=()):
        self.a=[0]*16;self.b=[0]*15;self.st=st;self.io=dict(io);self.mem=dict(mem);self.cycles=0;self.pc=None
        for name,value in regs.items():self[name]=value
    def __getitem__(self,name):return self.a[15] if name in('SP','A15','B15') else (self.a if name[0]=='A' else self.b)[int(name[1:])]
    def __setitem__(self,name,value):
        if name in('SP','A15','B15'):self.a[15]=value&M
        else:(self.a if name[0]=='A' else self.b)[int(name[1:])]=value&M
    def result(self,watch):return dict(a=self.a,b=self.b,st=self.st&M,cycles=self.cycles,pc=self.pc,mem={str(w):v for w in watch if (v:=self.mem.get(w,0))})
    # bus model: 16-bit words at aligned bit addresses
    def bits(self,address,width):
        value=0
        for n in range(width):
            word=(address+n)&~15;value|=((self.mem.get(word,0)>>((address+n)&15))&1)<<n
        return value
    def put(self,address,width,value):
        for n in range(width):
            word=(address+n)&~15;bit=1<<((address+n)&15)
            self.mem[word]=(self.mem.get(word,0)&~bit)|(bit if (value>>n)&1 else 0)
    # pixel model (set_pixel_function / io_register_w / WP / WP_T / RP)
    def size(self):return {2:2,4:4,8:8,16:16,32:32}.get(self.io.get(PSIZE,0),1)
    def xy(self,xy,source):
        reg=CONVSP if source else CONVDP;conv=1<<(~self.io[reg]&31)
        shift={1:0,2:1,4:2,8:3,16:4}.get(self.io[PSIZE],0)
        return (s16(xy>>16)*conv+(s16(xy)<<shift)+self.b[4])&M
    def rpixel(self,address):
        size=self.size()
        if size==32:return self.bits(address&~31,32)
        if size==16:return self.bits(address&~15,16)
        return self.bits(address&~(size-1),size)
    def wpixel(self,address,data):
        size=self.size();transparent=self.io.get(CONTROL,0)&0x20
        if size>=16:
            if not transparent or data:self.put(address&~(size-1),size,data)
            return
        data&=(1<<size)-1
        if not transparent or data:self.put(address&~(size-1),size,data)
    def window(self,xy):   # True: skip the write
        mode=(self.io.get(CONTROL,0)>>6)&3
        if not mode:return False
        self.st&=~V;x,y=s16(xy),s16(xy>>16)
        if x<s16(self.b[5]) or x>s16(self.b[6]) or y<s16(self.b[5]>>16) or y>s16(self.b[6]>>16):self.st|=V;return True
        return mode==1

def model(op,args,s,pc,size):
    """34010ops.hxx semantics of the forms under test (registers by name, s mutated); returns the cycle count."""
    nxt=pc+size;s.pc=nxt;c=lambda:(s.st>>30)&1
    if op=='SUBB':
        d,t=s[args[1]],s[args[0]];r=(d-t-c())&M;s.st=nz(s.st&~(N|C|Z|V),r)
        if t>d:s.st|=C
        if (d^t)&(d^r)&N:s.st|=V
        s[args[1]]=r;return 1
    if op=='NEGB':
        t=(s[args[0]]+c())&M;r=(-t)&M;s.st=nz(s.st&~(N|C|Z|V),r)|(C if t else 0)|(V if t&r&N else 0);s[args[0]]=r;return 1
    if op=='ABS':
        r=(-s[args[0]])&M;s.st=nz(s.st&~(N|Z|V),r)|(V if r==0x80000000 else 0)
        if s32(r)>0:s[args[0]]=r
        return 1
    if op=='MPYS':
        m1=s[args[0]];fw=(s.st>>6)&31
        if fw:m1=((m1&((1<<fw)-1))^(1<<(fw-1)))-(1<<(fw-1))
        p=s32(m1)*s32(s[args[1]]);s.st=(s.st&~(N|Z))|(Z if p==0 else 0)|(N if p<0 else 0)
        bank,n=args[1][0],int(args[1][1:]);s[args[1]]=p>>32;s[f'{bank}{n|1}']=p;return 20
    if op=='DIVS':
        rs=s32(s[args[0]]);bank,n=args[1][0],int(args[1][1:]);s.st&=~(N|Z|V)
        if n&1:
            if not rs:s.st|=V
            else:r=tdiv(s32(s[args[1]]),rs)&M;s[args[1]]=r;s.st=nz(s.st,r)
            return 39
        if not rs:s.st|=V
        else:
            dividend=s32(s[args[1]])<<32|s[f'{bank}{n+1}'];q_=tdiv(dividend,rs)
            if s32(q_)!=q_:s.st|=V
            else:s[f'{bank}{n+1}']=dividend-q_*rs;s[args[1]]=q_;s.st=nz(s.st,q_&M)
        return 40
    if op=='MODS':
        rs=s32(s[args[0]]);s.st&=~(N|Z|V)
        if rs:d=s32(s[args[1]]);r=(d-tdiv(d,rs)*rs)&M;s[args[1]]=r;s.st=nz(s.st,r)
        else:s.st|=V
        return 40
    if op=='CPW':
        x,y=s16(s[args[0]]),s16(s[args[0]]>>16)
        res=(0x20 if s16(s.b[5])>x else 0)|(0x40 if x>s16(s.b[6]) else 0)|(0x80 if s16(s.b[5]>>16)>y else 0)|(0x100 if y>s16(s.b[6]>>16) else 0)
        s[args[1]]=res;s.st=(s.st&~V)|(V if res else 0);return 1
    if op in('SLA','SRA','SRL'):
        res=s[args[1]]
        if op=='SLA':
            k=s[args[0]]&31;s.st&=~(N|C|Z|V)
            if k:
                mask=(M<<(31-k))&0x7fffffff;res2=res^mask if res&N else res
                if res2&mask:s.st|=V
                if (res<<(k-1))&N:s.st|=C
                res=(res<<k)&M
            s[args[1]]=res;s.st=nz(s.st,res);return 3
        k=(-s[args[0]])&31
        if op=='SRA':
            s.st&=~(N|C|Z)
            if k:v=s32(res)>>(k-1);s.st|=C if v&1 else 0;res=(v>>1)&M
            s[args[1]]=res;s.st=nz(s.st,res);return 1
        s.st&=~(C|Z)
        if k:s.st|=C if (res>>(k-1))&1 else 0;res>>=k
        s[args[1]]=res;s.st|=0 if res else Z;return 1
    if op=='CVXYL':s[args[1]]=s.xy(s[args[0]],False);return 3
    if op=='EXGF':
        shift=6 if args[1]=='1' else 0;t=(s.st>>shift)&0x3f;s.st=(s.st&~(0x3f<<shift))|((s[args[0]]&0x3f)<<shift);s[args[0]]=t;return 1
    if op=='REV':s[args[0]]=8;return 1
    if op=='ZEXT':
        fw=(s.st>>6)&31 if args[1]=='1' else s.st&31;v=s[args[0]]&(((1<<fw)-1) if fw else M);s[args[0]]=v;s.st=(s.st&~Z)|(0 if v else Z);return 1
    if op in('DSJEQ','DSJNE'):
        if bool(s.st&Z)==(op=='DSJEQ'):
            s[args[0]]=s[args[0]]-1
            if s[args[0]]:s.pc=int(args[1][:-1],16);return 3
        return 2
    if op=='MOVB' or op=='MOVE':
        def address(text):
            if text.startswith('@'):return int(text[1:-1],16)
            m=re.fullmatch(r'\*(\w+)(?:\(([0-9A-F]+)h\))?',text);return (s[m[1]]+(s16(int(m[2],16)) if m[2] else 0))&M
        if op=='MOVE':v=s.bits(address(args[0]),8);v=v-256 if v&128 else v;s[args[1]]=v;s.st=nz(s.st&~V,v&M);return 5
        s.put(address(args[1]),8,s.bits(address(args[0]),8));return 6 if args[0][0]=='@' else 5
    if op=='DRAV':
        xy=s[args[1]]
        if not s.window(xy):s.wpixel(s.xy(xy,False),s.b[9])
        d,t=s[args[1]],s[args[0]];s[args[1]]=((d+t)&0xffff)|((((d>>16)+(t>>16))&0xffff)<<16);return 4
    if op=='PIXT':
        shape=tuple('XY' if a=='XY' else '*' if a.startswith('*') else 'R' for a in args);src,dst=[a.lstrip('*') for a in args if a!='XY']
        load=lambda v:(s.__setitem__(dst,v),setattr(s,'st',(s.st&~V)|(V if v else 0)))
        if shape==('R','*'):s.wpixel(s[dst],s[src]);return 2
        if shape==('R','*','XY'):
            if not s.window(s[dst]):s.wpixel(s.xy(s[dst],False),s[src])
            return 4
        if shape==('*','R'):load(s.rpixel(s[src]));return 4
        if shape==('*','*'):s.wpixel(s[dst],s.rpixel(s[src]));return 4
        if shape==('*','XY','R'):load(s.rpixel(s.xy(s[src],True)));return 6
        if not s.window(s[dst]):s.wpixel(s.xy(s[dst],False),s.rpixel(s.xy(s[src],True)))
        return 7
    raise AssertionError(op)

PIX=dict(io={CONTROL:0x20,PSIZE:8,CONVSP:0x13,CONVDP:0x13,DPYCTL:0xf010})   # 8-bit pixels, transparency, 4096-bit rows
WIN=dict(io={CONTROL:0xa0,PSIZE:8,CONVSP:0x13,CONVDP:0x13,DPYCTL:0xf010})   # window mode 2 (clip)
def pix(**kw):return dict(PIX['io'],**kw)
# family -> (form key of generate.form, [(registers by role, ST, io, memory seed, watched words)])
R1,R2=0,1   # operand roles: R1 = first register operand (Rs), R2 = second (Rd)
FAMILIES={
 'SUBB':('SUBB R,R',[({R1:1,R2:0},0x10,None,{},()),({R1:0,R2:0},0x40000010,None,{},()),({R1:1,R2:0x80000000},0x10,None,{},()),({R1:0xffffffff,R2:0x7fffffff},0x40000010,None,{},())]),
 'NEGB':('NEGB R',[({R1:0},0x10,None,{},()),({R1:0},0x40000010,None,{},()),({R1:0x80000000},0x10,None,{},()),({R1:0xffffffff},0x40000010,None,{},())]),
 'ABS':('ABS R',[({R1:0},0x10,None,{},()),({R1:5},0x10,None,{},()),({R1:0xfffffffb},0x10,None,{},()),({R1:0x80000000},0x10,None,{},())]),
 'MPYS':('MPYS R,R',[({R1:3,R2:0xfffffffe},0x10,None,{},()),({R1:0,R2:7},0x10,None,{},()),({R1:0xffff,R2:2},0x400,None,{},()),({R1:0x80000000,R2:0x80000000},0x10,None,{},())]),
 'DIVS odd':('DIVS R,R',[({R1:3,R2:0xfffffff9},0x10,None,{},()),({R1:0,R2:7},0x10,None,{},()),({R1:7,R2:3},0x10,None,{},())]),
 'DIVS pair':('DIVS R,R',[({R1:7,R2:0,'pair':100},0x10,None,{},()),({R1:0xfffffffd,R2:0xffffffff,'pair':0xfffffff0},0x10,None,{},()),
                         ({R1:0,R2:1,'pair':1},0x10,None,{},()),({R1:2,R2:1,'pair':0},0x10,None,{},())]),
 'MODS':('MODS R,R',[({R1:3,R2:0xfffffff9},0x10,None,{},()),({R1:0,R2:7},0x10,None,{},()),({R1:7,R2:14},0x10,None,{},())]),
 'CPW':('CPW R,R',[({R1:0x00050005,'B5':0x00010001,'B6':0x00100010},0x10,None,{},()),({R1:0xffff0020,'B5':0x00010001,'B6':0x00100010},0x10,None,{},())]),
 'SLA R':('SLA R,R',[({R1:0,R2:0x80000001},0x50000010,None,{},()),({R1:4,R2:0x0fffffff},0x10,None,{},()),({R1:33,R2:0xc0000000},0x10,None,{},()),({R1:31,R2:1},0x10,None,{},())]),
 'SRA R':('SRA R,R',[({R1:0,R2:0x80000001},0x50000010,None,{},()),({R1:(-4)&M,R2:0x80000010},0x10,None,{},()),({R1:1,R2:0x80000000},0x10000010,None,{},())]),
 'SRL R':('SRL R,R',[({R1:0,R2:0x80000001},0x50000010,None,{},()),({R1:(-4)&M,R2:0x80000018},0x10,None,{},()),({R1:31,R2:3},0x10,None,{},())]),
 'CVXYL':('CVXYL R,R',[({R1:0x00020003,'B4':RAM},0x10,PIX['io'],{},()),({R1:0xffff0001,'B4':RAM+0x100000},0x10,PIX['io'],{},())]),
 'EXGF':('EXGF R,0',[({R1:0xffffffe5},0x00000ab3,None,{},())]),
 'REV':('REV R',[({R1:0x1234},0x10,None,{},())]),
 'ZEXT 1':('ZEXT R,1',[({R1:0xffffffff},0x00000310,None,{},()),({R1:0xffff0000},0x00000310,None,{},()),({R1:0xffffffff},0x10,None,{},())]),
 'DSJEQ':('DSJEQ R,K',[({R1:5},0x20000010,None,{},()),({R1:1},0x20000010,None,{},()),({R1:5},0x10,None,{},())]),
 'DSJNE':('DSJNE R,K',[({R1:5},0x10,None,{},()),({R1:1},0x10,None,{},()),({R1:5},0x20000010,None,{},())]),
 'MOVB NO_NO':('MOVB *R(K),*R(K)',[({R1:RAM+0x204,R2:RAM+0x404},0x10,None,{RAM+0x200:0xabcd,RAM+0x210:0x1234},'dst')]),
 'MOVB AA':('MOVB @K,@K',[({},0x10,None,{},'abs')]),
 'MOVB AR':('MOVE @K,R',[({},0x10,None,{},'abs')]),
 'DRAV':('DRAV R,R',[({R1:0x00010002,R2:0x00030004,'B4':RAM,'B9':0x5a},0x10,PIX['io'],{},'pix'),({R1:0x00010002,R2:0x00030004,'B4':RAM,'B9':0},0x10,PIX['io'],{},'pix'),
                     ({R1:0x00010002,R2:0x00300004,'B4':RAM,'B5':0,'B6':0x00100010,'B9':0x77},0x10,WIN['io'],{},'pix')]),
 'PIXT RI':('PIXT R,*R',[({R1:0x3c,R2:RAM+0x48},0x10,PIX['io'],{RAM+0x40:0x1111},'pix'),({R1:0,R2:RAM+0x48},0x10,PIX['io'],{RAM+0x40:0x1111},'pix'),
                        ({R1:0x123,R2:RAM+0x40},0x10,pix(**{str(CONTROL):0}),{RAM+0x40:0xffff},'pix')]),
 'PIXT RIXY':('PIXT R,*R,XY',[({R1:0x3c,R2:0x00020003,'B4':RAM},0x10,PIX['io'],{},'pix'),({R1:0x3c,R2:0x00200003,'B4':RAM,'B5':0,'B6':0x00100010},0x10,WIN['io'],{},'pix')]),
 'PIXT IR':('PIXT *R,R',[({R1:RAM+0x48},0x10000010,PIX['io'],{RAM+0x40:0x9a11},()),({R1:RAM+0x40},0x10000010,PIX['io'],{RAM+0x40:0x9a00},())]),
 'PIXT II':('PIXT *R,*R',[({R1:RAM+0x48,R2:RAM+0x80},0x10,PIX['io'],{RAM+0x40:0x9a11},'pix')]),
 'PIXT IXYR':('PIXT *R,XY,R',[({R1:0x00010001,'B4':RAM},0x10,PIX['io'],{RAM+0x1000:0x4400},())]),
 'PIXT IXYIXY':('PIXT *R,XY,*R,XY',[({R1:0x00010001,R2:0x00020002,'B4':RAM},0x10,PIX['io'],{RAM+0x1000:0x4400},'pix'),
                                   ({R1:0x00010001,R2:0x00200002,'B4':RAM,'B5':0,'B6':0x00100010},0x10,WIN['io'],{RAM+0x1000:0x4400},'pix')]),
}
UNTRANSLATED=('DW K','EMU')   # data: the only forms left untranslated (K1; graphics, SP multiplies: test_inventory.py)
SYNTHETIC={'MOVB NO_NO':('MOVB   *A1(14h),*A2(FFF8h)',48,(0x0c00,0,0)),'MOVB AA':('MOVB   @1000208h,@1000404h',80,(0x0340,0,0,0,0)),'MOVB AR':('MOVE   @100020Ch,A3',48,(0x07e3,0,0))}

def registers(args):return [m[1] for a in args if (m:=re.fullmatch(r'-?\*?([AB](?:1[0-5]|[0-9])|SP)(?:\([0-9A-F]+h\))?\+?',a))]

class Families(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom=roms.program_image(ROOT/'roms/mk3',roms.definition());cls.rows,_=generate.scan(cls.rom)
        owner=generate.verified();measured=set(owner)|generate.EXTERNAL_PCS
        (_,_),(graph,_),_=generate.closures(cls.rom,cls.rows,measured)
        cls.candidate=set(graph)|measured;cls.unverified=sorted(cls.candidate-measured)

    def pick(self,key,predicate=lambda asm:True):
        for fallback in (False,True):
            for pc in self.unverified:
                size,_,raw,asm=self.rows[pc]
                names=registers(asm.split(None,1)[1].split(',')) if ' ' in asm else []
                plain=len(set(names))==len(names) and not set(names)&{'B4','B5','B6','B9','SP'}   # no alias of the XY registers
                if generate.form(asm)==key and predicate(asm) and (plain or fallback):
                    try:return pc,size,raw,asm,generate.emit_unverified(pc,size,asm,raw,self.candidate,self.rom)
                    except ValueError:continue
        self.fail('no candidate PC of form '+key)

    def test_families_against_the_pinned_semantics(self):
        cases=[]
        for name,(key,inputs) in FAMILIES.items():
            pred={'DIVS odd':lambda a:int(a.split(',')[1][1:])&1,'DIVS pair':lambda a:not int(a.split(',')[1][1:])&1 and a.split(',')[1]!='SP',
                  'MPYS':lambda a:'SP' not in a and int(a.split(',')[1][1:])<14}.get(name,lambda a:'SP' not in a)
            if name in SYNTHETIC:   # the candidate's absolute byte forms address I/O, not RAM: same emitter path, synthetic operands
                asm,size,raw=SYNTHETIC[name];pc=self.unverified[0];code=generate.emit_unverified(pc,size,asm,raw,self.candidate,self.rom)
            else:pc,size,raw,asm,code=self.pick(key,pred)
            op,*rest=asm.split(None,1);args=rest[0].split(',') if rest else [];names=registers(args)
            for roles,st,io,seed,watch in inputs:
                regs={}
                for role,value in roles.items():
                    if role=='pair':regs[names[1][0]+str(int(names[1][1:])+1)]=value
                    elif isinstance(role,int):regs[names[role]]=value
                    else:regs[role]=value
                io={int(k):v for k,v in (io or {}).items()}
                state=State(regs,st,io,seed)
                if watch=='abs':   # absolute byte forms: seed the source, watch the destination
                    addrs=[int(a[1:-1],16) for a in args if a.startswith('@')]
                    state.mem[addrs[0]&~15]=0xa5c3;state.mem[(addrs[0]&~15)+16]=0x5a3c;watch=tuple({x&~15 for x in addrs}|{(x&~15)+16 for x in addrs})
                elif watch=='dst':watch=(RAM+0x400,RAM+0x410)
                elif watch=='pix':watch=tuple(range(RAM,RAM+0x10000,16))
                before=copy.deepcopy(state);state.cycles=model(op,args,state,pc,size)
                cases.append(dict(name=name,pc=pc,asm=asm,code=code,before=before,expected=state.result(watch),watch=watch))
        results=self.run_native(cases)
        failures=[(c['name'],c['asm'],r,c['expected']) for c,r in zip(cases,results) if r!=c['expected']]
        self.assertFalse(failures,failures[:3])
        negatives={}
        for c,r in zip(cases,results):   # one mutation per family, on its first case
            if c['name'] in negatives:continue
            bad=copy.deepcopy(c['expected'])
            if bad['mem'] and any(bad['mem'].values()):k=next(k for k,v in bad['mem'].items() if v);bad['mem'][k]^=1
            else:bad['st']^=V if c['name'] in('CPW','PIXT IR','PIXT IXYR') else Z;bad['cycles']+=0 if c['name']!='REV' else 1
            negatives[c['name']]=bad!=r
        self.assertTrue(all(negatives.values()),negatives)
        self.assertEqual(set(negatives),set(FAMILIES))
        for key in UNTRANSLATED:   # forms left untranslated stay explicit rejections in the generated case body
            pc=next(pc for pc in self.unverified if generate.form(self.rows[pc][3])==key)
            size,_,raw,asm=self.rows[pc]
            with self.assertRaises(ValueError):generate.emit_unverified(pc,size,asm,raw,self.candidate,self.rom)
        Families.receipt=dict(families=len(FAMILIES),cases=len(cases),negatives=negatives,untranslated_checked=list(UNTRANSLATED))

    def run_native(self,cases):
        body=[]
        for i,c in enumerate(cases):
            b=c['before'];setup=[f's.a[{n}]={v}u;' for n,v in enumerate(b.a) if v]+[f's.b[{n}]={v}u;' for n,v in enumerate(b.b) if v]
            setup+=[f'o.video.io[{k}]={v}; o.io_written|=1u<<{k};' for k,v in b.io.items()]
            setup+=[f'o.ram[{(k-RAM)//16}]={v};' for k,v in b.mem.items()]
            watch=','.join(f'{w}u' for w in c['watch']) or '0u'
            body.append(f'{{ mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000)); s.pc=0x{c["pc"]:x}u; s.status={b.st}u; '
                        +' '.join(setup)+f' o.Begin(); try {{ {c["code"]} }} catch (const std::exception& e) {{ std::printf("reject %s\\n", e.what()); }} '
                        +f'if (s.pc != 0x{c["pc"]:x}u || s.cycles) Dump(o,{{{watch}}},{len(c["watch"])}); }}')
        source=('#include "mk3_cpu.hpp"\n#include <cstdio>\n#include <initializer_list>\nnamespace {\n'
                'void Dump(mk3::Ops& o,std::initializer_list<uint32_t> watch,size_t count){ auto& s=o.s; std::printf("{\\"a\\":[");\n'
                ' for(int i=0;i<16;++i){std::printf("%s%u",i?",":"",s.a[i]);} std::printf("],\\"b\\":[");\n'
                ' for(int i=0;i<15;++i){std::printf("%s%u",i?",":"",s.b[i]);}\n'
                ' std::printf("],\\"st\\":%u,\\"cycles\\":%llu,\\"pc\\":%u,\\"mem\\":{",s.status,(unsigned long long)s.cycles,s.pc);\n'
                ' size_t n=0; for(auto w:watch){ if(n>=count)break; const unsigned v=o.ram[(w-0x01000000u)/16]; if(v) std::printf("%s\\"%u\\":%u",n++?",":"",w,v); } std::printf("}}\\n"); }\n}\n'
                'int main(){ mk3::Program program; program.bytes.resize(0x100000);\n'+'\n'.join(body)+'\nreturn 0; }\n')
        cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
        with q.scratch_tree() as (temp,cleanup):
            (temp/'families.cpp').write_text(source,encoding='utf-8');exe=temp/'families.exe'
            build=q.command([cc,'-std=c++17','-O1','-Wall','-Wextra','-Werror','-Wno-unused-variable','-static','-I'+str(ROOT/'native/mk3'),temp/'families.cpp',
                             ROOT/'native/mk3/mk3_program.cpp',ROOT/'native/src/mk5_program.cpp','-I'+str(ROOT/'native/include'),'-lbcrypt','-o',exe],temp,env=env,timeout=300)
            self.assertTrue(build['passed'],q.compact(build)['output_tail'])
            run=q.command([exe],temp,env=env,timeout=60);self.assertTrue(run['passed'],q.compact(run)['output_tail'])
            lines=[json.loads(line) if line.startswith('{') else line for line in run['stdout'].splitlines()]
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(len(lines),len(cases))
        return lines

    def test_profiles_strict_rejects_game_notes_first_executions(self):
        source=r'''#include "mk3_cpu.hpp"
#include <cstdio>
#include <string>
int main(){ mk3::Program program; program.bytes.resize(0x100000); mk3::ResetTrace s; mk3::Ops o(program,s,std::vector<uint16_t>(0x6000));
  s.pc=0xff9253c0u; o.Begin(); std::string strict_edge, strict_block;
  try { o.Edge(0xff9253d0u,0xff9253c0u,true); } catch (const std::exception& e) { strict_edge=e.what(); }
  try { o.Block(0xff9253c0u); } catch (const std::exception& e) { strict_block=e.what(); }
  mk3::FirstExecution first; o.profile=mk3::Profile::Game; o.first=&first; s.cycles=77;
  o.Block(0xff9253c0u); o.Block(0xff9253c0u); o.Edge(0xff9253d0u,0xff9253c0u,true); o.Edge(0xff9253d0u,0xff9253c0u,true); o.Edge(0xff925000u,0xff9253c0u,false);
  std::printf("%s\n%s\n%zu", strict_edge.c_str(), strict_block.c_str(), first.order.size());
  for (auto& e: first.order) std::printf(" %u:%u:%u:%llu", unsigned(e.kind), e.id, e.from, (unsigned long long)e.cycle);
  std::printf("\n"); return 0; }
'''
        cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
        with q.scratch_tree() as (temp,cleanup):
            (temp/'profiles.cpp').write_text(source,encoding='utf-8');exe=temp/'profiles.exe'
            build=q.command([cc,'-std=c++17','-O1','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/include'),temp/'profiles.cpp',
                             ROOT/'native/mk3/mk3_program.cpp',ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],temp,env=env,timeout=300)
            self.assertTrue(build['passed'],q.compact(build)['output_tail'])
            run=q.command([exe],temp,env=env,timeout=60);self.assertTrue(run['passed'])
            lines=run['stdout'].splitlines()
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(lines[0],'MK3 unobserved branch; PC 4287779776; address 4287779776')
        self.assertEqual(lines[1],'MK3 PC outside the authenticated fixed translation; PC 4287779776; address 4287779776')
        expected=f'3 0:{0xff9253c0}:0:77 1:{0xff9253d0}:{0xff9253c0}:77 1:{0xff925000}:{0xff9253c0}:77'
        self.assertEqual(lines[2],expected)
        self.assertNotEqual(lines[2],expected.replace('3 ','4 ',1))   # negative: a duplicate note would be detected

    def test_shift_register_fill_unmapped_gfxrom(self):
        """J2 classes found by the attract route (compared there with the Original, VRAM hash included): PIXT *B2,B2 and
        FILL XY with DPYCTL.SRT (tms34010.cpp read_pixel_shiftreg, 34010gfx.hxx fill + shiftreg_w, midtunit_v.cpp
        to/from_shiftreg: 1024 VRAM words at bit address >> 3), the restart over a timeslice end (m_gfxcycles > m_icount),
        an unmapped write (midwunit main_map has no 0x01d01010) and midwunit_gfxrom_r. The expected values below come from
        this model of the pinned source; negatives: a mutated expectation and a mapped-but-unhandled write must differ."""
        codes={}
        for pc in (0xff81b4d0,0xff81b580):
            size,_,raw,asm=self.rows[pc];codes[pc]=generate.emit_unverified(pc,size,asm,raw,self.candidate,self.rom)
        pattern=[(i*7+1)&0xffff for i in range(1024)]
        base=0x00000000;pitch=0x2000;rows=0x7f   # rows 0-126; the pattern row (word 0x3fc00) is row 255
        source=('#include "mk3_cpu.hpp"\n#include <cstdio>\nint main(){ mk3::Program program; program.bytes.resize(0x100000); mk3::ResetTrace s;\n'
                ' std::vector<uint8_t> gfx(0x800010); for(size_t i=0;i<gfx.size();++i) gfx[i]=uint8_t(i*13+5);\n'
                ' mk3::Ops o(program,s,std::vector<uint16_t>(0x6000),gfx);\n'
                ' for(unsigned i=0;i<1024;++i) o.vram[0x3fc00+i]=uint16_t(i*7+1);\n'
                f' o.video.io[{DPYCTL}]=0xf810; o.video.io[{PSIZE}]=8; o.video.io[{CONTROL}]=0x20; o.video.io[{CONVDP}]=0x13;\n'
                f' o.io_written|=1u<<{DPYCTL}|1u<<{PSIZE}|1u<<{CONTROL}|1u<<{CONVDP};\n'
                f' s.pc=0xff81b4d0u; s.status=0x10; s.b[2]=0x1fe000u; o.Begin(); {codes[0xff81b4d0]}\n'
                ' std::printf("pixt %u %u %llu %u\\n", s.b[2], s.status, (unsigned long long)s.cycles, s.pc);\n'
                f' s.pc=0xff81b580u; s.status=0x10; s.cycles=1000; s.b[2]=0; s.b[3]={pitch}u; s.b[4]={base}u; s.b[7]={rows<<16|1}u; o.slice_end=1100; o.Begin(); {codes[0xff81b580]}\n'
                ' std::printf("fill1 %u %u %llu %u\\n", s.pc, s.status, (unsigned long long)s.cycles, s.b[2]);\n'
                f' o.slice_end=~0ull; o.Begin(); {codes[0xff81b580]}\n'
                ' std::printf("fill2 %u %u %llu %u\\n", s.pc, s.status, (unsigned long long)s.cycles, s.b[2]);\n'
                f' for(unsigned y: {{0u,1u,{rows-1}u,{rows}u}}) std::printf("row %u %u %u\\n", y, o.vram[({base}u+y*{pitch}u)/8], o.vram[({base}u+y*{pitch}u)/8+1023]);\n'
                ' o.Write16(0x01d01010u,1); std::printf("unmapped ok\\n");\n'
                ' try { o.Write16(0x01680010u,1); std::printf("mapped ignored\\n"); } catch (const std::exception& e) { std::printf("mapped rejected\\n"); }\n'
                ' s.video_control=0x0100; std::printf("gfx %u\\n", o.Read16(0x02000010u));\n'
                ' std::printf("unmapped read %u\\n", o.Read16(0x781e6380u));\n'
                ' try { o.Read16(0x01b00000u); std::printf("mapped read ignored\\n"); } catch (const std::exception& e) { std::printf("mapped read rejected\\n"); }\n'
                ' return 0; }\n')
        cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
        with q.scratch_tree() as (temp,cleanup):
            (temp/'srt.cpp').write_text(source,encoding='utf-8');exe=temp/'srt.exe'
            build=q.command([cc,'-std=c++17','-O1','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/include'),temp/'srt.cpp',
                             ROOT/'native/mk3/mk3_program.cpp',ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],temp,env=env,timeout=300)
            self.assertTrue(build['passed'],q.compact(build)['output_tail'])
            run=q.command([exe],temp,env=env,timeout=60);self.assertTrue(run['passed'],q.compact(run)['output_tail'])
            got=run['stdout'].splitlines()
        self.assertFalse(cleanup['exists_after'])
        P=1<<25;gfxbyte=lambda i:(i*13+5)&0xff
        expected=[f'pixt {pattern[0]} {0x10|V} 4 {0xff81b4e0}',                      # B2 = shiftreg[0], V = nonzero, 4 cycles
                  f'fill1 {0xff81b580} {0x10|P} 1100 0',                            # 8 + 127*4 = 516 > 100 left: restart, ST.P
                  f'fill2 {0xff81b590} 16 1516 {rows<<16}',                         # the remaining 416, DADDR_Y += DYDX_Y
                  *(f'row {y} {pattern[0]} {pattern[1023]}' for y in (0,1,rows-1)),f'row {rows} 0 0',
                  'unmapped ok','mapped rejected',f'gfx {gfxbyte(0x800002)|gfxbyte(0x800003)<<8}','unmapped read 0','mapped read rejected']
        self.assertEqual(got,expected)
        self.assertNotEqual(got,[e.replace('1516','1517') for e in expected])   # negative: one cycle more would be detected

if __name__=='__main__':unittest.main()
