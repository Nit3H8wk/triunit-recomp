"""Offline direct ROM CFG additions; measured dynamic whitelists and runtime clocks stay unchanged.

static_cfg_path.json keeps addresses, widths, flow kinds, edges and the SHA-256 of each instruction's words; no
instruction text. Readers decode the text at run time from the user's ROM with the project decoder (validate()).
    python tools/mk2/generate_static_cfg.py [--check]   # rewrite (or compare) the file from the user's ROM
"""
from pathlib import Path
import hashlib
import json
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as emitter

PATH=Path(__file__).with_name('static_cfg_path.json')
ORIGIN='authenticated-ROM-direct-CFG'
CONDITIONAL=set(('JREQ JAEQ JRNE JRC JRNC JRN JRNN JRLT JRGE JRLE JRGT JRHI '
                 'JRV JRNV JRP JRLS JAC JANC JANE JAN').split())
CONDITIONAL.update('JA'+op[2:]for op in tuple(CONDITIONAL)if op.startswith('JR'))
DYNAMIC={'JUMP','CALL','EXGPC','RETS','RETI'}

def frontier(pc,asm,successors):
    """A dynamic return/jump of the closure without a measured whitelist stops the generated code (reject_frontier)."""
    op=asm.split(None,1)[0]
    if op not in DYNAMIC or successors.get(pc):return None
    if op=='RETS':return {'category':'missing_dynamic_return_whitelist','error':'Unqualified return'}
    if op in ('JUMP','CALL','EXGPC'):return {'category':'missing_dynamic_jump_whitelist','error':'Unqualified indirect jump'}
    raise ValueError('Unqualified static CFG dynamic form')

def flow_kind(asm):
    op=asm.split(None,1)[0]
    if op in DYNAMIC:return 'observed_dynamic'
    if op in ('CALLA','CALLR'):return 'direct_call_and_continuation'
    if op in ('JR','JA'):return 'direct_unconditional'
    if op in CONDITIONAL:return 'direct_conditional'
    if op in ('DSJ','DSJS','DSJEQ','DSJNE'):return 'direct_counter_branch'
    if op=='TRAP':raise ValueError('Unqualified static CFG software trap')
    return 'fallthrough'

def seed_digest(pcs,successors):
    payload={'pcs':sorted(pcs),'successors':{str(pc):sorted(targets) for pc,targets in sorted(successors.items())}}
    return hashlib.sha256(json.dumps(payload,separators=(',',':'),sort_keys=True).encode('ascii')).hexdigest()

def address(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{8}',value):
        raise ValueError('Static CFG address must be eight lowercase hex digits')
    result=int(value,16)
    if result%16 or not 0xff800000<=result<=0xfffffff0:
        raise ValueError('Static CFG target must be an aligned original ROM address')
    return result

def load():
    return json.loads(PATH.read_text(encoding='utf8'))

def extend(pcs,successors,manifest=None):
    data=load() if manifest is None else manifest
    if (data.get('schema_version')!=1 or data.get('origin')!=ORIGIN or data.get('qualified_original') is not False or
        data.get('program_sha256')!=emitter.PROGRAM_SHA256 or data.get('decoder_sha256')!=emitter.DECODER_SHA256 or
        data.get('provisional_call_continuations_imported') is not False or data.get('dynamic_whitelists_extended') is not False):
        raise ValueError('Static CFG provenance or scope is invalid')
    if data.get('seed_pcs')!=len(pcs) or data.get('seed_sha256')!=seed_digest(pcs,successors):
        raise ValueError('Static CFG measured seed differs; regenerate its direct closure')
    baseline=set(pcs);new=tuple(address(pc) for pc in data['new_pcs'])
    if new!=tuple(sorted(set(new))) or baseline.intersection(new):
        raise ValueError('Static CFG new PC list is not a disjoint sorted set')
    qualified=baseline|set(new);nodes=data['nodes']
    node_pcs={address(pc) for pc in nodes}
    if not set(new)<=node_pcs or not node_pcs<=qualified:
        raise ValueError('Static CFG word manifest does not cover its new PCs')
    merged=dict(successors)
    for pc,node in nodes.items():
        if (node.get('origin')!=ORIGIN or node.get('bits') not in (16,32,48,80) or
            not isinstance(node.get('word_sha256'),str) or not re.fullmatch('[0-9a-f]{64}',node['word_sha256'])):
            raise ValueError('Invalid static CFG instruction word manifest')
    for pc,targets in data['direct_successors'].items():
        source=address(pc)
        if pc not in nodes or nodes[pc]['flow_kind']=='observed_dynamic':
            raise ValueError('Static CFG cannot extend a dynamic jump/return whitelist')
        values=tuple(address(target) for target in targets)
        if values!=tuple(sorted(set(values))) or not set(values)<=qualified:
            raise ValueError('Static CFG direct targets are not a closed sorted PC set')
        merged[source]=values
    reached=set(baseline);pending=list(baseline)
    while pending:
        for target in merged.get(pending.pop(),()):
            if target not in reached:reached.add(target);pending.append(target)
    if not set(new)<=reached:
        raise ValueError('Static CFG contains PCs unreachable from the measured seed through its direct edges')
    return tuple(sorted(qualified)),merged

def direct_targets(pc,size,asm,vector):
    op,*tail=asm.split(None,1);args=tail[0].split(',') if tail else []
    nxt=pc+size
    if op in DYNAMIC:return None
    if op in ('CALLR','CALLA','JR','JA'):targets=(emitter.transfer_target(op,args[0]),)
    elif op in CONDITIONAL:targets=(emitter.transfer_target(op,args[0]),nxt)
    elif op in ('DSJ','DSJS','DSJEQ','DSJNE'):targets=(emitter.immediate(args[1]),nxt)
    elif op=='TRAP':
        if args!=['1h']:raise ValueError('Unqualified static CFG software trap')
        targets=(vector,)
    else:targets=(nxt,)
    return tuple(sorted(set(targets)))

def validate(rom,rows,base_pcs,base_successors,manifest=None):
    data=load() if manifest is None else manifest
    if len(rom)!=0x100000 or hashlib.sha256(rom).hexdigest()!=emitter.PROGRAM_SHA256:
        raise ValueError('Static CFG requires authenticated original program')
    pcs,successors=extend(base_pcs,base_successors,data)
    vector=int.from_bytes(rom[0xffff8:0xffffc],'little')
    for label,node in data['nodes'].items():
        pc=address(label)
        if pc not in rows:raise ValueError('Static CFG instruction missing from authenticated decoder output')
        size,flags,raw,asm=rows[pc]
        off=(pc-0xff800000)//8
        words=b''.join(word.to_bytes(2,'little') for word in raw)
        if size!=node['bits'] or rom[off:off+size//8]!=words or hashlib.sha256(words).hexdigest()!=node['word_sha256']:
            raise ValueError('Static CFG instruction word hash differs from original ROM')
        if flow_kind(asm)!=node['flow_kind']:raise ValueError('Static CFG flow kind differs from authenticated decoder')
        expected=direct_targets(pc,size,asm,vector)
        actual=data['direct_successors'].get(label)
        if expected is None:
            if actual is not None:raise ValueError('Static CFG modified a dynamic whitelist')
        elif tuple(address(target) for target in actual or ())!=expected:
            # A stopped unsupported form need not advertise a continuation that it cannot execute.
            if not node['frontier'] or actual:
                raise ValueError(f'Static CFG targets differ from encoded direct instruction operands at {pc:08x}: {actual} != {expected}')
        if node['frontier']!=frontier(pc,asm,successors):
            raise ValueError('Static CFG frontier differs from its decoded dynamic form and measured whitelist')
    return pcs,successors

def frontiers(manifest=None):
    data=load() if manifest is None else manifest
    return {address(pc) for pc,node in data['nodes'].items() if node['frontier']}

def reject_frontier(pc):
    return f'throw std::runtime_error("MK2 static CFG unqualified frontier {pc:08x}");'

def generate(rom,rows,base_pcs,base_successors,manifest=None):
    """Canonical manifest from the user's ROM: the closure (seed, new PCs, node set) is kept; widths, word digests,
    flow kinds, direct edges and frontiers are recomputed from the decoded instructions, then validate() runs."""
    data=load() if manifest is None else manifest
    nodes={};direct={}
    vector=int.from_bytes(rom[0xffff8:0xffffc],'little')
    pcs,successors=extend(base_pcs,base_successors,data)
    for label in sorted(data['nodes']):
        pc=address(label);size,flags,raw,asm=rows[pc]
        words=b''.join(word.to_bytes(2,'little') for word in raw)
        nodes[label]={'bits':size,'flow_kind':flow_kind(asm),'frontier':frontier(pc,asm,successors),'origin':ORIGIN,
                      'word_sha256':hashlib.sha256(words).hexdigest()}
        targets=direct_targets(pc,size,asm,vector)
        if targets is not None:direct[label]=[f'{target:08x}' for target in targets]
    out={key:value for key,value in data.items() if key not in ('nodes','direct_successors')}
    out.update(nodes=nodes,direct_successors=direct)
    validate(rom,rows,base_pcs,base_successors,out)
    return json.dumps(out,separators=(',',':'),sort_keys=True)+'\r\n'   # the versioned file keeps its CRLF (-text)

def main(argv=None):
    import argparse
    from tools.mk2 import generate_first_fight as fight,offline_decode
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check',action='store_true',help='compare instead of writing')
    args=parser.parse_args(argv)
    rom=emitter.load_program(emitter.ROOT/'roms/mk2');data=load()
    rows,_=offline_decode.decode(rom,{address(pc) for pc in data['nodes']})
    text=generate(rom,rows,fight.BASE_PCS,fight.BASE_SUCCESSORS,data)
    if args.check:
        if PATH.read_bytes()!=text.encode('ascii'):raise SystemExit('static_cfg_path.json differs from the ROM')
    else:PATH.write_bytes(text.encode('ascii'))
    print(hashlib.sha256(text.encode('ascii')).hexdigest())

if __name__=='__main__':main()
