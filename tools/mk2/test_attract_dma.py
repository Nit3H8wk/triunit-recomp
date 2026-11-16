"""Component regression for the attract MMTM DMA writer (synthetic operands at the Original writer PC)."""
from pathlib import Path
import argparse
import json
import os
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import profile,run
from tools.quality import run as q
REPORT = None


class AttractDmaTests(unittest.TestCase):
    @unittest.skipUnless((q.ROOT/'roms/mk2').is_dir(),'requires authenticated local MK2 ROMs')
    def test_original_writer_order_cycles_and_cold_domain_rejection(self):
        receipt={'passed':False,'scope':'Component fixture after authentic admitted first draw; not a reset-to-attract gameplay comparison.'}
        reference=q.ROOT/'docs/investigation/decoder-research/upstream/34010ops.hxx'
        receipt['reference_core_sha256']=q.sha(reference)
        self.assertEqual(receipt['reference_core_sha256'],'5596e7ca123d3d91e7dd7dc83538a1b05a83489b6abe80ac5e013748bd7d721f')
        sources=[p for p in run.SOURCES if p!='native/tests/mk2_foundation_tests.cpp']+['native/tests/mk2_attract_dma_tests.cpp']
        with q.scratch_tree() as (scratch,cleanup):
            receipt['cleanup']=cleanup
            exe=scratch/'attract-dma.exe'
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-O1','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-missing-field-initializers','-Inative/include',
                *[q.ROOT/p for p in sources],'-lbcrypt','-o',exe],scratch,cwd=q.ROOT,env=env,timeout=240)
            receipt['build']=q.compact(build)
            receipt['build'].pop('build_units',None)
            receipt['build']['metrics_scope']='linker driver only; per-compiler-driver records omitted from this compact component receipt'
            if 'compiler_cache' in receipt['build']:
                receipt['build']['compiler_cache'].pop('stats',None)
            if build['passed']:
                result=q.command([exe,q.ROOT/'roms/mk2',profile.FACTORY_SEED],scratch,cwd=q.ROOT,env=env,timeout=60)
                receipt['execution']=q.compact(result);receipt['passed']=result['passed']
        if REPORT is not None:
            REPORT.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(receipt,indent=2))
        self.assertTrue(receipt['passed'],receipt)
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--report',type=Path)
    args,remaining=parser.parse_known_args()
    REPORT=args.report
    if REPORT is not None and REPORT.exists():parser.error('Preserve the existing receipt')
    unittest.main(argv=[sys.argv[0],*remaining])
