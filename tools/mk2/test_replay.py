"""Compact crash input capture is complete or explicitly refuses replay."""
import os
import hashlib
from pathlib import Path
import sys
import struct
import json
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q


class ReplayTests(unittest.TestCase):
    def test_impossible_host_bits_are_rejected_before_execution(self):
        from tools.mk2.replay import read_capture
        from tools.mk2.generate_video_irq import PROGRAM_SHA256
        seed=bytes(16384);digest=hashlib.sha256(seed).hexdigest()
        text=f'MK2_REPLAY_V1 {PROGRAM_SHA256} {digest} 1 1\nMK2_REPLAY_CMOS {seed.hex()}\nMK2_REPLAY_INPUT 100 4294967167\nMK2_REPLAY_END\n'
        with self.assertRaisesRegex(ValueError,'host'):read_capture(text)

    def test_original_scene_metadata_is_preserved_and_conflicts_reject(self):
        from tools.mk2 import replay,profile,generate_video_irq as g
        scene={'accepted':True,'observed_outcome':'variant-f'}
        data={'format':'MK2_REPLAY_V1','timebase_hz':100000000,'initial_shared_active_low':0xffffffff,
              'factory_cmos_sha256':profile.FACTORY_SHA256,'factory_cmos_bytes':16384,'program_sha256':g.PROGRAM_SHA256,
              'request_rows':[[1,0xffffffff]],'end_frame':10,'Original_visual_acceptance':scene}
        self.assertEqual(replay.read_capture(json.dumps(data))['reference_visual_acceptance'],scene)
        data['visual_acceptance']={'accepted':False}
        with self.assertRaisesRegex(ValueError,'acceptance'):replay.read_capture(json.dumps(data))

    def test_archived_stage_locators_allow_replay_without_typed_recognition(self):
        from tools.mk2.replay import read_capture
        recipe = q.ROOT / 'tools/mk2/finisher_replays/natural-f08-stage-a.json'
        data = json.loads(recipe.read_text())
        capture = read_capture(json.dumps(data))
        self.assertIsNone(capture['reference_visual_acceptance'])
        self.assertEqual(capture['inputs'], [tuple(row) for row in data['request_rows']])
        for edits in ({'kind':'other'}, {'Original_accepted':1},
                      {'Original_visual_acceptance':{'accepted':True}},
                      {'visual_acceptance':{**data['visual_acceptance'],'stage_kill_frame':1}},
                      {'visual_acceptance':{**data['visual_acceptance'],'contact_sha256':7}}):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                read_capture(json.dumps({**data,**edits}))

    def test_snapshot_frames_must_fit_the_actual_observation_horizon(self):
        from tools.mk2.replay import checked_snapshot_frames
        self.assertEqual(checked_snapshot_frames([4,1],456982),[1,4])
        for frames in ([0],[5],[1,1],[True],list(range(1,66))):
            with self.subTest(frames=frames),self.assertRaises(ValueError):
                checked_snapshot_frames(frames,456982)
        with self.assertRaises(ValueError):checked_snapshot_frames([4],456981)

    def test_crlf_failure_header_keeps_cpu34(self):
        from tools.mk2.replay import read_capture
        from tools.mk2.generate_video_irq import PROGRAM_SHA256
        seed=bytes(16384);digest=hashlib.sha256(seed).hexdigest()
        cpu=[4288363872,2097200,2368204965]+list(range(31))
        capture='failure; CPU34 '+','.join(map(str,cpu))+'\n'+f'MK2_REPLAY_V1 {PROGRAM_SHA256} {digest} 0 1\nMK2_REPLAY_CMOS {seed.hex()}\nMK2_REPLAY_END\n'
        for text in (capture,capture.replace('\n','\r\n')):
            with self.subTest(crlf='\r' in text):
                self.assertEqual(read_capture(text)['failed_cpu34'],cpu)

    def test_long_legal_chains_get_bounded_host_time_without_guest_clock_changes(self):
        from tools.mk2.replay import execution_wall_seconds
        self.assertEqual(execution_wall_seconds(395750000),180)
        self.assertEqual(execution_wall_seconds(180*6250000),180)
        self.assertEqual(execution_wall_seconds(180*6250000+1),181)
        self.assertEqual(execution_wall_seconds(2423375000),388)
        self.assertEqual(execution_wall_seconds(16955500000),2400)
        self.assertEqual(execution_wall_seconds(10**18),2400)

    def test_case_directory_expands_only_direct_json_files_and_rejects_duplicates(self):
        from tools.mk2.replay import expand_logs
        with q.scratch_tree()as(scratch,cleanup):
            a=scratch/'case01.json';b=scratch/'case00.json';a.write_text('{}');b.write_text('{}')
            (scratch/'other.log').write_text('x');(scratch/'nested').mkdir();(scratch/'nested/hidden.json').write_text('{}')
            self.assertEqual(expand_logs([scratch]),[b,a])
            with self.assertRaises(ValueError):expand_logs([scratch,a])
            with self.assertRaises(ValueError):expand_logs([scratch/'nested/empty'])
        self.assertFalse(cleanup['exists_after'])

    def test_original_recipe_preserves_requests_and_extends_observation_to_full_audio_block(self):
        from tools.mk2.replay import read_capture
        from tools.mk2 import profile,generate_video_irq
        data={'format':'MK2_REPLAY_V1','timebase_hz':100000000,'initial_shared_active_low':0xffffffff,
              'factory_cmos_sha256':profile.FACTORY_SHA256,'factory_cmos_bytes':16384,
              'program_sha256':generate_video_irq.PROGRAM_SHA256,'request_rows':[[1,0xffffffff],[2,0xffffffef]],
              'end_frame':10,'snapshot_frames':[1,9]}
        result=read_capture(json.dumps(data))
        self.assertEqual(result['inputs'],[(1,0xffffffff),(2,0xffffffef)])
        self.assertEqual(result['end_cycles'],1250000)
        self.assertEqual(result['cmos'],profile.FACTORY_SEED.read_bytes())
        long_case=dict(data);long_case.update(end_frame=100,snapshot_frames=list(range(1,65)))
        self.assertEqual(len(read_capture(json.dumps(long_case))['snapshot_frames']),64)
        long_case['snapshot_frames']=list(range(1,66))
        with self.assertRaises(ValueError):read_capture(json.dumps(long_case))
        for key,value in [('timebase_hz',1),('factory_cmos_sha256','0'*64),('request_rows',[[True,1]]),('end_frame',False)]:
            bad=dict(data);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):read_capture(json.dumps(bad))

    def test_maximum_valid_capture_fits_the_explicit_runner_output_limit(self):
        from tools.mk2.replay import read_capture
        from tools.mk2.generate_video_irq import PROGRAM_SHA256
        seed=bytes(16384)
        text=f'MK2_REPLAY_V1 {PROGRAM_SHA256} {hashlib.sha256(seed).hexdigest()} 16384 1\nMK2_REPLAY_CMOS {seed.hex()}\n'+''.join(f'MK2_REPLAY_INPUT {0xffffffffffff0000+n} {0xfffffffe+(n&1)}\n'for n in range(16384))+'MK2_REPLAY_END\n'
        with q.scratch_tree()as(scratch,cleanup):
            path=scratch/'capture.txt';path.write_text(text)
            command=[sys.executable,'-c','from pathlib import Path;import sys;sys.stdout.write(Path(sys.argv[1]).read_text())',path]
            result=q.command(command,scratch,output_limit=1024*1024)
            self.assertTrue(result['passed']);self.assertEqual(result['discarded_output_bytes'],0)
            self.assertEqual(len(read_capture(result['stdout'])['inputs']),16384)
            with self.assertRaises(ValueError):read_capture(text.replace(' 16384 1\n',' 16385 1\n'))
            negative=q.command(command,scratch,output_limit=128*1024)
            self.assertGreater(negative['discarded_output_bytes'],0)
            with self.assertRaises(ValueError):read_capture(negative['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_very_easy_long_recipe_requires_the_pinned_initial_cmos(self):
        from tools.mk2 import replay,profile,generate_video_irq as g
        digest='0dd770a29c1c175b41e3d13916f8fce8fd67b019e6d00e937568a9536d9f1e44'
        data={'format':'MK2_REPLAY_V1','timebase_hz':100000000,'initial_shared_active_low':0xffffffff,
              'initial_cmos_sha256':digest,'initial_cmos_bytes':16384,'program_sha256':g.PROGRAM_SHA256,
              'request_rows':[[n+1,0xfffffffe+(n&1)]for n in range(10579)],'end_frame':110406}
        capture=replay.read_capture(json.dumps(data))
        self.assertEqual(len(capture['inputs']),10579)
        self.assertEqual(hashlib.sha256(capture['cmos']).hexdigest(),digest)
        factory=profile.FACTORY_SEED.read_bytes()
        self.assertEqual([(i,a,b)for i,(a,b)in enumerate(zip(factory,capture['cmos']))if a!=b],
                         [(4214,3,1),(4434,61,63)])
        for changes in ({'initial_cmos_sha256':'0'*64},{'initial_cmos_bytes':16383},
                        {'factory_cmos_sha256':profile.FACTORY_SHA256,'factory_cmos_bytes':16384},
                        {'request_rows':[[n+1,0xfffffffe+(n&1)]for n in range(16385)]}):
            with self.subTest(keys=changes.keys()),self.assertRaises(ValueError):
                replay.read_capture(json.dumps({**data,**changes}))

    def test_audio_stream_comparison_checks_every_bit_and_pcm_sample(self):
        from tools.mk2.replay_audio import compare_float_files, compare_pcm_file
        with q.scratch_tree()as(scratch,cleanup):
            a=scratch/'a';b=scratch/'b';pcm=scratch/'pcm'
            data=struct.pack('<fff',0,0.5,-0.5);a.write_bytes(data);b.write_bytes(data)
            pcm.write_bytes(struct.pack('<hhh',0,16384,-16384))
            self.assertEqual(compare_float_files(a,b,3,'DAC')['unequal_float32_bits'],0)
            self.assertEqual(compare_pcm_file(pcm,b,3)['unequal_samples'],0)
            a.write_bytes(struct.pack('<I',0x80000000)+data[4:])
            with self.assertRaises(ValueError):compare_float_files(a,b,3,'DAC')
            pcm.write_bytes(struct.pack('<hhh',0,16383,-16384))
            with self.assertRaises(ValueError):compare_pcm_file(pcm,b,3)
        self.assertFalse(cleanup['exists_after'])

    def test_audio_report_finds_exact_changed_sample_beyond_the_first_block(self):
        from tools.mk2.replay_audio import compare_float_files, compare_pcm_file
        count = 16390
        changed = 16386
        with q.scratch_tree() as (scratch, cleanup):
            original = scratch / 'original'
            candidate = scratch / 'candidate'
            original.write_bytes(bytes(count * 4))
            for compare, width, stream in (
                    (lambda a,b: compare_float_files(a,b,count,'DAC31250'), 4, 'DAC31250'),
                    (lambda a,b: compare_pcm_file(a,b,count), 2, 'PCM16')):
                bits = bytes([1]) + bytes(width - 1)
                candidate.write_bytes(bytes(changed * width) + bits + bytes((count - changed - 1) * width))
                with self.subTest(stream=stream), self.assertRaises(ValueError) as mismatch:
                    compare(candidate, original)
                self.assertEqual(mismatch.exception.difference, {
                    'stream': stream, 'sample_index': changed,
                    'native_bits_le': bits.hex(), 'original_bits_le': bytes(width).hex(),
                })
        self.assertFalse(cleanup['exists_after'])

    def test_dma_rejection_is_not_misclassified_as_an_untranslated_store_opcode(self):
        from tools.mk2.replay import describe_failure
        row=describe_failure('MK2 pair DMA outside measured unscaled commands; command 49330; xstep 256; ystep 256; TMS PC 4286596656; TMS cycle 54058125; status 16; CPU34 '+','.join(['1']*34))
        self.assertEqual(row['kind'],'dma_command')
        self.assertEqual(row['command'],'c0b2');self.assertEqual(row['xstep'],256)
        self.assertEqual(row['pc'],'ff804630');self.assertEqual(row['cpu34'],[1]*34)
        row=describe_failure('MK2 coin pair PC outside authenticated fixed translation; TMS PC 4288736464')
        self.assertEqual(row['kind'],'missing_static_pc');self.assertEqual(row['pc'],'ffa0ecd0')
        row=describe_failure('ADSP untranslated PC 2707; opcode 4325370; TMS PC 4286611568')
        self.assertEqual(row['kind'],'adsp_untranslated_pc');self.assertEqual(row['pc'],'0a93')
        self.assertEqual(row['opcode'],'41fffa');self.assertEqual(row['tms_pc'],'ff808070')
        row=describe_failure('ADSP translated opcode changed at PC 2707; expected 4325370; actual 4325354; TMS PC 4286611568')
        self.assertEqual(row['kind'],'adsp_opcode_changed');self.assertEqual(row['pc'],'0a93')
        self.assertEqual(row['opcode'],'41ffea');self.assertEqual(row['expected_opcode'],'41fffa')

    def test_generated_harness_checks_argument_count_before_any_optional_argument_access(self):
        from tools.mk2.replay import recovery_source
        source=recovery_source()
        self.assertLess(source.index('if(argc!=10)'),source.index('const uint64_t end='))
        self.assertLess(source.index('if(argc!=10)'),source.index('argv[8]'))

    def test_reader_authenticates_identity_and_rejects_incomplete_or_ambiguous_capture(self):
        from tools.mk2.replay import read_capture
        from tools.mk2.generate_video_irq import PROGRAM_SHA256
        seed=bytes(16384);digest=hashlib.sha256(seed).hexdigest()
        good=f'MK2_REPLAY_V1 {PROGRAM_SHA256} {digest} 2 1\nMK2_REPLAY_CMOS {seed.hex()}\nMK2_REPLAY_INPUT 100 4294967295\nMK2_REPLAY_INPUT 200 4294967279\nMK2_REPLAY_END\n'
        data=read_capture(good)
        neutral=f'MK2_REPLAY_V1 {PROGRAM_SHA256} {digest} 0 1\nMK2_REPLAY_CMOS {seed.hex()}\nMK2_REPLAY_END\n'
        self.assertEqual(read_capture(neutral)['inputs'],[])
        self.assertEqual(data['cmos'],seed);self.assertEqual(data['inputs'],[(100,4294967295),(200,4294967279)])
        self.assertEqual(read_capture('{"passed":true}\n'+good)['inputs'],data['inputs'])
        for bad in (good.replace(' 2 1\n',' 2 0\n'),good.replace(' 2 1\n',' 3 1\n'),
                    good.replace('INPUT 200','INPUT 99'),good.replace('INPUT 200','INPUT 100'),
                    good.replace(PROGRAM_SHA256,'0'*64),good.replace(digest,'0'*64),
                    good.replace('MK2_REPLAY_END\n',''),good+good,
                    good.replace('4294967279','4294967296')):
            with self.subTest(bad=bad[:160]),self.assertRaises(ValueError):read_capture(bad)

    def test_transitions_cmos_exception_and_bounded_overflow(self):
        from tools.mk2.replay import recovery_source
        generated=recovery_source()
        provider=generated.split('        size_t cursor=0;',1)[1].split('        auto current=',1)[0]
        source = r'''
#include "native/mk2/mk2_replay.hpp"
#include <sstream>
#include <stdexcept>
int main() {
    mk2::ReplayCapture capture;
    std::ostringstream empty;capture.Write(empty);if(!empty.str().empty())return 1;
    std::vector<uint8_t> cmos(16384);cmos[0]=0xab;cmos.back()=0xcd;
    capture.Start(std::string(64,'a'),std::string(64,'b'),cmos);
    capture.Observe(100,0xffffffff);capture.Observe(101,0xffffffff);
    try {capture.Observe(200,0xffffffef);throw std::runtime_error("actual failure");}
    catch(const std::runtime_error&) {}
    std::ostringstream out;capture.Write(out);const auto text=out.str();
    if(text.find("MK2_REPLAY_V1 "+std::string(64,'a')+" "+std::string(64,'b')+" 2 1\n")!=0 ||
       text.find("MK2_REPLAY_CMOS ab") == std::string::npos ||
       text.find("cd\nMK2_REPLAY_INPUT 100 4294967295\nMK2_REPLAY_INPUT 200 4294967279\nMK2_REPLAY_END\n")==std::string::npos ||
       text.find("INPUT 101")!=std::string::npos)return 2;
    capture.Observe(199,0);std::ostringstream backwards;capture.Write(backwards);
    if(backwards.str().find(" 2 0\n")==std::string::npos)return 3;
    mk2::ReplayCapture bounded;bounded.Start(std::string(64,'a'),std::string(64,'b'),cmos);
    for(unsigned n=0;n<100000;++n)bounded.Observe(n,n&1);
    std::ostringstream full;bounded.Write(full);
    if(full.str().find(" 4096 0\n")==std::string::npos || full.str().size()>250000)return 4;
    bool rejected=false;try {mk2::ReplayCapture bad;bad.Start("bad",std::string(64,'b'),cmos);}
    catch(const std::invalid_argument&){rejected=true;}
    if(!rejected)return 5;
    mk2::ReplayCapture duplicate;duplicate.Start(std::string(64,'a'),std::string(64,'b'),cmos);
    duplicate.Observe(100,1);duplicate.Observe(100,1);std::ostringstream same;duplicate.Write(same);
    if(same.str().find(" 1 1\n")==std::string::npos)return 6;
    duplicate.Observe(100,2);std::ostringstream different;duplicate.Write(different);
    if(different.str().find(" 1 0\n")==std::string::npos)return 7;
    mk2::ReplayCapture long_capture;long_capture.Start(std::string(64,'a'),std::string(64,'b'),cmos,16384);
    for(unsigned n=0;n<16384;++n)long_capture.Observe(n,n&1);
    std::ostringstream long_complete;long_capture.Write(long_complete);
    if(long_complete.str().find(" 16384 1\n")==std::string::npos)return 8;
    long_capture.Observe(16384,0);std::ostringstream long_overflow;long_capture.Write(long_overflow);
    if(long_overflow.str().find(" 16384 0\n")==std::string::npos)return 9;
    mk2::ReplayCapture runtime_capture;
    runtime_capture.Start(std::string(64,'a'),std::string(64,'b'),cmos,16384);
    std::vector<std::pair<uint64_t,uint32_t>> events;
    for(unsigned n=0;n<16384;++n)events.emplace_back(n+1,0xfffffffeu+(n&1));
    std::size_t cursor=0;REPLAY_PROVIDER
    if(provider(0)!=0xffffffffu)return 10;
    for(unsigned n=0;n<16384;++n)if(provider(n+1)!=events[n].second)return 11;
    std::ostringstream captured;runtime_capture.Write(captured);
    if(captured.str().find(" 16384 1\n")==std::string::npos)return 12;
}
'''.replace('REPLAY_PROVIDER',provider)
        with q.scratch_tree() as (scratch, cleanup):
            path=scratch/'capture.cpp';path.write_text(source)
            executable=scratch/'capture.exe'
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
            build=q.command([q.DEFAULT_CC,'-std=c++17','-Wall','-Wextra','-Werror',
                             '-I'+str(q.ROOT),path,'-o',executable],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=q.command([executable],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
