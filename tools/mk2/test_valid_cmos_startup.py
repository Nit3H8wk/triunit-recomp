"""Finite persistent startup keeps exact CPU bounds and authenticated static generation."""
from pathlib import Path
import copy
import json
import os
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native,run,generate_valid_cmos_startup as generator
from tools.quality import run as quality


class ValidCmosStartupTests(unittest.TestCase):
    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated L3.1 ROMs')
    def test_two_native_startups_preserve_exact_cmos_and_guest_audits(self):
        from tools.mk2 import profile
        sources=['native/tests/mk2_valid_cmos_startup_tests.cpp',*run.EXECUTOR_SOURCES]
        with quality.scratch_tree()as(scratch,cleanup):
            exe=scratch/'valid-startup.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT/'native/include'),*[quality.ROOT/p for p in sources],
                '-lbcrypt','-o',exe],scratch,env=env,timeout=600)
            self.assertTrue(build['passed'],build.get('stdout',''))
            fixture=json.loads((quality.ROOT/'tools/mk2/startup_credit_fixture.json').read_text())
            self.assertEqual(quality.sha(profile.FACTORY_SEED),fixture['factory_sha256'])
            image=bytearray(profile.FACTORY_SEED.read_bytes())
            for offset,value in fixture['changed_words']:image[offset:offset+2]=value.to_bytes(2,'little')
            import hashlib
            self.assertEqual(hashlib.sha256(image).hexdigest(),fixture['cmos_sha256'])
            used=scratch/'used-cmos.bin';used.write_bytes(image)
            regression=quality.command([exe,quality.ROOT/'roms/mk2',profile.FACTORY_SEED,used],scratch,env=env,timeout=90)
            self.assertTrue(regression['passed'],regression.get('stdout',''))
            result=quality.command([exe,quality.ROOT/'roms/mk2',profile.FACTORY_SEED],scratch,env=env,timeout=180)
            self.assertTrue(result['passed'],result.get('stdout',''))
        self.assertFalse(cleanup['exists_after'])

    def test_frontier_is_complete_task_setup_not_first_draw_or_gameplay(self):
        from unittest import mock
        from tools.mk2 import oracle_digest
        manifest=json.loads(generator.MANIFEST.read_text())
        expected=native.frontier('cmos-startup')
        self.assertEqual(expected,{'pc':manifest['dispatcher_end_CPU34_pc'],'cycle':manifest['dispatcher_end_CPU34_cycle'],
                                   'words':34,'sha256':manifest['dispatcher_end_CPU34_sha256']})
        # Raw rows are not versioned: a stand-in row at the same PC/cycle, with the frontier re-pointed to its digest.
        wanted=[expected['pc'],0x10,expected['cycle']]+list(range(31))
        patch=mock.patch.object(native,'frontier',return_value=dict(expected,sha256=oracle_digest.cpu34_digest(wanted)))
        patch.start();self.addCleanup(patch.stop)
        observed={'scope':'mk2-native-cmos-startup-check','gameplay_complete':False,'execution_continues':False,
            'termination':'finite_valid_cmos_startup_complete','through':'cmos-startup','frontier_pc':wanted[0],
            'cpu34':wanted,'frames':60,'width':400,'height':254,'frame_sha256':['0'*64]*60}
        native.validate_boundary(observed,'cmos-startup')
        for field in ('cpu34','gameplay_complete','frames'):
            invalid=copy.deepcopy(observed)
            if field=='cpu34':invalid[field][4]^=1
            elif field=='gameplay_complete':invalid[field]=True
            else:invalid[field]-=1
            with self.subTest(field=field),self.assertRaises(ValueError):native.validate_boundary(invalid,'cmos-startup')

    def test_startup_requires_existing_profile_without_initializing_or_building(self):
        with quality.scratch_tree()as(scratch,cleanup):
            path=scratch/'missing'
            result=native.run(quality.ROOT/'missing-roms',through='cmos-startup',profile_directory=path)
            self.assertFalse(result['passed']);self.assertIn('persistence',result)
            self.assertNotIn('build',result);self.assertFalse(path.exists())
        self.assertFalse(cleanup['exists_after'])

    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated L3.1 ROMs')
    def test_generator_reproduces_source_and_rejects_changed_words_or_unseen_successors(self):
        rom=generator.shared.load_program(quality.ROOT/'roms/mk2')
        self.assertEqual(generator.generate(rom),(__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir() and generator.OUTPUT).read_text())
        manifest=json.loads(generator.MANIFEST.read_text());pc=manifest['pcs'][0]
        invalid=copy.deepcopy(manifest);invalid['words_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'opcode differs'):generator.generate(rom,invalid)
        invalid=copy.deepcopy(manifest);invalid['successors'][pc]=['ff800010']
        with self.assertRaisesRegex(ValueError,'successor outside'):generator.generate(rom,invalid)


if __name__=='__main__':unittest.main()
