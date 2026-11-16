"""Finite native CMOS sessions must commit only complete supported outcomes."""
import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native,profile
from tools.quality import run as quality

from tools.mk2.oracle_digest import words_digest

# Synthetic CPU34 at the valid-CMOS boot frontier (PC and cycle are the Original's; ST and registers are sentinels).
# The session tests below run against this row's digest; the real row is checked against native.frontier() (the
# product's pinned SHA-256) by the executor test at the end, so no observed register value is versioned.
CPU34=[0xff811340,0x5e000015,6607529]+[0x5e000000|n<<4 for n in range(3,34)]
FRONTIER=native.frontier


def synthetic_frontier(through,*args,**kwargs):
    if through!='cmos-boot':return FRONTIER(through,*args,**kwargs)
    return {'pc':CPU34[0],'cycle':CPU34[2],'words':34,'sha256':words_digest(CPU34)}


class ProfileSessionTests(unittest.TestCase):
    def observed(self,data):
        return {'scope':'mk2-native-cmos-boot-check','gameplay_complete':False,'execution_continues':False,
                'through':'cmos-boot','termination':'finite_valid_cmos_boot_complete',
                'frontier_pc':CPU34[0],'cpu34':CPU34,'frames':CPU34[2]*16//1827925,
                'width':400,'height':254,'frame_sha256':['0'*64]*(CPU34[2]*16//1827925),
                'input':'qualified-valid-cmos-prefix','audio_playback':False,'audio':None,
                'presentation':None,'cmos_hex':data.hex()}

    def test_profile_cannot_select_unsupported_playable_frontier(self):
        result=native.run(quality.ROOT/'missing-roms',profile_directory=quality.ROOT/'unused',through='first-fight')
        self.assertFalse(result['passed'])
        self.assertIn('cmos-boot',result['error'])
        self.assertNotIn('build',result)

    def test_profile_load_failure_never_initializes_or_builds(self):
        with quality.scratch_tree() as (scratch,cleanup):
            target=scratch/'missing'
            result=native.run(quality.ROOT/'missing-roms',profile_directory=target,through='cmos-boot')
            self.assertFalse(result['passed'])
            self.assertFalse(target.exists())
            self.assertNotIn('build',result)
        self.assertFalse(cleanup['exists_after'])

    def run_fake(self,target,data,*,execution_error=None,mutate=None,cleanup_failure=False,source_changed=False,reference_frames=False):
        observed=self.observed(data)
        scratch_tree=quality.scratch_tree
        @contextmanager
        def session_tree():
            with scratch_tree() as (scratch,cleanup):yield scratch,cleanup
            if cleanup_failure:cleanup['exists_after']=True
        reads={}
        def identity(path):
            reads[path]=reads.get(path,0)+1
            return 'changed' if source_changed and reads[path]>1 else 'sealed'
        def command(argv,scratch,**kwargs):
            if '-o' in argv:
                return {'passed':True,'stdout':'','discarded_output_bytes':0}
            self.assertEqual(profile._read(Path(argv[argv.index('--cmos-image')+1])),profile.load(target))
            if '--frames' in argv:Path(argv[argv.index('--frames')+1]).write_bytes(b'')
            if mutate:mutate()
            return {'passed':execution_error is None,'stdout':json.dumps(observed),
                    'discarded_output_bytes':0,'exit_code':0 if execution_error is None else 1}
        with patch.object(quality,'command',side_effect=command),patch.object(quality,'compact',side_effect=dict),\
             patch.object(native.foundation,'verify_roms',return_value={'verified':20}),\
             patch.object(quality,'sha',side_effect=identity),patch.object(quality,'scratch_tree',side_effect=session_tree),\
             patch.object(native,'frontier',side_effect=synthetic_frontier):
            return native.run(quality.ROOT/'roms/mk2',profile_directory=target,through='cmos-boot',reference_frames=reference_frames)

    def test_original_cmos_mismatch_rejects_save_before_raster_transport(self):
        with quality.scratch_tree() as (scratch,cleanup):
            target=scratch/'profile';seed=profile.prepare(target)
            def original(directory,*args,**kwargs):
                (directory/'frame-cmos.bin').write_bytes(b'\x11'*16384)
                return {'cpu34':CPU34,'inputs':[]}
            with patch.object(native,'capture_screen',side_effect=original) as capture:
                result=self.run_fake(target,b'\x7f'*16384,reference_frames=True)
            capture.assert_called_once()
            self.assertFalse(result['passed']);self.assertIn('CMOS',result['error'])
            self.assertFalse(result['persistence']['committed']);self.assertEqual(profile.load(target),seed)
        self.assertFalse(cleanup['exists_after'])

    def test_exact_complete_cmos_transport_saved_after_supported_runtime(self):
        with quality.scratch_tree() as (scratch,cleanup):
            target=scratch/'profile';seed=profile.prepare(target)
            data=bytes(range(256))*64
            result=self.run_fake(target,data)
            self.assertTrue(result['passed'],result)
            self.assertEqual(profile.load(target),data)
            self.assertEqual((target/'factory-seed.bin').read_bytes(),seed)
            self.assertNotIn('cmos_hex',result['native'])
            self.assertEqual(result['persistence']['loaded_sha256'],hashlib.sha256(seed).hexdigest())
            self.assertEqual(result['persistence']['saved_sha256'],hashlib.sha256(data).hexdigest())
        self.assertFalse(cleanup['exists_after'])

    def test_cleanup_source_change_and_atomic_save_failure_never_commit(self):
        with quality.scratch_tree() as (scratch,cleanup):
            for mode in ('cleanup','sources','fsync'):
                with self.subTest(mode=mode):
                    target=scratch/mode;seed=profile.prepare(target)
                    if mode=='fsync':
                        with patch.object(profile.os,'fsync',side_effect=OSError('disk failure')):
                            result=self.run_fake(target,b'\x7f'*16384)
                    else:result=self.run_fake(target,b'\x7f'*16384,
                        cleanup_failure=mode=='cleanup',source_changed=mode=='sources')
                    self.assertFalse(result['passed'],result)
                    self.assertFalse(result['persistence']['committed'])
                    self.assertEqual(profile.load(target),seed)
        self.assertFalse(cleanup['exists_after'])

    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_real_valid_cmos_message_and_original_clean_delay(self):
        from tools.mk2 import run
        import os
        run.verify_roms(quality.ROOT/'roms/mk2')
        source=r'''
#include "native/mk2/mk2_executor.hpp"
#include "native/mk2/mk2_cmos_image.hpp"
#include <fstream>
#include <iterator>
#include <iostream>
int main(int argc,char** argv) {try {
 if(argc!=3)throw std::runtime_error("arguments");
 const auto p=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
 const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
 std::ifstream input(argv[2],std::ios::binary);
 const std::vector<uint8_t> image{std::istreambuf_iterator<char>(input),{}};
 mk2::DcsBootMachine m(boot,rom);m.dsp.SetTraceObservation(false);
 // Generated closure from reset to the valid-CMOS clean-delay exit (before the startup admission).
 mk2::GeneratedBoot generated(p,m,&image,0xfc7d);
 const auto& s=generated.RunToBoundary(mk2::BootEvent::admit_startup).ready;
 std::cout<<"{\"cpu34\":["<<s.next_pc<<','<<s.status<<','<<s.cycles;
 for(auto value:s.a)std::cout<<','<<value;for(auto value:s.b)std::cout<<','<<value;
 std::cout<<"],\"cmos\":[";
 for(size_t n=0;n<s.cmos.size();++n)std::cout<<(n?",":"")<<s.cmos[n];
 std::cout<<"]}";
 }catch(const std::exception& e){std::cerr<<e.what();return 1;}}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'valid.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'valid.exe'
            sources=[p.removeprefix('native/mk2/') for p in run.EXECUTOR_SOURCES if p.startswith('native/mk2/')]
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
            result=quality.command([quality.DEFAULT_CC,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-Wno-misleading-indentation','-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),cpp,
                *[quality.ROOT/'native/mk2'/p for p in sources],quality.ROOT/'native/src/mk5_program.cpp',
                '-lbcrypt','-o',exe],scratch,timeout=600,env=env)
            self.assertTrue(result['passed'],result['stdout'])
            result=quality.command([exe,quality.ROOT/'roms/mk2',profile.FACTORY_SEED],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
            expected=native.frontier('cmos-boot')
            observed=json.loads(result['stdout']);self.assertTrue(native.frontier_matches(observed['cpu34'],expected))
            data=profile._read(profile.FACTORY_SEED,factory=True)
            row=observed['cpu34'];expected=list(__import__('struct').unpack('<8192H',data));expected[0xf0:0xf6]=[0,0,0,1,255,254]
            self.assertEqual(observed['cmos'],expected)
            # Reboot the exact returned bytes with the same executable, preserving guest audits.
            image=scratch/'second.cmos';image.write_bytes(__import__('struct').pack('<8192H',*observed['cmos']))
            result=quality.command([exe,quality.ROOT/'roms/mk2',image],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
            second=json.loads(result['stdout']);self.assertEqual(second['cpu34'],row)
            expected[0xf3]=2;expected[0xf5]=253
            self.assertEqual(second['cmos'],expected)
            invalid=bytearray(image.read_bytes());invalid[2*0x800]^=1;image.write_bytes(invalid)
            result=quality.command([exe,quality.ROOT/'roms/mk2',image],scratch,env=env)
            self.assertFalse(result['passed'],'unsupported CMOS checksum must reject')
            # The firmware leaves the valid-CMOS route: the executor rejects at the missed clean-delay admission.
            self.assertIn('missed a route boundary',result['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_crash_unsupported_context_and_cas_conflict_preserve_state(self):
        with quality.scratch_tree() as (scratch,cleanup):
            for mode in ('crash','boundary','conflict','truncated'):
                with self.subTest(mode=mode):
                    target=scratch/mode;seed=profile.prepare(target);data=b'\x13\x57'*8192
                    mutate=None
                    if mode=='conflict':
                        mutate=lambda:profile.save(target,b'\x44'*16384,expected_sha256=hashlib.sha256(seed).hexdigest())
                    if mode=='boundary':
                        original=self.observed
                        def invalid(payload):
                            value=original(payload);value['cpu34']=value['cpu34'].copy();value['cpu34'][4]^=1;return value
                        with patch.object(self,'observed',side_effect=invalid):result=self.run_fake(target,data)
                    else:result=self.run_fake(target,data[:-1] if mode=='truncated' else data,
                                              execution_error='crash' if mode=='crash' else None,mutate=mutate)
                    self.assertFalse(result['passed'],result)
                    self.assertEqual(profile.load(target),b'\x44'*16384 if mode=='conflict' else seed)
                    self.assertNotIn('saved_sha256',result['persistence'])
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
