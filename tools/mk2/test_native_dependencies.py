"""The compiler's local include closure must be sealed by native observations."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native
from tools.quality import run as quality


class NativeDependencyTests(unittest.TestCase):
    def test_compiler_include_closure_is_in_observation_identity(self):
        observed=native.run(quality.ROOT/'missing-roms')
        self.assertFalse(observed['passed'])
        sealed=observed['sources']
        from tools.setup import mk2   # generated page units carry their source-tree name in the identity
        sources=[mk2.source(name).as_posix() for name in sealed if name.endswith('.cpp')]
        result=quality.command([quality.DEFAULT_CC,'-std=c++17','-Inative/include',
            '-MM','-MT','native-dependencies',*sources],quality.ROOT,
            cwd=quality.ROOT,env=native.environment(),timeout=30)
        self.assertTrue(result['passed'],result['stdout'])
        self.assertEqual(result['discarded_output_bytes'],0)
        import shlex   # make-escaped spaces in the absolute generated/ include paths
        tokens=shlex.split(result['stdout'].replace('\\\r\n',' ').replace('\\\n',' '))
        def named(path):   # generated includes carry their former source-tree name (native/mk2/<name>)
            if path.parent.parent.as_posix().endswith('generated/mk2'):return 'native/mk2/'+path.name
            return path.relative_to(quality.ROOT).as_posix()
        dependencies={named((quality.ROOT/token).resolve()) for token in tokens if token!='native-dependencies:'}
        self.assertTrue(dependencies)
        self.assertEqual(sorted(dependencies-set(sealed)),[],
                         'Native source identity omits compiler dependencies')


if __name__=='__main__':unittest.main()
