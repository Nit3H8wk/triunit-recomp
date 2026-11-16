"""Bulk compiler dependency discovery must preserve the exact identity contract."""
import hashlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.mk2 import package_native as package
from tools.quality import run as q


class BuildIdentityTests(unittest.TestCase):
    def test_bulk_dependencies_keep_escaped_paths_and_all_source_hashes(self):
        with q.scratch_tree() as (scratch, cleanup):
            folder = scratch / 'native/mk2'
            folder.mkdir(parents=True)
            texts = {'native/mk2/mk2_native_check.cpp': '#include "space header.hpp"\nint a(){return VALUE;}\n',
                     'native/mk2/other.cpp': '#include "space header.hpp"\nint b(){return VALUE+1;}\n',
                     'native/mk2/space header.hpp': '#define VALUE 12\n'}
            for name, value in texts.items():
                (scratch / name).write_text(value, newline='\n')
            bezel = scratch / package.BEZEL
            bezel.parent.mkdir()
            bezel.write_bytes(b'bezel fixture')
            calls = []
            real = q.command
            def counted(*args, **kwargs):
                calls.append(args[0])
                return real(*args, **kwargs)
            with patch.object(package, 'ROOT', scratch), patch.object(package, 'SOURCES', list(texts)[:2]), \
                 patch.object(package, 'FLAGS', ['-std=c++17']), patch.object(q, 'command', side_effect=counted):
                value = package.identities(scratch, {'PATH': str(q.DEFAULT_CC.parent) + os.pathsep + os.environ['PATH']})
            expected = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()}
            expected[package.BEZEL] = q.sha(bezel)
            self.assertEqual(value['files'], expected)
            self.assertEqual(value['source_sha256'], expected['native/mk2/mk2_native_check.cpp'])
            self.assertEqual(len(calls), 1, 'dependency scan still launches one compiler per source')
        self.assertFalse(cleanup['exists_after'])


if __name__ == '__main__':
    unittest.main()
