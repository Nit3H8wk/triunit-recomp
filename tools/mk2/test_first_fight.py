"""Measured ladder/fight suffixes require one closed endpoint and an actual prefix."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import run,batch_reference


class FirstFightTests(unittest.TestCase):
    def test_measured_ongoing_fight_keeps_all_cpu34_boundaries_and_original_inputs(self):
        from tools.mk2 import generate_first_fight as fight
        previous=fight.interval(76)['end_cpu34_sha256']
        for index,end,count in ((77,112088129,634733),(78,114030393,591386),
                                (79,116086770,630247),(80,118028828,582457),
                                (81,120088901,627229),(82,122028011,582868),(83,124084549,630058),(84,126026668,602777),
                                (85,128083937,620100),(86,130026066,594173),(87,132082620,639341),(88,134024907,606665),
                                (89,136081615,628940),(90,138023927,597678),(91,140080408,643873),(92,142022847,617955),(93,144079292,670769),(94,146024868,783122),(95,148081944,905329),(96,150023965,856509)):
            try:window=fight.interval(index)
            except ValueError as error:self.fail('Measured fight continuation is missing: '+str(error))
            self.assertEqual(window['start_cpu34_sha256'],previous)
            self.assertEqual((window['end'],window['cpu_rows']),(end,count))
            self.assertEqual(window['end_cpu34_cycle'],end)
            self.assertEqual(window['input_events'],20)
            previous=window['end_cpu34_sha256']

    def test_high_punch_branch_keeps_the_actual_prefix_and_physical_latches(self):
        from tools.mk2 import generate_first_fight as fight
        window=fight.high_punch_interval()
        self.assertEqual(window['start_cpu34_sha256'],fight.interval(85)['end_cpu34_sha256'])
        self.assertEqual((window['start'],window['end'],window['cpu_rows'],window['input_events']),
                         (128083937,130026078,592595,24))
        self.assertEqual(window['input_timeline'],[[2050931850,1,65535,0],[2052759775,1,65519,1],
                                                 [2058243550,0,65519,0],[2060071475,0,65535,1]])
        self.assertNotEqual(window['end_cpu34_sha256'],fight.interval(86)['end_cpu34_sha256'])

    def test_software_trap_uses_rom_vector_and_rejects_unauthenticated_program(self):
        from tools.mk2 import generate_first_fight as fight
        from tools.mk2 import generate_architectural as static
        rom=bytearray(0x100000)
        rom[0xffff8:0xffffc]=(0xff8045d0).to_bytes(4,'little')
        self.assertEqual(fight.SUCCESSORS[0xff804940],(0xff8045d0,))
        self.assertEqual(fight.SUCCESSORS[0xff805470],(0xff8045d0,))
        vector=int.from_bytes(rom[0xffff8:0xffffc],'little')
        for pc in (0xff804940,0xff805470):
            edges=fight.static_cfg.direct_targets(pc,16,'TRAP 1h',vector)
            self.assertEqual(edges,(0xff8045d0,))
            self.assertEqual(static.closure_targets(pc,16,'TRAP 1h',vector),(vector,pc+16))
            self.assertEqual(fight.shared.emit_instruction(pc,16,'TRAP 1h',(0x901,),
                             {vector,pc+16},{pc:edges}),f'o.TrapOne(0xff8045d0u,0x{pc+16:08x}u);')
        with self.assertRaisesRegex(ValueError,'authenticated ROM'):
            fight.generate(rom)

    def test_first_fight_rejects_missing_batch_or_mixed_endpoints_before_rom_io(self):
        for call in (lambda:run.run('check',Path('absent-roms'),first_fight_window=0),
                     lambda:run.run('reset',Path('absent-roms'),batch=True,first_fight_window=0,selection_window=0),
                     lambda:run.run('reset',Path('absent-roms'),batch=True,first_fight_window=0,start_release=True),
                     lambda:batch_reference.capture(Path('unused'),first_fight_window=0,selection_window=0)):
            try:
                with self.assertRaises(ValueError):call()
            except TypeError as error:self.fail('First-fight endpoint missing: '+str(error))

    def test_measured_intervals_keep_the_selection_prefix_and_reject_unknown_indices(self):
        try:
            from tools.mk2 import generate_first_fight as fight,generate_selection as selection
        except ImportError as error:self.fail('First-fight manifest missing: '+str(error))
        self.assertEqual(fight.measured['start_cpu34_sha256'],selection.measured['end_cpu34_sha256'])
        self.assertEqual((fight.interval(0)['start'],fight.interval(0)['end'],fight.interval(0)['cpu_rows']),
                         (30060282,31087223,463684))
        previous=30060282
        for index in range(97):
            window=fight.interval(index)
            self.assertEqual(window['start'],previous)
            self.assertGreater(window['end'],window['start'])
            self.assertEqual(window['end_cpu34_cycle'],window['end'])
            self.assertEqual(window['input_events'],20)
            previous=window['end']
        self.assertEqual(previous,150023965)
        self.assertEqual((fight.interval(70)['start'],fight.interval(70)['cpu_rows']),
                         (100091930,312310))
        self.assertEqual(fight.interval(69)['end'],100091930)
        self.assertEqual([(fight.interval(n)['end'],fight.interval(n)['cpu_rows']) for n in (71,72,73)],
                         [(102034236,339132),(103062155,326233),(104090574,319751)])
        self.assertEqual([(fight.interval(n)['end'],fight.interval(n)['cpu_rows']) for n in (74,75,76)],
                         [(105004473,278542),(106032616,320402),(110030700,1233062)])
        for index in (-1,97,True,'0',None):
            with self.assertRaises(ValueError):fight.interval(index)

    def test_cold_first_fight_admission_cannot_extend_any_board_or_machine_clock(self):
        from tools.mk2 import test_coin_pair
        test_coin_pair.CoinPairPrimitiveTests.compile_and_run(self,r'''
    const auto before=machine->dsp.Registers(),device=machine->dsp.DeviceState();
    const auto io=s.board.io;
    bool rejected=false;
    try { machine->AdmitFirstFight(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=before ||
       machine->dsp.DeviceState()!=device || s.board.io!=io || !s.board.input_events.empty()) return 1;
    rejected=false;
    try { machine->MainInstruction(30060283); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles()) return 2;
''')

    def test_generator_rejects_a_changed_program_before_emitting_fixed_blocks(self):
        try:
            from tools.mk2 import generate_first_fight as fight
        except ImportError as error:self.fail('First-fight generator missing: '+str(error))
        with self.assertRaises(ValueError):fight.generate(bytearray(0x100000))


if __name__=='__main__':unittest.main()
