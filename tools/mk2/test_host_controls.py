"""Host requests retain the original next-frame latch and reject mixed scripts."""
import os
import copy
import json
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native
from tools.quality import run as quality


class HostControlTests(unittest.TestCase):
    def test_provider_handoff_latches_on_the_following_original_frame(self):
        source=r'''
#include "native/mk2/mk2_board.hpp"
#include <functional>
#include <stdexcept>
int main() {
    mk2::BoardBootControls board;
    board.io[8]=0x2000;board.io[7]=288;
    board.input_events.push_back({100,0,65535,1});
    unsigned calls=0;
    board.SetHostInputProvider([&](uint64_t tick) {
        if(tick!=94875+uint64_t(274+289*calls)*6325) throw std::runtime_error("clock");
        return calls++ ? 0xffffffffu : 0xffffffefu;
    },101);
    if(board.input0!=0xffff || board.input_events.size()!=1) return 1;
    board.AdvanceScanlines(275);
    if(calls!=1 || board.input0!=0xffff || board.input_events.back()[3]!=6) return 2;
    bool rejected=false;
    const auto before=board.input_events;
    try {board.SetP1HighPunch(true,2000000);} catch(const std::runtime_error&) {rejected=true;}
    if(!rejected || board.input_events!=before) return 3;
    board.AdvanceScanlines(564);
    if(calls!=2 || board.input0!=0xffef || board.input_events[2][3]!=7) return 4;
    board.AdvanceScanlines(853);
    if(calls!=3 || board.input0!=0xffff) return 5;
    for(unsigned mode=0;mode<4;++mode) {
        mk2::BoardBootControls bad;
        if(mode==0)bad.input0=0xffef;
        if(mode==1)bad.requested_coin1=true;
        if(mode==2)bad.input_events.push_back({102,0,65535,1});
        auto events=bad.input_events;
        rejected=false;
        try {bad.SetHostInputProvider(mode==3 ? std::function<uint32_t(uint64_t)>{} :
            std::function<uint32_t(uint64_t)>{[](uint64_t){return 0xffffffffu;}},101);}
        catch(const std::runtime_error&) {rejected=true;}
        if(!rejected || bad.input_events!=events || bad.HostInputProviderActive()) return 6;
    }
}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'host.cpp';cpp.write_text(source,encoding='ascii')
            exe=scratch/'host.exe'
            env={'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([quality.DEFAULT_CC,'-std=c++17','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT),cpp,'-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env)
            self.assertTrue(result['passed'],result)
        self.assertFalse(cleanup['exists_after'])

    def test_host_mode_rejects_nonwindow_and_reference_before_rom_loading(self):
        for options in ({},{'window':True,'reference_frames':True},{'window':True,'through':'next-wait'}):
            with self.subTest(options=options):
                receipt=native.run(quality.ROOT/'missing-roms',host_controls=True,**options)
                self.assertFalse(receipt['passed'])
                self.assertIn('Host controls require',receipt['error'])
                self.assertNotIn('roms',receipt)
                self.assertNotIn('build',receipt)

    def test_host_receipt_cannot_claim_fixed_route_or_complete_gameplay(self):
        bounds=native.host_control_range()
        cycle=bounds['minimum_stop_cycle']
        frames=cycle*16//1827925
        observed={'scope':'mk2-native-host-controls-check','gameplay_complete':False,
            'execution_continues':False,'termination':'finite_host_cooperative_boundary',
            'input':'host-keyboard-xinput-finite','through':'first-fight',
            'frontier_pc':0xff80dd30,
            'cpu34':[0xff80dd30,0xe0200030,cycle]+[0]*31,
            'host_controls':dict(bounds,events=[[(bounds['start_cycle']+100)*16,0xffffffffffff,0xffffffffffff,6]]),
            'frames':frames,'width':400,'height':254,'frame_sha256':['0'*64]*frames}
        native.validate_host_boundary(observed)
        for key,value in (('gameplay_complete',True),('execution_continues',True),
                          ('termination','translated_frontier_reached'),('input','fixed-measured-route'),
                          ('frontier_pc',0xff800000)):
            bad=copy.deepcopy(observed);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):native.validate_host_boundary(bad)
        for cycle in (bounds['start_cycle'],bounds['maximum_cycle']+1):
            bad=copy.deepcopy(observed);bad['cpu34'][2]=cycle
            with self.subTest(cycle=cycle),self.assertRaises(ValueError):native.validate_host_boundary(bad)
        bad=copy.deepcopy(observed);bad['host_controls']['events'][0][3]=0
        with self.assertRaises(ValueError):native.validate_host_boundary(bad)
        for field in bounds:
            bad=copy.deepcopy(observed);bad['host_controls'][field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):native.validate_host_boundary(bad)


    def test_complete_long_host_receipt_and_explicit_truncation_rejection(self):
        bounds=native.host_control_range();cycle=bounds['minimum_stop_cycle'];frames=cycle*16//1827925
        events=[[(bounds['start_cycle']*16)+1+n*1827925,0xffffffffffff,0xffffffffffff,6] for n in range(1024)]
        observed={'scope':'mk2-native-host-controls-check','gameplay_complete':False,'execution_continues':False,
            'termination':'finite_host_cooperative_boundary','input':'host-keyboard-xinput-finite','through':'first-fight',
            'frontier_pc':0xff80dd30,'cpu34':[0xff80dd30,0xe0200030,cycle]+[0]*31,
            'host_controls':dict(bounds,events=events),'frames':frames,'width':400,'height':254,
            'frame_sha256':['0'*64]*frames,'audio_playback':False,'audio':None,
            'presentation':{'renderer':'D3D12-DXGI-flip','gpu_validation_frames':1,'gpu_validation_mismatches':0,
                            'bicubic_fighter_validation_frames':0}}
        payload=json.dumps(observed);self.assertGreater(len(payload),quality.OUTPUT_LIMIT)
        for forced_loss in (False,True):
            def command(args,scratch,**options):
                if args[0]==quality.DEFAULT_CC:return {'passed':True,'stdout':'','discarded_output_bytes':0}
                cap=options.get('output_limit',quality.OUTPUT_LIMIT);discard=max(len(payload)-cap,0)
                if forced_loss:discard=max(discard,1)
                return {'passed':True,'stdout':payload[discard:],'discarded_output_bytes':discard}
            with self.subTest(forced_loss=forced_loss),patch.object(native.quality,'command',side_effect=command),patch.object(native.foundation,'verify_roms',return_value={'verified':20}):
                receipt=native.run(quality.ROOT/'roms/mk2',window=True,through='first-fight',host_controls=True)
            self.assertFalse(receipt['cleanup']['exists_after'])
            if forced_loss:
                self.assertFalse(receipt['passed']);self.assertIn('truncat',receipt['error'].lower())
            else:
                self.assertTrue(receipt['passed'],receipt.get('error'));self.assertEqual(receipt['native'],observed)

if __name__=='__main__':unittest.main()
