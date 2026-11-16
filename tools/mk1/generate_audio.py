"""MK1 sound CPU (6809 on the Williams ADPCM board) ahead-of-time translation from the user's U3.

Inputs: U3 (authenticated by tools/mk1/roms-l1.json), the project 6809 decoder (tools/mk1/m6809.py) and the address
table tools/mk1/audio_nodes.json (the translated (bank, pc) keys; addresses only). Outputs, in generated/mk1/<sha>/:
  mk5_audio_graph.inc        one case per key: the instruction's fixed C++ body (bus-cycle order of the pinned 6809
                             core: dummy cycles before reads, stack and indirect cycle offsets), no runtime decoding
  mk5_audio_checkpoints.inc  the m_icount check spans of each key (cycles consumed before a suspension point)
"""
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk1 import m6809

ROOT=Path(__file__).resolve().parents[2]
NODES=ROOT/'tools/mk1/audio_nodes.json'
U3_SHA256='ce0b5ee6c0ce7daf23dfcc4fb78a11bcc5caa600eeb3e6d7badbdf0fb880b396'

REG={'A':'c.a','B':'c.b','D':'d()','X':'c.x','Y':'c.y','U':'c.u','S':'c.s','DP':'c.dp','CC':'c.cc','PC':'c.pc'}
WORD={'D','X','Y','U','S'}


def put(reg,expr):
    return f'setd({expr});' if reg=='D' else f'{REG[reg]}={expr};'


def keys():
    data=json.loads(NODES.read_text('utf-8'))
    return [(b,p) for b,p in data['keys']]


def indexed(ix,nxt):
    """(statement computing ea, extra cycles) of an indexed operand."""
    base={'X':'c.x','Y':'c.y','U':'c.u','S':'c.s','PC':'c.pc'}.get(ix.base,'')
    pre=post='';extra=0
    if ix.kind=='off5':expr=f'uint16_t({base}+({ix.offset}))';extra=1
    elif ix.kind in ('inc1','inc2'):
        n=1 if ix.kind=='inc1' else 2;expr=base;post=f'{base}+={n};';extra=2 if n==1 else 3
    elif ix.kind in ('dec1','dec2'):
        n=1 if ix.kind=='dec1' else 2;pre=f'{base}-={n};';expr=base;extra=2 if n==1 else 3
    elif ix.kind=='zero':expr=base
    elif ix.kind in ('accA','accB'):expr=f'uint16_t({base}+int8_t({"c.b" if ix.kind=="accB" else "c.a"}))';extra=1
    elif ix.kind=='off8':expr=f'uint16_t({base}+({ix.offset}))';extra=1
    elif ix.kind=='off16':expr=f'uint16_t({base}+({ix.offset}))';extra=4
    elif ix.kind=='accD':expr=f'uint16_t({base}+int16_t(d()))';extra=4
    elif ix.kind in ('pcr8','pcr16'):expr=f'uint16_t(next+({ix.offset}))';extra=1 if ix.kind=='pcr8' else 5
    else:expr=hex(ix.offset);extra=2
    if ix.indirect:
        extra+=3
        if post:return pre+f'uint16_t pointer_address={expr};'+post+'uint16_t ea=r16(pointer_address);',extra
        expr=f'r16({expr})'
    return pre+f'uint16_t ea={expr};'+post,extra


def translate(ins):
    m=ins.mnemonic;nxt=ins.next;page=bool(ins.page);op=ins.opcode
    prefix=f'constexpr uint16_t next=0x{nxt:04x};c.pc=next;';cycles=2;code=''
    def operand(word=False):
        nonlocal cycles,prefix
        if ins.mode in (m6809.IMM8,m6809.IMM16):
            cycles=(3 if word else 2)+page;return hex(ins.value)
        if ins.mode==m6809.DIR:prefix+=f'uint16_t ea=uint16_t((c.dp<<8)|0x{ins.value:02x});';cycles=5 if word else 4
        elif ins.mode==m6809.IDX:
            stmt,extra=indexed(ins.index,nxt);prefix+=stmt;cycles=(5 if word else 4)+extra
        else:prefix+=f'uint16_t ea=0x{ins.value:04x};';cycles=6 if word else 5
        cycles+=page;return 'r16(ea)' if word else 'r8(ea)'
    if m in ('ORCC','ANDCC'):code=f'c.cc {"|=" if m=="ORCC" else "&="} 0x{ins.value:02x};';cycles=3
    elif m in ('TFR','EXG'):
        src,dst=m6809.REGISTERS[ins.value>>4],m6809.REGISTERS[ins.value&15];code=put(dst,REG[src]);cycles=6
        if m=='EXG':code=f'auto tmp={REG[dst]};'+code+put(src,'tmp');cycles=8
    elif m in ('PSHS','PULS','PSHU','PULU'):
        stack='c.s' if m.endswith('S') else 'c.u';other='c.u' if stack=='c.s' else 'c.s';mask=ins.value;push=m.startswith('PSH');cycles=5
        order=[(0,'c.cc',False),(1,'c.a',False),(2,'c.b',False),(3,'c.dp',False),(4,'c.x',True),(5,'c.y',True),(6,other,True),(7,'c.pc',True)]
        size=sum((2 if word else 1) for bit,_,word in order if mask&(1<<bit))
        code=f'bus_cycle-={size-1 if push else size};'   # the stack accesses end one cycle before (push) / at (pull) the end
        for bit,reg,word in (reversed(order) if push else order):
            if mask&(1<<bit):code+=f'push{16 if word else 8}({stack},{reg});' if push else f'{reg}=pop{16 if word else 8}({stack});';cycles+=2 if word else 1
    elif m in ('RTS','RTI'):
        if m=='RTS':code='bus_cycle-=2;c.pc=pop16(c.s);';cycles=5
        else:code='bus_cycle=c.cycles+3;c.cc=pop8(c.s);if(c.cc&0x80){c.a=pop8(c.s);c.b=pop8(c.s);c.dp=pop8(c.s);c.x=pop16(c.s);c.y=pop16(c.s);c.u=pop16(c.s);cost+=9;}c.pc=pop16(c.s);';cycles=6
    elif m in ('JMP','JSR','BSR','LBSR'):
        if m in ('BSR','LBSR'):code=f'bus_cycle-=1;push16(c.s,next);c.pc=0x{ins.value:04x};';cycles=7 if m=='BSR' else 9
        else:operand();code=('bus_cycle-=1;push16(c.s,next);' if m=='JSR' else '')+'c.pc=ea;';cycles+=3 if m=='JSR' else -1
    elif ins.mode in (m6809.REL8,m6809.REL16):
        branch=m[2:] if m.startswith('LB') else m[1:]
        cond={'RA':'true','RN':'false','HI':'!(c.cc&5)','LS':'(c.cc&5)','CC':'!(c.cc&1)','CS':'(c.cc&1)','NE':'!(c.cc&4)','EQ':'(c.cc&4)',
              'VC':'!(c.cc&2)','VS':'(c.cc&2)','PL':'!(c.cc&8)','MI':'(c.cc&8)','GE':'bool(c.cc&8)==bool(c.cc&2)','LT':'bool(c.cc&8)!=bool(c.cc&2)',
              'GT':'!(c.cc&4) && (bool(c.cc&8)==bool(c.cc&2))','LE':'(c.cc&4) || (bool(c.cc&8)!=bool(c.cc&2))'}[branch]
        cycles=5 if m.startswith('LB') else 3
        code=f'if({cond}){{c.pc=0x{ins.value:04x};'+('++cost;' if m.startswith('LB') and branch not in ('RA','RN') else '')+'}'
    elif m.startswith('LEA'):
        reg=m[3:];stmt,extra=indexed(ins.index,nxt);prefix+=stmt;code=put(reg,'ea')+(f'z16({REG[reg]});' if reg in ('X','Y') else '');cycles=4+extra
    elif m.startswith(('LD','ST','CMP','SUB','ADD','ADC','SBC','AND','BIT','EOR','OR')) and m not in ('ORCC','ANDCC'):
        family=next(x for x in ('CMP','SUB','ADD','ADC','SBC','AND','BIT','EOR','LD','ST','OR') if m.startswith(x));reg=m[len(family):]
        word=reg in WORD;value=operand(word);rv=REG[reg];width=16 if word else 8
        if family=='LD':code=f'auto v={value};'+put(reg,f'nz{width}(v)')
        elif family=='ST':code=f'w{width}(ea,{rv});nz{width}({rv});'
        elif family in ('CMP','SUB','ADD','ADC','SBC'):
            isadd=family in ('ADD','ADC');carry='(c.cc&1)' if family in ('ADC','SBC') else '0'
            expr=f'{"add" if isadd else "sub"}{width}({rv},{value},{carry})';code=f'(void){expr};' if family=='CMP' else put(reg,expr)
            if word and reg=='D' and family in ('ADD','SUB'):cycles+=1
            if family=='CMP' and word:cycles+=1
        else:
            oper={'AND':'&','BIT':'&','EOR':'^','OR':'|'}[family];expr=f'nz8({rv}{oper}{value})';code=f'(void){expr};' if family=='BIT' else put(reg,expr)
    elif m in ('NOP','ABX','MUL','SEX'):
        code={'NOP':'','ABX':'c.x+=c.b;','MUL':'setd(uint16_t(c.a)*c.b);c.cc=(c.cc&~5)|(d()==0?4:0)|(c.b&0x80?1:0);','SEX':'c.a=(c.b&0x80)?0xff:0;(void)nz16(d());'}[m]
        cycles={'NOP':2,'ABX':3,'MUL':11,'SEX':2}[m]
    elif m.rstrip('AB') in ('CLR','COM','NEG','INC','DEC','TST','LSR','ASR','ASL','ROL','ROR'):
        reg=m[-1] if ins.mode==m6809.INH else None;kind=m[:-1] if reg else m
        if reg:v=REG[reg];cycles=2
        else:v=operand();cycles+=2
        if reg:code=f'uint8_t v={v};'
        else:code=f'bus_cycle-=2;uint8_t v={v};bus_cycle+=2;'
        code+=f'uint8_t result=unary(v,Unary::{kind});'
        if kind!='TST':code+=put(reg,'result') if reg else 'w8(ea,result);'
        else:code+='(void)result;'
    else:raise ValueError('untranslated 6809 form '+ins.text)
    if ins.index is not None and ins.index.indirect:
        # The pointer read of an indirect operand happens `tail` cycles before the end of the instruction.
        if m=='JSR':tail=5
        elif m.startswith(('LD','ST','CMP','SUB','ADD','ADC','SBC','AND','BIT','EOR','OR')):tail=3 if m[-1] in WORD else 2
        else:raise ValueError('untranslated 6809 indirect form '+ins.text)
        head,ea=prefix.split('uint16_t ea=',1) if 'pointer_address' not in prefix else prefix.split('uint16_t pointer_address=',1)
        ea=('uint16_t ea=' if 'pointer_address' not in prefix else 'uint16_t pointer_address=')+ea
        return f'{head}const unsigned cost={cycles};begin_bus(cost-{tail});{ea}begin_bus(cost);{code}finish(cost);return;'
    return f'{prefix}unsigned cost={cycles};begin_bus(cost);{code}finish(cost);return;'


def graph(u3):
    out=['// Generated offline from authenticated original U3 bytes. No runtime opcode decode.',
         'switch((uint32_t(instruction_start.pc<0xc000?instruction_bank:0)<<16)|instruction_start.pc){']
    for bank,pc in keys():   # table order (the emission order of the qualified graph)
        ins=m6809.decode(m6809.u3_reader(u3,bank),pc)
        out.append(f'case 0x{bank:x}{pc:04x}:{{ // {ins.raw.hex()} {ins.text}\n{translate(ins)}\n}}')
    out+=['default: frontier=true;return;','}']
    return '\n'.join(out)+'\n'


def suspension_spans(ins):
    """(first, last) cycle offsets inside the instruction where the pinned 6809 core checks its cycle budget only after
    a group of cycles (MUL, TFR/EXG, ORCC/ANDCC, stack and BSR/LBSR sequences, auto-increment/decrement and 16-bit,
    accumulator-D and PC-relative indexed operands); a frontier inside a span completes at its last cycle."""
    p=int(bool(ins.page));op=ins.opcode;out=[]
    if op in (0x1a,0x1c):out.append((2,3))
    if op==0x3d:out.append((3,11))
    if op==0x1e:out.append((2,8))
    if op==0x1f:out.append((2,6))
    if op in (0x34,0x35,0x36,0x37):out.append((3,4))
    if op==0x8d:out.append((3,5))
    if op==0x17:out.append((4,7))
    if ins.mode==m6809.IDX and ins.index.post&0x80:
        mode=ins.index.post&15
        if mode in (0,2):out.append((4,5))
        if mode in (1,3):out.append((4,6))
        if mode in (9,11):out.append((5,7))
        if mode==13:out.append((5,8))
    return [(a+p,b+p) for a,b in out]


def checkpoints(u3):
    out=['// Generated offline from U3 bytes and pinned 6809 suspension groups.']
    for bank,pc in keys():
        spans=suspension_spans(m6809.decode(m6809.u3_reader(u3,bank),pc))
        if spans:
            tests=''.join(f'if(offset>={a} && offset<={b})return instruction_start.cycles+{b};' for a,b in spans)
            out.append(f'case 0x{bank:x}{pc:04x}: {tests} break;')
    return '\n'.join(out)+'\n'


def texts(u3):
    """{include name: text} of the sound CPU translation of `u3` (refused unless it is the supported U3)."""
    if hashlib.sha256(u3).hexdigest()!=U3_SHA256:raise ValueError('mks-u3.rom differs from the supported MK1 revision')
    return {'mk5_audio_graph.inc':graph(u3),'mk5_audio_checkpoints.inc':checkpoints(u3)}
