"""Host chunks resume their provider and clocks, without importing a replay boundary."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality


class HostResumeTests(unittest.TestCase):
    def test_resume_api_preserves_the_existing_host_owner(self):
        source = r'''
#include "native/mk2/mk2_task_batch.hpp"
#include <type_traits>
using Resume = mk2::TaskBatchInit (*)(const mk2::Program&, const mk2::TaskBatchInit&,
                                    mk2::DcsBootMachine&, uint64_t);
static_assert(std::is_same_v<decltype(&mk2::ResumeHostContinuation), Resume>);
'''
        with quality.scratch_tree() as (scratch, cleanup):
            cpp = scratch / 'host-resume.cpp'
            cpp.write_text(source, encoding='ascii')
            env = {'PATH': str(quality.DEFAULT_CC.parent) + os.pathsep + os.environ.get('PATH', '')}
            result = quality.command([quality.DEFAULT_CC, '-std=c++17', '-fsyntax-only',
                                      '-I' + str(quality.ROOT), cpp], scratch, env=env)
            self.assertTrue(result['passed'], result['stdout'])
        self.assertFalse(cleanup['exists_after'])


if __name__ == '__main__':
    unittest.main()
