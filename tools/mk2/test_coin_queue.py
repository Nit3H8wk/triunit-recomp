"""Original coin request timeline and fixed translation provenance."""
import unittest
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_coin_queue as coin
from tools.mk2 import generate_video_irq as shared
from tools.quality import run as quality


class CoinQueueTests(unittest.TestCase):
    def test_measured_input_and_new_blocks(self):
        self.assertEqual((coin.START, coin.END_PC, coin.END),
                         (3087189, 0xff8119b0, 3315882))
        self.assertEqual(coin.REQUESTS, ((28, 1), (30, 0)))
        for pc in (0xff8172d0, 0xff817560, 0xff80e280, 0xff811b40):
            self.assertIn(pc, coin.PCS)
        self.assertNotIn(0xffa51760, coin.PCS)  # Accounting task has not executed.
        self.assertNotIn(0xff816370, coin.SUCCESSORS.get(0xff807e20, ()))

    def test_generator_rejects_wrong_rom(self):
        with self.assertRaisesRegex(ValueError, 'authenticated'):
            coin.generate(bytes(0x100000))

    def test_new_dynamic_rotate_and_queue_store_keep_original_operands(self):
        pcs={0xff8175e0,0xff8175f0,0xff817620,0xff817630}
        emitted=shared.emit_instruction(0xff8175e0,16,'RL     A0,A2',(0,),pcs,{},end=0xff817630)
        self.assertIn('s.a[0]', emitted)
        self.assertIn('s.a[2]', emitted)

    def test_coin_request_is_applied_at_next_original_frame_and_keeps_p1(self):
        source = r'''
#include "native/mk2/mk2_board.hpp"
#include <stdexcept>
int main() {
    mk2::BoardBootControls b;
    b.io[7]=288; b.io[8]=0x2000;
    b.SetCoin1(true,100);
    if(b.input1!=0xffff || !b.requested_coin1 || b.input_events.size()!=1) return 1;
    b.AdvanceScanlines(274);
    if(b.input1!=0xffff) return 2;
    b.AdvanceScanlines(275);
    if(b.input1!=0xfffe || b.input0!=0xffff || b.input_events.size()!=2) return 3;
    if(b.input_events[0]!=std::array<uint64_t,4>{100,1,0xffff,2} ||
       b.input_events[1]!=std::array<uint64_t,4>{1827925,1,0xfffe,3}) return 4;
    b.SetCoin1(false,1827926); b.AdvanceScanlines(563);
    if(b.input1!=0xfffe) return 5;
    b.AdvanceScanlines(564);
    if(b.input1!=0xffff || b.input_events.size()!=4 ||
       b.input_events.back()!=std::array<uint64_t,4>{3655850,0,0xffff,3}) return 6;
    try { b.SetCoin1(true,0); return 7; } catch(const std::runtime_error&) {}
    if(b.requested_coin1 || b.input_events.size()!=4) return 8;
}
'''
        with quality.scratch_tree() as (scratch, cleanup):
            path=scratch/'coin.cpp'; path.write_text(source)
            executable=scratch/'coin.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-Wall','-Wextra','-Werror',
                                   '-I'+str(quality.ROOT),path,'-o',executable],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            execution=quality.command([executable],scratch,env=env)
            self.assertTrue(execution['passed'],execution['stdout'])
        self.assertFalse(cleanup['exists_after'])


if __name__ == '__main__': unittest.main()
