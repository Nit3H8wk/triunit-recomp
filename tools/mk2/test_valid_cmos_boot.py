"""Original valid-CMOS reset endpoints and exact state; unknown contexts reject before DSP mutation."""
import json,os,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality
from tools.mk2 import run,profile
from tools.mk2.oracle_digest import cpu34_digest
# Eight CPU34 checkpoints of the Original (pinned MAME 0.280 + the user's ROMs): PC, cycle and the SHA-256 of the full
# row (tools/mk2/oracle_digest.py). The raw rows are regenerated locally by the oracle and never versioned.
EXPECTED={
    'returned':(0xff8111f0,1868,'770635de027f0dc91c7a860842d85fcc5eb375e8b547e35dd8c60ad6aa41aabe'),
    'board_entry':(0xffa5fa20,1871,'4d48beea8b5c6db51813d3e1948a3d7bd79c09422364168f919776ee48a1892a'),
    'board_configured':(0xffa5c180,2076,'57fb46c60e5bd1cbdac2df86e5840dff01295bf4d5eb4d806981e74a595a278e'),
    'board_ready':(0xffa5c200,2086,'1326f8339c88f96cc869e0d963408ceea2fd6a9282b43b6a9235539e13f99f6e'),
    'powerup_ready':(0xffa5a000,100452,'14159ede7c4b754fc8d56884a211dad9b3a984efff3da77283710495b0757640'),
    'video_ready':(0xffa5a190,297190,'094d7805ed765e1e571a45c229dc2e8017ecb1bb95770e405203eb036fe6a432'),
    'text_cmos_checked':(0xffa5a2d0,306024,'966322a96b8b48c27241da8fbd3b00e120c4b7939df27a280883c7e76caa1373'),
    'valid_message':(0xffa5a6e0,306026,'5094330abceabb96a0a7213fd632af9140c0f2c7b13978e5ef79b9ca7941e299'),
}
class ValidCmosBootTests(unittest.TestCase):
    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_valid_contexts_full_cpu_cmos_and_mutation_rejection(self):
        run.verify_roms(quality.ROOT/'roms/mk2')
        sources=['native/tests/mk2_valid_cmos_boot_tests.cpp',*run.EXECUTOR_SOURCES]
        with quality.scratch_tree() as (scratch,cleanup):
            exe=scratch/'valid-cmos.exe';cc=quality.DEFAULT_CC
            env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),
                *[quality.ROOT/p for p in sources],'-lbcrypt','-o',exe],scratch,timeout=600,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            # Generated closure from reset, stopped at each boundary's (PC, cycle).
            points=[f'{pc}:{cycle}' for pc,cycle,_ in EXPECTED.values()]
            result=quality.command([exe,quality.ROOT/'roms/mk2',profile.FACTORY_SEED,*points],scratch,env=env,timeout=120)
            self.assertTrue(result['passed'],result['stdout'])
            observed=json.loads(result['stdout'])
            self.assertEqual([(row[0],row[2],cpu34_digest(row)) for row in observed['CPU34']],list(EXPECTED.values()))
            wanted=list(struct.unpack('<8192H',profile._read(profile.FACTORY_SEED,factory=True)))
            wanted[0xf0:0xf6]=[0,0,0,1,255,254]
            self.assertEqual(observed['cmos'],wanted)
        self.assertFalse(cleanup['exists_after'])
if __name__=='__main__':unittest.main()
