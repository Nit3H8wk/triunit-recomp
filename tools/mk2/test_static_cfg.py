"""Static direct CFG additions preserve measured dynamic whitelists and reject altered words."""
import copy
import hashlib
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

class StaticCfgTests(unittest.TestCase):
    def test_jan_cfg_keeps_taken_and_fallthrough(self):
        from tools.mk2.generate_static_cfg import direct_targets
        self.assertEqual(direct_targets(0xff9b3d60,48,'JAN FF8BDDE0h',0xff8045d0),
                         (0xff8bdde0,0xff9b3d90))

    def setUp(self):
        try:self.cfg=importlib.import_module('tools.mk2.generate_static_cfg')
        except ImportError:self.fail('Offline static CFG extension is missing')
        self.pcs=(0xff800000,0xff800010)
        self.edges={self.pcs[0]:(self.pcs[1],),self.pcs[1]:(self.pcs[0],)}
        self.manifest={'schema_version':1,'origin':'authenticated-ROM-direct-CFG','qualified_original':False,
            'program_sha256':self.cfg.emitter.PROGRAM_SHA256,'decoder_sha256':self.cfg.emitter.DECODER_SHA256,
            'seed_sha256':self.cfg.seed_digest(self.pcs,self.edges),'seed_pcs':2,
            'new_pcs':['ff800100'],'provisional_call_continuations_imported':False,
            'dynamic_whitelists_extended':False,
            'nodes':{'ff800000':{'bits':16,'word_sha256':'0'*64,'origin':'authenticated-ROM-direct-CFG',
                     'flow_kind':'direct_conditional','frontier':None},
                     'ff800100':{'bits':16,'word_sha256':'0'*64,'origin':'authenticated-ROM-direct-CFG',
                     'flow_kind':'observed_dynamic',
                     'frontier':{'category':'missing_dynamic_return_whitelist','error':'Unqualified return'}}},
            'direct_successors':{'ff800000':['ff800010','ff800100']}}

    def test_union_keeps_dynamic_whitelists_and_does_not_mutate_the_seed(self):
        before=copy.deepcopy(self.edges)
        pcs,edges=self.cfg.extend(self.pcs,self.edges,self.manifest)
        self.assertEqual(pcs,(0xff800000,0xff800010,0xff800100))
        self.assertEqual(edges[0xff800000],(0xff800010,0xff800100))
        self.assertEqual(edges[0xff800010],self.edges[0xff800010])
        self.assertNotIn(0xff800100,edges)
        self.assertEqual(self.edges,before)

    def test_provisional_continuations_changed_seed_and_dynamic_targets_reject(self):
        for change in ('provisional','seed','dynamic','alignment','unreachable'):
            bad=copy.deepcopy(self.manifest)
            if change=='provisional':bad['provisional_call_continuations_imported']=True
            if change=='seed':bad['seed_sha256']='0'*64
            if change=='dynamic':bad['direct_successors']['ff800100']=['ff800000']
            if change=='alignment':bad['new_pcs']=['ff800101']
            if change=='unreachable':bad['direct_successors']={}
            with self.subTest(change=change),self.assertRaises(ValueError):self.cfg.extend(self.pcs,self.edges,bad)

    def test_authentication_and_instruction_word_hash_reject_before_emission(self):
        rom=bytes(0x100000)
        with self.assertRaisesRegex(ValueError,'program'):
            self.cfg.validate(rom,{},self.pcs,self.edges,self.manifest)
        bad=copy.deepcopy(self.manifest)
        digest=hashlib.sha256(rom).hexdigest();bad['program_sha256']=digest
        rows={0xff800000:(16,0,(0,),'JRNE FF800100h'),0xff800100:(16,0,(0,),'RETS')}
        with patch.object(self.cfg.emitter,'PROGRAM_SHA256',digest):
            with self.assertRaisesRegex(ValueError,'word hash'):
                self.cfg.validate(rom,rows,self.pcs,self.edges,bad)

    def test_rom_word_valid_instruction_still_rejects_an_invented_direct_target(self):
        rom=bytes(0x100000);digest=hashlib.sha256(rom).hexdigest()
        data=copy.deepcopy(self.manifest);data['program_sha256']=digest
        for node in data['nodes'].values():node['word_sha256']=hashlib.sha256(bytes(2)).hexdigest()
        rows={0xff800000:(16,0,(0,),'JRNE FF800100h'),0xff800100:(16,0,(0,),'RETS')}
        with patch.object(self.cfg.emitter,'PROGRAM_SHA256',digest):
            self.cfg.validate(rom,rows,self.pcs,self.edges,data)
            data['direct_successors']['ff800000']=['ff800000','ff800010','ff800100']
            with self.assertRaisesRegex(ValueError,'encoded direct'):
                self.cfg.validate(rom,rows,self.pcs,self.edges,data)

    def test_direct_targets_are_encoded_operands_not_provisional_call_returns(self):
        vector=0xff8045d0
        self.assertEqual(self.cfg.direct_targets(0xff800000,48,'CALLA FF800100h',vector),(0xff800100,))
        self.assertEqual(self.cfg.direct_targets(0xff800000,16,'JRNE FF800100h',vector),(0xff800010,0xff800100))
        self.assertEqual(self.cfg.direct_targets(0xff800000,16,'TRAP 1h',vector),(vector,))
        self.assertIsNone(self.cfg.direct_targets(0xff800000,16,'JUMP A0',vector))

    @unittest.skipUnless((Path(__file__).resolve().parents[2]/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_versioned_manifest_is_the_generator_output_for_the_user_rom(self):
        # No instruction text is versioned: it is decoded here from the user's ROM and checked against word_sha256.
        from tools.mk2 import generate_first_fight as fight,offline_decode
        data=self.cfg.load()
        self.assertNotIn('"asm"',self.cfg.PATH.read_text(encoding='utf8'))
        rom=self.cfg.emitter.load_program(self.cfg.emitter.ROOT/'roms/mk2')
        rows,_=offline_decode.decode(rom,{self.cfg.address(pc) for pc in data['nodes']})
        text=self.cfg.generate(rom,rows,fight.BASE_PCS,fight.BASE_SUCCESSORS,data)
        self.assertEqual(text.encode('ascii'),self.cfg.PATH.read_bytes())
        label=sorted(data['nodes'])[0]
        dynamic=next(pc for pc,node in sorted(data['nodes'].items()) if node['frontier'])
        for pc,field,value,message in ((label,'word_sha256','0'*64,'word hash'),(label,'flow_kind','fallthrough','flow kind'),
                                       (label,'bits',48,'word hash'),(label,'frontier',{'category':'x','error':'y'},'frontier'),
                                       (dynamic,'frontier',None,'frontier')):
            bad=copy.deepcopy(data);bad['nodes'][pc][field]=value
            with self.subTest(field=field,pc=pc),self.assertRaisesRegex(ValueError,message):
                self.cfg.validate(rom,rows,fight.BASE_PCS,fight.BASE_SUCCESSORS,bad)
        changed=dict(rows);pc=self.cfg.address(label);size,flags,raw,asm=changed[pc]
        changed[pc]=(size,flags,(raw[0]^1,*raw[1:]),asm)
        with self.assertRaisesRegex(ValueError,'word hash'):
            self.cfg.validate(rom,changed,fight.BASE_PCS,fight.BASE_SUCCESSORS,data)

if __name__=='__main__':unittest.main()
