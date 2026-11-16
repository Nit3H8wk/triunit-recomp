"""Compare bounded native PCM observation to the unchanged pinned DMADAC kernel."""
import json,os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality


class DacTimelineTests(unittest.TestCase):
    def test_original_dmadac_kernel_and_native_timeline_are_bit_exact(self):
        root=quality.ROOT
        manifest=json.loads((root/'docs/investigation/decoder-research/adsp-sources.json').read_text())
        upstream=root/'docs/investigation/decoder-research/upstream'
        for name in ('dmadac.cpp','dmadac.h','disound.cpp'):
            entry=next(row for row in manifest['files'] if row['file']==name)
            self.assertEqual(quality.sha(upstream/name),entry['sha256'])
        cc=quality.DEFAULT_CC;environment={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
        with quality.scratch_tree() as (scratch,cleanup):
            exe=scratch/'dac-timeline.exe'
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-I'+str(root/'tools/mk2/dac_reference'),'-I'+str(upstream),'-I'+str(root/'native/include'),
                root/'native/tests/mk2_dac_timeline_tests.cpp',root/'native/mk2/mk2_adsp.cpp',
                root/'native/mk2/mk2_dcs.cpp',root/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],
                scratch,env=environment)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=environment)
            self.assertTrue(result['passed'],result['stdout'])
            print(result['stdout'].strip())
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
