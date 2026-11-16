"""Execute fixed task-queue translations against real BootOps primitives."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g
from tools.quality import run as quality


class TaskQueueGeneratorTests(unittest.TestCase):
    def test_signed_less_equal_and_absolute_equal_execute_original_flags_and_cycles(self):
        try:
            absolute = g.emit_instruction(0x100, 48, "JAEQ 200h", (0,0,0),
                                          {0x130, 0x200}, {0x100: (0x130, 0x200)})
            branch = g.emit_instruction(0x100, 16, "JRLE 200h", (0xc701,),
                                        {0x110, 0x200}, {0x100: (0x110, 0x200)})
        except ValueError as error:
            self.fail(f"Task continuation cannot be translated: {error}")
        source = r'''
#include "native/mk2/mk2_boot_ops.hpp"
#include <stdexcept>
void check(bool ok) { if (!ok) throw std::runtime_error("task-queue instruction contract"); }
int main() {
    mk2::Program program;
    for (unsigned flags : {0u,0x20000000u}) {
        mk2::DcsBootMachine machine(std::vector<uint32_t>(376));
        mk2::BootContinuation out;
        mk2::BootOps o(program, machine, out);
        auto& s=o.s; s.board.io[8]=0x2000;
        s.next_pc=0x100; s.status=flags|0xd0200030u;
        const auto status=s.status;
        ABSOLUTE
        check(s.status==status && s.next_pc==(flags ? 0x200u : 0x130u) && s.cycles==(flags ? 3u : 4u));
        check(s.instructions==1 && out.bus.empty() && machine.dsp.trace.empty());
    }
    for (unsigned flags : {0u,0x10000000u,0x20000000u,0x30000000u,0x80000000u,0x90000000u,0xa0000000u,0xb0000000u}) {
        mk2::DcsBootMachine machine(std::vector<uint32_t>(376));
        mk2::BootContinuation out;
        mk2::BootOps o(program, machine, out);
        auto& s=o.s; s.board.io[8]=0x2000;
        s.next_pc=0x100; s.status=flags|0x40200030u;
        const auto status=s.status;
        BRANCH
        const bool take=flags!=0 && flags!=0x90000000u;
        check(s.status==status && s.next_pc==(take ? 0x200u : 0x110u) && s.cycles==(take ? 2u : 1u));
        check(s.instructions==1 && out.bus.empty() && machine.dsp.trace.empty());
    }
}
'''.replace("ABSOLUTE", absolute).replace("BRANCH", branch)
        with quality.scratch_tree() as (scratch, cleanup):
            path=scratch / "task-queue.cpp"
            path.write_text(source, encoding="utf-8")
            executable=scratch / "task-queue.exe"
            compiler=quality.DEFAULT_CC
            env={"PATH": str(compiler.parent)+os.pathsep+os.environ.get("PATH", "")}
            build=quality.command([compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror",
                "-I"+str(g.ROOT),"-I"+str(g.ROOT/"native/include"),path,
                g.ROOT/"native/mk2/mk2_adsp.cpp",g.ROOT/"native/mk2/mk2_dcs.cpp",
                g.ROOT/"native/src/mk5_program.cpp","-lbcrypt","-o",executable],scratch,env=env)
            self.assertTrue(build["passed"],build.get("stdout", ""))
            result=quality.command([executable],scratch,env=env)
            self.assertTrue(result["passed"],result.get("stdout", ""))
        self.assertFalse(cleanup["exists_after"])


if __name__ == "__main__":
    unittest.main()
