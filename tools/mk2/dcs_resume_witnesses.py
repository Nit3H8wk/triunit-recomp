"""DCS resume fixtures of native/tests/mk2_adsp_resume_tests.cpp: synthetic start states stepped in pinned MAME 0.280.

Evidence class D9 (synthetic state, one instruction per step; tools/oracle/mame_step.py, target :dcs:dcs). Each block
runs the authenticated U2 words at its PCs from a synthetic state: registers from a fixed formula (IMASK/ICNTL 0, no
circular buffers, the DAG pointers inside internal DM), the PC stack pushed by a CALL preamble, and every internal PM,
external PM and internal DM word seeded with the C++ test's isolation sentinels. The generated include keeps the start
state (synthetic), the code PCs (their words are read from the user's U2 by the test) and only the SHA-256 of the
DSP76 rows MAME reached after each step and of its data-write lanes; no Original state is stored. The table lives
between the BEGIN/END markers of the C++ test; this tool rewrites (or compares) only that region.

The irq2 block is the DSP side of the test's host-write x scanline-timer replay: the idle loop from 0x130 with IRQ2
unmasked (IMASK 0x20, level IRQ2), five idle instructions (the number the board replay runs before the queued host
write reaches the DSP), then IRQ2 raised through the debugger (MAME dispatches on the write: PC and status pushed,
vector 0x0004) and the two vector instructions up to 0x395. MAME has to follow that PC path.

    python tools/mk2/dcs_resume_witnesses.py [--check]   # rerun MAME, rewrite (or compare) the test's table
"""
from pathlib import Path
import argparse,json,os,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.mk2.oracle_digest import words_digest
from tools.quality import run as q

TEST=ROOT/'native/tests/mk2_adsp_resume_tests.cpp'
BEGIN,END='// BEGIN dcs_resume_witnesses\n','// END dcs_resume_witnesses\n'
COMMAND='python tools/mk2/dcs_resume_witnesses.py'
# (id, first PC, instructions, PC stack bottom first, start cycle, code PCs or None for the consecutive U2 words from
# the first PC, step after which IRQ2 is raised or 0, PC after each step or None).
IRQ2_CODE=(0x004,0x130,0x131,0x132,0x394)
BLOCKS=(('wrap',0x358,6,(0x1a1,0x2b7,0x3c5),1000003,None,0,None),('clear',0x246,8,(0x1a1,0x31d),2000005,None,0,None),
        ('irq2',0x130,7,(),208263833,IRQ2_CODE,5,(0x131,0x132,0x130,0x131,0x132,0x394,0x395)))

def pm_sentinel(n):return (n*1337+0x55555)&0xffffff
def external_sentinel(n):return (n*293+0xabcdef)&0xffffff
def dm_sentinel(n):return (n*29^0xa55a)&0xffff

def u2_word(u2,pc):
    offset=0x1000+pc*4 if pc<0x400 else 0x2000+(pc-0x800)*4
    return u2[offset]<<16|u2[offset+1]<<8|u2[offset+2]

def start_registers(index,pc,cycles,stack):
    """Synthetic DSP76 (AdspBoot::Registers() order) for block `index`."""
    k=index+1
    v=lambda n,mask=0xffff:((0x2c49*(n+3*k)^0x5ab3*k)+n*n*7)&mask
    i=[0x3800+((v(20+n)%0x1f0)) for n in range(8)]          # DAG pointers inside internal DM 0x3800-0x39ef
    m=[(v(30+n)%7)-3 & 0x3fff for n in range(8)]            # small signed modifies, masked as Registers() shows them
    row=[pc,cycles,v(1),v(2),v(3,0xff),v(4,0x3fff),v(5,0xff),0x55 if k%2 else 0x54,0x18,0,0,len(stack),0,0,0,0]
    row+=i+m+[0]*8
    row+=[v(40+n) for n in range(11)]+[v(51,0xff),v(52),v(53,0xff),v(54,0x1f),v(55),v(56)]
    row+=[v(60+n) for n in range(12)]+[v(72,0xff),v(73),v(74),v(75,0xff),v(76,0x1f),v(77),v(78)]
    if len(row)!=76:raise AssertionError(len(row))
    if pc==0x130:
        # Idle loop AR=I7; AF=AR-AY0; IF GE JUMP 0x130: AY0 below I7 keeps it looping. IRQ2 unmasked, level-sensitive.
        row[42]=row[23]-0x25;row[9]=0x20
    if pc==0x246:
        # The clear block computes its DAG pointer from ALU/MAC inputs (MR0, AY0, AF): keep AR, AX/AY/AF, MX/MY and
        # MR0/MR1 in 0x80-0x1ff so the pointer stays in the seeded external-RAM window of DM (0x0000-0x07ff).
        for n in [2]+list(range(40,51)):row[n]=row[n]&0x17f|0x80
    if len(row)!=76:raise AssertionError(len(row))
    return row

def mame_regs(row):
    from tools.oracle.mame_step import DCS_REGISTERS
    names=DCS_REGISTERS
    if len(names)!=75:raise AssertionError('DCS register list')
    # DSP76 = PC, cycles, then the MAME names from AR on in the same order.
    return dict(zip(['PC']+names[1:],[row[0]]+row[2:]))

def blocks(u2):
    out=[]
    for index,(name,pc,count,stack,cycles,code_pcs,irq2_after,path) in enumerate(BLOCKS):
        row=start_registers(index,pc,cycles,stack)
        code={p:u2_word(u2,p) for p in (code_pcs or range(pc,pc+count))}
        pm={n:pm_sentinel(n) for n in range(0x400)}
        pm.update({0x800+n:external_sentinel(n) for n in range(0x800)})
        pm.update(code)
        dm={0x3800+n:dm_sentinel(n) for n in range(0x200)}
        regs=mame_regs(row);regs.pop('PC');regs.pop('PCSP')
        out.append(dict(id=name,pc=pc,steps=count,stack=list(stack),pm=pm,dm=dm,regs=regs,watch=[],_row=row,
                        after={irq2_after:{'IRQ2':1}} if irq2_after else {},_irq2=irq2_after,_path=path))
    return out

def rows_of(block,result):
    from tools.oracle.mame_step import DCS_REGISTERS
    if result['error']:raise ValueError(block['id']+': '+result['error'])
    start=block['_row'][1];rows=[]
    for k in range(block['steps']+1):
        got=result['rows'][k]
        rows.append([got['PC'],start+got['cycles']]+[got[n] for n in DCS_REGISTERS[1:]])
    if rows[0]!=block['_row']:
        bad=[(i,a,b) for i,(a,b) in enumerate(zip(rows[0],block['_row'])) if a!=b]
        raise ValueError(f"{block['id']}: MAME did not take the synthetic start state: {bad[:6]}")
    if any(r[1]!=start+k for k,r in enumerate(rows)):raise ValueError(block['id']+': not one cycle per instruction')
    if block['_path'] and [r[0] for r in rows[1:]]!=list(block['_path']):
        raise ValueError(f"{block['id']}: MAME PC path {[hex(r[0]) for r in rows]}")
    # Data writes: (PC, address, value, cycle offset of the writing instruction); native AdspBoot::accesses 'd'.
    writes=[(pc,address,value,step-1) for step,pc,address,value in result['writes']]
    return rows,writes

def emit(results):
    lines=['// Synthetic DCS resume blocks, compared with MAME 0.280 (:dcs:dcs) by '+COMMAND+' --check.',
           '// start: synthetic DSP76; rows: SHA-256 of the DSP76 MAME reached after each step (oracle_digest order);',
           '// writes: SHA-256 of the data-write lanes (PC, address, value, cycle offset); irq2: IRQ2 raised after that',
           '// step (0: none).']
    for block,(rows,writes) in results:
        lines.append(f"constexpr ResumeBlock k_{block['id']}{{0x{block['pc']:x},{block['steps']},{{{','.join(f'0x{s:x}' for s in block['stack'])}}},")
        lines.append('    {'+','.join(str(x) for x in block['_row'])+'},')
        lines.append('    {'+','.join(f'"{words_digest(r)}"' for r in rows[1:])+'},')
        lines.append(f'    "{words_digest([x for w in writes for x in w])}",{len(writes)},{block["_irq2"]}}};')
    return '\n'.join(lines)+'\n'

def mame_rompath(scratch):
    manifest=json.loads((ROOT/'tools/mk2/roms-l31.json').read_text('utf-8'))
    roms=scratch/'mk2';roms.mkdir()
    for rom in manifest['roms']:
        name=rom['upstream_name']
        if Path(name).name!=name:raise ValueError('ROM name')
        os.link(ROOT/'roms/mk2'/rom['path'],roms/name)   # same-volume hard links: removal keeps the sources

def generate():
    from tools.oracle import mame_step, mk2_oracle
    u2=(ROOT/'roms/mk2/su2.l1').read_bytes()
    identity=mk2_oracle.mk2_identity()
    bs=blocks(u2)
    with q.scratch_tree() as (scratch,cleanup):
        mame_rompath(scratch)
        results,receipt=mame_step.run_dcs(bs,rompath=scratch,verify=lambda:identity)
    if cleanup.get('exists_after'):raise RuntimeError('rompath scratch retained')
    return emit([(b,rows_of(b,r)) for b,r in zip(bs,results)]),receipt

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    text,receipt=generate()
    source=TEST.read_text(encoding='utf-8')
    head,rest=source.split(BEGIN);current,tail=rest.split(END)
    if args.check:
        if current!=text:raise SystemExit('DCS resume witnesses differ from MAME')
    else:TEST.write_bytes((head+BEGIN+text+END+tail).encode('utf-8'))
    print(json.dumps(dict(receipt,output_sha256=__import__('hashlib').sha256(text.encode()).hexdigest()),default=str))

if __name__=='__main__':main()
