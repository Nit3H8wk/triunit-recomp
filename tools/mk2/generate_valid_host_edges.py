"""Offline only: exact original valid-host edges plus encoded ROM successors, preserving all other dispatch bytes."""
from pathlib import Path
import hashlib,json,re
from tools.mk2 import generate_static_cfg as cfg,generate_video_irq as emitter
from tools.mk2.offline_decode import decode

PATH=Path(__file__).with_name('valid_host_edges_path.json')
ORIGIN='original-valid-CMOS-host-edges-and-ROM-direct-CFG'

COSTS={'JUMP':2,'CALL':3,'EXGPC':2,'RETS':7}
STACK={'CALL':-32,'RETS':32}

def digest(values):
    """CPU34 serialization of tools/mk2/oracle_digest.py (8-byte little-endian words)."""
    return hashlib.sha256(b''.join(int(v).to_bytes(8,'little')for v in values)).hexdigest()

def contexts_identity(contexts):
    return hashlib.sha256(json.dumps(contexts,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()

def opcode_identity(words):
    return hashlib.sha256(b''.join(v.to_bytes(2,'little')for v in words)).hexdigest()

def check_register(edge,pc,data):
    register=edge.get('register',0)
    if edge['kind']in('JUMP','CALL','EXGPC')and register not in{'JUMP':(0,7),'CALL':(0,11),'EXGPC':(7,)}[edge['kind']]:
        if not(edge['kind']=='CALL'and register==5 and pc==0xffa0d990 and data.get('schema_version')==3 and edge.get('register_bank','A')=='A'):
            raise ValueError('Unsupported original control register or unqualified CALL A5 source')
    if edge['kind']not in COSTS:raise ValueError('Only original fixed register JUMP/CALL/EXGPC and RETS edge records are admitted')

def check_raw_context(edge,context,pc,extra,data):
    """Relations between the raw before/after CPU34 rows of a local oracle capture (never versioned)."""
    before,after=context['before'],context['after']
    if(len(before)!=34 or len(after)!=34 or any(type(v)is not int or v<0 for v in before+after)or
       before[0]!=pc or after[0]not in extra):raise ValueError('Invalid original valid-host CPU34 edge context')
    register=edge.get('register',0);check_register(edge,pc,data)
    if edge['kind']=='JUMP':
        if(before[3+register]!=after[0]or after[2]!=before[2]+2 or after[1]!=before[1]or after[3:]!=before[3:]):
            raise ValueError('Original JUMP context or cost changed')
    elif edge['kind']=='CALL':
        if(before[3+register]!=after[0]or context.get('saved_return_word')!=pc+16 or after[2]!=before[2]+3 or
           after[18]!=before[18]-32 or any(a!=b for n,(a,b)in enumerate(zip(before,after))if n not in(0,2,18))):
            raise ValueError('Original CALL stack, saved return, CPU context or cost changed')
    elif edge['kind']=='EXGPC':
        if(register!=7 or before[10]!=after[0]or after[10]!=pc+16 or after[2]!=before[2]+2 or
           any(a!=b for n,(a,b)in enumerate(zip(before,after))if n not in(0,2,10))):
            raise ValueError('Original EXGPC exchange, CPU context or cost changed')
    elif edge['kind']=='RETS':
        if(context.get('stack_word')!=after[0]or after[2]!=before[2]+7 or after[18]!=before[18]+32 or
           any(left!=right for n,(left,right)in enumerate(zip(before,after))if n not in(0,2,18))):
            raise ValueError('Original RETS stack, CPU context or cost changed')

def context_facts(edge,context,pc,extra,data):
    """Versioned form of a checked raw context: target, cost, stack step and the CPU34 digests."""
    check_raw_context(edge,context,pc,extra,data)
    before,after=context['before'],context['after']
    facts={'target':f'{after[0]:08x}','cost':after[2]-before[2]}
    if edge['kind']in STACK:facts['stack_step']=after[18]-before[18]
    facts.update(before_cpu34_sha256=digest(before),after_cpu34_sha256=digest(after))
    return facts

def check_context(edge,context,extra,data):
    """Digest form: the raw relations were checked by context_facts() when the capture was converted."""
    pc=cfg.address(edge['source']);check_register(edge,pc,data)
    if(set(context)!={'target','cost','before_cpu34_sha256','after_cpu34_sha256',*(('stack_step',)if edge['kind']in STACK else())}or
       cfg.address(context['target'])not in extra or context['cost']!=COSTS[edge['kind']]or
       context.get('stack_step',None)!=STACK.get(edge['kind'])or
       not all(re.fullmatch('[0-9a-f]{64}',context[k])for k in('before_cpu34_sha256','after_cpu34_sha256'))):
        raise ValueError('Original '+edge['kind']+' context, stack or cost changed')

def validate(rom,pcs,successors,manifest=None):
    data=json.loads(PATH.read_text(encoding='utf8'))if manifest is None else manifest
    if(data.get('schema_version')not in(1,2,3) or data.get('origin')!=ORIGIN or
       data.get('program_sha256')!=emitter.PROGRAM_SHA256 or data.get('decoder_sha256')!=emitter.DECODER_SHA256 or
       data.get('new_nodes_qualified_as_measured_paths')is not False or data.get('inferred_call_continuations')is not False or
       data.get('gameplay_complete')is not False or data.get('strict_full_DSP_qualification')is not False):
        raise ValueError('Invalid valid-host edge/CFG provenance or qualification scope')
    if data.get('base_PCs')!=len(pcs)or data.get('base_seed_sha256')!=cfg.seed_digest(pcs,successors):
        raise ValueError('Valid-host edge base dispatcher changed')
    nodes=data['nodes'];new=tuple(cfg.address(v)for v in nodes)
    if new!=tuple(sorted(set(new)))or set(new)&set(pcs):raise ValueError('New valid-host ROM PCs must be a disjoint sorted set')
    qualified=set(pcs)|set(new);merged=dict(successors);edges=data['measured_edges'];sources=set();targets=set()
    for edge in edges:
        pc=cfg.address(edge['source'])
        if pc in sources or pc not in qualified:raise ValueError('Invalid measured valid-host edge source')
        sources.add(pc)
        old=tuple(cfg.address(v)for v in edge['old_targets']);extra=tuple(cfg.address(v)for v in edge['new_targets'])
        if old!=tuple(successors.get(pc,()))or extra!=tuple(sorted(set(extra)))or set(extra)&set(old)or not extra:
            raise ValueError('Measured valid-host edge changed an old target or duplicated an edge')
        if not set(extra)<=qualified:raise ValueError('Measured valid-host edge points outside fixed translation')
        if not re.fullmatch('[0-9a-f]{64}',edge.get('proof_sha256','')):raise ValueError('Missing original edge receipt identity')
        observed=set()
        for context in edge['contexts']:
            if 'before' in context:check_raw_context(edge,context,pc,extra,data)
            else:check_context(edge,context,extra,data)
            observed.add(cfg.address(context['target'])if 'target' in context else context['after'][0])
        if observed!=set(extra):raise ValueError('Every added dynamic target needs its own original before/after context')
        merged[pc]=tuple(sorted(set(old)|set(extra)));targets.update(extra)
    extended=data.get('extended_register_calls',{})
    expected_extended={e['source']for e in edges if e['kind']=='CALL'and e.get('register')==5}
    if type(extended)is not dict or tuple(extended)!=tuple(sorted(expected_extended)):
        raise ValueError('Every narrowly admitted CALL A5 needs its sorted explicit provenance declaration')
    base_frontiers=cfg.frontiers(cfg.load())
    replaced=tuple(cfg.address(v)for v in data.get('replaced_base_frontiers',[]))
    if replaced!=tuple(sorted(sources&base_frontiers))or any(not(edge['kind']=='RETS'or(edge['kind']=='JUMP'and edge.get('register')==0))for edge in edges if cfg.address(edge['source'])in base_frontiers):
        raise ValueError('Base frontier replacement requires its original RETS or explicitly declared JUMP A0 context')
    jumps=data.get('base_frontier_jumps',{})
    expected_jumps={edge['source']for edge in edges if cfg.address(edge['source'])in base_frontiers and edge['kind']=='JUMP'}
    if type(jumps)is not dict or tuple(jumps)!=tuple(sorted(expected_jumps)):
        raise ValueError('Every replaced base JUMP A0 STOP needs its explicit sorted provenance declaration')
    rows,_=decode(rom,set(new)|sources)
    vector=int.from_bytes(rom[0xffff8:0xffffc],'little')
    for edge in edges:
        row=rows[cfg.address(edge['source'])]
        if edge['source']in extended and extended[edge['source']]!={'bank':'A','register':5,'opcode_sha256':opcode_identity(row[2]),'proof_sha256':edge['proof_sha256'],'contexts_sha256':contexts_identity(edge['contexts']),'ISA_source_sha256':'5596e7ca123d3d91e7dd7dc83538a1b05a83489b6abe80ac5e013748bd7d721f'}:
            raise ValueError('CALL A5 declaration differs from authenticated opcode/original contexts/source identity')
        if edge['source']in jumps and jumps[edge['source']]!={'register':0,'opcode_sha256':opcode_identity(row[2]),'proof_sha256':edge['proof_sha256'],'contexts_sha256':contexts_identity(edge['contexts'])}:
            raise ValueError('Base JUMP A0 origin differs from authenticated opcode or original proof identity')
        if row[3].split()!=(['RETS']if edge['kind']=='RETS'else[edge['kind'],'A'+str(edge.get('register',0))]):
            raise ValueError('Measured valid-host edge opcode differs from authenticated ROM')
    for label,node in nodes.items():
        pc=cfg.address(label);size,flags,raw,asm=rows[pc];words=b''.join(v.to_bytes(2,'little')for v in raw)
        if(size!=node['bits']or hashlib.sha256(words).hexdigest()!=node['word_sha256']):
            raise ValueError('Valid-host direct CFG instruction differs from original ROM words')
        if node['origin'].get('origin')not in('original-observed-RETS-target','original-observed-JUMP-target','original-observed-CALL-target','original-observed-EXGPC-target','authenticated-ROM-direct-CFG'):
            raise ValueError('Unqualified valid-host ROM node origin')
        expected=cfg.direct_targets(pc,size,asm,vector)
        actual=tuple(cfg.address(v)for v in node['direct_successors'])
        if actual!=tuple(sorted(set(actual)))or not set(actual)<=qualified:
            raise ValueError('Valid-host direct successor is outside fixed translation')
        if expected is None:
            if actual:raise ValueError('Direct ROM closure cannot invent a dynamic successor')
        elif actual!=expected and not(node['frontier_sha256']and not actual):
            raise ValueError('Valid-host CFG edge differs from encoded ROM target')
        if expected is not None:merged[pc]=actual
    reached=set(pcs)|targets;pending=list(targets)
    while pending:
        for target in merged.get(pending.pop(),()):
            if target not in reached:reached.add(target);pending.append(target)
    if not set(new)<=reached:raise ValueError('Valid-host ROM closure contains an unreachable new PC')
    return data,nodes,rows,qualified,merged

def apply(rom,source,pcs,successors,manifest=None):
    data,nodes,rows,qualified,merged=validate(rom,pcs,successors,manifest)
    if hashlib.sha256(source.encode('utf8')).hexdigest()!=data.get('base_dispatch_text_sha256'):
        raise ValueError('Valid-host base dispatch case text changed')
    edges=data['measured_edges'];base_frontiers=cfg.frontiers(cfg.load())
    output=source;overrides=[]
    for edge in edges:
        pc=cfg.address(edge['source']);size,flags,raw,asm=rows[pc]
        if pc not in pcs:continue
        old=(cfg.reject_frontier(pc)if pc in base_frontiers else
             emitter.emit_instruction(pc,size,asm,raw,set(pcs),successors,end=0xff80dd30))
        updated=emitter.emit_instruction(pc,size,asm,raw,qualified,merged,end=0xff80dd30)
        count=output.count('    '+old+'\n')
        if count==1:output=output.replace('    '+old+'\n','    '+updated+'\n',1)
        elif count==0:
            from tools.mk2 import generate_selection as pair
            if pc not in pair.PCS or successors.get(pc)!=pair.SUCCESSORS.get(pc):
                raise ValueError('Valid-host override does not match unchanged selection fallback')
            overrides.append(f'case 0x{pc:08x}u: {{ // {asm}\n    {updated}\n    break;\n}}\n')
        else:raise ValueError('Original valid-host dynamic case is not unique in base dispatch')
    output+=''.join(overrides)
    for label,node in nodes.items():
        pc=cfg.address(label);size,flags,raw,asm=rows[pc]
        if node['frontier_sha256']:
            try:emitter.emit_instruction(pc,size,asm,raw,qualified,merged,end=0xff80dd30)
            except ValueError as error:
                if hashlib.sha256(str(error).encode('utf8')).hexdigest()!=node['frontier_sha256']:raise ValueError('Valid-host ROM frontier changed')from error
            else:raise ValueError('Valid-host ROM frontier became executable; regenerate its manifest')
            code=cfg.reject_frontier(pc)
        else:code=emitter.emit_instruction(pc,size,asm,raw,qualified,merged,end=0xff80dd30)
        output+=f'case 0x{pc:08x}u: {{ // {asm}\n    {code}\n    break;\n}}\n'
    return output
