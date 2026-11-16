"""Authenticated offline PC closure for the MK2 architectural dispatcher."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
from tools.mk2 import generate_video_irq as emitter
from tools.mk2 import generate_static_cfg as cfg
from tools.mk2.offline_decode import decode


# Observed exchanges supplement the graph without closing the register domains.
EXCHANGE_EVIDENCE = {
    # The factory VRAM clear returns to FFA5A190; FFA5A1C0 overwrites FFA59F30.
    0xffa59f20: ('B6', (0xffa5a190,)),
    # GETPC+ADDI saves these targets via FF819100 / FF819170, read back by MMFM.
    0xff81a2b0: ('A7', (0xff819140, 0xff81a2c0)),
    0xff81a890: ('A7', (0xff8191b0, 0xff81a8a0)),
    0xff83c420: ('A7', (0xff83c430, 0xff8bde90)),  # Pit II continuation saved at FF8BDE50
}

# Observed CALL destinations leave their computed domains open.
CALL_EVIDENCE = {
    0xff8049e0: ('A0', (0xff8049f0, 0xff82da10, 0xff85d400)),  # FF82C720 / FF85C270 write 0105D0E0
    0xff804f90: ('A2', (0xff800000, 0xff804fa0)),  # FFA044C0 stream operand
    0xff9f88e0: ('A1', (0xff9f88f0, 0xffa04620)),  # FFA03FC0 producer record
}

JUMP_EVIDENCE = {
    # Task continuations restored by FF80DDE0, from authenticated Original witnesses.
    0xff80de00: ('A7', (
        0xff81f4e0, 0xff820ac0, 0xff820b90, 0xff820be0, 0xff8214a0, 0xff8218c0,
        0xff821910, 0xff83e3c0, 0xff841f10, 0xff870a60, 0xff870ec0, 0xff870f40,
        0xff8713b0, 0xff8714a0, 0xff876980, 0xff8de9f0, 0xff8e1350, 0xff8e6e00,
        0xff8e6fe0, 0xff9a7f70, 0xff9a8210, 0xff9a9010, 0xff9ac820, 0xff9ac940,
        0xff9acac0, 0xff9acc20, 0xff9ace60, 0xff9b0e50, 0xff9b2760, 0xff9b2d00,
        0xff9b5640, 0xff9b6560, 0xffa0c780, 0xffa0d4e0, 0xffa0d600, 0xffa0e2b0,
        0xffa0e340, 0xffa0e740, 0xffa0e8a0, 0xffa17e10,
    )),
    0xff85d960: ('A10', (0xff85dab0, 0xff85db40, 0xff85dbb0, 0xff85dc50)),  # Four render legs
}
PARTITIONS = Path(__file__).with_name('partitions.json')
TRANSFER_EVIDENCE = {'EXGPC': EXCHANGE_EVIDENCE, 'CALL': CALL_EVIDENCE, 'JUMP': JUMP_EVIDENCE}


def closure_targets(pc, size, asm, vector, *, rom=None, mk2=True):
    """mk2=False: another authenticated program; the MK2 L3.1 evidence below does not apply."""
    targets=cfg.direct_targets(pc,size,asm,vector)
    parts=asm.split()
    op=parts[0]
    transfer=TRANSFER_EVIDENCE.get(op, {}).get(pc) if mk2 else None
    if transfer and size == 16 and parts == [op, transfer[0]]:
        if rom is not None and hashlib.sha256(rom).hexdigest() == emitter.PROGRAM_SHA256:
            return transfer[1]
    # Authenticated FF83D7E0 pops A7, then either loads the inline pointer
    # (actor C/D) or adds32 bits before JUMP A7. Both entries are executable roots.
    if mk2 and op in ('CALLA','CALLR') and 0xff83d7e0 in (targets or ()):
        targets=tuple(sorted(set(targets) | {pc+size+32}))
    if op in ('CALL','CALLA','CALLR','EXGPC','TRAP'):
        return tuple(sorted(set(targets or ()) | {pc+size}))
    return targets or ()


def saved_pc_entry(pc, asm, previous, *, size=32):
    """A saved GETPC plus a constant offset can be resumed after a task switch."""
    parts=asm.split()
    if previous is None or previous[0]!=16 or len(parts)!=2 or parts[0]!='ADDI':return None
    value,destination=parts[1].split(',')
    if previous[3].split()!=['GETPC',destination]:return None
    offset=emitter.immediate(value)
    if size==32 and offset&0x8000:offset|=0xffff0000
    return (pc+offset)&0xfffffff0


def computed_pc_entries(rows):
    """Encoded constants are conservative offline roots, never imported CPU state."""
    previous={pc+row[0]:pc for pc,row in rows.items()}
    entries=set()
    def parts(pc):
        row=rows.get(pc)
        if row is None:return None
        match=re.fullmatch(r'(MOVI|MOVE|ADDI)\s+([^, ]+),([AB](?:1[0-5]|[0-9])|SP)',row[3])
        return (row[0],*match.groups()) if match else None
    def immediate(value,size):
        result=emitter.immediate(value)
        return result | 0xffff0000 if size==32 and result&0x8000 else result
    for pc,row in rows.items():
        item=parts(pc)
        if item is None or item[1]!='ADDI' or item[0] not in (32,48):continue
        size,op,value,destination=item
        following=parts(pc+size)
        if following and following[1]=='ADDI' and following[3]==destination:continue
        offset=immediate(value,size);cursor=previous.get(pc)
        before=parts(cursor)
        while before and before[1]=='ADDI' and before[3]==destination and before[0] in (32,48):
            offset+=immediate(before[2],before[0]);cursor=previous.get(cursor);before=parts(cursor)
        if before and before[0]==16 and before[1]=='MOVE' and before[3]==destination:
            destination=before[2];cursor=previous.get(cursor);before=parts(cursor)
        if before is None or before[1]!='MOVI' or before[3]!=destination or before[0] not in (32,48):continue
        target=(immediate(before[2],before[0])+offset)&0xffffffff
        if 0xff800000<=target<=0xfffffff0 and not target&15:entries.add(target)
    return entries


def partition(source, *, shards=None):
    """Keep each instruction body intact, with at most256 PC slots per function."""
    blocks=re.findall(r'^(case 0x([0-9a-f]{8})u: \{ // [^\n]*\n.*?^\}\n)',source,re.M|re.S)
    if not blocks or len(blocks)!=len(re.findall(r'^case 0x',source,re.M)):
        raise ValueError('Static dispatcher case format differs')
    pages={};seen=set()
    executable=set()
    for block,label in blocks:
        pc=int(label,16)
        if pc in seen or pc&15:raise ValueError('Duplicate or unaligned static PC')
        seen.add(pc);pages.setdefault(pc>>12,[]).append(block)
        if not block.split('\n',1)[1].lstrip().startswith('throw std::runtime_error('):executable.add(pc)
    output=[]
    base=min(seen)&~0x3ff
    masks=[0]*(((max(seen)-base)>>10)+1)
    for pc in executable:
        slot=(pc-base)>>4;masks[slot>>6]|=1<<(slot&63)
    output.append('static bool IsFirstFightStaticPC(uint32_t pc) {\n')
    lower=f'pc<0x{base:08x}u || 'if base else ''
    output.append(f'    if((pc&15) || {lower}pc>0x{max(seen):08x}u)return false;\n')
    output.append('    static constexpr uint64_t bits[]={\n')
    for n in range(0,len(masks),8):output.append('        '+','.join(f'0x{v:016x}ull'for v in masks[n:n+8])+',\n')
    output.append(f'    }};\n    const auto slot=(pc-0x{base:08x}u)>>4;\n    return (bits[slot>>6]>>(slot&63))&1;\n}}\n')
    for page,entries in sorted(pages.items()):
        linkage = 'static ' if shards is None else ''
        body = (f'[[gnu::noinline]] {linkage}bool FirstFightPage_{page:x}(BootOps& o) {{\n'
                '    auto& s=o.s;\n    switch(s.next_pc) {\n' + ''.join(entries) +
                '    default:return false;\n    }\n    return true;\n}\n')
        if shards is None:
            output.append(body)
        else:
            base = (page << 12) & ~0x7ffff
            shards[base] = shards.get(base, '') + body
            output.append(f'bool FirstFightPage_{page:x}(BootOps&);\n')
    output.append('[[gnu::noinline]] static bool ExecuteFirstFightStatic(BootOps& o) {\n    switch(o.s.next_pc>>12) {\n')
    for page in sorted(pages):output.append(f'    case {page}:return FirstFightPage_{page:x}(o);\n')
    output.append('    default:return false;\n    }\n}\n')
    return ''.join(output)


def generate(rom):
    if hashlib.sha256(rom).hexdigest()!=emitter.PROGRAM_SHA256:
        raise ValueError('Architectural closure requires authenticated ROM')
    directory=emitter.ROOT/'native/mk2'
    # Feature units and their PC sets: tools/mk2/partitions.json (addresses only); nothing generated is read back.
    partitions=json.loads(PARTITIONS.read_text(encoding='utf8'))
    if partitions.get('schema')!='mk2-partitions/1' or partitions.get('program_sha256')!=emitter.PROGRAM_SHA256:
        raise ValueError('partitions.json names another program image')
    units={name:{int(pc,16) for pc in text.split()} for name,text in partitions['units'].items()}
    from tools.mk2 import generate_first_fight as fight
    from tools.mk2 import generate_valid_host_edges as host
    roots=set(fight.PCS)
    roots.update(int(pc,16) for pc in json.loads(Path(__file__).with_name('architectural_roots.json').read_text())['pcs'])
    roots.update(int(pc,16) for pc in json.loads(host.PATH.read_text())['nodes'])
    for pcs in units.values():roots.update(pcs)
    # ROM pointer candidates only add static code entries; they never import guest state.
    pointers={int.from_bytes(rom[n:n+4],'little') for n in range(0,len(rom)-3,2)}
    pointers={pc for pc in pointers if 0xff800000<=pc<=0xfffffff0 and not pc&15}
    pending=roots|pointers;rows={};cache={};edges={};decode_calls=0
    vector=int.from_bytes(rom[0xffff8:0xffffc],'little')
    class RomAddresses:
        def __contains__(self,pc):return 0xff800000<=pc<=0xfffffff0 and not pc&15
    while pending:
        decoded,proof=decode(rom,sorted(pending),cache=cache);decode_calls+=proof['calls']
        rows.update(decoded);pending=set()
        for pc,(size,flags,raw,asm) in decoded.items():
            try:
                emitter.emit_instruction(pc,size,asm,raw,RomAddresses(),{pc:(vector,)},end=0xff80dd30,mame_table=True)
                targets=closure_targets(pc,size,asm,vector)
                instruction_targets=cfg.direct_targets(pc,size,asm,vector) or ()
                # Reserved dispatch is a 16-bit no-op in MAME; the decoded targets stay roots, so no PC leaves the closure.
                if emitter.reserved(raw[0]):targets=tuple(sorted(set(targets)|{pc+16}));instruction_targets=(pc+16,)
            except ValueError:targets=();instruction_targets=()
            targets=tuple(t for t in targets if 0xff800000<=t<=0xfffffff0 and not t&15)
            edges[pc]=instruction_targets
            pending.update(t for t in targets if t not in rows)
            saved=saved_pc_entry(pc,asm,rows.get(pc-16),size=size)
            if saved is not None and saved not in rows and saved in RomAddresses():pending.add(saved)
        pending.update(computed_pc_entries(rows)-rows.keys())
    pcs=set(rows);blocks={};frontiers={}
    for pc,(size,flags,raw,asm) in sorted(rows.items()):
        try:code=emitter.emit_instruction(pc,size,asm,raw,pcs,edges,end=0xff80dd30,mame_table=True)
        except ValueError as error:
            frontiers[f'{pc:08x}']={'asm':asm,'error':str(error)}
            code=f'throw std::runtime_error("MK2 untranslated instruction {pc:08x}: {asm}");'
        blocks[pc]=f'case 0x{pc:08x}u: {{ // {asm}\n    {code}\n    break;\n}}\n'
    header='// Generated offline by tools/mk2/generate_architectural.py; no runtime decoder.\n// ROM SHA256 '+emitter.PROGRAM_SHA256+'\n'
    outputs={}
    outputs[directory/'mk2_first_fight.inc']=header+partition(''.join(blocks[pc] for pc in sorted(pcs)))
    for name,selected in sorted(units.items()):
        if selected-pcs:raise ValueError(name+': partition PCs outside the static closure')
        outputs[directory/name]=header+''.join(blocks[pc] for pc in sorted(selected))
    report={'program_sha256':emitter.PROGRAM_SHA256,'decoder_sha256':emitter.DECODER_SHA256,
            'policy':'architectural transfers to closed static PC dispatcher',
            'existing_roots':len(roots),'ROM_pointer_candidates':len(pointers),
            'static_PCs':len(pcs),'decoder_calls':decode_calls,'frontier_count':len(frontiers),
            'dispatch_pages':len({pc>>12 for pc in pcs}),'maximum_page_cases':max(Counter(pc>>12 for pc in pcs).values()),
            'frontier_reasons':dict(Counter(re.sub(r'[0-9a-f]{8}','PC',v['error'].split(':')[0]) for v in frontiers.values())),
            'frontier_examples':dict(list(frontiers.items())[:24]),
            'output_newlines':'CRLF',
            'outputs':{str(p.relative_to(emitter.ROOT)):hashlib.sha256(s.replace('\n','\r\n').encode()).hexdigest() for p,s in outputs.items()},
            'gameplay_qualified':False}
    return outputs,report


if __name__=='__main__':
    outputs,report=generate(emitter.load_program(emitter.ROOT/'roms/mk2'))
    for path,source in outputs.items():path.write_text(source,encoding='utf8',newline='\r\n')
    target=emitter.ROOT/'build/native/mk2-delivery-recovery-20261102/generation.json'
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('frontier_reasons','frontier_examples','outputs')},indent=2))
    print('frontiers',report['frontier_count'])
