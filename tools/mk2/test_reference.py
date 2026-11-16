"""False-positive controls for the finite MAME/native reset comparison."""
import copy
import hashlib
import json
from array import array
import importlib.util
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("mk2_reference", Path(__file__).with_name("reference.py"))
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class ReferenceTests(unittest.TestCase):
    def test_batch_fetch_widths_reject_mutation_and_keep_adjacent_rom_data(self):
        source = 0xff811e50
        for opcode, bits in ((0x0bc0, 48), (0x8621, 16), (0x482d, 16),
                             (0x8a22, 16), (0x4c4d, 16), (0xc0df, 16)):
            with self.subTest(opcode=hex(opcode)):
                self.assertEqual(reference.dispatcher_fetch_bits(opcode, False), bits)
                words = {source: opcode, source+16: 4, source+32: 0, source+bits: 0x1234}
                words[source] = opcode
                for offset in range(0, bits, 16):
                    pc = source + (16 if offset == 0 else bits)
                    self.assertIsNone(reference.dispatcher_bus_row(pc, source+offset,
                        words[source+offset], 1261260, 16, source, False, words.__getitem__))
                    with self.assertRaisesRegex(ValueError, "Unauthenticated"):
                        reference.dispatcher_bus_row(pc, source+offset, words[source+offset]^1,
                            1261260, 16, source, False, words.__getitem__)
                self.assertIsNotNone(reference.dispatcher_bus_row(source+bits, source+bits,
                    0x1234, 1261260, 16, source, False, words.__getitem__))

    def test_mame_debugger_diagnostics_reject_before_observation_parsing(self):
        for diagnostic in ("Invalid breakpoint number 0", "Invalid watchpoint number 2C", "Invalid command: bogus",
                           "Unknown command: bogus", "Error opening save file", "Error in expression: ar", "FATAL ERROR: debugger", "[LUA ERROR] callback"):
            with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(ValueError, "MAME diagnostic"):
                reference.parse_log("MAME v0.280\n" + diagnostic)

    def test_dispatcher_frontier_preserves_startup_and_rejects_unknown_fetch(self):
        self.assertEqual(reference.STARTUP_CYCLE, 818697)
        self.assertEqual(reference.DISPATCHER_CYCLE, 846457)
        self.assertTrue({0x3b2, *range(0x3b7, 0x3bf)} <= set(reference.DSP_PCS))
        self.assertEqual(reference.POINTS["dispatcher_ready"], 0xff80dd30)
        with self.assertRaisesRegex(ValueError, "Unknown dispatcher bus opcode"):
            reference.dispatcher_fetch_bits(0xffff, False)

    def test_dispatcher_raw_fetch_filter_checks_adjacent_operands_and_call_push(self):
        source = 0xff811710
        words = {source: 0x0d5f, source+16: 0xdae0, source+32: 0xff80, source+48: 0x8222}
        read = lambda address: words[address]
        for address in (source, source+16, source+32):
            self.assertIsNone(reference.dispatcher_bus_row(source+16, address, words[address], 818697, 16, source, False, read))
        row = reference.dispatcher_bus_row(source+16, 0x010fffd0, 0x1740, 818697, 16, source, True, read)
        self.assertEqual(row, [119, source, 0x010fffd0, 0x1740, 818697, 16])
        # The next opcode is adjacent to this CALL's final operand and remains data.
        self.assertIsNotNone(reference.dispatcher_bus_row(source+16, source+48, 0x8222, 818697, 16, source, False, read))
        for address, value, pc in ((source+16, 0, source+16), (source+32, 0xff80, source+32), (source, 0x0d5f, source+48)):
            with self.assertRaisesRegex(ValueError, "Unauthenticated dispatcher instruction fetch lane"):
                reference.dispatcher_bus_row(pc, address, value, 818697, 16, source, False, read)
        with self.assertRaisesRegex(ValueError, "Unexpected dispatcher fetched PC"):
            reference.dispatcher_bus_row(source+48, 0x010fffd0, 0x1740, 818697, 16, source, True, read)

    def test_dispatcher_dsj_displacement_is_fetched_before_pc_advance(self):
        source = 0xffa13cc0
        words = {source: 0x0d82, source+16: 0xfffc}
        self.assertIsNone(reference.dispatcher_bus_row(source+16, source+16, 0xfffc, 845000, 16, source, False, words.__getitem__))
        with self.assertRaisesRegex(ValueError, "Unauthenticated dispatcher instruction fetch lane"):
            reference.dispatcher_bus_row(source+32, source+16, 0xfffc, 845000, 16, source, False, words.__getitem__)

    def test_dispatcher_two_offset_fetches_use_their_original_stages(self):
        source = 0xff83acf0
        words = {source: 0xbaa8, source+16: 0x40, source+32: 0x100}
        for address, pc in ((source, source+16), (source+16, source+32), (source+32, source+48)):
            self.assertIsNone(reference.dispatcher_bus_row(pc, address, words[address], 846227, 16, source, False, words.__getitem__))
        with self.assertRaisesRegex(ValueError, "Unauthenticated dispatcher instruction fetch lane"):
            reference.dispatcher_bus_row(source+48, source+16, 0x40, 846227, 16, source, False, words.__getitem__)

    def test_task_resume_absolute_copy_authenticates_both_parameter_stages(self):
        source = 0xff816450
        words = {source: 0x05c0, source+16: 0xd070, source+32: 0x105, source+48: 0x3f0, source+64: 0x180}
        for address, pc in ((source, source+16), (source+16, source+48), (source+32, source+48),
                            (source+48, source+80), (source+64, source+80)):
            self.assertIsNone(reference.dispatcher_bus_row(pc, address, words[address], 914000, 16, source, False, words.__getitem__))
        self.assertEqual(reference.dispatcher_bus_row(source+48, 0x0105d070, 0x1234, 914000, 16, source, False, words.__getitem__)[0], 114)
        self.assertEqual(reference.dispatcher_bus_row(source+80, 0x018003f0, 0x1234, 914000, 16, source, True, words.__getitem__)[0], 119)
        with self.assertRaisesRegex(ValueError, "Unauthenticated dispatcher instruction fetch lane"):
            reference.dispatcher_bus_row(source+80, source+16, 0xd070, 914000, 16, source, False, words.__getitem__)
        with self.assertRaisesRegex(ValueError, "Unexpected dispatcher fetched PC"):
            reference.dispatcher_bus_row(source+80, 0x0105d070, 0x1234, 914000, 16, source, False, words.__getitem__)

    def test_every_located_opcode_class_keeps_its_exact_fetch_length(self):
        # Task queue (palette, long branches), task draw (TRAP/RETI, stack stages) and every other reached class:
        # the opcode is read from the user's program image at its locator, the length is the versioned fact.
        locators = json.loads((ROOT / "tools/mk2/dispatcher_opcode_locators.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "tools/mk2/roms-l31.json").read_text(encoding="utf-8"))
        opcode = reference.factory_opcode_reader(reference.factory_program_image(ROOT / "roms/mk2", manifest))
        checked = 0
        for bits, pcs in locators["bits"].items():
            for pc in pcs:
                value = opcode(int(pc, 16))
                self.assertIn(value, reference.DISPATCHER_INSTRUCTION_BITS)
                if value in (0x05c0, 0x0d3f, 0x0d5f): continue  # stage-specific fetch lengths, tested above
                for write in (False, True):
                    with self.subTest(pc=pc, write=write):
                        self.assertEqual(reference.dispatcher_fetch_bits(value, write), int(bits))
                checked += 1
        self.assertEqual(checked, len(reference.DISPATCHER_INSTRUCTION_BITS) - 3)

    def test_task_palette_observes_the_complete_measured_voice_tail(self):
        self.assertTrue(set(range(0x998, 0x99f)) <= set(reference.DSP_PCS))

    def test_dispatcher_native_self_read_is_rejected_before_fetch_subtraction(self):
        rows = [[114, 0xff811710, 0xff811740, 0x8222, 818697, 16]]
        with patch.object(reference, "factory_program_image", return_value=b""), patch.object(reference, "factory_opcode_reader", return_value=lambda pc: 0x0d5f):
            proof = reference.validate_dispatcher_native_data({"dispatcher_bus": rows}, None, None)
            self.assertEqual(proof, {"data_read_lanes": 1, "rom_data_read_lanes": 1, "self_overlapping_reads": 0})
            rows[0][2] -= 16
            with self.assertRaisesRegex(ValueError, "self-reads current instruction"):
                reference.validate_dispatcher_native_data({"dispatcher_bus": rows}, None, None)

    def test_task_resume_native_data_keeps_every_read_and_rejects_unknown_phase(self):
        rows = [[114, 0xff811710, 0xff811740, 0x8222, 846457, 16]]
        with patch.object(reference, "factory_program_image", return_value=b""), patch.object(reference, "factory_opcode_reader", return_value=lambda pc: 0x0d5f):
            for phase in ("task_resume", "task_queue", "task_palette", "task_draw"):
                self.assertEqual(reference.validate_dispatcher_native_data({phase + "_bus": rows}, None, None, phase=phase)["data_read_lanes"], 1)
                rows[0][2] -= 16
                with self.assertRaisesRegex(ValueError, "self-reads current instruction"):
                    reference.validate_dispatcher_native_data({phase + "_bus": rows}, None, None, phase=phase)
                rows[0][2] += 16
            with self.assertRaisesRegex(ValueError, "Unknown native data phase"):
                reference.validate_dispatcher_native_data({}, None, None, phase="typo")

    def test_factory_opcode_fetch_classes_and_authenticated_program_image(self):
        expected = {0x01c0: 16, 0x01e0: 16, 0x0960: 16, 0x098f: 32, 0x09af: 32, 0x099f: 32, 0x09bf: 32, 0x0d3f: 16, 0x0d5f: 16,
                    0x0780: 48, 0x0581: 48, 0x05a2: 48, 0x05e0: 48, 0x07a0: 48, 0x07e1: 48, 0x8c07: 16, 0x8e20: 16, 0x8ee0: 16,
                    0x8ee1: 16, 0x8ee2: 16, 0x8ee3: 16, 0x8ee4: 16, 0x8eee: 16, 0x9500: 16, 0x9501: 16,
                    0x9502: 16, 0x9503: 16, 0x9620: 16, 0x9704: 16, 0x9820: 16, 0x9201: 16, 0x8001: 16,
                    0xa20f: 16, 0xa22f: 16, 0x8684: 16, 0x8686: 16, 0x0fa0: 16}
        for opcode, bits in expected.items():
            with self.subTest(opcode=hex(opcode)): self.assertEqual(reference.factory_fetch_bits(opcode), bits)
        with self.assertRaisesRegex(ValueError, "Unknown factory bus opcode"): reference.factory_fetch_bits(0xffff)
        data = {"even": bytes([0xe0])*0x80000, "odd": bytes([0x05])*0x80000}
        image = bytes([0xe0, 0x05])*0x80000
        manifest = {"program_sha256": hashlib.sha256(image).hexdigest(), "roms": [
            {"region": "maincpu", "path": name, "offset_bytes": offset, "stride_bytes": 2,
             "sha256": hashlib.sha256(data[name]).hexdigest()} for offset, name in enumerate(data)]}
        with patch.object(Path, "read_bytes", autospec=True, side_effect=lambda path: data[path.name]):
            observed = reference.factory_program_image(Path("synthetic"), manifest)
            self.assertEqual(observed, image)
            self.assertEqual(reference.factory_opcode_reader(observed)(0xffa4d370), 0x05e0)
            for kind in ("lane_hash", "image_hash", "duplicate_lane", "path", "stride"):
                bad = copy.deepcopy(manifest)
                if kind == "lane_hash": bad["roms"][0]["sha256"] = "0"*64
                elif kind == "image_hash": bad["program_sha256"] = "0"*64
                elif kind == "duplicate_lane": bad["roms"][1]["offset_bytes"] = 0
                elif kind == "path": bad["roms"][0]["path"] = "../seed"
                else: bad["roms"][0]["stride_bytes"] = 4
                with self.subTest(invalid=kind), self.assertRaises(ValueError):
                    reference.factory_program_image(Path("synthetic"), bad)
        record = "MK2_FACTORY_READ FFA4D3A0 1480000 FFFF 305765 16 FFA4D370"
        with self.assertRaisesRegex(ValueError, "Missing authenticated factory opcode reader"):
            reference.parse_log(record)
        with self.assertRaisesRegex(ValueError, "Unknown factory bus opcode"):
            reference.parse_log(record, lambda pc: 0xffff)

    def test_capture_removes_transient_log_on_success_and_failure(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from tools.quality import run as quality
        with quality.scratch_tree() as (scratch, cleanup):
            log = scratch / "debug.log"
            log.write_text("small transport test")
            metadata = {}
            with patch.object(reference, "_capture", return_value=({}, metadata)):
                self.assertEqual(reference.capture(scratch, None, None, None), ({}, metadata))
            self.assertFalse(log.exists())
            self.assertTrue(metadata["debug_log_removed_before_return"])
            log.write_text("small failed transport test")
            with patch.object(reference, "_capture", side_effect=ValueError("failed capture")):
                with self.assertRaisesRegex(ValueError, "failed capture"):
                    reference.capture(scratch, None, None, None)
            self.assertFalse(log.exists())
        self.assertFalse(cleanup["exists_after"])

    def fixture(self):
        self.assertTrue(hasattr(reference, "compare"), "MK2 differential comparator is missing")
        # Synthetic register, write, display and RAM values at the Original PCs and cycles: the parser and the
        # comparison only carry them.
        cpu = {"pc": 0xff811150, "status": 0x815, "cycles": 232, "a": [0]*16, "b": [0]*15}
        cpu["a"][0], cpu["a"][15] = 0x1357, 0x01234560
        points = {name: copy.deepcopy(cpu) for name in reference.POINTS}
        points["status"].update(pc=0xff811180, cycles=237)
        points["status"]["a"][0] = 0x2468
        points["branch"].update(pc=0xff8111c0, cycles=241)
        points["branch"]["a"][0] = 0x1111
        points["sound"]["pc"] = reference.POINTS["sound"]
        points["scan"].update(pc=reference.POINTS["scan"], cycles=517)
        points["checked"].update(pc=reference.POINTS["checked"], cycles=626)
        points["stored"].update(pc=reference.POINTS["stored"], cycles=1793)
        for name, cycles in (("routine", 1817), ("restored", 1839), ("returned", 1871)):
            points[name].update(pc=reference.POINTS[name], cycles=cycles)
        for name, cycles in (("board_entry", 1874), ("board_configured", 2079), ("board_ready", 2089)):
            points[name].update(pc=reference.POINTS[name], cycles=cycles)
        for name, cycles in (("dsw_read", 2094), ("dsw_branch", 2098), ("dsw_taken", 2101),
                             ("reset_entry", 2112), ("ram_clear_entry", 2139), ("ram_cleared", 100444),
                             ("timer_first", 5931), ("timer_second", 6327), ("ram_midpoint", 51291),
                             ("after_clear", 100446), ("powerup_ready", 100455)):
            points[name].update(pc=reference.POINTS[name], cycles=cycles)
        points["record"].update(pc=reference.POINTS["record"], cycles=938)
        writes = [{"pc": pc, "address_bit": addr, "value": val, "cycle": t}
                  for pc, addr, val, t in [(0xff811000, 0x01b00000, 0x5a, 11),
                  (0xff811030, 0x0105bb10, 0x5a, 14), (0xff811090, 0x01d01030, 0xfe5a, 20),
                  (0xff811120, 0x01d01030, 0xff3c, 229),
                  (0xffa4bfe0, 0x010b95a0, 0x3c, 266), (0xffa4bc30, 0x010b95a0, 0x3d, 628)]]
        board_io = [0x100 + i for i in range(28)]
        board_writes = [[0xffa5fa90, 0x01a80010, 0, 1884, 16],
                        [0xffa5fac0, 0x01a80010, 0, 1887, 16],
                        [0xffa5faf0, 0xc00000b0, 0, 1890, 16],
                        [0xffa5fb40, 0x01b00000, 0x5a, 1895, 16]]
        board_writes += [[0xffa5fc00, 0xc0000000 + i*16, value, 1907 + i*6, 16]
                         for i, value in enumerate(board_io)]
        board_writes += [[0xffa5c1a0, 0x01a80010, 0, 2083, 16],
                         [0xffa5c1d0, 0x01a80010, 0, 2086, 16]]
        native = {"checkpoints": points, "writes": writes, "boot_words": [0x5a5a5a]*376,
                  "board_writes": board_writes, "board_io": board_io, "board_dma_command": 0,
                  "board_ram": [[a, 0] for a in reference.STORED_RAM_ADDRESSES]}
        native.update(boot_input_reads=[[0xffa5c200, 0x01600030, 0xfc7d, 2089, 16],
                                        [0xffa5c200, 0x01600040, 0xffff, 2089, 16]],
                      powerup_writes=[[0xffa5fc60, 0x0105bb10, 0x5a, 2103, 16],
                                      [0xffa5fc90, 0x01b00000, 0x5a, 2106, 16],
                                      [0xff811280, 0x010fffd0, 0xff8112b0, 2121, 32]] +
                                     [[0xff814e80, 0x01000000 + i*32, 0, 2139+i*3, 32] for i in range(32768)] +
                                     [[0xff8112e0, 0x010b1c30, 0x5e6f7a8b, 100449, 32]],
                      main_ram=[0]*65536, powerup_board_io=board_io.copy(), powerup_display=[0x21, 0x1111])
        native["main_ram"][45507:45509] = [0x7a8b, 0x5e6f]
        for name, cycles in (("video_palette_entry", 100479), ("video_palette_ready", 100571),
                             ("video_vram_entry", 100582), ("video_vram_mid", 198886),
                             ("video_vram_last", 297187), ("video_vram_cleared", 297191), ("video_ready", 297193)):
            points[name].update(pc=reference.POINTS[name], cycles=cycles)
        video_writes = [[pc, 0x01a80010, 0, 100456 + i * 3, 16]
                        for i, pc in enumerate((0xffa5a020, 0xffa5a050, 0xffa5a0a0, 0xffa5a0d0,
                                               0xffa5b170, 0xffa5b1a0))]
        video_writes += [[0xffa5b240, 0x01800000 + i*16, i, 100493+i*6, 16] for i in range(10)]
        video_writes += [[pc, 0x01a80010, 0, 100556 + i*3, 16]
                         for i, pc in enumerate((0xffa5b270, 0xffa5b2a0, 0xffa5b2d0, 0xffa5b300))]
        video_writes += [[0xffa59f00, i*32, 0, 100582+i*3, 32] for i in range(65536)]
        native.update(video_writes=video_writes, video_board_io=board_io.copy(), video_display=[0x21, 0x1111],
                      video_dma_command=0, dma_palette=0, video_main_ram=array("H", native["main_ram"]),
                      palette_ram=array("H", list(range(10)) + [0]*32758), vram=array("H", [0])*524288)
        for name, cycles in (("text_center_entry", 297201), ("text_centered", 297530),
                             ("text_renderer_entry", 297541), ("text_first_glyph", 297580),
                             ("text_last_glyph", 299440), ("text_rendered", 299625),
                             ("text_cmos_checked", 305358), ("text_ready", 305359)):
            points[name].update(pc=reference.POINTS[name], cycles=cycles)
        blits = []
        restarts = {0: 297670, 5: 298460, 7: 298856, 9: 299251}
        for i, cycles in enumerate((297580, 297736, 297892, 298096, 298220, 298424, 298548, 298752, 298956, 299112, 299316, 299440)):
            cpu = copy.deepcopy(points["text_first_glyph"])
            cpu.update(cycles=cycles, status=8)
            cpu["a"][0] = 0xffa401c8 + i*8
            blits.append(cpu)
            if i in restarts:
                cpu = copy.deepcopy(cpu)
                cpu.update(cycles=restarts[i], status=0x02000008)
                blits.append(cpu)
        points["text_first_glyph"], points["text_last_glyph"] = copy.deepcopy(blits[0]), copy.deepcopy(blits[-1])
        native.update(text_reads=[[0xffa593e0, 0xffa401c0, i, 297204, 16] for i in range(reference.TEXT_READ_COUNT)],
                      text_writes=[[0xffa592b0, 0x1e6b0, i, 297580, 16] for i in range(reference.TEXT_WRITE_COUNT)],
                      text_pixblt=blits, text_pixblt_dsp=[[0]*len(reference.DSP_REGISTERS) for _ in blits],
                      text_main_ram=array("H", native["main_ram"]), text_palette_ram=native["palette_ram"][:],
                      text_vram=native["vram"][:], text_board_io=board_io.copy(), text_display=[0x22, 0x2222],
                      text_dma_command=0, text_dma_palette=0)
        native["text_bus"] = [[114, *row] for row in native["text_reads"]] + [[119, *row] for row in native["text_writes"]]
        cold_ram = native["text_main_ram"] + array("H", [0])*196608
        native.update(factory_entry_main_ram=cold_ram, factory_main_ram=cold_ram[:], factory_cmos=array("H", [0])*8192,
                      factory_palette_ram=native["text_palette_ram"][:], factory_vram=native["text_vram"][:],
                      factory_board_io=board_io.copy(), factory_display=[0x23, 0x3333], factory_dma_command=0, factory_dma_palette=0,
                      factory_bus=[[114 if i % 2 == 0 else 119, 0xffa4d370, 0x01480000, 0xffff if i % 2 == 0 else 0xff00, 305765, 16]
                                   for i in range(reference.FACTORY_BUS_COUNT)])
        for name, pc in reference.FACTORY_POINTS.items():
            points[name].update(pc=pc, cycles=305359)
        points["factory_ready"]["cycles"] = 379387
        native.update(post_factory_bus=[[114 if i%2==0 else 119, 0xffa4d370, 0x01480000, i, 379400, 16] for i in range(6542)],
                      post_factory_main_ram=native["factory_main_ram"][:], post_factory_cmos=native["factory_cmos"][:],
                      post_factory_palette_ram=native["factory_palette_ram"][:], post_factory_vram=native["factory_vram"][:],
                      post_factory_board_io=native["factory_board_io"][:], post_factory_display=[0x24, 0x4444],
                      post_factory_dma_command=0, post_factory_dma_palette=0,
                      post_factory_pixblt=[copy.deepcopy(native["text_pixblt"][0]) for _ in range(74)],
                      post_factory_pixblt_dsp=[[0]*len(reference.DSP_REGISTERS) for _ in range(74)])
        for name, pc in reference.POST_FACTORY_POINTS.items(): points[name].update(pc=pc, cycles=399187)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["sound_command_" + suffix] = native["post_factory_" + suffix][:]
        native.update(sound_command_bus=[[119, 0xffa13c60, 0x01d01030, 0xff02 + i, 399230 + i, 16]
                                         for i in range(37)],
                      sound_command_dma_command=0, sound_command_dma_palette=0)
        for name, pc in reference.SOUND_COMMAND_POINTS.items(): points[name].update(pc=pc, cycles=399321)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["input_wait_" + suffix] = native["sound_command_" + suffix][:]
        native.update(input_wait_bus=[[114 if i%2 == 0 else 119, 0xffa592b0, 0x000e6000, i, 400462, 16]
                                      for i in range(reference.INPUT_WAIT_BUS_COUNT)],
                      input_wait_dma_command=0, input_wait_dma_palette=0,
                      input_wait_pixblt=[copy.deepcopy(native["text_pixblt"][0]) for _ in range(reference.INPUT_WAIT_PIXBLT_COUNT)],
                      input_wait_pixblt_dsp=[[0]*len(reference.DSP_REGISTERS) for _ in range(reference.INPUT_WAIT_PIXBLT_COUNT)])
        for name, pc in reference.INPUT_WAIT_POINTS.items(): points[name].update(pc=pc, cycles=400774)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["input_poll_" + suffix] = native["input_wait_" + suffix][:]
        native.update(input_poll_bus=[[114 if i%2==0 else 119, 0xffa5aef0, 0x01d01070, i, 407933, 16] for i in range(2828)],
                      input_poll_dma_command=0, input_poll_dma_palette=0,
                      input_poll_pixblt=[copy.deepcopy(native["text_pixblt"][0]) for _ in range(56)],
                      input_poll_pixblt_dsp=[[0]*len(reference.DSP_REGISTERS) for _ in range(56)])
        for name, pc in reference.INPUT_POLL_POINTS.items(): points[name].update(pc=pc, cycles=407967)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["input_idle_" + suffix] = native["input_poll_" + suffix][:]
        native.update(input_idle_bus=[[119 if i%9==0 else 114, 0xffa5aef0, 0x01d01070, i, 407967, 16]
                                      for i in range(reference.INPUT_IDLE_BUS_COUNT)],
                      input_idle_dma_command=0, input_idle_dma_palette=0)
        for name, pc in reference.INPUT_IDLE_POINTS.items(): points[name].update(pc=pc, cycles=reference.INPUT_IDLE_CYCLE)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["sport_wrap_" + suffix] = native["input_idle_" + suffix][:]
        native.update(sport_wrap_bus=[[119 if i%9==0 else 114, 0xffa5aef0, 0x01d01070, i, 460021, 16]
                                     for i in range(reference.SPORT_WRAP_BUS_COUNT)],
                      sport_wrap_dma_command=0, sport_wrap_dma_palette=0, sport_wrap_dma_registers=[0]*18)
        for name, pc in reference.SPORT_WRAP_POINTS.items(): points[name].update(pc=pc, cycles=reference.SPORT_WRAP_CYCLE)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["button_exit_" + suffix] = native["sport_wrap_" + suffix][:]
        native.update(button_exit_bus=[[119, 0xff80f290, (i % 65536) * 32, i & 0xffff, 583629, 16]
                                       for i in range(reference.BUTTON_EXIT_BUS_COUNT)],
                      button_exit_dma_command=0, button_exit_dma_palette=0, button_exit_dma_registers=[0]*18)
        for name, (pc, cycle) in reference.BUTTON_EXIT_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display"):
            native["video_irq_" + suffix] = native["button_exit_" + suffix][:]
        native.update(video_irq_bus=[[114 if i % 2 == 0 else 119, 0xff8089f0, 0x01068e70, i, 780300, 16]
                                     for i in range(reference.VIDEO_IRQ_BUS_COUNT)],
                      video_irq_dma_command=0, video_irq_dma_palette=0, video_irq_dma_registers=[0]*18)
        for name, (pc, cycle) in reference.VIDEO_IRQ_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers"):
            native["startup_" + suffix] = native["video_irq_" + suffix][:]
        native.update(startup_bus=[[114, 0xffa28f70, 0x0140c000, i, 816500, 16] for i in range(reference.STARTUP_BUS_COUNT)],
                      startup_dma_command=0, startup_dma_palette=0)
        for name, (pc, cycle) in reference.STARTUP_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers"):
            native["dispatcher_" + suffix] = native["startup_" + suffix][:]
        native.update(dispatcher_bus=[[114, 0xff80dd30, 0x01068ea0, i, 818697, 16] for i in range(reference.DISPATCHER_BUS_COUNT)],
                      dispatcher_dma_command=0, dispatcher_dma_palette=0)
        for name, (pc, cycle) in reference.DISPATCHER_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for name, (pc, cycle) in reference.TASK_RESUME_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for name, (pc, cycle) in reference.TASK_QUEUE_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers"):
            native["task_resume_" + suffix] = native["dispatcher_" + suffix][:]
        native.update(task_resume_dma_command=0, task_resume_dma_palette=0,
                      task_resume_bus=[[114, 0xff80dd30, 0x01068ea0, i & 0xffff, 846457, 16] for i in range(99699)])
        native.update(dispatcher_shiftreg=[0]*4096, task_resume_shiftreg=[0]*4096)
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers", "shiftreg"):
            native["task_queue_" + suffix] = native["task_resume_" + suffix][:]
        native.update(task_queue_bus=[[114, 0xff80dd30, 0x01068ea0, i, 1146279, 16] for i in range(reference.TASK_QUEUE_BUS_COUNT)],
                      task_queue_dma_command=0, task_queue_dma_palette=0)
        for name, (pc, cycle) in reference.TASK_PALETTE_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for key, value in list(native.items()):
            if key.startswith("task_queue_"): native[key.replace("task_queue_", "task_palette_", 1)] = copy.deepcopy(value)
        native["task_palette_bus"] = [[114, 0xff80dd30, 0x01068ea0, i & 0xffff, 1159587, 16] for i in range(reference.TASK_PALETTE_BUS_COUNT)]
        for name, (pc, cycle) in reference.TASK_DRAW_POINTS.items(): points[name].update(pc=pc, cycles=cycle)
        for key, value in list(native.items()):
            if key.startswith("task_palette_"): native[key.replace("task_palette_", "task_draw_", 1)] = copy.deepcopy(value)
        native["task_draw_bus"] = [[114, 0xff80dd30, 0x01068ea0, i & 0xffff, reference.TASK_PALETTE_CYCLE, 16] for i in range(reference.TASK_DRAW_BUS_COUNT)]
        native["task_draw_graphics_dma"] = [[1259256, 0xc382, 0], [1260496, 0xc382, 0], [1260517, 0x4382, 2]]
        native["task_draw_dma_deadline_subticks"] = 0
        for boundary in ("busy", "completed"):
            native["task_draw_dma_" + boundary + "_vram"] = [0]*524288
            native["task_draw_dma_" + boundary + "_registers"] = [0]*18
        observed = copy.deepcopy(native)
        return native, observed

    def test_task_queue_requires_every_image_latch_and_ordered_lane(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])
        for field in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers", "shiftreg"):
            key = "task_queue_" + field
            missing = dict(observed); del missing[key]
            with self.subTest(missing=key): self.assertFalse(reference.compare(native, missing)["passed"])
            short = dict(observed, **{key: observed[key][:-1]})
            with self.subTest(truncated=key): self.assertFalse(reference.compare(short, short)["passed"])
            changed = observed[key][:]; changed[-1] ^= 1
            with self.subTest(changed=key): self.assertFalse(reference.compare(native, dict(observed, **{key: changed}))["passed"])
        for key in ("task_queue_dma_command", "task_queue_dma_palette"):
            missing = dict(observed); del missing[key]
            with self.subTest(missing=key): self.assertFalse(reference.compare(native, missing)["passed"])
            with self.subTest(changed=key): self.assertFalse(reference.compare(native, dict(observed, **{key: 1}))["passed"])
        missing = dict(observed); del missing["task_queue_bus"]
        self.assertFalse(reference.compare(native, missing)["passed"])
        self.assertFalse(reference.compare(native, dict(observed, task_queue_bus=observed["task_queue_bus"][:-1]))["passed"])
        for column in range(6):
            rows = observed["task_queue_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(column=column): self.assertFalse(reference.compare(native, dict(observed, task_queue_bus=rows))["passed"])
        rows = observed["task_queue_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(observed, task_queue_bus=rows))["passed"])
        for name in reference.TASK_QUEUE_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(observed["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(point=name, field=field):
                    self.assertFalse(reference.compare(native, dict(observed, checkpoints=points))["passed"])

    def test_task_palette_requires_complete_images_latches_and_ordered_lanes(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers", "shiftreg", "bus", "dma_command", "dma_palette"):
            key = "task_palette_" + suffix
            missing = dict(observed); del missing[key]
            with self.subTest(missing=key): self.assertFalse(reference.compare(native, missing)["passed"])
            bad = dict(observed)
            if isinstance(observed[key], (list, array)):
                bad[key] = observed[key][:]
                if suffix == "bus": bad[key][-1] = bad[key][-1][:]; bad[key][-1][3] ^= 1
                else: bad[key][-1] ^= 1
            else: bad[key] ^= 1
            with self.subTest(changed=key): self.assertFalse(reference.compare(native, bad)["passed"])
        rows = observed["task_palette_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(observed, task_palette_bus=rows))["passed"])
        self.assertFalse(reference.compare(native, dict(observed, task_palette_bus=rows[:-1]))["passed"])
        for column in range(6):
            rows = observed["task_palette_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(column=column): self.assertFalse(reference.compare(native, dict(observed, task_palette_bus=rows))["passed"])
        for name in reference.TASK_PALETTE_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(observed["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(point=name, field=field):
                    self.assertFalse(reference.compare(native, dict(observed, checkpoints=points))["passed"])

    def test_task_draw_requires_its_own_images_and_preserves_palette_history(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])
        for phase in ("task_palette", "task_draw"):
            for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers", "shiftreg", "bus", "dma_command", "dma_palette"):
                key = phase + "_" + suffix
                missing = dict(observed); missing.pop(key, None)
                with self.subTest(missing=key): self.assertFalse(reference.compare(native, missing)["passed"])
                bad = dict(observed)
                if isinstance(observed[key], (list, array)):
                    bad[key] = observed[key][:]
                    if suffix == "bus": bad[key][-1] = bad[key][-1][:]; bad[key][-1][3] ^= 1
                    else: bad[key][-1] ^= 1
                    short = dict(observed, **{key: observed[key][:-1]})
                    with self.subTest(truncated=key): self.assertFalse(reference.compare(short, short)["passed"])
                else: bad[key] ^= 1
                with self.subTest(changed=key): self.assertFalse(reference.compare(native, bad)["passed"])
        rows = observed["task_draw_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(observed, task_draw_bus=rows))["passed"])
        for column in range(6):
            rows = observed["task_draw_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(column=column): self.assertFalse(reference.compare(native, dict(observed, task_draw_bus=rows))["passed"])
        for name in reference.TASK_DRAW_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(observed["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(point=name, field=field):
                    self.assertFalse(reference.compare(native, dict(observed, checkpoints=points))["passed"])

    def test_task_draw_graphics_dma_requires_the_actual_busy_irq_transition(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])
        missing = dict(observed); del missing["task_draw_graphics_dma"]
        self.assertFalse(reference.compare(native, missing)["passed"])
        self.assertFalse(reference.compare(dict(native, task_draw_dma_deadline_subticks=1), observed)["passed"])
        for boundary in ("busy", "completed"):
            for suffix in ("vram", "registers"):
                key = "task_draw_dma_" + boundary + "_" + suffix
                missing = dict(observed); del missing[key]
                with self.subTest(missing=key): self.assertFalse(reference.compare(native, missing)["passed"])
                short = dict(observed, **{key: observed[key][:-1]})
                with self.subTest(truncated=key): self.assertFalse(reference.compare(short, short)["passed"])
                bad = observed[key][:]; bad[-1] ^= 1
                with self.subTest(changed=key): self.assertFalse(reference.compare(native, dict(observed, **{key: bad}))["passed"])
        short = dict(native, task_draw_graphics_dma=native["task_draw_graphics_dma"][:-1])
        self.assertFalse(reference.compare(short, short)["passed"])
        for row in range(3):
            for column in range(3):
                bad = copy.deepcopy(observed["task_draw_graphics_dma"]); bad[row][column] ^= 1
                with self.subTest(row=row, column=column):
                    self.assertFalse(reference.compare(native, dict(observed, task_draw_graphics_dma=bad))["passed"])

    def test_shift_register_snapshots_require_all4096_words_at_both_endpoints(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])
        for field in ("dispatcher_shiftreg", "task_resume_shiftreg"):
            missing = dict(native); del missing[field]
            for left, right in ((missing, observed), (native, missing), (missing, missing)):
                with self.subTest(missing=field): self.assertFalse(reference.compare(left, right)["passed"])
            short = dict(native, **{field: native[field][:-1]})
            with self.subTest(truncated=field): self.assertFalse(reference.compare(short, short)["passed"])
            for index in (0, 512, 1023, 1024, 2048, 3072, 4095):
                values = observed[field][:]; values[index] ^= 1
                with self.subTest(word=field, index=index):
                    self.assertFalse(reference.compare(native, dict(observed, **{field: values}))["passed"])

    def test_task_resume_requires_every_complete_memory_and_latch(self):
        native, _ = self.fixture()
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers"):
            native["task_resume_" + suffix] = native["dispatcher_" + suffix][:]
        native.update(task_resume_dma_command=0, task_resume_dma_palette=0,
                      task_resume_bus=[[114, 0xff80dd30, 0x01068ea0, i & 0xffff, 846457, 16] for i in range(99699)])
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("task_resume_")]:
            bad = dict(native); del bad[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, bad)["passed"])
            bad = dict(native)
            if isinstance(native[field], int): bad[field] ^= 1
            else:
                bad[field] = copy.deepcopy(native[field])
                if isinstance(bad[field][-1], list): bad[field][-1][-1] ^= 1
                else: bad[field][-1] ^= 1
            with self.subTest(changed=field): self.assertFalse(reference.compare(native, bad)["passed"])
        for column in range(6):
            rows = native["task_resume_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(lane_column=column): self.assertFalse(reference.compare(native, dict(native, task_resume_bus=rows))["passed"])
        rows = native["task_resume_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, task_resume_bus=rows))["passed"])
        self.assertFalse(reference.compare(native, dict(native, task_resume_bus=rows[:-1]))["passed"])
        for name in reference.TASK_RESUME_POINTS:
            points = dict(native["checkpoints"]); del points[name]
            with self.subTest(missing_checkpoint=name): self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_dispatcher_requires_full_memory_ordered_lanes_and_every_checkpoint(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])
        for field in [key for key in native if key.startswith("dispatcher_")]:
            with self.subTest(missing=field):
                self.assertFalse(reference.compare(native, {key: value for key, value in observed.items() if key != field})["passed"])
            value = native[field]
            if not isinstance(value, int):
                with self.subTest(truncated=field): self.assertFalse(reference.compare(native, dict(observed, **{field: value[:-1]}))["passed"])
            else:
                with self.subTest(scalar=field): self.assertFalse(reference.compare(native, dict(observed, **{field: value ^ 1}))["passed"])
        for field in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers"):
            key = "dispatcher_" + field
            values = observed[key][:]; values[-1] ^= 1
            with self.subTest(word=key): self.assertFalse(reference.compare(native, dict(observed, **{key: values}))["passed"])
        for column in range(6):
            rows = observed["dispatcher_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(lane_column=column): self.assertFalse(reference.compare(native, dict(observed, dispatcher_bus=rows))["passed"])
        rows = observed["dispatcher_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(observed, dispatcher_bus=rows))["passed"])
        for name in reference.DISPATCHER_POINTS:
            checkpoints = dict(observed["checkpoints"]); del checkpoints[name]
            with self.subTest(checkpoint=name): self.assertFalse(reference.compare(native, dict(observed, checkpoints=checkpoints))["passed"])

    def test_startup_requires_every_memory_bus_lane_and_checkpoint(self):
        native, _ = self.fixture()
        for suffix in ("main_ram", "cmos", "palette_ram", "vram", "board_io", "display", "dma_registers"):
            native["startup_" + suffix] = native["video_irq_" + suffix][:]
        native.update(startup_bus=[[114, 0xffa28f70, 0x0140c000, i, 816500, 16] for i in range(reference.STARTUP_BUS_COUNT)],
                      startup_dma_command=0, startup_dma_palette=0)
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("startup_")]:
            bad = dict(native); del bad[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, bad)["passed"])
            bad = dict(native)
            if isinstance(native[field], int): bad[field] ^= 1
            elif field == "startup_bus":
                bad[field] = [row[:] for row in native[field]]; bad[field][-1][-1] ^= 1
            else: bad[field] = native[field][:]; bad[field][-1] ^= 1
            with self.subTest(mutation=field): self.assertFalse(reference.compare(native, bad)["passed"])
        for column in range(6):
            rows = native["startup_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(bus_column=column): self.assertFalse(reference.compare(native, dict(native, startup_bus=rows))["passed"])
        rows = native["startup_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, startup_bus=rows))["passed"])
        for name in reference.STARTUP_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(native["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(checkpoint=name, field=field):
                    self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_video_irq_requires_every_new_memory_bus_lane_and_checkpoint(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("video_irq_")]:
            observed = dict(native); del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("video_irq_main_ram", "video_irq_cmos", "video_irq_palette_ram", "video_irq_vram",
                      "video_irq_board_io", "video_irq_display", "video_irq_dma_registers"):
            observed = dict(native, **{field: native[field][:]}); observed[field][-1] ^= 1
            with self.subTest(mutation=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = native["video_irq_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(bus_column=column): self.assertFalse(reference.compare(native, dict(native, video_irq_bus=rows))["passed"])
        for field in ("video_irq_dma_command", "video_irq_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        rows = native["video_irq_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, video_irq_bus=rows))["passed"])
        for name in reference.VIDEO_IRQ_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(native["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(checkpoint=name, field=field):
                    self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_video_irq_fetch_provenance_checks_dual_absolute_and_interrupts(self):
        for opcode in (0x8201, 0x8202, 0x8222, 0x9020, 0x9023, 0x9043, 0x91c1, 0x9a43, 0xa023, 0x0d60, 0x0940):
            self.assertEqual(reference.video_irq_fetch_bits(opcode, False), 16)
        self.assertEqual(reference.video_irq_fetch_bits(0xb041, False), 32)
        self.assertEqual(reference.video_irq_fetch_bits(0xb422, True), 32)
        self.assertEqual(reference.video_irq_fetch_bits(0x05c0, False), 48)
        self.assertEqual(reference.video_irq_fetch_bits(0x05c0, True), 80)
        with self.assertRaisesRegex(ValueError, "Unknown factory bus opcode"):
            reference.video_irq_fetch_bits(0xffff, False)
        for kind, post in (("READ", "FF8164A0"), ("WRITE", "FF816480")):
            record = f"MK2_VIDEO_IRQ_{kind} {post} 105D070 0 815774 16 FF816450"
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Unexpected factory fetched PC"):
                reference.parse_log(record, lambda pc: 0x05c0)

    def test_startup_mmtm_a2_retains_the_original_mask_fetch(self):
        self.assertEqual(reference.video_irq_fetch_bits(0x0982, True), 32)
        self.assertEqual(reference.video_irq_fetch_bits(0x0982, False), 32)
        self.assertEqual(reference.video_irq_fetch_bits(0x8ba0, True), 16)
        self.assertEqual(reference.video_irq_fetch_bits(0x8ba0, False), 16)
        for opcode in (0x820d, 0xa182, 0xa022):
            for write in (False, True):
                self.assertEqual(reference.video_irq_fetch_bits(opcode, write), 16)

    def test_button_exit_preserves_every_memory_bus_lane_and_checkpoint(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("button_exit_")]:
            observed = dict(native); del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("button_exit_main_ram", "button_exit_cmos", "button_exit_palette_ram", "button_exit_vram",
                      "button_exit_board_io", "button_exit_display", "button_exit_dma_registers"):
            observed = dict(native); observed[field] = native[field][:]; observed[field][-1] ^= 1
            with self.subTest(changed=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = native["button_exit_bus"][:]; rows[-1] = rows[-1][:]; rows[-1][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, button_exit_bus=rows))["passed"])
        rows = native["button_exit_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, button_exit_bus=rows))["passed"])
        for field in ("button_exit_dma_command", "button_exit_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        for name in reference.BUTTON_EXIT_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(native["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(checkpoint=name, field=field):
                    self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_sport_wrap_observations_are_required_and_fully_compared(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("sport_wrap_")]:
            observed = dict(native); del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("sport_wrap_main_ram", "sport_wrap_cmos", "sport_wrap_palette_ram", "sport_wrap_vram",
                      "sport_wrap_board_io", "sport_wrap_display", "sport_wrap_dma_registers"):
            observed = dict(native, **{field: native[field][:]}); observed[field][-1] ^= 1
            with self.subTest(word=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = copy.deepcopy(native["sport_wrap_bus"]); rows[-1][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, sport_wrap_bus=rows))["passed"])
        rows = native["sport_wrap_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, sport_wrap_bus=rows))["passed"])
        for field in ("sport_wrap_dma_command", "sport_wrap_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        for name in reference.SPORT_WRAP_POINTS:
            points = copy.deepcopy(native["checkpoints"]); points[name]["cycles"] ^= 1
            self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_input_idle_observations_are_required_and_fully_compared(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("input_idle_")]:
            observed = dict(native); del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("input_idle_main_ram", "input_idle_cmos", "input_idle_palette_ram", "input_idle_vram",
                      "input_idle_board_io", "input_idle_display"):
            observed = dict(native, **{field: native[field][:]}); observed[field][-1] ^= 1
            with self.subTest(word=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = copy.deepcopy(native["input_idle_bus"]); rows[-1][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, input_idle_bus=rows))["passed"])
        rows = native["input_idle_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, input_idle_bus=rows))["passed"])
        for field in ("input_idle_dma_command", "input_idle_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        for name in reference.INPUT_IDLE_POINTS:
            points = copy.deepcopy(native["checkpoints"]); points[name]["cycles"] ^= 1
            self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_input_poll_observations_are_required_and_fully_compared(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("input_poll_")]:
            observed = dict(native); del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("input_poll_main_ram", "input_poll_cmos", "input_poll_palette_ram", "input_poll_vram",
                      "input_poll_board_io", "input_poll_display"):
            observed = dict(native, **{field: native[field][:]}); observed[field][-1] ^= 1
            with self.subTest(word=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = copy.deepcopy(native["input_poll_bus"]); rows[-1][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, input_poll_bus=rows))["passed"])
        rows = native["input_poll_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, input_poll_bus=rows))["passed"])
        for field in ("input_poll_dma_command", "input_poll_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        for field in ("pc", "status", "cycles", "a", "b"):
            rows = copy.deepcopy(native["input_poll_pixblt"])
            if field in ("a", "b"): rows[-1][field][-1] ^= 1
            else: rows[-1][field] ^= 1
            with self.subTest(pix_field=field):
                self.assertFalse(reference.compare(native, dict(native, input_poll_pixblt=rows))["passed"])
        for column in range(len(reference.DSP_REGISTERS)):
            rows = copy.deepcopy(native["input_poll_pixblt_dsp"]); rows[-1][column] ^= 1
            with self.subTest(dsp_column=column):
                self.assertEqual(reference.compare(native, dict(native, input_poll_pixblt_dsp=rows))["passed"], column == 1)
        for name in reference.INPUT_POLL_POINTS:
            points = copy.deepcopy(native["checkpoints"]); points[name]["cycles"] ^= 1
            with self.subTest(point=name):
                self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_input_wait_requires_and_compares_bus_memories_and_pixblt(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("input_wait_")]:
            observed = dict(native); del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("input_wait_main_ram", "input_wait_cmos", "input_wait_palette_ram", "input_wait_vram",
                      "input_wait_board_io", "input_wait_display"):
            observed = dict(native, **{field: native[field][:]}); observed[field][-1] ^= 1
            with self.subTest(word=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = copy.deepcopy(native["input_wait_bus"]); rows[-1][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, input_wait_bus=rows))["passed"])
        rows = native["input_wait_bus"][:]; rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, input_wait_bus=rows))["passed"])
        for field in ("input_wait_dma_command", "input_wait_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        for field in ("pc", "status", "cycles", "a", "b"):
            rows = copy.deepcopy(native["input_wait_pixblt"])
            if field in ("a", "b"): rows[-1][field][-1] ^= 1
            else: rows[-1][field] ^= 1
            with self.subTest(pix_field=field):
                self.assertFalse(reference.compare(native, dict(native, input_wait_pixblt=rows))["passed"])
        for column in range(len(reference.DSP_REGISTERS)):
            rows = copy.deepcopy(native["input_wait_pixblt_dsp"]); rows[-1][column] ^= 1
            with self.subTest(dsp_column=column):
                self.assertEqual(reference.compare(native, dict(native, input_wait_pixblt_dsp=rows))["passed"], column == 1)
        for name in reference.INPUT_WAIT_POINTS:
            points = copy.deepcopy(native["checkpoints"]); points[name]["cycles"] ^= 1
            with self.subTest(point=name): self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_sound_command_requires_and_compares_every_new_observation(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in [key for key in native if key.startswith("sound_command_")]:
            observed = dict(native)
            del observed[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            if field == "sound_command_bus": observed[field][-1][3] ^= 1
            elif isinstance(observed[field], int): observed[field] ^= 1
            else: observed[field][-1] ^= 1
            with self.subTest(mutation=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = copy.deepcopy(native["sound_command_bus"]); rows[-1][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, sound_command_bus=rows))["passed"])
        rows = native["sound_command_bus"].copy(); rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, sound_command_bus=rows))["passed"])
        for name in reference.SOUND_COMMAND_POINTS:
            for field in ("pc", "status", "cycles", "a", "b"):
                points = copy.deepcopy(native["checkpoints"])
                if field in ("a", "b"): points[name][field][-1] ^= 1
                else: points[name][field] ^= 1
                with self.subTest(checkpoint=name, field=field):
                    self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_capture_preserves_dsp_observers_until_sound_command_return(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from tools.quality import run as quality
        with quality.scratch_tree() as (scratch, cleanup):
            with patch.object(reference, "factory_program_image", return_value=bytes(0x100000)), \
                    patch.object(quality, "command", side_effect=RuntimeError("execution intentionally skipped")):
                with self.assertRaisesRegex(RuntimeError, "intentionally skipped"):
                    reference.capture(scratch, Path("unused"), Path("unused"), {"roms": []})
            script = (scratch / "reset.cmd").read_text()
            video_script = (scratch / "video.lua").read_text()
            self.assertIn('local shiftreg = bind(main, "m_shiftreg")', video_script)
            self.assertIn("assert(shiftreg.size == 2 and shiftreg.count == 4096)", video_script)
            self.assertIn('if prefix == "dispatcher_" or prefix == "task_resume_" or prefix == "task_queue_" or prefix == "task_palette_" or prefix == "task_draw_" then', video_script)
            self.assertIn('io.open(prefix .. "shiftreg.bin", "wb")', video_script)
            self.assertIn('for index = 0, 4095 do assert(file:write(string.pack("<I2", assert(shiftreg:read(index))))) end', video_script)
            dsp_addresses = [line.split(":dcs:dcs,", 1)[0].removeprefix("bpset ")
                             for line in script.splitlines() if "MK2_DSP_BEGIN" in line]
            self.assertEqual([int(address, 16) for address in dsp_addresses], reference.DSP_PCS + [pc for pc, _ in reference.DSP_IRQ_HOOKS])
            self.assertTrue(all(address[0].isdigit() for address in dsp_addresses))
            serial_hook = next(line for line in script.splitlines() if line.startswith("bpset 0829:dcs:dcs,"))
            self.assertIn('printf "MK2_DSP_BEGIN %X\\n",:dcs:dcs.pd@829;symlist :dcs:dcs', serial_hook)
            self.assertTrue(all(f"{address:04x}" in dsp_addresses for address in (*range(0xa0, 0xaa), *range(0xb0, 0xba))))

            for pc, cycle in ((0x131, 158527), (0x132, 158528)):
                hooks = [line for line in script.splitlines() if line.startswith(f"bpset {pc:04x}:dcs:dcs,")]
                self.assertEqual(len(hooks), 4 if pc == 0x131 else 5)
                self.assertIn(f"totalcycles!={cycle:x}", hooks[0])
                self.assertIn(f"totalcycles=={cycle:x}", hooks[1])
                self.assertIn("MK2_DSP_IRQ1", hooks[1]); self.assertIn("w@1a80000", hooks[1])
            idle = next(line for line in script.splitlines() if 'MK2_CPU input_idle_ready ' in line)
            self.assertNotIn(";wpclear;", idle); self.assertNotIn("quit", idle)
            self.assertIn("save input_idle_pm.bin", idle)
            self.assertIn("MK2_SPORT_WRAP_READ", idle)
            self.assertNotIn('\\"', idle)
            post = next(line for line in script.splitlines() if 'MK2_CPU post_factory_ready ' in line)
            sound = next(line for line in script.splitlines() if 'MK2_CPU sound_command_ready ' in line)
            wrap = next(line for line in script.splitlines() if 'MK2_CPU sport_wrap_ready ' in line)
            button_final = next(line for line in script.splitlines() if 'MK2_CPU button_exit_ready ' in line)
            video_final = next(line for line in script.splitlines() if 'MK2_CPU video_irq_ready ' in line)
            startup_final = next(line for line in script.splitlines() if 'MK2_CPU startup_ready ' in line)
            dispatcher_final = next(line for line in script.splitlines() if 'MK2_CPU dispatcher_ready ' in line)
            resume_final = next(line for line in script.splitlines() if 'MK2_CPU task_resume_ready ' in line)
            final = next(line for line in script.splitlines() if 'MK2_CPU task_queue_ready ' in line)
            self.assertNotIn("quit", final)
            self.assertIn("MK2_TASK_PALETTE_READ", final)
            palette_final = next(line for line in script.splitlines() if 'MK2_CPU task_palette_ready ' in line)
            self.assertIn("MK2_TASK_PALETTE_BOUNDARY", palette_final)
            self.assertIn("save task_palette_pm.bin", palette_final)
            self.assertNotIn("quit", palette_final)
            self.assertIn(";wpclear 32,33;", palette_final)
            self.assertIn("MK2_TASK_DRAW_READ", palette_final)
            draw_final = next(line for line in script.splitlines() if 'MK2_CPU task_draw_ready ' in line)
            self.assertIn("MK2_TASK_DRAW_BOUNDARY", draw_final)
            self.assertIn("save task_draw_pm.bin", draw_final)
            self.assertIn(";wpclear;", draw_final)
            self.assertIn(";quit", draw_final)
            for name in ("task_draw_dma_started", "task_draw_dma_busy", "task_draw_dma_completed"):
                dma_point = next(line for line in script.splitlines() if "MK2_CPU " + name + " " in line)
                self.assertIn('totalcycles,w@1a80010,w@c0000120', dma_point)
            self.assertIn(";wpclear 1a,1b;", post)
            self.assertNotIn(";wpclear;", post)
            self.assertNotIn("quit", post)
            self.assertNotIn("save pm.bin", post)
            self.assertIn("save post_factory_pm.bin,0:dcs:dcs,400", post)
            self.assertIn("saved post_factory_dm.bin,3800:dcs:dcs,200", post)
            self.assertIn("saved post_factory_control.bin,3fe0:dcs:dcs,20", post)
            self.assertIn(";wpclear 1c,1d;", sound)
            self.assertNotIn(";wpclear;", sound)
            self.assertNotIn("quit", sound)
            for key in ("pm", "dm", "control"):
                self.assertIn("sound_command_" + key + ".bin", sound)
            self.assertIn(";wpclear 30,31;", final)
            self.assertIn("MK2_DISPATCHER_BOUNDARY", dispatcher_final)
            self.assertIn("MK2_DISPATCHER_DCS_CONTROL", dispatcher_final)
            self.assertIn("save dispatcher_pm.bin", dispatcher_final)
            self.assertNotIn("quit", dispatcher_final)
            self.assertIn(";wpclear 2c,2d;", dispatcher_final)
            self.assertIn("MK2_TASK_RESUME_READ", dispatcher_final)
            self.assertIn("MK2_TASK_RESUME_BOUNDARY", resume_final)
            self.assertIn("save pm.bin", resume_final)
            self.assertIn("saved dm.bin", resume_final)
            self.assertIn("saved control.bin", resume_final)
            self.assertNotIn(";wpclear;", resume_final)
            self.assertNotIn("quit", resume_final)
            self.assertIn(";wpclear 2e,2f;", resume_final)
            self.assertIn("MK2_TASK_QUEUE_READ", resume_final)
            self.assertIn("MK2_TASK_QUEUE_BOUNDARY", final)
            self.assertIn("save task_queue_pm.bin", final)
            self.assertIn("saved task_queue_dm.bin", final)
            self.assertIn("saved task_queue_control.bin", final)
            self.assertEqual(script.count(";quit"), 1)
            self.assertIn(f'totalcycles=={reference.TASK_RESUME_CYCLE:x}', resume_final)
            self.assertIn(f'totalcycles=={reference.TASK_QUEUE_CYCLE:x}', final)
            self.assertIn('MK2_STARTUP_BOUNDARY', startup_final)
            self.assertIn(';wpclear 2a,2b;', startup_final)
            self.assertNotIn('quit', startup_final)
            self.assertNotIn('quit', video_final)
            self.assertIn(';wpclear 28,29;', video_final)
            self.assertIn('MK2_VIDEO_IRQ_BOUNDARY', video_final)
            self.assertIn('MK2_VIDEO_IRQ_DCS_CONTROL', video_final)
            self.assertIn('MK2_STARTUP_READ', video_final)
            for suffix in ("pm", "dm", "control", "external_pm", "external_dm"):
                self.assertIn("video_irq_" + suffix + ".bin", video_final)
            self.assertNotIn('quit', button_final)
            self.assertIn(';wpclear 26,27;', button_final)
            self.assertIn('MK2_BUTTON_EXIT_BOUNDARY', button_final)
            self.assertIn('MK2_BUTTON_EXIT_DCS_CONTROL', button_final)
            self.assertIn('MK2_VIDEO_IRQ_READ', button_final)
            self.assertIn('wpaddr>=fffffea0', button_final)
            self.assertNotIn("quit", wrap)
            self.assertNotIn("save pm.bin", wrap)
            self.assertIn("save sport_wrap_pm.bin", wrap)
            self.assertIn("MK2_SPORT_WRAP_DCS_CONTROL", wrap)
            self.assertIn("MK2_CPU button_exit_pressed", wrap)
            self.assertIn("MK2_BUTTON_EXIT_READ", wrap)
            self.assertIn(";wpclear 24,25;", wrap)
            self.assertIn("w@1a80000", wrap)
            for name in reference.BUTTON_DSP_POINTS:
                point = next(line for line in script.splitlines() if f'MK2_CPU {name} ' in line)
                for suffix in ("pm", "dm", "control", "external_pm", "external_dm"):
                    self.assertIn(name + "_" + suffix + ".bin", point)
            lua = (scratch / "video.lua").read_text()
            self.assertIn('input_port.fields["P1 High Punch"]', lua)
            self.assertIn("button:set_value(requested)", lua)
            self.assertIn("emu.add_machine_frame_notifier", lua)
            self.assertIn("assert(input_frame_subscription)", lua)
            self.assertIn("input_port:read()", lua)
            self.assertIn('if machine.debugger.execution_state ~= "run" then return end', lua)
            self.assertNotIn("return data", lua)
            pix = next(line for line in script.splitlines() if 'printf "MK2_INPUT_WAIT_PIXBLT ' in line)
            self.assertIn(f'totalcycles<{400774:x}', pix)
            old_endpoint = next(line for line in script.splitlines() if 'MK2_CPU input_wait_ready ' in line)
            self.assertIn("MK2_INPUT_POLL_PIXBLT", old_endpoint)
            self.assertIn(";wpclear 1e,1f;", old_endpoint)
            self.assertNotIn("quit", old_endpoint)
            poll_hook = next(line for line in script.splitlines() if line.startswith(f'bpset ffa592b0,totalcycles>{400774:x},'))
            self.assertIn("MK2_DSP_INPUT_POLL_PIXBLT", poll_hook)
            for pc in (4, *range(0x16e, 0x177)):
                self.assertIn(f"bpset {pc:04x}:dcs:dcs,", script)
            self.assertIn('[0xffa5acc0] = "sound_command_"', (scratch / "video.lua").read_text())
            self.assertIn('[0xffa592b0] = "input_wait_"', (scratch / "video.lua").read_text())
        self.assertFalse(cleanup["exists_after"])

    def test_post_factory_complete_bus_memories_and_pixblt_are_compared(self):
        native, _ = self.fixture()
        self.assertTrue(reference.compare(native, native)["passed"])
        for field in ("post_factory_bus", "post_factory_main_ram", "post_factory_cmos", "post_factory_palette_ram",
                      "post_factory_vram", "post_factory_board_io", "post_factory_display", "post_factory_dma_command",
                      "post_factory_dma_palette", "post_factory_pixblt", "post_factory_pixblt_dsp"):
            observed = dict(native)
            observed.pop(field)
            with self.subTest(missing=field): self.assertFalse(reference.compare(native, observed)["passed"])

    def test_post_factory_mutations_and_bus_order_are_detected(self):
        native, _ = self.fixture()
        for field in ("post_factory_main_ram", "post_factory_cmos", "post_factory_palette_ram", "post_factory_vram",
                      "post_factory_board_io", "post_factory_display"):
            observed = dict(native, **{field: native[field][:]})
            observed[field][-1] ^= 1
            with self.subTest(field=field): self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            rows = native["post_factory_bus"].copy()
            rows[0] = rows[0].copy(); rows[0][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, dict(native, post_factory_bus=rows))["passed"])
        rows = native["post_factory_bus"].copy(); rows[0], rows[1] = rows[1], rows[0]
        self.assertFalse(reference.compare(native, dict(native, post_factory_bus=rows))["passed"])
        for field in ("post_factory_dma_command", "post_factory_dma_palette"):
            self.assertFalse(reference.compare(native, dict(native, **{field: 1}))["passed"])
        for field in ("pc", "status", "cycles", "a", "b"):
            rows = native["post_factory_pixblt"].copy(); rows[-1] = copy.deepcopy(rows[-1])
            if field in ("a", "b"): rows[-1][field][-1] ^= 1
            else: rows[-1][field] ^= 1
            with self.subTest(pix_field=field):
                self.assertFalse(reference.compare(native, dict(native, post_factory_pixblt=rows))["passed"])
        for column in range(len(reference.DSP_REGISTERS)):
            rows = native["post_factory_pixblt_dsp"].copy(); rows[-1] = rows[-1].copy(); rows[-1][column] ^= 1
            with self.subTest(dsp_column=column):
                self.assertEqual(reference.compare(native, dict(native, post_factory_pixblt_dsp=rows))["passed"], column==1)
        for name in reference.POST_FACTORY_POINTS:
            points = native["checkpoints"].copy(); points[name] = dict(points[name], cycles=0)
            with self.subTest(point=name): self.assertFalse(reference.compare(native, dict(native, checkpoints=points))["passed"])

    def test_equal_finite_scope_passes(self):
        native, observed = self.fixture()
        self.assertTrue(reference.compare(native, observed)["passed"])

    def test_factory_bus_cmos_and_complete_memories_are_required(self):
        native, _ = self.fixture()
        for field in ("factory_bus", "factory_entry_main_ram", "factory_main_ram", "factory_cmos", "factory_palette_ram", "factory_vram",
                      "factory_board_io", "factory_display", "factory_dma_command", "factory_dma_palette"):
            observed = dict(native)
            observed.pop(field, None)
            with self.subTest(missing=field):
                self.assertFalse(reference.compare(native, observed)["passed"])

    def test_factory_bus_order_and_every_raw_word_are_compared(self):
        native, _ = self.fixture()
        for field in ("factory_bus", "factory_entry_main_ram", "factory_main_ram", "factory_cmos", "factory_palette_ram",
                      "factory_vram", "factory_board_io", "factory_display"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field].pop()
            with self.subTest(incomplete=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("factory_entry_main_ram", "factory_main_ram", "factory_cmos", "factory_palette_ram", "factory_vram",
                      "factory_board_io", "factory_display"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field][-1] ^= 1
            with self.subTest(raw_word=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(6):
            observed = dict(native, factory_bus=copy.deepcopy(native["factory_bus"]))
            observed["factory_bus"][0][column] ^= 1
            with self.subTest(bus_column=column):
                self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native, factory_bus=native["factory_bus"].copy())
        observed["factory_bus"][0], observed["factory_bus"][1] = observed["factory_bus"][1], observed["factory_bus"][0]
        self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("factory_dma_command", "factory_dma_palette"):
            observed = dict(native, **{field: native[field] ^ 1})
            self.assertFalse(reference.compare(native, observed)["passed"])
        for name in reference.FACTORY_POINTS:
            observed = dict(native, checkpoints=copy.deepcopy(native["checkpoints"]))
            observed["checkpoints"][name]["cycles"] += 1
            with self.subTest(checkpoint=name):
                self.assertFalse(reference.compare(native, observed)["passed"])

    def test_text_bus_and_complete_memories_are_required(self):
        native, _ = self.fixture()
        for field in ("text_reads", "text_writes", "text_pixblt", "text_pixblt_dsp", "text_main_ram",
                      "text_palette_ram", "text_vram", "text_board_io", "text_display",
                      "text_dma_command", "text_dma_palette", "text_bus"):
            observed = dict(native)
            observed.pop(field, None)
            with self.subTest(missing=field):
                self.assertFalse(reference.compare(native, observed)["passed"])

    def test_text_read_write_interleaving_is_compared(self):
        native, _ = self.fixture()
        observed = dict(native, text_bus=native["text_bus"].copy())
        i = reference.TEXT_READ_COUNT - 1
        observed["text_bus"][i], observed["text_bus"][i+1] = observed["text_bus"][i+1], observed["text_bus"][i]
        self.assertEqual(observed["text_reads"], native["text_reads"])
        self.assertEqual(observed["text_writes"], native["text_writes"])
        self.assertFalse(reference.compare(native, observed)["passed"])

    def test_text_observations_compare_every_word_access_column_and_restart(self):
        native, _ = self.fixture()
        for field in ("text_reads", "text_writes", "text_bus", "text_pixblt", "text_pixblt_dsp",
                      "text_main_ram", "text_palette_ram", "text_vram", "text_board_io", "text_display"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field].pop()
            with self.subTest(incomplete=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("text_reads", "text_writes", "text_bus"):
            for column in range(len(native[field][0])):
                observed = dict(native, **{field: copy.deepcopy(native[field])})
                observed[field][0][column] ^= 1
                with self.subTest(field=field, column=column):
                    self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("text_main_ram", "text_palette_ram", "text_vram", "text_board_io", "text_display"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field][-1] ^= 1
            with self.subTest(word=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("text_dma_command", "text_dma_palette"):
            observed = dict(native, **{field: native[field] ^ 1})
            self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("pc", "status", "cycles", "a", "b"):
            observed = dict(native, text_pixblt=copy.deepcopy(native["text_pixblt"]))
            if field in ("a", "b"): observed["text_pixblt"][1][field][-1] ^= 1
            else: observed["text_pixblt"][1][field] ^= 1
            with self.subTest(restart=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native, text_pixblt_dsp=copy.deepcopy(native["text_pixblt_dsp"]))
        observed["text_pixblt_dsp"][1][-1] ^= 1
        self.assertFalse(reference.compare(native, observed)["passed"])
        for name in reference.POINTS:
            if name.startswith("text_"):
                observed = dict(native, checkpoints=copy.deepcopy(native["checkpoints"]))
                observed["checkpoints"][name]["cycles"] += 1
                self.assertFalse(reference.compare(native, observed)["passed"])

    def test_board_observations_detect_mutations_missing_order_and_shape(self):
        native, _ = self.fixture()
        for field in ("board_writes", "board_io", "board_dma_command", "board_ram"):
            observed = dict(native)
            del observed[field]
            with self.subTest(missing=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(5):
            observed = dict(native, board_writes=copy.deepcopy(native["board_writes"]))
            observed["board_writes"][-1][column] ^= 1
            with self.subTest(write_column=column):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("board_writes", "board_io", "board_ram"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field].pop()
            with self.subTest(incomplete=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("board_io", "board_ram"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            if field == "board_ram": observed[field][-1][-1] ^= 1
            else: observed[field][-1] ^= 1
            with self.subTest(mutation=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native)
        observed["board_dma_command"] ^= 1
        self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native, board_writes=copy.deepcopy(native["board_writes"]))
        observed["board_writes"][0], observed["board_writes"][1] = observed["board_writes"][1], observed["board_writes"][0]
        self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native, board_writes=copy.deepcopy(native["board_writes"]))
        observed["board_writes"][-1].pop()
        self.assertFalse(reference.compare(native, observed)["passed"])

    def test_powerup_observations_are_complete_and_compare_every_field(self):
        native, _ = self.fixture()
        sections = ("boot_input_reads", "powerup_writes", "main_ram", "powerup_board_io", "powerup_display")
        for field in sections:
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field].pop()
            with self.subTest(incomplete=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            if field in ("boot_input_reads", "powerup_writes"): observed[field][-1][2] ^= 1
            else: observed[field][-1] ^= 1
            with self.subTest(mutation=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("boot_input_reads", "powerup_writes"):
            for column in range(5):
                observed = dict(native, **{field: copy.deepcopy(native[field])})
                observed[field][1][column] ^= 1
                with self.subTest(field=field, column=column):
                    self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native, powerup_writes=native["powerup_writes"].copy())
        observed["powerup_writes"][3], observed["powerup_writes"][4] = observed["powerup_writes"][4], observed["powerup_writes"][3]
        self.assertFalse(reference.compare(native, observed)["passed"])
        for point in ("dsw_read", "dsw_branch", "dsw_taken", "reset_entry", "ram_clear_entry",
                      "timer_first", "timer_second", "ram_midpoint",
                      "ram_cleared", "after_clear", "powerup_ready"):
            observed = dict(native, checkpoints=copy.deepcopy(native["checkpoints"]))
            observed["checkpoints"][point]["cycles"] += 1
            with self.subTest(point=point):
                self.assertFalse(reference.compare(native, observed)["passed"])
    def test_parser_accepts_actual_output_and_rejects_duplicate_checkpoint(self):
        parse = lambda capture: reference.parse_log(capture, lambda pc: {0xffa4d370: 0x05e0, 0xffa13c60: 0x0583, 0xffa592b0: 0x0fa0, 0xffa5aef0: 0x0580, 0xff80f290: 0x9201, 0xff8089f0: 0x8222, 0xffa28f70: 0x8222, 0xff80dd30: 0x8222}.get(pc, 0xffff))
        native, observed = self.fixture()
        lines = []
        for name, cpu in observed["checkpoints"].items():
            if name in reference.TEXT_GLYPH_POINTS.values(): continue
            fields = [f'{cpu["pc"]:08x}', f'{cpu["status"]:08x}', str(cpu["cycles"])]
            fields += [f'{v:08x}' for v in cpu["a"] + cpu["b"]]
            lines.append("MK2_CPU " + name + " " + " ".join(fields))
        for w in observed["writes"]:
            lines.append(f'MK2_WRITE {w["pc"]+48:08x} {w["address_bit"]:08x} {w["value"]:04x} {w["cycle"]}')
        for pc, address, value, cycle, size in observed["board_writes"]:
            fetch = 16 if pc == 0xffa5fc00 else 48
            lines.append(f'MK2_BOARD_WRITE {pc+fetch:X} {address:X} {value:X} {cycle} {size}')
        lines += [f'MK2_BOARD_IO {i:X} {v:X}' for i, v in enumerate(observed["board_io"])]
        lines += [f'MK2_BOARD_RAM {a:X} {v:X}' for a, v in observed["board_ram"]]
        lines.append('MK2_BOARD_DMA 0')
        for pc, address, value, cycle, size in observed["boot_input_reads"]:
            lines.append(f'MK2_INPUT_READ {pc+48:X} {address:X} {value:X} {cycle} {size}')
        for pc, address, value, cycle, size in observed["powerup_writes"]:
            fetch = 16 if pc in (0xff811280, 0xff814e80) else 48
            lines.append(f'MK2_POWERUP_WRITE {pc+fetch:X} {address:X} {value & 0xffff:X} {cycle} 16')
            if size == 32:
                lines.append(f'MK2_POWERUP_WRITE {pc+fetch:X} {address+16:X} {value >> 16:X} {cycle} 16')
        lines += [f'MK2_POWERUP_IO {i:X} {v:X}' for i, v in enumerate(observed["powerup_board_io"])]
        lines.append('MK2_POWERUP_DISPLAY 21 1111')
        for pc, address, value, cycle, size in observed["video_writes"]:
            fetch = 16 if pc in (0xffa5b240, 0xffa59f00) else 48
            lines.append(f'MK2_VIDEO_WRITE {pc+fetch:X} {address:X} {value & 0xffff:X} {cycle} 16')
            if size == 32:
                lines.append(f'MK2_VIDEO_WRITE {pc+fetch:X} {address+16:X} {value >> 16:X} {cycle} 16')
        lines += [f'MK2_VIDEO_IO {i:X} {v:X}' for i, v in enumerate(observed["video_board_io"])]
        lines += ['MK2_VIDEO_DISPLAY 21 1111', 'MK2_VIDEO_DMA 0']
        for marker, key, fetch in (("MK2_TEXT_READ", "text_reads", reference.TEXT_READ_FETCH),
                                   ("MK2_TEXT_WRITE", "text_writes", reference.TEXT_WRITE_FETCH)):
            fetched = {source: pc for pc, source in fetch.items()}
            for pc, address, value, cycle, size in observed[key]:
                lines.append(f'{marker} {fetched[pc]:X} {address:X} {value:X} {cycle} {size}')
        for cpu in observed["text_pixblt"]:
            fields = [f'{cpu["pc"]:08x}', f'{cpu["status"]:08x}', str(cpu["cycles"])]
            fields += [f'{v:08x}' for v in cpu["a"] + cpu["b"]]
            lines.append("MK2_TEXT_PIXBLT " + " ".join(fields))
        lines += [f'MK2_TEXT_IO {i:X} {v:X}' for i, v in enumerate(observed["text_board_io"])]
        lines += ['MK2_TEXT_DISPLAY 22 2222', 'MK2_TEXT_DMA 0']
        for kind, pc, address, value, cycle, size in observed["factory_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_FACTORY_{marker} {pc+48:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_FACTORY_IO {i:X} {v:X}' for i, v in enumerate(observed["factory_board_io"])]
        lines += ['MK2_FACTORY_DISPLAY 23 3333', 'MK2_FACTORY_DMA 0']
        for kind, pc, address, value, cycle, size in observed["post_factory_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_POST_FACTORY_{marker} {pc+48:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        for cpu in observed["post_factory_pixblt"]:
            fields = [f'{cpu["pc"]:08x}', f'{cpu["status"]:08x}', str(cpu["cycles"])]
            fields += [f'{v:08x}' for v in cpu["a"] + cpu["b"]]
            lines.append("MK2_POST_FACTORY_PIXBLT " + " ".join(fields))
        lines += [f'MK2_POST_FACTORY_IO {i:X} {v:X}' for i, v in enumerate(observed["post_factory_board_io"])]
        lines += ['MK2_POST_FACTORY_DISPLAY 24 4444', 'MK2_POST_FACTORY_DMA 0']
        for kind, pc, address, value, cycle, size in observed["sound_command_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_SOUND_COMMAND_{marker} {pc+48:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_SOUND_COMMAND_IO {i:X} {v:X}' for i, v in enumerate(observed["sound_command_board_io"])]
        lines += ['MK2_SOUND_COMMAND_DISPLAY 24 4444', 'MK2_SOUND_COMMAND_DMA 0']
        for kind, pc, address, value, cycle, size in observed["input_wait_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_INPUT_WAIT_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        for cpu in observed["input_wait_pixblt"]:
            fields = [f'{cpu["pc"]:08x}', f'{cpu["status"]:08x}', str(cpu["cycles"])]
            fields += [f'{v:08x}' for v in cpu["a"] + cpu["b"]]
            lines.append("MK2_INPUT_WAIT_PIXBLT " + " ".join(fields))
        lines += [f'MK2_INPUT_WAIT_IO {i:X} {v:X}' for i, v in enumerate(observed["input_wait_board_io"])]
        lines += ['MK2_INPUT_WAIT_DISPLAY 24 4444', 'MK2_INPUT_WAIT_DMA 0']
        for kind,pc,address,value,cycle,size in observed["input_poll_bus"]:
            marker="READ" if kind==114 else "WRITE"
            lines.append(f'MK2_INPUT_POLL_{marker} {pc+48:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        for cpu in observed["input_poll_pixblt"]:
            fields=[f'{cpu["pc"]:08x}',f'{cpu["status"]:08x}',str(cpu["cycles"])]
            fields += [f'{v:08x}' for v in cpu["a"]+cpu["b"]]
            lines.append("MK2_INPUT_POLL_PIXBLT "+" ".join(fields))
        lines += [f'MK2_INPUT_POLL_IO {i:X} {v:X}' for i,v in enumerate(observed["input_poll_board_io"])]
        lines += ['MK2_INPUT_POLL_DISPLAY 24 4444','MK2_INPUT_POLL_DMA 0']
        for kind,pc,address,value,cycle,size in observed["input_idle_bus"]:
            marker="READ" if kind==114 else "WRITE"
            lines.append(f'MK2_INPUT_IDLE_{marker} {pc+48:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_INPUT_IDLE_IO {i:X} {v:X}' for i,v in enumerate(observed["input_idle_board_io"])]
        lines += ['MK2_INPUT_IDLE_DISPLAY 24 4444','MK2_INPUT_IDLE_DMA 0']
        for kind,pc,address,value,cycle,size in observed["sport_wrap_bus"]:
            marker="READ" if kind==114 else "WRITE"
            lines.append(f'MK2_SPORT_WRAP_{marker} {pc+48:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_SPORT_WRAP_IO {i:X} {v:X}' for i,v in enumerate(observed["sport_wrap_board_io"])]
        lines += ['MK2_SPORT_WRAP_DISPLAY 24 4444','MK2_SPORT_WRAP_DMA 0']
        for kind,pc,address,value,cycle,size in observed["button_exit_bus"]:
            marker="READ" if kind==114 else "WRITE"
            lines.append(f'MK2_BUTTON_EXIT_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_BUTTON_EXIT_IO {i:X} {v:X}' for i,v in enumerate(observed["button_exit_board_io"])]
        lines += ['MK2_BUTTON_EXIT_DISPLAY 24 4444','MK2_BUTTON_EXIT_DMA 0']
        for kind, pc, address, value, cycle, size in observed["video_irq_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_VIDEO_IRQ_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_VIDEO_IRQ_IO {i:X} {v:X}' for i, v in enumerate(observed["video_irq_board_io"])]
        lines += ['MK2_VIDEO_IRQ_DISPLAY 24 4444', 'MK2_VIDEO_IRQ_DMA 0']
        for kind, pc, address, value, cycle, size in observed["startup_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_STARTUP_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_STARTUP_IO {i:X} {v:X}' for i,v in enumerate(observed["startup_board_io"])]
        lines += ['MK2_STARTUP_DISPLAY 24 4444', 'MK2_STARTUP_DMA 0']
        for kind, pc, address, value, cycle, size in observed["dispatcher_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_DISPATCHER_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_DISPATCHER_IO {i:X} {v:X}' for i,v in enumerate(observed["dispatcher_board_io"])]
        lines += ['MK2_DISPATCHER_DISPLAY 24 4444', 'MK2_DISPATCHER_DMA 0']
        for kind, pc, address, value, cycle, size in observed["task_resume_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_TASK_RESUME_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_TASK_RESUME_IO {i:X} {v:X}' for i,v in enumerate(observed["task_resume_board_io"])]
        lines += ['MK2_TASK_RESUME_DISPLAY 24 4444', 'MK2_TASK_RESUME_DMA 0']
        for kind, pc, address, value, cycle, size in observed["task_queue_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_TASK_QUEUE_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_TASK_QUEUE_IO {i:X} {v:X}' for i, v in enumerate(observed["task_queue_board_io"])]
        lines += ['MK2_TASK_QUEUE_DISPLAY 24 4444', 'MK2_TASK_QUEUE_DMA 0']
        for kind, pc, address, value, cycle, size in observed["task_palette_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_TASK_PALETTE_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_TASK_PALETTE_IO {i:X} {v:X}' for i, v in enumerate(observed["task_palette_board_io"])]
        lines += ['MK2_TASK_PALETTE_DISPLAY 24 4444', 'MK2_TASK_PALETTE_DMA 0']
        for kind, pc, address, value, cycle, size in observed["task_draw_bus"]:
            marker = "READ" if kind == 114 else "WRITE"
            lines.append(f'MK2_TASK_DRAW_{marker} {pc+16:X} {address:X} {value:X} {cycle} {size} {pc:X}')
        lines += [f'MK2_TASK_DRAW_IO {i:X} {v:X}' for i, v in enumerate(observed["task_draw_board_io"])]
        lines += ['MK2_TASK_DRAW_DISPLAY 24 4444', 'MK2_TASK_DRAW_DMA 0']
        lines += [f'MK2_TASK_DRAW_GRAPHICS_DMA {cycle} {command:X} {pending:X}'
                  for cycle, command, pending in observed["task_draw_graphics_dma"]]
        text = "\n".join(lines)
        parsed = parse(text)
        self.assertEqual(parse(iter(text.splitlines(True))), parsed)
        self.assertEqual(parsed["checkpoints"], native["checkpoints"])
        self.assertEqual(parsed["writes"], native["writes"])
        for field in ("board_writes", "board_io", "board_ram", "board_dma_command", "boot_input_reads",
                      "powerup_writes", "powerup_board_io", "powerup_display", "video_writes",
                      "video_board_io", "video_display", "video_dma_command", "text_reads", "text_writes",
                      "text_pixblt", "text_board_io", "text_display", "text_dma_command", "text_bus", "factory_bus",
                      "factory_board_io", "factory_display", "factory_dma_command", "post_factory_bus", "post_factory_board_io",
                      "post_factory_display", "post_factory_dma_command", "post_factory_pixblt", "sound_command_bus",
                      "sound_command_board_io", "sound_command_display", "sound_command_dma_command", "input_wait_bus",
                      "input_wait_pixblt", "input_wait_board_io", "input_wait_display", "input_wait_dma_command", "input_poll_bus",
                      "input_poll_pixblt", "input_poll_board_io", "input_poll_display", "input_poll_dma_command",
                      "input_idle_bus", "input_idle_board_io", "input_idle_display", "input_idle_dma_command",
                      "sport_wrap_bus", "sport_wrap_board_io", "sport_wrap_display", "sport_wrap_dma_command",
                      "button_exit_bus", "button_exit_board_io", "button_exit_display", "button_exit_dma_command"):
            self.assertEqual(parsed[field], native[field])
        low_lane = 'MK2_POWERUP_WRITE FF811290 10FFFD0 12B0 2121 16'
        noisy = text.replace(low_lane, low_lane + '\n\n> debugger transport prompt')
        with self.assertRaises(ValueError):
            parse(text + "\n" + lines[0])
        for bad in (text.replace(' 1884 16', ' 1884 8'),
                    text.replace('MK2_BOARD_WRITE FFA5FAC0', 'MK2_BOARD_WRITE FFA5FAB0'),
                    text.replace('MK2_BOARD_IO 0 100\n', ''),
                    text + '\nMK2_BOARD_IO 0 100', text + '\nMK2_BOARD_DMA 0',
                    text + '\nMK2_BOARD_WRITE FFA5FAC0 1A80010 0 1884',
                    text + '\nMK2_BOARD_IO 1C 0', text + '\nMK2_BOARD_RAM 10FFF10',
                    text.replace('MK2_BOARD_DMA 0', 'MK2_BOARD_DMA')):
            with self.subTest(text=bad[-60:]), self.assertRaises(ValueError):
                parse(bad)
        for bad in (text.replace('MK2_POWERUP_WRITE FF811290 10FFFE0 FF81 2121 16', ''),
                    text.replace('MK2_POWERUP_WRITE FF811290 10FFFE0 FF81 2121 16',
                                 'MK2_POWERUP_WRITE FF811290 10FFFF0 FF81 2121 16'),
                    text.replace('MK2_POWERUP_WRITE FF811290 10FFFE0 FF81 2121 16',
                                 'MK2_POWERUP_WRITE FF811290 10FFFE0 FF81 2122 16'),
                    text + '\nMK2_POWERUP_IO 0 100', text + '\nMK2_POWERUP_DISPLAY 21 1111',
                    text.replace('MK2_INPUT_READ FFA5C230 1600040 FFFF 2089 16', ''),
                    text.replace('MK2_POWERUP_IO 1B 11B', '')):
            with self.subTest(powerup=bad[-70:]), self.assertRaises(ValueError):
                parse(bad)
        for bad in (text.replace(low_lane, low_lane.replace('12B0 2121', '112B0 2121')),
                    text.replace(low_lane, low_lane.replace('12B0 2121', '-1 2121')),
                    text.replace('10FFFE0 FF81 2121', '10FFFE0 1FF81 2121'),
                    text.replace('1600030 FC7D 2089', '1600030 1FC7D 2089'),
                    text.replace('FFA5FB70 1B00000 5A 1895', 'FFA5FB70 1B00000 1005A 1895'),
                    text.replace('MK2_BOARD_IO 0 100', 'MK2_BOARD_IO 0 10100'),
                    text.replace('MK2_POWERUP_IO 0 100', 'MK2_POWERUP_IO 0 10100'),
                    text.replace('MK2_BOARD_DMA 0', 'MK2_BOARD_DMA 10000'),
                    text.replace('MK2_POWERUP_DISPLAY 21 1111', 'MK2_POWERUP_DISPLAY 10021 1111'),
                    text.replace(low_lane, low_lane + '\nMK2_INPUT_READ FFA5C230 1600030 FC7D 2089 16')):
            with self.subTest(word_boundary=bad[-70:]), self.assertRaises(ValueError):
                parse(bad)
        video_low = 'MK2_VIDEO_WRITE FFA59F10 0 0 100582 16'
        video_high = 'MK2_VIDEO_WRITE FFA59F10 10 0 100582 16'
        for bad in (text.replace(video_high, ''),
                    text.replace(video_high, video_high.replace('100582', '100583')),
                    text.replace(video_high, video_high.replace(' 10 ', ' 20 ')),
                    text.replace(video_low, video_low.replace(' 0 100582', ' 10000 100582')),
                    text.replace(video_high, 'MK2_VIDEO_DMA 0\n' + video_high),
                    text + '\nMK2_VIDEO_IO 0 100', text + '\nMK2_VIDEO_DMA 0',
                    text.replace('MK2_VIDEO_DISPLAY 21 1111', 'MK2_VIDEO_DISPLAY 10021 1111')):
            with self.subTest(video=bad[-70:]), self.assertRaises(ValueError):
                parse(bad)
        for bad in (text.replace('MK2_TEXT_READ FFA593F0 FFA401C0 0 297204 16', ''),
                    text.replace('MK2_TEXT_READ FFA593F0 FFA401C0 0 297204 16',
                                 'MK2_TEXT_READ FFA593E0 FFA401C0 0 297204 16'),
                    text.replace('MK2_TEXT_WRITE FFA592C0 1E6B0 0 297580 16',
                                 'MK2_TEXT_WRITE FFA592C0 1E6B0 10000 297580 16'),
                    text.replace('MK2_TEXT_WRITE FFA592C0 1E6B0 0 297580 16',
                                 'MK2_TEXT_WRITE FFA592C0 1E6B8 0 297580 8'),
                    text + '\nMK2_TEXT_IO 0 100', text + '\nMK2_TEXT_DMA 0'):
            with self.subTest(text_bus=bad[-70:]), self.assertRaises(ValueError):
                parse(bad)
        factory_read = 'MK2_FACTORY_READ FFA4D3A0 1480000 FFFF 305765 16 FFA4D370'
        with self.assertRaisesRegex(ValueError, "Unexpected factory fetched PC"):
            parse(text.replace(factory_read, factory_read.replace('FFA4D3A0', 'FFA4D380'), 1))
        with self.assertRaisesRegex(ValueError, "Incomplete factory reference capture"):
            parse(text.replace(factory_read, '', 1))
        for bad in (factory_read.replace('FFA4D3A0', 'FFA4D371'),
                    factory_read.replace('FFA4D3A0', 'FFA4D3D0'),
                    factory_read.replace('1480000', '1480008'),
                    factory_read.replace('FFFF 305765', '10000 305765'),
                    factory_read.replace('16 FFA4D370', '8 FFA4D370'),
                    factory_read.replace('16 FFA4D370', '16 1000000')):
            with self.subTest(factory=bad), self.assertRaisesRegex(ValueError, "Unexpected factory bus"):
                parse(bad)
        for bad, error in (("MK2_FACTORY_IO 0 15\nMK2_FACTORY_IO 0 15", "duplicate factory IO"),
                           ("MK2_FACTORY_DMA 0\nMK2_FACTORY_DMA 0", "factory DMA observation")):
            with self.assertRaisesRegex(ValueError, error): parse(bad)
        post_read = 'MK2_POST_FACTORY_READ FFA4D3A0 1480000 0 379400 16 FFA4D370'
        with self.assertRaisesRegex(ValueError, "Incomplete post_factory reference capture"):
            parse(text.replace(post_read, '', 1))
        for bad in (post_read.replace('FFA4D3A0', 'FFA4D380'), post_read.replace('1480000', '1480008'),
                    post_read.replace('0 379400', '10000 379400'), post_read.replace('16 FFA4D370', '8 FFA4D370'),
                    'MK2_POST_FACTORY_IO 0 1\nMK2_POST_FACTORY_IO 0 1',
                    'MK2_POST_FACTORY_DISPLAY 0 0\nMK2_POST_FACTORY_DISPLAY 0 0',
                    'MK2_POST_FACTORY_DMA 0\nMK2_POST_FACTORY_DMA 0'):
            with self.subTest(post=bad), self.assertRaises(ValueError): parse(bad)
        sound_write = 'MK2_SOUND_COMMAND_WRITE FFA13C90 1D01030 FF02 399230 16 FFA13C60'
        with self.assertRaisesRegex(ValueError, "Incomplete sound_command reference capture"):
            parse(text.replace(sound_write, '', 1))
        for bad in (sound_write.replace('FFA13C90', 'FFA13C70'), sound_write.replace('1D01030', '1D01038'),
                    sound_write.replace('FF02', '10000'), sound_write.replace('16 FFA13C60', '8 FFA13C60'),
                    'MK2_SOUND_COMMAND_IO 0 1\nMK2_SOUND_COMMAND_IO 0 1',
                    'MK2_SOUND_COMMAND_DISPLAY 0 0\nMK2_SOUND_COMMAND_DISPLAY 0 0',
                    'MK2_SOUND_COMMAND_DMA 0\nMK2_SOUND_COMMAND_DMA 0'):
            with self.subTest(sound=bad), self.assertRaises(ValueError):
                parse(text.replace(sound_write, bad, 1) if bad.startswith('MK2_SOUND_COMMAND_WRITE') else bad)
        self.assertEqual(parse(noisy), parsed)
        text = text.replace('MK2_WRITE ff811030 01b00000 005a 11',
                            'MK2_BOARD_WRITE FF811030 1B00000 5A 11 16')
        self.assertEqual(parse(text)["writes"], native["writes"])

    def test_video_observations_require_full_memory_order_width_and_timing(self):
        native, _ = self.fixture()
        for field in ("video_writes", "video_board_io", "video_display", "video_main_ram", "palette_ram", "vram"):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field].pop()
            with self.subTest(incomplete=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            if field == "video_writes": observed[field][-1][2] ^= 1
            else: observed[field][-1] ^= 1
            with self.subTest(mutation=field):
                self.assertFalse(reference.compare(native, observed)["passed"])
        for column in range(5):
            observed = dict(native, video_writes=copy.deepcopy(native["video_writes"]))
            observed["video_writes"][-1][column] ^= 1
            self.assertFalse(reference.compare(native, observed)["passed"])
        observed = dict(native, video_writes=native["video_writes"].copy())
        observed["video_writes"][-1], observed["video_writes"][-2] = observed["video_writes"][-2], observed["video_writes"][-1]
        self.assertFalse(reference.compare(native, observed)["passed"])
        for field in ("video_dma_command", "dma_palette"):
            observed = dict(native)
            del observed[field]
            self.assertFalse(reference.compare(native, observed)["passed"])
            observed = dict(native)
            observed[field] ^= 1
            self.assertFalse(reference.compare(native, observed)["passed"])
        for name in reference.POINTS:
            if name.startswith("video_"):
                observed = dict(native, checkpoints=copy.deepcopy(native["checkpoints"]))
                observed["checkpoints"][name]["cycles"] += 1
                self.assertFalse(reference.compare(native, observed)["passed"])

    def test_changed_state_event_or_any_boot_word_is_detected(self):
        native, _ = self.fixture()
        for kind in ("pc", "status", "cycles", "register", "write", "missing_write", "boot", "record", "stored", "routine", "restored", "returned", "board_entry", "board_configured", "board_ready", "diagnostic_write"):
            field = "writes" if kind in ("write", "missing_write", "diagnostic_write") else "boot_words" if kind == "boot" else "checkpoints"
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            if kind in ("pc", "status", "cycles"):
                observed["checkpoints"]["status"][kind] ^= 1
            elif kind == "register": observed["checkpoints"]["prefix"]["b"][14] = 1
            elif kind == "record": observed["checkpoints"]["record"]["cycles"] += 1
            elif kind == "stored": observed["checkpoints"]["stored"]["a"][1] ^= 1
            elif kind in ("routine", "restored", "returned", "board_entry", "board_configured", "board_ready"): observed["checkpoints"][kind]["status"] ^= 0x20000000
            elif kind == "diagnostic_write": observed["writes"][-1]["value"] ^= 1
            elif kind == "write": observed["writes"][2]["cycle"] += 1
            elif kind == "missing_write": observed["writes"].pop()
            else: observed["boot_words"][-1] ^= 1
            with self.subTest(kind=kind):
                self.assertFalse(reference.compare(native, observed)["passed"])

    def test_missing_duplicate_or_echo_only_capture_is_rejected(self):
        self.assertTrue(hasattr(reference, "parse_log"), "MK2 reference parser is missing")
        for text in ("", '>bpset ff811150,1,{printf "MK2_CPU prefix...";g}\n',
                     "MK2_CPU prefix 0 0 0\n", "MK2_CPU unknown 0 0 0\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                reference.parse_log(text)

    def test_dsp_comparator_requires_complete_observations(self):
        self.assertTrue(hasattr(reference, "compare_dsp"), "ADSP differential comparison is missing")
        self.assertFalse(reference.compare_dsp({}, {})["passed"])

    def test_dsp_mutations_are_detected(self):
        self.assertTrue(hasattr(reference, "compare_dsp"), "ADSP differential comparison is missing")
        native = {"dsp_trace": [[0]*76], "dsp_points": [[0]*76 for _ in reference.POINTS],
                  "dsp_accesses": [[112, 0x39, 4, 0x1816ef, 24]],
                  "ram": [[a, 0] for a in reference.RAM_ADDRESSES],
                  "checked_ram": [[a, 0] for a in reference.RAM_ADDRESSES],
                  "stored_ram": [[a, 0] for a in reference.STORED_RAM_ADDRESSES],
                  "cmos_writes": [[0xffa4d370, 0x01480000, 0xff00, n] for n in range(12)],
                  "cmos": [0]*8192,
                  "sound_ram": [[a, 0] for a in reference.SOUND_RAM_ADDRESSES],
                  "cmos_reads": [[0xffa4d320, 0x01400f00 + n*16, 0, 0] for n in range(22)],
                  "dsp_pm": [0]*1024, "dsp_dm": [0]*512, "dsp_control": [0]*32, "dcs_control": 0xc00,
                  "post_factory_dsp_pm": [0]*1024, "post_factory_dsp_dm": [0]*512,
                  "post_factory_dsp_control": [0]*32,
                  "sound_command_dsp_pm": [0]*1024, "sound_command_dsp_dm": [0]*512, "sound_command_dsp_control": [0]*32}
        native.update(dsp_external_pm=[0]*2048, dsp_external_dm=[0]*2048, dsp_device=[0]*len(reference.DCS_DEVICE_FIELDS),
                      input_wait_dsp_pm=[0]*1024, input_wait_dsp_dm=[0]*512, input_wait_dsp_control=[0]*32,
                      input_wait_dsp_external_pm=[0]*2048, input_wait_dsp_external_dm=[0]*2048, input_wait_dsp_device=[0]*len(reference.DCS_DEVICE_FIELDS),
                      input_poll_dsp_pm=[0]*1024, input_poll_dsp_dm=[0]*512, input_poll_dsp_control=[0]*32,
                      input_poll_dsp_external_pm=[0]*2048, input_poll_dsp_external_dm=[0]*2048, input_poll_dsp_device=[0]*len(reference.DCS_DEVICE_FIELDS), sport_pcm=[0]*reference.SPORT_SAMPLES, sport_dac_buffer=[0]*reference.SPORT_SAMPLES,
                      sport_dma_reads=[[7225490, 0x136, 81726, address, 0] for address in range(0x400, 0x4f0)],
                      sport_dma_position=1, sport_dma_positions=[1, 2, 3], sport_irq1_state=[0, 0],
                      sport_wrap_dac_buffer=[0]*480, sport_wrap_irq1_state=[0, 1], sport_wrap_dcs_control=0xc00,
                      input_events=[[8096368, 1, 0xffff, 0], [9139625, 1, 0xffef, 1],
                                    [9140064, 0, 0xffef, 0], [10967550, 0, 0xffff, 1]],
                      sport_irq1_events=[[7993490, 0x131, 158527, 1], [7993500, 0x132, 158528, 0]])
        native["sport_dma_reads"] += [[7993490, 0x131, 158526, address, 0] for address in range(0x4f0, 0x5e0)]
        native["sport_dma_reads"] += [[8761490, 0x137, 235326, address, 0] for address in range(0x400, 0x4f0)]
        native.update(button_exit_irq1_state=[0, 0], button_exit_dac_buffer=[0]*reference.SPORT_SAMPLES,
                      button_exit_dcs_control=0xc00, button_exit_sport_deadline_ticks=0,
                      button_exit_event_counts=[1, 1, 1, 1, 720, 2, 3, 3],
                      video_irq_irq1_state=[0, 0], video_irq_dac_buffer=[0]*reference.SPORT_SAMPLES,
                      video_irq_dcs_control=0xc00, video_irq_sport_deadline=13552570,
                      video_irq_event_counts=[1, 1, 1, 1, 720, 2, 3, 3],
                      startup_irq1_state=[0, 0], startup_dac_buffer=[0]*reference.SPORT_SAMPLES,
                      startup_dcs_control=0xc00, startup_sport_deadline=13552570, startup_event_counts=[1, 1, 1, 1, 720, 2, 3, 3])
        native.update({point + "_" + key: [0]*count
                       for point in ("sport_wrap", *reference.BUTTON_DSP_POINTS, "video_irq", "startup") for key, count in reference.DSP_IMAGE_SIZES})
        native.update({"dispatcher_" + key: [0]*count for key, count in reference.DSP_IMAGE_SIZES})
        native.update(dispatcher_irq1_state=[0, 0], dispatcher_dac_buffer=[0]*720,
                      dispatcher_dcs_control=0xc00, dispatcher_sport_deadline=13552570,
                      dispatcher_event_counts=[1, 1, 1, 1, 720, 2, 3, 3])
        native.update(task_resume_pcm=[0]*1680, task_resume_dma_reads=[[0]*5 for _ in range(1680)],
                      task_resume_dma_positions=list(range(4, 11)), task_resume_irq1_events=[[0]*4 for _ in range(6)],
                      task_resume_irq1_state=[0, 0], task_resume_dac_buffer=[0]*2400,
                      task_resume_dcs_control=0xc00, task_resume_sport_deadline=18928570,
                      task_resume_event_counts=[1, 1, 1, 1, 2400, 8, 10, 10])
        native.update({"task_queue_" + key: [0]*count for key, count in reference.DSP_IMAGE_SIZES})
        native.update(task_queue_irq1_state=[0, 0], task_queue_dac_buffer=[0]*2400,
                      task_queue_dcs_control=0xc00, task_queue_sport_deadline=18928570,
                      task_queue_event_counts=[1, 1, 1, 1, 2400, 8, 10, 10],
                      task_queue_pcm=[], task_queue_dma_reads=[], task_queue_dma_positions=[],
                      task_queue_transfers=[], task_queue_irq1_events=[])
        native.update({"task_palette_" + key: [0]*count for key, count in reference.DSP_IMAGE_SIZES})
        native.update(task_palette_irq1_state=[0, 0], task_palette_dac_buffer=[0]*2880,
                      task_palette_dcs_control=0xc00, task_palette_sport_deadline=20464570,
                      task_palette_event_counts=[1, 1, 1, 1, 2880, 10, 12, 12],
                      task_palette_pcm=[0]*480, task_palette_dma_reads=[[0]*5 for _ in range(480)],
                      task_palette_dma_positions=[10, 11], task_palette_transfers=[[0]*7 for _ in range(2)],
                      task_palette_irq1_events=[[0]*4 for _ in range(2)])
        native.update({"task_draw_" + key: [0]*count for key, count in reference.DSP_IMAGE_SIZES})
        native.update(task_draw_irq1_state=[0, 0], task_draw_dac_buffer=[0]*2880,
                      task_draw_dcs_control=0xc00, task_draw_sport_deadline=20464570,
                      task_draw_event_counts=[1, 1, 1, 1, 2880, 10, 12, 12],
                      task_draw_pcm=[], task_draw_dma_reads=[], task_draw_dma_positions=[],
                      task_draw_transfers=[], task_draw_irq1_events=[])
        native.update({"input_idle_" + key: native[key][:] for key in ("dsp_pm", "dsp_dm", "dsp_control", "dsp_external_pm", "dsp_external_dm", "dsp_device")})
        for field in ("input_idle_dsp_pm", "input_idle_dsp_dm", "input_idle_dsp_control", "input_idle_dsp_external_pm", "input_idle_dsp_external_dm", "input_idle_dsp_device", "sport_dma_positions", "sport_irq1_state", "sport_irq1_events"):
            for side in (0, 1):
                missing = dict(native); del missing[field]
                self.assertFalse(reference.compare_dsp(*((missing, native) if side == 0 else (native, missing)))["passed"])
                short = dict(native, **{field: native[field][:-1]})
                self.assertFalse(reference.compare_dsp(*((short, native) if side == 0 else (native, short)))["passed"])
        for field in ("sport_dma_positions", "sport_irq1_events"):
            self.assertFalse(reference.compare_dsp(native, dict(native, **{field: native[field][::-1]}))["passed"])
        native["dsp_dm"][0x1fc] = 1
        native.update({key: [[a, 0] for a in reference.STORED_RAM_ADDRESSES] for key in reference.RETURN_RAM_KEYS})
        self.assertTrue(reference.compare_dsp(native, copy.deepcopy(native))["passed"])
        for suffix in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events", "irq1_state", "dac_buffer", "event_counts", "dcs_control", *[key for key, _ in reference.DSP_IMAGE_SIZES]):
            field = "task_palette_" + suffix
            missing = dict(native); del missing[field]
            with self.subTest(task_palette_missing=field): self.assertFalse(reference.compare_dsp(native, missing)["passed"])
            if isinstance(native[field], list):
                short = dict(native, **{field: native[field][:-1]})
                with self.subTest(task_palette_truncated=field): self.assertFalse(reference.compare_dsp(short, short)["passed"])
        for suffix, width in (("dma_reads", 5), ("transfers", 7), ("irq1_events", 4)):
            field = "task_palette_" + suffix
            malformed = dict(native, **{field: [row[:-1] for row in native[field]]})
            with self.subTest(task_palette_malformed=field): self.assertFalse(reference.compare_dsp(malformed, malformed)["passed"])
            for column in range(width):
                bad = dict(native, **{field: copy.deepcopy(native[field])}); bad[field][-1][column] ^= 1
                with self.subTest(task_palette_field=field, column=column): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        self.assertFalse(reference.compare_dsp(dict(native, task_palette_sport_deadline=0), native)["passed"])
        for suffix in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events", "irq1_state", "dac_buffer", "event_counts", "dcs_control", *[key for key, _ in reference.DSP_IMAGE_SIZES]):
            field = "task_draw_" + suffix
            missing = dict(native); del missing[field]
            with self.subTest(task_draw_missing=field): self.assertFalse(reference.compare_dsp(native, missing)["passed"])
            bad = dict(native)
            if isinstance(native[field], list):
                bad[field] = native[field][:]
                if bad[field]: bad[field][-1] ^= 1
                else: bad[field].append(0)
            else: bad[field] ^= 1
            with self.subTest(task_draw_changed=field): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        self.assertFalse(reference.compare_dsp(dict(native, task_draw_sport_deadline=0), native)["passed"])

        for field in ("task_queue_irq1_state", "task_queue_dac_buffer", "task_queue_event_counts", "task_queue_dcs_control",
                      *["task_queue_" + key for key, _ in reference.DSP_IMAGE_SIZES]):
            missing = dict(native); del missing[field]
            with self.subTest(task_queue_missing=field): self.assertFalse(reference.compare_dsp(native, missing)["passed"])
            bad = dict(native)
            if isinstance(native[field], list):
                bad[field] = native[field][:]; bad[field][-1] ^= 1
            else: bad[field] ^= 1
            with self.subTest(task_queue_changed=field): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        for field in ("task_queue_pcm", "task_queue_dma_reads", "task_queue_dma_positions", "task_queue_transfers", "task_queue_irq1_events"):
            missing = dict(native); del missing[field]
            with self.subTest(task_queue_missing=field): self.assertFalse(reference.compare_dsp(native, missing)["passed"])
            unexpected = dict(native, **{field: [0]})
            with self.subTest(task_queue_unexpected=field): self.assertFalse(reference.compare_dsp(unexpected, unexpected)["passed"])
        self.assertFalse(reference.compare_dsp(dict(native, task_queue_sport_deadline=0), native)["passed"])
        for field in ("dispatcher_dsp_pm", "dispatcher_dsp_dm", "dispatcher_dsp_control",
                      "dispatcher_dsp_external_pm", "dispatcher_dsp_external_dm", "dispatcher_dsp_device",
                      "dispatcher_irq1_state", "dispatcher_dac_buffer", "dispatcher_event_counts", "dispatcher_dcs_control"):
            missing = dict(native); del missing[field]
            with self.subTest(historical_dispatcher_missing=field): self.assertFalse(reference.compare_dsp(native, missing)["passed"])
            bad = dict(native)
            if isinstance(native[field], list):
                bad[field] = native[field][:]; bad[field][-1] ^= 1
            else: bad[field] ^= 1
            with self.subTest(historical_dispatcher_changed=field): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        self.assertFalse(reference.compare_dsp(dict(native, dispatcher_sport_deadline=0), native)["passed"])
        for field in ("task_resume_pcm", "task_resume_dma_reads", "task_resume_dma_positions", "task_resume_irq1_events",
                      "task_resume_irq1_state", "task_resume_dac_buffer", "task_resume_event_counts", "task_resume_dcs_control"):
            missing = dict(native); del missing[field]
            with self.subTest(task_resume_missing=field): self.assertFalse(reference.compare_dsp(native, missing)["passed"])
        for field in ("task_resume_dma_reads", "task_resume_irq1_events"):
            malformed = dict(native, **{field: [row[:-1] for row in native[field]]})
            with self.subTest(task_resume_malformed=field): self.assertFalse(reference.compare_dsp(malformed, malformed)["passed"])
        for field in ("button_exit_irq1_state", "button_exit_dac_buffer", "button_exit_event_counts",
                      "video_irq_irq1_state", "video_irq_dac_buffer", "video_irq_event_counts"):
            bad = dict(native); del bad[field]
            with self.subTest(missing=field): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
            bad = dict(native, **{field: native[field][:]}); bad[field][-1] ^= 1
            with self.subTest(mutation=field): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        self.assertFalse(reference.compare_dsp(dict(native, button_exit_sport_deadline_ticks=1), native)["passed"])
        self.assertFalse(reference.compare_dsp(native, dict(native, button_exit_dcs_control=0))["passed"])
        self.assertFalse(reference.compare_dsp(native, dict(native, video_irq_dcs_control=0))["passed"])
        self.assertFalse(reference.compare_dsp(dict(native, video_irq_sport_deadline=0), native)["passed"])
        for point in ("sport_wrap", *reference.BUTTON_DSP_POINTS, "video_irq", "startup"):
            for key, _ in reference.DSP_IMAGE_SIZES:
                field = point + "_" + key
                for observed in (dict(native, **{field: native[field][:-1]}), {k: v for k, v in native.items() if k != field}):
                    with self.subTest(incomplete=field): self.assertFalse(reference.compare_dsp(native, observed)["passed"])
        for index in range(4):
            for column in range(4):
                bad = dict(native, input_events=copy.deepcopy(native["input_events"])); bad["input_events"][index][column] ^= 1
                with self.subTest(input_event=index, column=column): self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        for column in range(5):
            bad = dict(native, sport_dma_reads=copy.deepcopy(native["sport_dma_reads"])); bad["sport_dma_reads"][-1][column] ^= 1
            self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        bad = dict(native); del bad["sport_dma_position"]
        self.assertFalse(reference.compare_dsp(native, bad)["passed"])
        partial = dict(native, dsp_trace=[[1]*len(reference.DSP_REGISTERS)])
        self.assertFalse(reference.compare_dsp(native, partial)["passed"])
        micro = reference.compare_dsp(native, partial, instruction_trace=False)
        self.assertTrue(micro["passed"])
        self.assertFalse(micro["dsp_instruction_trace_compared"])
        self.assertEqual(micro["dsp_instruction_boundaries"], 0)
        bad_device = dict(partial, dsp_device=partial["dsp_device"][:]); bad_device["dsp_device"][0] ^= 1
        self.assertFalse(reference.compare_dsp(native, bad_device, instruction_trace=False)["passed"])

        for field in native:
            if field in ("button_exit_sport_deadline_ticks", "video_irq_sport_deadline", "startup_sport_deadline", "dispatcher_sport_deadline", "task_resume_sport_deadline", "task_queue_sport_deadline", "task_palette_sport_deadline", "task_draw_sport_deadline"): continue  # Native cancellation guard has no independent MAME readback.
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            if isinstance(observed[field], int): observed[field] ^= 1
            elif not observed[field]: observed[field].append(0)
            elif field in ("dsp_trace", "dsp_points", "dsp_accesses", "ram", "checked_ram", "stored_ram", "sound_ram", "cmos_reads", "cmos_writes", "sport_dma_reads", "sport_irq1_events", "task_resume_dma_reads", "task_resume_irq1_events", "task_palette_dma_reads", "task_palette_transfers", "task_palette_irq1_events", "input_events", *reference.RETURN_RAM_KEYS): observed[field][-1][-1] ^= 1
            else: observed[field][-1] ^= 1
            with self.subTest(field=field):
                self.assertFalse(reference.compare_dsp(native, observed)["passed"])
        for column in range(4):
            observed = dict(native, cmos_writes=copy.deepcopy(native["cmos_writes"]))
            observed["cmos_writes"][-1][column] ^= 1
            with self.subTest(cmos_write_column=column):
                self.assertFalse(reference.compare_dsp(native, observed)["passed"])
        observed = dict(native, cmos=copy.deepcopy(native["cmos"]))
        observed["cmos"][0xf3] ^= 1
        self.assertFalse(reference.compare_dsp(native, observed)["passed"])
        observed = dict(native, dsp_trace=copy.deepcopy(native["dsp_trace"]))
        observed["dsp_trace"][0][1] += 1
        self.assertFalse(reference.compare_dsp(native, observed)["passed"])
        for field in ("dsp_trace", "dsp_points", "dsp_accesses", "ram", "checked_ram", "stored_ram", "sound_ram", "cmos_reads", "cmos_writes", "cmos", "dsp_pm", "dsp_dm", "dsp_control", "post_factory_dsp_pm", "post_factory_dsp_dm", "post_factory_dsp_control", "sound_command_dsp_pm", "sound_command_dsp_dm", "sound_command_dsp_control", "dsp_external_pm", "dsp_external_dm", "dsp_device",
                      "input_wait_dsp_pm", "input_wait_dsp_dm", "input_wait_dsp_control", "input_wait_dsp_external_pm",
                      "input_wait_dsp_external_dm", "input_wait_dsp_device",
                      "input_poll_dsp_pm", "input_poll_dsp_dm", "input_poll_dsp_control",
                      "input_poll_dsp_external_pm", "input_poll_dsp_external_dm", "input_poll_dsp_device", "sport_pcm", "sport_dma_reads", "sport_dac_buffer", *reference.RETURN_RAM_KEYS):
            observed = dict(native, **{field: copy.deepcopy(native[field])})
            observed[field].pop()
            self.assertFalse(reference.compare_dsp(native, observed)["passed"])
        for field in ("post_factory_dsp_pm", "post_factory_dsp_dm", "post_factory_dsp_control", "sound_command_dsp_pm", "sound_command_dsp_dm", "sound_command_dsp_control", "dsp_external_pm", "dsp_external_dm", "dsp_device",
                      "input_wait_dsp_pm", "input_wait_dsp_dm", "input_wait_dsp_control", "input_wait_dsp_external_pm",
                      "input_wait_dsp_external_dm", "input_wait_dsp_device",
                      "input_poll_dsp_pm", "input_poll_dsp_dm", "input_poll_dsp_control",
                      "input_poll_dsp_external_pm", "input_poll_dsp_external_dm", "input_poll_dsp_device", "sport_pcm", "sport_dma_reads", "sport_dac_buffer"):
            incomplete = dict(native); del incomplete[field]
            with self.subTest(missing_post_factory=field):
                self.assertFalse(reference.compare_dsp(incomplete, native)["passed"])
                self.assertFalse(reference.compare_dsp(native, incomplete)["passed"])
        observed = dict(native, post_factory_dsp_dm=native["dsp_dm"])
        self.assertFalse(reference.compare_dsp(native, observed)["passed"])

    def test_sport_dma_provenance_order_and_independent_lua_observations(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        records = ["MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        cpu = "MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23"
        records += [cpu, "MK2_DCS_CONTROL C00"]
        packets, lua = [], []
        for tick, pc, previous, cycle, first, after in reference.SPORT_PACKETS:
            dma_symbols = symbols.replace("pc = 0\n", f"pc = {pc:X}\n").replace("totalcycles = 0", f"totalcycles = {cycle:X}") + f"\ncurpc = {previous:X}"
            packets.append([f"MK2_DSP_ACCESS 72 {address:X} {address & 1:X}\n" + dma_symbols for address in range(first, first + 240)])
            lua.extend((tick, pc, address, address & 1) for address in range(first, first + 240))
        parsed = reference.parse_dsp("\n".join(records + [record for packet in packets for record in packet + [cpu]]))
        self.assertEqual(len(parsed["dsp_accesses"]), 4)
        self.assertEqual(parsed["sport_dma_positions"], [1, 2, 3])
        raw = parsed["sport_dma_raw"]
        observed = reference.sport_dma_observations(raw, lua, parsed["sport_dma_positions"])
        self.assertEqual(observed["sport_dma_reads"][240], [7993490, 0x131, 158526, 0x4f0, 0])
        for wrong_raw, wrong_lua, positions in ((raw[:-1], lua, [1, 2, 3]), (raw[::-1], lua, [1, 2, 3]), (raw, lua[:-1], [1, 2, 3]),
                                               (raw, lua[::-1], [1, 2, 3]), (raw, lua, None), (raw, lua, [2, 1, 3])):
            with self.assertRaises(ValueError): reference.sport_dma_observations(wrong_raw, wrong_lua, positions)
        for packet in range(len(packets)):
            for column in range(4):
                wrong = list(lua); row = list(wrong[packet * 240 + 239]); row[column] ^= 1; wrong[packet * 240 + 239] = tuple(row)
                with self.assertRaises(ValueError): reference.sport_dma_observations(raw, wrong, [1, 2, 3])
            prefix = records + [record for previous in packets[:packet] for record in previous + [cpu]]
            suffix = [record for following in packets[packet + 1:] for record in following + [cpu]]
            with self.assertRaisesRegex(ValueError, "Non-contiguous SPORT"):
                reference.parse_dsp("\n".join(prefix + packets[packet][:2] + [cpu] + packets[packet][2:] + suffix))
        regular = reference.parse_dsp("\n".join(records + [packets[0][0].replace("curpc = 138", "curpc = 137")]))
        self.assertEqual(regular["sport_dma_raw"], [])
        self.assertEqual(len(regular["dsp_accesses"]), 2)

    def test_historical_button_counts_stop_at_observed_boundary(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        serial = symbols.replace("pc = 0\n", "pc = 829\n")
        reboot = "MK2_DSP_ACCESS 64 3FFF 208\n" + symbols + "\ncurpc = 42"
        control = "MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23"
        records = ["MK2_DSP_BEGIN 0D0CB0\n" + serial, "MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        records += [reboot, control, "MK2_BUTTON_EXIT_DCS_CONTROL C00", "MK2_BUTTON_EXIT_BOUNDARY",
                    "MK2_DSP_BEGIN 0D0CB0\n" + serial, reboot, "MK2_DCS_CONTROL C00"]
        parsed = reference.parse_dsp("\n".join(records))
        self.assertEqual(parsed["button_exit_event_counts"], [2, 2, 1, 1, 0, 0, 0, 0])
        self.assertEqual(parsed["button_exit_dcs_control"], 0xc00)
        self.assertEqual(len(parsed["dsp_trace"]), 3)
        self.assertEqual(len(parsed["dsp_accesses"]), 3)
        with self.assertRaisesRegex(ValueError, "Duplicate historical button boundary"):
            reference.parse_dsp("\n".join(records + ["MK2_BUTTON_EXIT_BOUNDARY"]))
        records = [row.replace("MK2_BUTTON_EXIT_", "MK2_VIDEO_IRQ_") for row in records]
        parsed = reference.parse_dsp("\n".join(records))
        self.assertEqual(parsed["video_irq_event_counts"], [2, 2, 1, 1, 0, 0, 0, 0])
        self.assertEqual(parsed["video_irq_dcs_control"], 0xc00)
        with self.assertRaisesRegex(ValueError, "Duplicate historical video IRQ boundary"):
            reference.parse_dsp("\n".join(records + ["MK2_VIDEO_IRQ_BOUNDARY"]))
        records = [row.replace("MK2_VIDEO_IRQ_", "MK2_DISPATCHER_") for row in records]
        parsed = reference.parse_dsp("\n".join(records))
        self.assertEqual(parsed["dispatcher_event_counts"], [2, 2, 1, 1, 0, 0, 0, 0])
        self.assertEqual(parsed["dispatcher_dcs_control"], 0xc00)
        with self.assertRaisesRegex(ValueError, "Duplicate historical dispatcher boundary"):
            reference.parse_dsp("\n".join(records + ["MK2_DISPATCHER_BOUNDARY"]))

    def test_serial_tx_counts_require_the_observed_opcode_at_reused_pc(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        serial = symbols.replace("pc = 0\n", "pc = 829\n")
        records = ["MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        records += ["MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23", "MK2_DCS_CONTROL C00"]
        records += ["MK2_DSP_BEGIN 0D0CB0\n" + serial] * 2
        records += ["MK2_DISPATCHER_BOUNDARY"]
        records += ["MK2_DSP_BEGIN 806114\n" + serial] * 8
        records += ["MK2_TASK_RESUME_BOUNDARY"]
        records += ["MK2_TASK_QUEUE_DCS_CONTROL C00", "MK2_TASK_QUEUE_BOUNDARY"]
        parsed = reference.parse_dsp("\n".join(records))
        self.assertEqual(parsed["dispatcher_event_counts"][3], 2)
        self.assertEqual(parsed["task_resume_event_counts"][3], 2)
        self.assertEqual(len(parsed["dsp_trace"]), 11)
        self.assertTrue(all(len(row) == 76 for row in parsed["dsp_trace"]))
        self.assertEqual(parsed["task_queue_event_counts"], parsed["task_resume_event_counts"])
        self.assertEqual(parsed["task_queue_dcs_control"], 0xc00)
        self.assertTrue(all(parsed["task_queue_" + key] == [] for key in
                            ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events")))
        for duplicate in ("MK2_TASK_QUEUE_DCS_CONTROL C00", "MK2_TASK_QUEUE_BOUNDARY"):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                reference.parse_dsp("\n".join(records + [duplicate]))

    def test_serial_pc_requires_one_known_observed_opcode(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS).replace("pc = 0\n", "pc = 829\n")
        for header in ("MK2_DSP_BEGIN", "MK2_DSP_BEGIN FFFFFF", "MK2_DSP_BEGIN 0D0CB0 0D0CB0"):
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, "0829 opcode"):
                reference.parse_dsp(header + "\n" + symbols)

    def test_irq1_hook_preserves_exact_cycles_without_expanding_instruction_fields(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        records = ["MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        records += ["MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23", "MK2_DCS_CONTROL C00"]
        irq = symbols.replace("pc = 0\n", "pc = 131\n").replace("totalcycles = 0", "totalcycles = 26B3F")
        parsed = reference.parse_dsp("\n".join(records + ["MK2_DSP_IRQ1\n" + irq + "\nirq1 = 1"]))
        self.assertEqual(len(parsed["dsp_trace"][0]), 76)
        self.assertEqual(parsed["sport_irq1_hooks"], [[0x131, 158527, 1]])
        with self.assertRaisesRegex(ValueError, "Missing IRQ1"):
            reference.parse_dsp("\n".join(records + ["MK2_DSP_IRQ1\n" + irq]))

    def test_sport_dma_expected_reads_use_observed_instruction_predecessor(self):
        trace, events = [], []
        i7 = reference.DSP_REGISTERS.index("i7")
        for tick, pc, previous, cycle, first, after in reference.SPORT_PACKETS:
            before, following = [0]*len(reference.DSP_REGISTERS), [0]*len(reference.DSP_REGISTERS)
            before[:2], following[:2] = [previous, cycle], [pc, cycle + 1]
            before[i7], following[i7] = first, after
            trace.extend((before, following)); events.append([tick, pc, cycle + 1, 7, first, after, 240])
        native = {"sport_transfers": events, "sport_pcm": [0]*(reference.SPORT_SAMPLES - 1)+[-1], "dsp_trace": trace}
        expected = reference.native_sport_dma_reads(native)
        self.assertEqual(expected[-1], [8761490, 0x137, 235326, 0x4ef, 0xffff])
        for field in ("sport_transfers", "sport_pcm", "dsp_trace"):
            bad = dict(native, **{field: copy.deepcopy(native[field])}); bad[field].pop()
            with self.assertRaises(ValueError): reference.native_sport_dma_reads(bad)
        for packet in range(len(reference.SPORT_PACKETS)):
            for column in range(7):
                bad = dict(native, sport_transfers=copy.deepcopy(native["sport_transfers"])); bad["sport_transfers"][packet][column] ^= 1
                with self.assertRaises(ValueError): reference.native_sport_dma_reads(bad)
        self.assertEqual(reference.native_dac_buffer([0, 32767]), [0, 0x3f800000])
        self.assertEqual(reference.native_dac_buffer([1, -1]), [0x38000100, 0xb8000100])

    def test_task_resume_dma_disambiguates_reset_cycles_from_historical_packets(self):
        packets = ((13552570, 0x136, 0x138, 81726, 0x400, 0x4f0),
                   (14320570, 0x131, 0x130, 158526, 0x4f0, 0x400),
                   (15088570, 0x138, 0x137, 235326, 0x400, 0x4f0),
                   (15856570, 0x131, 0x130, 312126, 0x4f0, 0x400),
                   (16624570, 0x137, 0x136, 388926, 0x400, 0x4f0),
                   (17392570, 0x131, 0x130, 465726, 0x4f0, 0x400),
                   (18160570, 0x136, 0x138, 542526, 0x400, 0x4f0))
        trace, events = [], []
        i7 = reference.DSP_REGISTERS.index("i7")
        for tick, pc, previous, cycle, first, after in (*reference.SPORT_PACKETS, *packets):
            before, following = [0]*len(reference.DSP_REGISTERS), [0]*len(reference.DSP_REGISTERS)
            before[:2], following[:2] = [previous, cycle], [pc, cycle+1]
            before[i7], following[i7] = first, after
            trace.extend((before, following)); events.append([tick, pc, cycle+1, 7, first, after, 240])
        native = {"sport_transfers": events[:3], "sport_pcm": [0]*720, "dsp_trace": trace,
                  "dispatcher_event_counts": [6, 0, 0, 0, 720, 2, 3, 3],
                  "task_resume_transfers": events[3:], "task_resume_pcm": [0]*1680}
        self.assertEqual(len(reference.native_sport_dma_reads(native)), 720)
        self.assertEqual(len(reference.native_sport_dma_reads(native, phase="task_resume")), 1680)
        for column in range(7):
            bad = dict(native, task_resume_transfers=copy.deepcopy(native["task_resume_transfers"])); bad["task_resume_transfers"][-1][column] ^= 1
            with self.subTest(suffix_transfer_column=column), self.assertRaises(ValueError):
                reference.native_sport_dma_reads(bad, phase="task_resume")
        bad = dict(native, dispatcher_event_counts=[0]*8)
        with self.assertRaises(ValueError): reference.native_sport_dma_reads(bad, phase="task_resume")

    def test_task_palette_dma_uses_its_measured_hooks_and_historical_boundary(self):
        packets = ((18928570, 0x132, 0x131, 619326, 0x4f0, 0x400),
                   (19696570, 0x138, 0x137, 696126, 0x400, 0x4f0))
        self.assertEqual(getattr(reference, "TASK_PALETTE_SPORT_PACKETS", ()), packets)
        trace, events, raw, lua = [[0]*76], [], [], []
        i7 = reference.DSP_REGISTERS.index("i7")
        for tick, pc, previous, cycle, first, after in packets:
            before, following = [0]*76, [0]*76
            before[:2], following[:2] = [previous, cycle], [pc, cycle+1]
            before[i7], following[i7] = first, after
            trace.extend((before, following)); events.append([tick, pc, cycle+1, 7, first, after, 240])
            raw.extend([[114, previous, first+i, i, cycle] for i in range(240)])
            lua.extend([(tick, pc, first+i, i) for i in range(240)])
        native = {"task_palette_transfers": events, "task_palette_pcm": list(range(240))*2, "dsp_trace": trace,
                  "task_queue_event_counts": [1]*8, "dispatcher_event_counts": [1]*8}
        reads = reference.native_sport_dma_reads(native, phase="task_palette")
        observed = reference.sport_dma_observations(raw, lua, [1, 1], phase="task_palette")
        self.assertEqual(reads, observed["task_palette_dma_reads"])
        self.assertEqual(events, observed["task_palette_transfers"])
        for column in range(7):
            bad = dict(native, task_palette_transfers=copy.deepcopy(native["task_palette_transfers"])); bad["task_palette_transfers"][-1][column] ^= 1
            with self.subTest(column=column), self.assertRaises(ValueError):
                reference.native_sport_dma_reads(bad, phase="task_palette")
        for column in range(5):
            bad = copy.deepcopy(raw); bad[-1][column] ^= 1
            with self.subTest(raw_column=column), self.assertRaises(ValueError):
                reference.sport_dma_observations(bad, lua, [1, 1], phase="task_palette")
        with self.assertRaisesRegex(ValueError, "boundary"):
            reference.native_sport_dma_reads(dict(native, task_queue_event_counts=[6]*8), phase="task_palette")

    def test_task_palette_parser_freezes_historical_dma_and_requires_new_packets(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        records = ["MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        records += ["MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23", "MK2_DCS_CONTROL C00"]
        def packet_rows(packets):
            result = []
            for _, pc, previous, cycle, first, _ in packets:
                state = symbols.replace("pc = 0\n", f"pc = {pc:X}\n").replace("totalcycles = 0", f"totalcycles = {cycle:X}")
                result += [f"MK2_DSP_ACCESS 72 {first+i:X} {i:X}\n" + state + f"\ncurpc = {previous:X}" for i in range(240)]
            return result
        records += packet_rows(reference.SPORT_PACKETS) + ["MK2_DISPATCHER_BOUNDARY"]
        records += packet_rows(reference.TASK_RESUME_SPORT_PACKETS) + ["MK2_TASK_RESUME_BOUNDARY", "MK2_TASK_QUEUE_BOUNDARY"]
        new_rows = packet_rows(reference.TASK_PALETTE_SPORT_PACKETS)
        records += new_rows
        for pc, cycle in reference.DSP_IRQ_HOOKS[-2:]:
            state = symbols.replace("pc = 0\n", f"pc = {pc:X}\n").replace("totalcycles = 0", f"totalcycles = {cycle:X}")
            records.append("MK2_DSP_IRQ1\n" + state + "\nirq1 = 0")
        records += ["MK2_TASK_PALETTE_DCS_CONTROL C00", "MK2_TASK_PALETTE_BOUNDARY"]
        parsed = reference.parse_dsp("\n".join(records))
        self.assertTrue("task_palette_event_counts" in parsed)
        self.assertEqual(len(parsed["task_resume_dma_raw"]), 1680)
        self.assertEqual(len(parsed["task_palette_dma_raw"]), 480)
        self.assertEqual(len(parsed["task_palette_dma_positions"]), 2)
        self.assertEqual(parsed["task_palette_event_counts"][4:], [2880, 2, 12, 12])
        self.assertEqual(parsed["task_queue_event_counts"][4:], [2400, 0, 10, 10])
        tail = ["MK2_DSP_BEGIN\n" + symbols, "MK2_DSP_ACCESS 64 3800 1\n" + symbols + "\ncurpc = 131",
                "MK2_TASK_DRAW_DCS_CONTROL C00", "MK2_TASK_DRAW_BOUNDARY"]
        drawn = reference.parse_dsp("\n".join(records + tail))
        self.assertEqual(drawn["task_palette_event_counts"], parsed["task_palette_event_counts"])
        self.assertEqual(drawn["task_draw_event_counts"][:2], [value + 1 for value in parsed["task_palette_event_counts"][:2]])
        self.assertEqual(drawn["task_draw_event_counts"][4:], parsed["task_palette_event_counts"][4:])
        for suffix in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events"):
            self.assertEqual(drawn["task_draw_" + suffix], [])
        for duplicate in ("MK2_TASK_DRAW_DCS_CONTROL C00", "MK2_TASK_DRAW_BOUNDARY"):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                reference.parse_dsp("\n".join(records + tail + [duplicate]))
        for missing in ("MK2_TASK_PALETTE_BOUNDARY", new_rows[-1]):
            bad = records[:]; bad.remove(missing)
            with self.subTest(draw_missing=missing[:40]), self.assertRaises(ValueError):
                reference.parse_dsp("\n".join(bad + tail))
        for duplicate in ("MK2_TASK_PALETTE_DCS_CONTROL C00", "MK2_TASK_PALETTE_BOUNDARY"):
            with self.subTest(duplicate=duplicate), self.assertRaises(ValueError):
                reference.parse_dsp("\n".join(records + [duplicate]))
        for missing in ("MK2_TASK_QUEUE_BOUNDARY", new_rows[-1]):
            bad = records[:]; bad.remove(missing)
            with self.subTest(missing=missing[:40]), self.assertRaises(ValueError):
                reference.parse_dsp("\n".join(bad))

    def test_task_resume_dma_parser_keeps_last_lane_before_serial_symbol_snapshot(self):
        symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        records = ["MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        records += ["MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23", "MK2_DCS_CONTROL C00"]
        lua = []
        for phase, packets in enumerate((reference.SPORT_PACKETS, reference.TASK_RESUME_SPORT_PACKETS)):
            if phase: records += ["MK2_DISPATCHER_BOUNDARY"]
            for tick, pc, previous, cycle, first, after in packets:
                state = symbols.replace("pc = 0\n", f"pc = {pc:X}\n").replace("totalcycles = 0", f"totalcycles = {cycle:X}") + f"\ncurpc = {previous:X}"
                records += [f"MK2_DSP_ACCESS 72 {address:X} {address & 1:X}\n" + state for address in range(first, first+240)]
                records += ["MK2_DSP_BEGIN 806114\n" + symbols.replace("pc = 0\n", "pc = 829\n")]
                if phase: lua += [(tick, pc, address, address & 1) for address in range(first, first+240)]
        parsed = reference.parse_dsp("\n".join(records))
        self.assertEqual(len(parsed["sport_dma_raw"]), 720)
        self.assertEqual(len(parsed["task_resume_dma_raw"]), 1680)
        raw = parsed["task_resume_dma_raw"]
        observed = reference.sport_dma_observations(raw, lua, parsed["task_resume_dma_positions"], phase="task_resume")
        self.assertEqual(len(observed["task_resume_pcm"]), 1680)
        bad = copy.deepcopy(raw); bad[-1][-1] += 1
        with self.assertRaises(ValueError): reference.sport_dma_observations(bad, lua, parsed["task_resume_dma_positions"], phase="task_resume")
        bad = list(records); bad[-1] = bad[-1].replace("MK2_DSP_BEGIN 806114\n", "")
        with self.assertRaisesRegex(ValueError, "Duplicate ADSP symbol"):
            reference.parse_dsp("\n".join(bad))
        with self.assertRaisesRegex(ValueError, "Non-contiguous SPORT DMA"):
            reference.parse_dsp("\n".join(row for row in records if row != "MK2_DISPATCHER_BOUNDARY"))

    def test_dsp_symbol_parser_rejects_missing_duplicate_and_echo_only(self):
        symbol_lines = [f"{reg} = 0" for reg in reference.DSP_REGISTERS]
        symbols = "\n".join(symbol_lines)
        records = ["MK2_DSP_BEGIN\n" + symbols]
        records += ["MK2_DSP_POINT " + name + "\n" + symbols for name in reference.POINTS]
        records += ["MK2_DSP_ACCESS 64 3FFF 10\n" + symbols + "\ncurpc = 23", "MK2_DCS_CONTROL C00",
                    "MK2_CMOS_READ FFA4D330 1400F40 0 219", "MK2_SOUND_RAM 10FFED0 FFA4BC10",
                    "MK2_CHECKED_RAM 10B95A0 3C",
                    "MK2_CMOS_WRITE FFA4D3A0 1480000 5A01 497",
                    "MK2_CMOS_WRITE FFA4D3B0 1400F30 3 498",
                    "MK2_ROUTINE_RAM 10FFF10 815", "MK2_RESTORED_RAM 10FFEF0 3D",
                    "MK2_RETURNED_RAM 10FFFD0 FF8111F0"]
        text = "\n".join(records)
        post_symbols = "\n".join(f"{reg} = 0" for reg in reference.DSP_REGISTERS)
        text += "\nMK2_DSP_POST_FACTORY_PIXBLT\n" + post_symbols
        text += "\nMK2_DSP_INPUT_WAIT_PIXBLT\n" + post_symbols
        poll_symbols = post_symbols.replace("se = 0", "se = FFFFFFFFFFFFFFF8").replace("sb = 0", "sb = FFFFFFFFFFFFFFF0").replace("mr2 = 0", "mr2 = FFFFFFFFFFFFFFFF")
        text += "\nMK2_DSP_INPUT_POLL_PIXBLT\n" + poll_symbols
        parsed = reference.parse_dsp(text)
        self.assertEqual(parsed["input_wait_pixblt_dsp"], [[0]*len(reference.DSP_REGISTERS)])
        poll = parsed["input_poll_pixblt_dsp"][0]
        for name, value in (("se",0xfffffffffffffff8),("sb",0xfffffffffffffff0),("mr2",0xffffffffffffffff)):
            self.assertEqual(poll[reference.DSP_REGISTERS.index(name)],value)
        self.assertEqual(parsed["post_factory_pixblt_dsp"], [[0]*len(reference.DSP_REGISTERS)])
        self.assertEqual(reference.parse_dsp(iter(text.splitlines(True))), parsed)
        self.assertEqual(len(parsed["dsp_trace"]), 1)
        self.assertEqual(parsed["dsp_accesses"], [[100, 35, 16383, 16, 0]])
        self.assertEqual(parsed["cmos_reads"], [[0xffa4d320, 0x01400f40, 0, 537]])
        self.assertEqual(parsed["cmos_writes"], [[0xffa4d370, 0x01480000, 0x5a01, 1175],
                                                  [0xffa4d3a0, 0x01400f30, 3, 1176]])
        self.assertEqual(parsed["routine_ram"], [[0x010fff10, 0x815]])
        self.assertEqual(parsed["restored_ram"], [[0x010ffef0, 0x3d]])
        self.assertEqual(parsed["returned_ram"], [[0x010fffd0, 0xff8111f0]])
        self.assertEqual(parsed["checked_ram"], [[0x010b95a0, 0x3c]])
        self.assertEqual(parsed["sound_ram"], [[0x010ffed0, 0xffa4bc10]])
        for bad in ("", '>bpset 0,1,{printf "MK2_DSP_BEGIN";g}',
                    text.replace(symbol_lines[-1], ""), text + "\n" + records[1],
                    text + "\nMK2_CMOS_READ FFA4D330 1400F40 0",
                    text + "\nMK2_CMOS_WRITE FFA4D3B0 1400F30 1",
                    text + "\nMK2_ROUTINE_RAM 10FFF10",
                    text.replace("pc = 0\n", "pc = 0\npc = 0\n", 1)):
            with self.subTest(text=bad[:50]), self.assertRaises(ValueError):
                reference.parse_dsp(bad)


if __name__ == "__main__":
    unittest.main()
