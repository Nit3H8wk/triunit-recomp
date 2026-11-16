"""Fixed AOT blocks for the MK3 DCS 8K ADSP-2105 (U2 bank-0 boot page and the bank-1 program); no runtime decoder.

Semantics follow the pinned MAME adsp2100.cpp / 2100ops.hxx (docs/investigation/decoder-research/upstream).
Every word of every PM image the DCS 8K loads (IMAGES) is emitted by a linear sweep: the instruction has a fixed
24-bit width and Fetch() checks the run-time word, so a block that is never reached changes nothing. Measured
(pc, opcode) pairs (PCS, BANK1) are the verified blocks and emit exactly as before; every other block first calls
Unverified(), which rejects in the strict profile and records the first execution in the game profile. A word whose
form is not translated emits an explicit rejection in both profiles; a measured pair with such a form stops generation.
"""
from pathlib import Path
import argparse,hashlib,json,sys

ROOT=Path(__file__).resolve().parents[2]
U2='l1_mortal_kombat_3_u2_music_spch.u2'
U2_SHA256='eeffa20b1b436860682874464cc17efee597fdaa96c0bda34bd7e949072ffda6'
# Output: generated/mk3/<program_sha256>/ (tools/setup/mk3.py; never versioned).
# Measured PCs of the bank-0 boot code: power-on/reset path through the delay loop (window), its loop exit and
# host-command check, the IRQ2 handler and the bank-1 software reboot.
PCS=(0x00,*range(0x22,0x4a),*range(0xf5,0x101),*range(0x176,0x17f))
# PM 0x04 (IRQ2 vector) executes the word that the loop at 0x38/0x39 copies from PM 0x1c; the reload at
# every DCS reset restores the U2 word, so Fetch() checks the copied value at run time.
RUNTIME={0x04:0x1c}


def pcs(text):
    out=[]
    for part in text.split():
        a,_,b=part.partition('-');out+=range(int(a,16),int(b or a,16)+1)
    return tuple(out)


# Bank-1 program: (PC, opcode) pairs measured in the Original (debugger trace, pd@pc) from the boot-3 entry for
# 2.6 s, plus those of boot 5 (the bank-1 program after the host's second DCS reset) from power-on to 16 s
# (tools/mk3/reference_dcs.py capture_pairs, -seconds_to_run 16: the option is an integer). Each pair matches exactly one code identity; the same PC can carry two (0x802).
# PC 0 is the entry itself (the breakpoint that starts the trace stops on it).
#   page: internal PM, loaded by dcs_boot from U2 0x1000 (1024 words).
#   init: external PM 0x800.., copied at run time by PC 0x3f1 from data bank 0 DM 0x2800 (U2 0x0800).
#   main: external PM 0x800.., copied by the same routine from data bank 2 DM 0x2000 (U2 0x2000), over 'init'.
# Fetch() checks the run-time word, so a different copy rejects.
BANK1={'page':(0x1000,0x000,pcs('0 4 8-58 6a-19b 19e-1d0 1d5-22e 23e-24c 255-267 26b-270 2b3-2b8 2be-2cd 2d8-2dd 2eb-2f0 301-315 317 31a 321 '
                                 '32b-331 335-35a 361-3b8 3c0-3e2 3eb-3fe')),
       'init':(0x0800,0x800,pcs('800-8ad')),
       'main':(0x2000,0x800,pcs('800-835 838-867 869-89c 89f-8a1 8a4-9ee 9f2-a25 a29-a62 a65-a88 a9c-aad ab0-ab2 ab4-aeb af3-afc'))}


# PM images the DCS 8K loads (linear sweep). Extents: the boot pages as dcs_boot loads them ((U2[page + 3] + 1) * 8
# words); 'init' and 'main' up to the end of their data-bank window (DM 0x2fff, one PM word per 4 bank bytes) - a
# declared bound of the PC 0x3f1 copy, not its measured length: a PC past it rejects as outside the translation.
def images(u2):
    return {'boot':(0x0000,0x000,(u2[3]+1)*8,0),'page':(0x1000,0x000,(u2[0x1003]+1)*8,1),
            'init':(0x0800,0x800,(0x3000-0x2800)//4,1),'main':(0x2000,0x800,(0x3000-0x2000)//4,1)}


def sext14(v):return v-0x4000 if v&0x2000 else v


def emit(op,pc=-1):
    """C++ of one instruction (execute_run in adsp2100.cpp, ADSP-2105 = CHIP_TYPE_ADSP2105 >= ADSP2101, < ADSP2181)."""
    top,r=op>>16,op&15
    fn,x,y,reg=(op>>13)&15,(op>>8)&7,(op>>11)&3,(op>>4)&15
    def compute(kind):   # 0 MAC to MR, 1 ALU to AR, 2 MAC to MF, 3 ALU to AF
        if kind&1:return f'Alu({kind>>1}, {fn}, {x}, {y});'
        return f'Mac({kind>>1}, {fn}, {x}, {y});' if fn else ''   # mac_op_mr/mf case 0x00: no-op
    def shift(count):   # shift_op (count from SE) / shift_op_imm (functions 0x0c-0x0f have no case there: no-op)
        f=(op>>11)&15
        if count!='se':return f'Shift({f}, {x}, {count}, true);' if f<12 else ''
        return f'Shift({f}, {x}, int8_t(core_.se));'
    if top==0x00:return ''                                        # NOP (all low bits ignored)
    if top==0x01:return ''                                        # IO(x) moves: ADSP-218x only
    if top==0x02:
        if op&0x8000:return 'EatSlice();'                         # IDLE: m_idle = 1, m_icount = 0 (m_idle is never read)
        return f'if (Condition({r})) FlagOut(0x{op&0xfff0:04x});'
    if top==0x03:
        return f'if ({"flagin_" if op&2 else "!flagin_"}) {{{" PcPush();" if op&1 else ""} pc = 0x{((op>>4)&0xfff)|((op>>2)&3)<<12:04x}; }}'
    if top==0x04:
        out=('PcPopVal(); ' if op&0x10 else '')+('LoopPop(); ' if op&8 else '')+('CntrPop(); ' if op&4 else '')
        if op&2:out+='StatPop(); ' if op&1 else 'StatPush(); '
        return out.strip()
    if top==0x05:return 'SatMr();'
    if top==0x06:return f'Divs({x}, {y});'
    if top==0x07:return f'Divq({x});'
    if top==0x08:return ''                                        # reserved
    if top==0x09:return f'Modify({(op>>2)&7}, {(op>>2)&4|op&3});'
    if top==0x0a:return f'if (Condition({r})) {{ PcPop();{" StatPop();" if op&0x10 else ""} }}'
    if top==0x0b:
        return f'if (Condition({r})) {{{" PcPush();" if op&0x10 else ""} pc = uint16_t(i_[{4+((op>>6)&3)}] & 0x3fff); }}'
    if top==0x0c:
        clear=set_=0   # (enable bit, value bit) pairs of the mode-control word -> MSTAT bits
        for bit,mask in ((3,0x40),(13,0x10),(15,0x20),(5,0x01),(7,0x02),(9,0x04),(11,0x08)):
            if op>>bit&1:clear|=mask;set_|=mask if op>>(bit-1)&1 else 0
        return f'mstat_ = uint16_t((mstat_ & ~0x{clear:02x}) | 0x{set_:02x}); UpdateMstat();' if clear else 'UpdateMstat();'
    if top==0x0d:
        d=(op>>8)&15
        return f'WriteReg{d>>2}({reg}, ReadReg{d&3}({r}));'
    if top==0x0e:return f'if (Condition({r})) {shift("se")}'
    if top==0x0f:return shift(op&0xff if not op&0x80 else (op&0xff)-0x100)
    if top==0x10:   # shift with internal data register move: source read after the shift
        return f'{shift("se")} WriteReg0({reg}, ReadReg0({r}));'
    if 0x11<=top<=0x13:   # shift with program (DAG2) / data (DAG1, DAG2) memory read or write
        name={0x11:'Pgm{}Dag2',0x12:'Data{}Dag1',0x13:'Data{}Dag2'}[top]
        if op&0x8000:return f'{name.format("Write")}(0x{op:06x}u, ReadReg0({reg})); {shift("se")}'
        return f'{shift("se")} WriteReg0({reg}, {name.format("Read")}(0x{op:06x}u));'
    if 0x14<=top<=0x17:return f'LoopPush(0x{op&0x3ffff:05x}); PcPush();'
    if 0x18<=top<=0x1f:
        target=(op>>4)&0x3fff
        busy=' EatSlice();' if top<0x1c and target==pc else ''   # "check for a busy loop": m_icount = 0
        return f'if (Condition({r})) {{{" PcPush();" if top>=0x1c else ""} pc = 0x{target:04x};{busy} }}'
    if 0x20<=top<=0x27:return f'if (Condition({r})) {{ {compute((top>>1)&3)} }}'   # bits 4-7: ADSP-218x forms only
    if 0x28<=top<=0x2f:   # ALU/MAC with internal data register move: source read before the operation
        return f'{{ const int32_t t = ReadReg0({r}); {compute((top>>1)&3)} WriteReg0({reg}, t); }}'
    if 0x30<=top<=0x3f:return f'WriteReg{(top-0x30)>>2}({r}, {sext14((op>>4)&0x3fff)});'
    if 0x40<=top<=0x4f:return f'WriteReg0({r}, 0x{(op>>4)&0xffff:04x});'
    if 0x50<=top<=0x7f:   # ALU/MAC with program (DAG2) / data (DAG1, DAG2) memory read or write
        name={5:'Pgm{}Dag2',6:'Data{}Dag1',7:'Data{}Dag2'}[top>>4]
        if top&8:return f'{name.format("Write")}(0x{op:06x}u, ReadReg0({reg})); {compute((top>>1)&3)}'
        return f'{compute((top>>1)&3)} WriteReg0({reg}, {name.format("Read")}(0x{op:06x}u));'
    if 0x80<=top<=0x8f:return f'WriteReg{(top-0x80)>>2}({r}, DataRead(0x{(op>>4)&0x3fff:04x}));'
    if 0x90<=top<=0x9f:return f'DataWrite(0x{(op>>4)&0x3fff:04x}, uint16_t(ReadReg{(top-0x90)>>2}({r})));'
    if 0xa0<=top<=0xaf:return f'DataWriteDag1(0x{op:06x}u, 0x{(op>>4)&0xffff:04x});'
    if 0xb0<=top<=0xbf:return f'DataWriteDag2(0x{op:06x}u, 0x{(op>>4)&0xffff:04x});'
    # 0xc0-0xff: MAC to MR / ALU to AR with a DAG1 data read to AX0/AX1/MX0/MX1 and a DAG2 program read to
    # AY0/AY1/MY0/MY1; the operation reads the old registers first.
    return (f'{compute(1 if top&2 else 0)} WriteReg0({(0,1,2,3)[(top>>2)&3]}, DataReadDag1(0x{op:06x}u)); '
            f'WriteReg0({(4,5,6,7)[(top>>4)&3]}, PgmReadDag2(0x{op>>4:06x}u));').strip()


HEADER=['// Generated by tools/mk3/generate_adsp.py; do not edit.','// U2 SHA-256: '+U2_SHA256,
        '// Semantics: pinned MAME adsp2100.cpp / 2100ops.hxx (BSD-3-Clause, Aaron Giles).']


def block(pc,op,verified=True,measured_pc=True):
    """One emitted block. Verified: as the measured-only build. Otherwise Unverified() first (strict: the measured-only
    rejection, 'outside' when no verified identity shares the PC); a form emit() refuses rejects in both profiles."""
    try:body=emit(op,pc)
    except ValueError as e:
        if verified:raise ValueError(f'measured pair {pc:04x}/{op:06x}: {e}')
        return f'Unverified(0x{op:06x}u, {str(measured_pc).lower()}); Untranslated(); break;'
    head='' if verified else f'Unverified(0x{op:06x}u, {str(measured_pc).lower()}); '
    return f'{head}Fetch(0x{op:06x}u); {body} break;'.replace('  ',' ')


def authenticated(u2):
    if len(u2)!=0x100000 or hashlib.sha256(u2).hexdigest()!=U2_SHA256:raise ValueError('Generation requires the authenticated MK3 U2')
    return lambda offset:int.from_bytes(u2[offset:offset+3],'big')


def boot_pairs(u2):
    """Measured (pc, opcode) of the bank-0 boot page (PM 0x04 at its run-time copy of PM 0x1c)."""
    word=authenticated(u2)
    return sorted((pc,word(4*RUNTIME.get(pc,pc))) for pc in {*PCS,*RUNTIME})


def bank1_pairs(u2):
    """Measured (pc, opcode, identity) of the bank-1 program, from the authenticated U2."""
    word=authenticated(u2)
    return sorted((pc,word(offset+4*(pc-base)),name) for name,(offset,base,measured) in BANK1.items() for pc in measured)


def sweep(u2,page):
    """{pc: [(opcode, identities, verified)]} of every word of the boot page's PM images, in identity order."""
    word=authenticated(u2)
    verified={(pc,op) for pc,op in boot_pairs(u2)} if page==0 else {(pc,op) for pc,op,_ in bank1_pairs(u2)}
    out={}
    for name,(offset,base,count,image_page) in images(u2).items():
        if image_page!=page:continue
        for k in range(count):
            pc=base+k;op=word(4*RUNTIME[pc] if page==0 and pc in RUNTIME else offset+4*k)
            ids=out.setdefault(pc,[])
            same=[i for i in ids if i[0]==op]
            if same:same[0][1].append(name)
            else:ids.append((op,[name],(pc,op) in verified))
    missing=verified-{(pc,op) for pc,ids in out.items() for op,_,_ in ids}
    if missing:raise ValueError(f'measured pairs outside the swept images: {sorted(missing)[:4]}')
    return out


def lines_for(swept):
    lines=[]
    for pc,ids in sorted(swept.items()):
        measured_pc=any(v for *_,v in ids)
        if len(ids)==1:lines.append(f'case 0x{pc:04x}: '+block(pc,ids[0][0],ids[0][2],measured_pc));continue
        # the same PC under several code identities: select by the run-time word, validated by Fetch()
        lines.append(f'case 0x{pc:04x}: switch (Opcode()) {{')
        lines+=[f'    case 0x{op:06x}u: /* {"/".join(names)} */ '+block(pc,op,v,measured_pc) for op,names,v in ids]
        first=next((op for op,_,v in ids if v),None)
        lines.append(f'    default: Fetch(0x{first:06x}u); break;' if first is not None else
                     f'    default: Unverified(Opcode(), false); Fetch(0x{ids[0][0]:06x}u); break;')
        lines.append('    } break;')
    return lines


def generate(u2):
    return '\n'.join(HEADER+['// Code identity: boot = U2 0x0000 at PM 0x000']+lines_for(sweep(u2,0)))+'\n'


def generate_bank1(u2):
    lines=HEADER+['// Code identities: '+', '.join(f'{n} = U2 0x{o:04x} at PM 0x{b:03x} ({c} words)' for n,(o,b,c,page) in images(u2).items() if page==1)]
    return '\n'.join(lines+lines_for(sweep(u2,1)))+'\n'


def census(u2):
    """Compact sweep counts for receipts: words, blocks, verified, unverified, untranslated forms by top byte."""
    out={}
    for page,name in ((0,'boot'),(1,'bank1')):
        swept=sweep(u2,page);forms={}
        blocks=[(pc,op,v) for pc,ids in swept.items() for op,_,v in ids]
        for pc,op,v in blocks:
            try:emit(op,pc)
            except ValueError:forms[f'{op>>16:02x}']=forms.get(f'{op>>16:02x}',0)+1
        out[name]=dict(pcs=len(swept),blocks=len(blocks),verified=sum(v for *_,v in blocks),untranslated=sum(forms.values()),untranslated_by_top=forms)
    out['words']={n:c for n,(_,_,c,_) in images(u2).items()}
    return out


def main():
    """Writes both includes into generated/mk3/<program_sha256>/; --check regenerates them in memory and requires the
    files there and the acceptance manifest digests (tools/acceptance/manifest.json) to match."""
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--check',action='store_true');p.add_argument('--roms',type=Path,default=ROOT/'roms/mk3')
    a=p.parse_args();sys.path.insert(0,str(ROOT))
    from tools.setup import mk3 as setup_mk3
    texts,u2=setup_mk3.adsp_texts(a.roms);out=setup_mk3.adsp_dir(a.roms)
    accepted=json.loads((ROOT/'tools/acceptance/manifest.json').read_text('utf-8'))['files']
    for name,text in texts.items():
        if a.check:
            if (out/name).read_text('utf-8')!=text:raise SystemExit('stale '+name)
            want=accepted.get('native/mk3/'+name)
            if want and hashlib.sha256(text.encode()).hexdigest()!=want['sha256']:raise SystemExit('differs from the acceptance manifest: '+name)
        print(f'ADSP {name} '+('checked' if a.check else 'generated')+' in '+str(out.relative_to(ROOT)))
    print(json.dumps(census(u2)))


if __name__=='__main__':sys.exit(main())
