"""Genuine valid-CMOS dynamic edges and conservative ROM closure, without new runtime decoding."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_first_fight as fight,generate_valid_host_edges as host,generate_video_irq as shared

class ValidHostEdgeTests(unittest.TestCase):
    def test_exact_generated_dispatch_and_counterfactual_rejection(self):
        rom=shared.load_program(shared.ROOT/'roms/mk2')
        import json
        data=json.loads(host.PATH.read_text(encoding='utf8'))
        base=fight.generate(rom)
        self.assertEqual(base,(__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir()/'mk2_first_fight.inc').read_text(encoding='utf8'))
        host.validate(rom,fight.PCS,fight.SUCCESSORS)
        with self.assertRaisesRegex(ValueError,'base dispatch case text changed'):
            host.apply(rom,base,fight.PCS,fight.SUCCESSORS)
        self.assertEqual((len(set(fight.PCS)|{int(pc,16)for pc in data['nodes']}),len(fight.STATIC_CFG_FRONTIERS)+sum(bool(v['frontier_sha256'])for v in data['nodes'].values())-len(data.get('replaced_base_frontiers',[]))),(10356,60))
        cases=[]
        bad=deepcopy(data);bad['base_seed_sha256']='0'*64;cases.append(('base_seed',rom,base,bad))
        cases.append(('base_case_drift',rom,base.replace('o.Finish(','o.Finish( ',1),data))
        image=bytearray(rom);image[(0xff8ea450-0xff800000)//8]^=1;cases.append(('changed_ROM_word',bytes(image),base,data))
        bad=deepcopy(data);bad['measured_edges'][0]['new_targets']=['ff9b6840'];cases.append(('unknown_edge',rom,base,bad))
        bad=deepcopy(data);bad['measured_edges'][1]['contexts'][0]['stack_step']-=32;cases.append(('return_stack',rom,base,bad))
        bad=deepcopy(data);bad['measured_edges'][1]['contexts'][0]['cost']+=1;cases.append(('return_cycles',rom,base,bad))
        bad=deepcopy(data);bad['measured_edges'][1]['old_targets'].pop();cases.append(('old_target_removed',rom,base,bad))
        bad=deepcopy(data);pc=next(k for k,v in bad['nodes'].items()if v['direct_successors']);bad['nodes'][pc]['direct_successors']=['ff9b6840'];cases.append(('invented_direct_target',rom,base,bad))
        bad=deepcopy(data);bad['inferred_call_continuations']=True;cases.append(('inferred_continuation',rom,base,bad))
        def first(d,kind):return next(e for e in d['measured_edges']if e['kind']==kind)
        bad=deepcopy(data);first(bad,'CALL')['contexts'][0]['target']='ff9b6840';cases.append(('call_unobserved_target',rom,base,bad))
        bad=deepcopy(data);first(bad,'CALL')['contexts'][0]['cost']+=1;cases.append(('call_cost',rom,base,bad))
        bad=deepcopy(data);first(bad,'CALL')['contexts'][0]['stack_step']+=32;cases.append(('call_stack',rom,base,bad))
        bad=deepcopy(data);first(bad,'EXGPC')['contexts'][0]['after_cpu34_sha256']='0';cases.append(('exchange_digest',rom,base,bad))
        bad=deepcopy(data);first(bad,'EXGPC')['contexts'][0]['cost']+=1;cases.append(('exchange_cost',rom,base,bad))
        bad=deepcopy(data);first(bad,'EXGPC')['register']=6;cases.append(('exchange_register',rom,base,bad))
        bad=deepcopy(data);bad['replaced_base_frontiers']=[];cases.append(('missing_frontier_provenance',rom,base,bad))
        def neutral(d):return next(e for e in d['measured_edges']if e['source']=='ff840a40')
        bad=deepcopy(data);neutral(bad)['new_targets']=['ff800000'];cases.append(('neutral_unknown',rom,base,bad))
        bad=deepcopy(data);neutral(bad)['contexts'][0]['stack_step']=32;cases.append(('neutral_stack',rom,base,bad))
        bad=deepcopy(data);neutral(bad)['contexts'][0]['before_cpu34_sha256']='0'*63;cases.append(('neutral_digest',rom,base,bad))
        bad=deepcopy(data);neutral(bad)['contexts'][0]['cost']+=1;cases.append(('neutral_cost',rom,base,bad))
        bad=deepcopy(data);neutral(bad)['old_targets'].pop();cases.append(('neutral_old_target',rom,base,bad))
        bad=deepcopy(data);neutral(bad)['register']=0;cases.append(('neutral_register',rom,base,bad))
        image=bytearray(rom);image[(0xff840a40-0xff800000)//8]^=1;cases.append(('neutral_opcode',bytes(image),base,data))
        def neutral119(d):return next(e for e in d['measured_edges']if e['source']=='ff80de00')
        bad=deepcopy(data);e=neutral119(bad);e['new_targets'][e['new_targets'].index('ff9b0e50')]='ff800000';cases.append(('neutral119_unknown',rom,base,bad))
        bad=deepcopy(data);neutral119(bad)['contexts'][-1]['target']='ff800000';cases.append(('neutral119_target',rom,base,bad))
        bad=deepcopy(data);neutral119(bad)['contexts'][-1]['extra']=0;cases.append(('neutral119_extra_field',rom,base,bad))
        bad=deepcopy(data);neutral119(bad)['contexts'][-1]['cost']+=1;cases.append(('neutral119_cost',rom,base,bad))
        bad=deepcopy(data);neutral119(bad)['old_targets'].pop();cases.append(('neutral119_old_target',rom,base,bad))
        bad=deepcopy(data);neutral119(bad)['register']=0;cases.append(('neutral119_register',rom,base,bad))
        image=bytearray(rom);image[(0xff80de00-0xff800000)//8]^=1;cases.append(('neutral119_opcode',bytes(image),base,data))
        def bad(label,change):
         d=deepcopy(data);change(d);cases.append((label,rom,base,d))
        def basejump(d):return next(e for e in d['measured_edges']if e['source']=='ff836e10')
        def origin(d):return d['base_frontier_jumps']['ff836e10']
        bad('base_jump_missing_declaration',lambda d:d.update(base_frontier_jumps={}))
        bad('base_jump_wrong_declaration_type',lambda d:d.update(base_frontier_jumps=[]))
        bad('base_jump_wrong_origin_register',lambda d:origin(d).__setitem__('register',7))
        bad('base_jump_wrong_origin_opcode',lambda d:origin(d).__setitem__('opcode_sha256','0'*64))
        bad('base_jump_wrong_origin_proof',lambda d:origin(d).__setitem__('proof_sha256','0'*64))
        bad('base_jump_wrong_origin_context_hash',lambda d:origin(d).__setitem__('contexts_sha256','0'*64))
        bad('base_jump_extra_origin',lambda d:d['base_frontier_jumps'].__setitem__('ff888df0',dict(origin(d))))
        bad('base_jump_missing_frontier',lambda d:d['replaced_base_frontiers'].remove('ff836e10'))
        bad('base_jump_unobserved_target',lambda d:basejump(d)['new_targets'].__setitem__(0,'ffa147b0'))
        bad('base_jump_cost',lambda d:basejump(d)['contexts'][0].__setitem__('cost',3))
        def coherent_flags(d):
         c=basejump(d)['contexts'][0];c['before_cpu34_sha256']=host.digest([1]*34);c['after_cpu34_sha256']=host.digest([2]*34)
        bad('base_jump_coherent_unmeasured_flags',coherent_flags)
        def coherent_cycle(d):
         c=basejump(d)['contexts'][0];c['before_cpu34_sha256'],c['after_cpu34_sha256']=c['after_cpu34_sha256'],c['before_cpu34_sha256']
        bad('base_jump_coherent_unmeasured_cycle',coherent_cycle)
        def form(d,kind):
         e=basejump(d);e['kind']=kind;c=e['contexts'][0]
         c['cost']=host.COSTS[kind]
         if kind=='CALL':c['stack_step']=-32
         else:e['register']=7
        bad('base_jump_unadmitted_CALL',lambda d:form(d,'CALL'))
        bad('base_jump_unadmitted_EXGPC',lambda d:form(d,'EXGPC'))
        bad('base_jump_unadmitted_JUMP_A7',lambda d:form(d,'JUMP'))
        image=bytearray(rom);image[(0xff836e10-0xff800000)//8]^=1;cases.append(('base_jump_changed_original_word',bytes(image),base,data))
        for label,image,source,manifest in cases:
            with self.subTest(case=label),self.assertRaises(ValueError):
                if label=='base_case_drift':host.apply(image,source,fight.PCS,fight.SUCCESSORS,manifest)
                else:host.validate(image,fight.PCS,fight.SUCCESSORS,manifest)

    def test_raw_capture_relations_reject_every_changed_register_stack_or_cost(self):
        # Synthetic rows (sentinels, no observed value) exercise the checks a local oracle capture passes through.
        pc,target=0xff800100,0xff800200
        def raw(kind,register=0):
            before=[pc,0x30,1000]+[0x01000000+16*n for n in range(31)];after=list(before);after[0]=target
            edge={'source':f'{pc:08x}','kind':kind,'register':register};context={'before':before,'after':after}
            if kind=='JUMP':before[3+register]=target;after[3+register]=target;after[2]+=2
            if kind=='CALL':before[3+register]=target;after[3+register]=target;after[2]+=3;after[18]-=32;context['saved_return_word']=pc+16
            if kind=='EXGPC':before[10]=target;after[10]=pc+16;after[2]+=2
            if kind=='RETS':after[2]+=7;after[18]+=32;context['stack_word']=target
            return edge,context
        data={'schema_version':3}
        for kind,register in (('JUMP',0),('JUMP',7),('CALL',0),('CALL',11),('EXGPC',7),('RETS',0)):
            edge,context=raw(kind,register)
            facts=host.context_facts(edge,context,pc,(target,),data)
            host.check_context(edge,facts,(target,),data)
            self.assertEqual((facts['target'],facts['cost'],facts.get('stack_step')),(f'{target:08x}',host.COSTS[kind],host.STACK.get(kind)))
            changes=[('cycles',lambda c:c['after'].__setitem__(2,c['after'][2]+1)),
                     ('flags',lambda c:c['after'].__setitem__(1,c['after'][1]^1)),
                     ('other_register',lambda c:c['after'].__setitem__(30,c['after'][30]^16)),
                     ('source',lambda c:c['before'].__setitem__(0,pc+16)),
                     ('target',lambda c:c['after'].__setitem__(0,target+16))]
            if kind in('CALL','RETS'):changes.append(('stack',lambda c:c['after'].__setitem__(18,c['after'][18]+16)))
            if kind=='CALL':changes.append(('saved_return',lambda c:c.__setitem__('saved_return_word',pc+32)))
            if kind=='RETS':changes.append(('stack_word',lambda c:c.__setitem__('stack_word',target+16)))
            if kind=='EXGPC':changes.append(('swap',lambda c:c['after'].__setitem__(10,pc+32)))
            if kind in('JUMP','CALL'):changes.append(('register_value',lambda c,r=register:c['before'].__setitem__(3+r,target+16)))
            for label,change in changes:
                edge,context=raw(kind,register);change(context)
                with self.subTest(kind=kind,register=register,change=label),self.assertRaises(ValueError):
                    host.context_facts(edge,context,pc,(target,),data)
        edge,context=raw('EXGPC',6)
        with self.assertRaises(ValueError):host.context_facts(edge,context,pc,(target,),data)

if __name__=='__main__':unittest.main()
