import hashlib
import unittest

from tools.mk2 import generate_architectural as architectural, oracle_digest


class StaticBatchTests(unittest.TestCase):
    def test_original_cmos_boot_text_and_wide_glyph_are_data(self):
        from tools.mk2 import static_batch

        image = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        spans = set(static_batch.boot_text_data(image))
        self.assertTrue({(0xffa6abb0, 8, 0xffa59180), (0xffa6a6c0, 19, 0xffa59180),
                         (0xffa57d70, 4, 0xffa591f0), (0xffa57350, 8, 0xffa59200),
                         (0xffa58690, 16, 0xffa592b0)} <= spans)
        changed = bytearray(image)
        changed[(0xffa6abb0-static_batch.BASE)//8] ^= 1
        with self.assertRaisesRegex(ValueError, 'Boot text differs'):
            static_batch.boot_text_data(changed)

    def test_original_service_text_preserves_label_padding_and_glyph_spans(self):
        from tools.mk2 import static_batch

        image = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        spans = set(static_batch.boot_text_data(image))
        self.assertTrue({(0xffa6ff00, 5, 0xffa59180), (0xffa6ff30, 5, 0xffa59180),
                         (0xffa70c90, 22, 0xffa59180), (0xffa57970, 4, 0xffa591f0),
                         (0xffa56cd0, 8, 0xffa59200), (0xffa58010, 8, 0xffa592b0)} <= spans)
        self.assertFalse(any(address <= 0xffa6ff28 < address+size*8 for address, size, _ in spans))
        changed = bytearray(image)
        changed[(0xffa6ff00-static_batch.BASE)//8] = ord('X')
        with self.assertRaisesRegex(ValueError, 'Service text differs'):
            static_batch.boot_text_data(changed)

    def test_original_u3_unpack_preserves_physical_gaps_and_authenticates_bytes(self):
        import json
        from unittest.mock import patch
        from tools.mk2 import static_batch
        from tools.quality import run as q

        directory = static_batch.ROOT/'roms/mk2'
        roms = static_batch.run.read_manifest()['roms']
        spans = static_batch.dcs_data_spans(directory, roms)['su3.l1']
        self.assertEqual(len(spans), 360)
        self.assertEqual(sum(end-start for start,end,_ in spans), 5826)
        self.assertEqual(spans[0], (0x63058, 0x6305a, 2))
        self.assertEqual(spans[-1], (0x65222, 0x65228, 2))
        self.assertFalse(any(start <= 0x6305a < end for start,end,_ in spans))
        changed = bytearray((directory/'su3.l1').read_bytes())
        changed[0x63058] ^= 1
        with q.scratch_tree() as (scratch, cleanup):
            (scratch/'su3.l1').write_bytes(changed)
            with self.assertRaisesRegex(ValueError, 'DCS data evidence offsets or bytes differ'):
                static_batch.dcs_data_spans(scratch, roms)
            evidence = json.loads((static_batch.ROOT/'tools/mk2/dcs_data_reads.json').read_text(encoding='utf8'))
            self.assertEqual(changed[9805:9807], bytes.fromhex('cef5'))
            evidence['physical_intervals'][0] = [9805, 9807]
            (scratch/'dcs_data_reads.json').write_text(json.dumps(evidence), encoding='utf8')
            with patch.object(static_batch, '__file__', str(scratch/'static_batch.py')):
                with self.assertRaisesRegex(ValueError, 'DCS data evidence offsets or bytes differ'):
                    static_batch.dcs_data_spans(directory, roms)
        self.assertFalse(cleanup['exists_after'])

    def test_replayed_program_reads_authenticate_spans_and_reader_roots(self):
        from tools.mk2 import static_batch

        rom = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        spans, roots = static_batch.tms_replay_data(rom)
        self.assertEqual(len(spans), 535)
        self.assertEqual(sum(end-start for start,end,_ in spans), 28066)
        self.assertEqual(spans[:2], [(3216, 3224, 2), (3240, 3248, 2)])
        self.assertEqual(len(roots), 16)
        self.assertIn(0xff9faef0, roots)
        changed = bytearray(rom)
        changed[3216] ^= 1
        with self.assertRaisesRegex(ValueError, 'TMS replay data offsets or bytes differ'):
            static_batch.tms_replay_data(changed)

    def test_observed_transfers_add_targets_without_closing_computed_domains(self):
        from tools.mk2 import static_batch

        rom = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        rows, _ = static_batch.scan_aligned(rom)
        witnessed = static_batch.tms_observed_transfers(rows)
        self.assertEqual(len(witnessed), 85)
        self.assertEqual(sum(map(len, witnessed.values())), 278)
        graph, _, _, open_edges = static_batch.tms_graph(rom, rows, witnessed_transfers=witnessed)
        self.assertEqual(graph[0xff80c270], (0xff8093a0, 0xff80c280))
        self.assertEqual(witnessed[0xff9fa130], (0xff9fb190, 0xff9fb220))
        self.assertIn(0xff80c270, open_edges['computed:CALL'])
        self.assertIn(0xff9fa130, open_edges['computed:JUMP'])
        self.assertIn(0xff809570, open_edges['computed:RETS'])
        self.assertTrue(set(witnessed[0xff809570]) <= set(graph[0xff809570]))
        scheduler = 0xff80de00
        from tools.mk2 import tms_lane_witnesses as witnesses
        segments = witnesses.load()['groups']['round6_jump']
        targets = {segment['pcs'][1] for segment in segments if segment['pcs'][0] == scheduler}
        self.assertEqual(set(witnessed[scheduler]), targets)
        self.assertEqual(set(graph[scheduler]), targets | set(architectural.JUMP_EVIDENCE[scheduler][1]))
        self.assertIn(scheduler, open_edges['computed:JUMP'])
        rows[0xff9fa130] = rows[0xff80c270]
        with self.assertRaisesRegex(ValueError, 'TMS observed transfer source differs'):
            static_batch.tms_observed_transfers(rows)

    def test_original_dcs_sample_playback_authenticates_six_physical_sockets(self):
        from tools.mk2 import static_batch
        from tools.quality import run as q

        directory = static_batch.ROOT/'roms/mk2'
        roms = static_batch.run.read_manifest()['roms']
        groups = static_batch.dcs_playback_spans(directory, roms)
        self.assertEqual({name:sum(end-start for start,end,_ in spans) for name,spans in groups.items()},
                         {'su2.l1':40034, 'su3.l1':52618, 'su4.l1':43072,
                          'su5.l1':44544, 'su6.l1':63708, 'su7.l1':41918})
        self.assertEqual(groups['su2.l1'][:2], [(176940,177014,2), (177020,177102,2)])
        changed = bytearray((directory/'su2.l1').read_bytes())
        changed[176940] ^= 1
        with q.scratch_tree() as (scratch, cleanup):
            (scratch/'su2.l1').write_bytes(changed)
            with self.assertRaisesRegex(ValueError, 'DCS data evidence offsets or bytes differ'):
                static_batch.dcs_playback_spans(scratch, roms)
        self.assertFalse(cleanup['exists_after'])

    def test_original_dcs_voice_script_preserves_unclassified_delay(self):
        from tools.mk2 import static_batch

        directory = static_batch.ROOT/'roms/mk2'
        spans = static_batch.dcs_data_spans(directory, static_batch.run.read_manifest()['roms'])['su2.l1']
        self.assertEqual(len(spans), 68)
        self.assertEqual(sum(end-start for start,end,_ in spans), 1481)
        self.assertTrue(all(end <= 0x5602 or start >= 0x5604 for start,end,_ in spans))

    def test_authenticated_loop_field_and_revision_forms(self):
        from tools.mk2 import generate_video_irq as emitter, generate_static_cfg as cfg, offline_decode
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests
        image = emitter.load_program(emitter.ROOT/'roms/mk2')
        loop, field, revision = 0xff940cd0, 0xff940750, 0xff810960
        rows, _ = offline_decode.decode(image, (loop, field, revision))
        self.assertEqual(cfg.direct_targets(loop, 32, rows[loop][3], 0), (0xff940630, 0xff940cf0))

        def code(pc, targets):
            width, _, words, asm = rows[pc]
            return emitter.emit_instruction(pc, width, asm, words, set(targets), {}, batch_forms=True)

        body = '''
    for (unsigned zero=0;zero<2;++zero) for (uint32_t count: {0u,1u,2u}) {
        const auto cycles=s.cycles;
        const uint32_t status=0xd0000010u|(zero<<29);
        s.status=status; s.b[0]=count; s.next_pc=0xff940cd0u;
''' + code(loop, (0xff940630, 0xff940cf0)) + '''
        const bool taken=zero && count!=1;
        if(s.b[0]!=count-zero || s.status!=status || s.cycles-cycles!=(taken?3:2) ||
           s.next_pc!=(taken?0xff940630u:0xff940cf0u))return 1;
    }
    {
        const auto cycles=s.cycles;
        s.status=0xd0000110u; s.a[0]=0xffff0100u; s.next_pc=0xff940750u;
''' + code(field, (field+16,)) + '''
        if(s.a[0] || s.status!=0xf0000110u || s.cycles-cycles!=1 || s.next_pc!=0xff940760u)return 2;
    }
    {
        const auto cycles=s.cycles;
        const auto status=s.status;
        s.b[0]=0xffffffffu; s.next_pc=0xff810960u;
''' + code(revision, (revision+16,)) + '''
        if(s.b[0]!=8 || s.status!=status || s.cycles-cycles!=1 || s.next_pc!=0xff810970u)return 3;
    }
'''
        CoinPairPrimitiveTests.compile_and_run(self, body)

    def test_partition_links_the_same_pages_from_independent_ranges(self):
        source = ('case 0xff800010u: { // NOP\n    o.Finish(0xff800020u,1);\n    break;\n}\n'
                  'case 0xff880010u: { // RETS\n    o.ReturnSubroutine(0);\n    break;\n}\n')
        shards = {}
        dispatcher = architectural.partition(source, shards=shards)
        self.assertEqual(set(shards), {0xff800000, 0xff880000})
        self.assertIn('bool FirstFightPage_ff800(BootOps&);', dispatcher)
        self.assertIn('case 1046528:return FirstFightPage_ff800(o);', dispatcher)
        self.assertNotIn('o.Finish(', dispatcher)
        self.assertIn('o.Finish(0xff800020u,1);', shards[0xff800000])
        self.assertIn('o.ReturnSubroutine(0);', shards[0xff880000])

    def test_code_evidence_uses_inline_pointer_without_falling_into_its_data(self):
        from tools.mk2.static_batch import successors
        pc = 0xff9ba100
        image = bytearray(0x100000)
        offset = (pc + 48 - 0xff800000) // 8
        image[offset:offset+4] = (0xff9ba800).to_bytes(4, 'little')
        targets, data = successors(image, pc, 48, 'CALLA FF83D7E0h', 0xff8045d0)
        self.assertEqual(set(targets), {0xff83d7e0, pc+80, 0xff9ba800})
        self.assertEqual(data, (offset, offset+4))

    def test_inline_selectors_consume_one_or_two_pointer_words(self):
        from tools.mk2.static_batch import BASE, successors
        pc = 0xff8e4880
        offset = (pc + 48 - BASE) // 8
        image = bytearray(offset + 8)
        pointers = (0xff8e4900, 0xff8e4a00)
        for index, pointer in enumerate(pointers):
            image[offset+index*4:offset+index*4+4] = pointer.to_bytes(4, 'little')
        for callee, targets, width in (
                (0xff83d710, {pointers[0], pc+80}, 4),
                (0xff9c9b80, set(pointers) | {pc+112}, 8),
                (0xff9c9ca0, set(pointers), 8)):
            with self.subTest(callee=hex(callee)):
                actual, data = successors(image, pc, 48, f'CALLA {callee:X}h', 0)
                self.assertEqual(set(actual), {callee} | targets)
                self.assertEqual(data, (offset, offset+width))

    def test_authenticated_cfg_closes_bounded_tables_and_excludes_inline_data(self):
        from tools.mk2 import generate_video_irq as emitter, static_batch
        rom = emitter.load_program(emitter.ROOT/'roms/mk2')
        rows, _ = static_batch.scan_aligned(rom)
        graph, data, _, open_edges = static_batch.tms_graph(rom, rows)
        for site, base, slots, targets in (
                (0xff836e10, 0xff836e30, 3, (0xffa14780, 0xffa147a0, 0xffa14500)),
                (0xff83bbf0, 0xff83bc00, 10, (0xff83be70, 0xff83be90, 0xff83bec0,
                    0xff83bf10, 0xff83bf60, 0xff83be40, 0xff83bdf0, 0xff83bd70, 0xff83bd40)),
                (0xff9b6bf0, 0xff9b6c30, 3, (0xff9b6f80, 0xff9b6c90, 0xff9b7230)),
                (0xffa49cb0, 0xffa49cc0, 5, (0xffa49d60, 0xffa49e60, 0xffa49ee0,
                    0xffa49f60, 0xffa49fc0)),
                (0xffa51fb0, 0xffa521d0, 9, (0xffa520c0, 0xffa51fc0))):
            with self.subTest(site=hex(site)):
                self.assertEqual(set(graph[site]), set(targets))
                self.assertTrue(set(targets) <= graph.keys())
                offset = (base - static_batch.BASE) // 8
                self.assertEqual(data[offset], offset + slots * 4)
                self.assertNotIn(site, open_edges['computed:JUMP'])
        # Decoded text of the table-call chain, from the user's ROM; only its SHA-256 is versioned.
        chain = (0xffa49c10, 0xffa49c20, 0xff80eaf0, 0xff80eb00, 0xff80e980, 0xff80eab0,
                 0xff80eb20, 0xff80eb30, 0xffa49c50, 0xffa49c60, 0xffa49c70, 0xffa49ca0)
        listing = '\n'.join(f"{pc:08x} {' '.join(rows[pc][3].split())}" for pc in chain)
        self.assertEqual(hashlib.sha256(listing.encode('ascii')).hexdigest(),
                         '9efb3b1d0ee66e657782e7a596ceda756346f526730a7eced4834030e474dd85')
        self.assertIn(0xff888df0, open_edges['computed:JUMP'])
        for site, slot, target in ((0xff878130, 0xff8781e0, 0xff86bc60),
                                   (0xff888df0, 0xff888fa0, 0xff892e70),
                                   (0xff81a320, 0xff81a330, 0xff81a3b0)):
            self.assertEqual(graph[site], (target,))
            self.assertIn(site, open_edges['computed:JUMP'])
            offset = (slot-static_batch.BASE)//8
            self.assertEqual(data[offset], offset+4)
        for address, size in ((0xffa03fc0, 12), (0xffa04320, 96), (0xff85dd10, 52), (0xff85deb0, 234)):
            offset = (address-static_batch.BASE)//8
            self.assertEqual(data[offset], offset+size)
        terminator_tail = (0xff85e600-static_batch.BASE)//8
        self.assertFalse(any(start <= terminator_tail < end for start,end in data.items()))
        for pc in (0xff8e48b0, 0xff8e48c0, 0xff9b6850, 0xff9b6870, 0xff9c70d0, 0xff9c70e0,
                   0xff9e0830, 0xff9e0840, 0xffa4ee10, 0xffa4ee20):
            self.assertFalse(pc in graph, f'{pc:08x} is data')
            offset = (pc - static_batch.BASE) // 8
            self.assertTrue(any(start <= offset < end for start,end in data.items()))
        self.assertIn(0xff8e48d0, graph)
        for source, targets in (
                (0xff819bf0, (0xff964e10,)), (0xff8cdab0, (0xffa0ecd0,)),
                (0xffa0ef10, (0xff810f80,)), (0xff814770, (0xff814c90, 0xff814cd0, 0xff814780)),
                (0xff830bb0, (0xff9068f0, 0xff906970, 0xff830bc0)),
                (0xff876830, (0xff906050, 0xff906090, 0xff876840))):
            self.assertEqual(set(graph[source]), set(targets), f'{source:08x}')
            op = rows[source][3].split()[0]
            self.assertNotIn(source, open_edges['computed:'+op])
        for pc in (0xff9e0820, 0xffa4ee00):
            self.assertIn(pc, open_edges['computed:EXGPC'])
        changed = bytearray(rom)
        changed[(0xff888fa0-static_batch.BASE)//8] ^= 1
        with self.assertRaisesRegex(ValueError, 'Observed jump table provenance differs'):
            static_batch.tms_graph(changed, rows)


    def test_original_tms_transfers_match_cpu_and_ordered_bus_lanes(self):
        from tools.mk2 import generate_video_irq as emitter, offline_decode
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests

        # Table reads of the Original (site, slot, target); the last three use the legal 1P tape. The CPU state is
        # synthetic: sentinel registers the two instructions neither read nor write, the slot in A0 (or the CALL
        # target in A0 and a synthetic stack), and a status whose N/Z/V the negative table entry reproduces.
        cases = ((0xff83bbe0, 0xff83bca0, 0xff83bf60), (0xff836e00, 0xff836e30, 0xffa14780),
                 (0xff876830, None, 0xff906090), (0xff878120, 0xff8781e0, 0xff86bc60),
                 (0xff888de0, 0xff888fa0, 0xff892e70), (0xff81a310, 0xff81a330, 0xff81a3b0))
        rom = emitter.load_program(emitter.ROOT/'roms/mk2')
        pcs = (0xff83bbe0, 0xff83bbf0, 0xff836e00, 0xff836e10, 0xff876830,
               0xff878120, 0xff878130, 0xff888de0, 0xff888df0, 0xff81a310, 0xff81a320)
        rows, _ = offline_decode.decode(rom, pcs)

        def cpp(values):
            return '{' + ','.join(f'0x{value:x}u' for value in values) + '}'

        def instruction(pc):
            width, _, words, asm = rows[pc]
            code = emitter.emit_instruction(pc, width, asm, words, set(pcs), {})
            return '{' + code + '}\n'

        body = 'program.bytes.resize(0x100000);\n'
        for number, (pc, slot, target) in enumerate(cases):
            call = slot is None
            registers = [0x5e000000 | number << 12 | n << 4 for n in range(31)]
            registers[0] = target if call else slot
            if call:
                registers[15] = 0x01200400
            status = 0x30000030 if call else 0xc0000010
            address = registers[15] - 32 if call else registers[0]
            bus_words = ((pc+16) & 0xffff, (pc+16) >> 16) if call else (target & 0xffff, target >> 16)
            if not call:
                offset = (address - 0xff800000) // 8
                self.assertEqual(int.from_bytes(rom[offset:offset+4], 'little'), target)
                body += f'{{ const uint8_t bytes[] = {cpp(rom[offset:offset+4])}; '
                body += f'std::copy(std::begin(bytes), std::end(bytes), program.bytes.begin()+{offset}); }}\n'
            body += '{\n'
            body += f's.next_pc=0x{pc:x}u; s.status=0x{status:x}u; s.a={cpp(registers[:16])}; '
            body += f's.b={cpp(registers[16:])}; const auto cycles=s.cycles; out->bus.clear();\n'
            body += instruction(pc)
            if not call:
                registers[0] = target
                body += f'if(s.next_pc!=0x{pc+16:x}u || s.cycles!=cycles+3 || '
                body += f's.status!=0x{status:x}u || s.a!=decltype(s.a){cpp(registers[:16])} || '
                body += f's.b!=decltype(s.b){cpp(registers[16:])})return 1;\n'
                body += instruction(pc+16)
            else:
                registers[15] = address
            body += f'if(s.next_pc!=0x{target:x}u || s.cycles!=cycles+{3 if call else 5} || '
            body += f's.status!=0x{status:x}u || s.a!=decltype(s.a){cpp(registers[:16])} || '
            body += f's.b!=decltype(s.b){cpp(registers[16:])} || out->bus.size()!=2)return 2;\n'
            for lane, value in enumerate(bus_words):
                kind = 'w' if call else 'r'
                body += f'if(out->bus[{lane}].kind!=\'{kind}\' || out->bus[{lane}].pc!=0x{pc:x}u || '
                body += f'out->bus[{lane}].address_bit!=0x{address+16*lane:x}u || '
                body += f'out->bus[{lane}].value!=0x{value:x}u || out->bus[{lane}].cycle!=cycles)return 3;\n'
            body += '}\n'
        CoinPairPrimitiveTests.compile_and_run(self, body)

    def test_service_immediate_exchanges_close_observed_rom_targets(self):
        from tools.mk2 import static_batch
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests

        rom = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        rows, _ = static_batch.scan_aligned(rom)
        graph, data, _, edges = static_batch.tms_graph(rom, rows)
        self.assertEqual(graph[0xffa59f20], (0xffa5a190,))
        self.assertIn(0xffa59f20, edges['computed:EXGPC'])
        for address, size in ((0xffa65c20, 40), (0xffa5e640, 35), (0xffa5dcb0, 16),
                              (0xffa5f0d0, 2), (0xffa5f0f0, 2)):
            offset = (address-static_batch.BASE)//8
            self.assertEqual(data.get(offset), offset+size)
        self.assertIn(0xffa65c20, graph[0xffa65c10])
        for address, size in ((0xffa401c0, 13), (0xffa57e10, 4), (0xffa57490, 8), (0xffa58820, 8)):
            offset = (address-static_batch.BASE)//8
            self.assertEqual(data[offset], offset+size)
            self.assertFalse(any(pc in graph for pc in range(address,address+size*8,16)))
        # Destinations and cycle counts from the Original Test Switch CPU34 brackets.
        observed = (
            (0xffa5a140, 0xffa5b160, 'B5', 'ffa5a150', '1887a', '1887c'),
            (0xffa5a180, 0xffa59ea0, 'B6', 'ffa5a190', '188db', '188dd'),
            (0xffa5a1f0, 0xffa593b0, 'B6', 'ffa5a200', '488ec', '488ee'),
            (0xffa5a290, 0xffa590c0, 'B6', 'ffa5a2a0', '48a40', '48a42'),
        )
        body = ''
        for pc, target, reg, exchanged, start, end in observed:
            self.assertIn(target, graph[pc])
            self.assertIn(target, graph)
            self.assertIn(pc, edges['computed:EXGPC'])  # Other incoming states remain unresolved.
            width, _, words, asm = rows[pc]
            code = static_batch.emitter.emit_instruction(pc, width, asm, words, graph.keys(), {})
            # Synthetic registers: the exchange reads and writes only the named B register.
            a = [0x5e000000 | n << 4 for n in range(16)]
            b = [0x5e100000 | n << 4 for n in range(15)]
            b[int(reg[1])] = target
            cpp = lambda values: '{' + ','.join(f'0x{value:x}u' for value in values) + '}'
            body += f'{{ s.next_pc=0x{pc:x}; s.status=0x50000010; s.a={cpp(a)}; s.b={cpp(b)}; '
            body += 'const auto cycles=s.cycles; out->bus.clear(); {'+code+'}'
            b[int(reg[1])] = int(exchanged,16)
            delta = int(end,16)-int(start,16)
            body += (f'if(s.next_pc!=0x{target:x} || s.cycles!=cycles+{delta} || s.status!=0x50000010 || '
                     f's.a!=decltype(s.a){cpp(a)} || s.b!=decltype(s.b){cpp(b)} || !out->bus.empty())return 1; }}\n')
        CoinPairPrimitiveTests.compile_and_run(self, body)

    def test_service_field_exchange_and_subtract_borrow_follow_pinned_tms34010(self):
        from tools.mk2 import offline_decode, static_batch
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests

        rom = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        cases = {
            0xffa5fe90: ('f7777c3af5a7eb8ba8f122a8df3ee066ec6e4f8a7c9027f3dc0a14f30aa59c88', 9, (
                (0xfffffff3, 0, 0xa0200155, 0x15, 0xa0200173),
            )),
            0xffa5fe40: ('16c47be7b68c8f3987507932f13465b18bbdc1591fa37b4a60d1059f1c0655fa', 9, (
                (0xfffffff2, 0, 0xa0200155, 0x05, 0xa0200c95),
            )),
            0xffa5dce0: ('566b2af054c7d6f7b64dfaf3f705ece2359a48c0a0b5fc304ac975fec2bf7808', 14, (
                (0, 0, 0x40000030, 0xffffffff, 0x80000030),
                (0x80000000, 1, 0x40000030, 0x7ffffffe, 0x10000030),
                (1, 1, 0x30, 0, 0x20000030),
                (0, 0xffffffff, 0x30, 1, 0x40000030),
                (0x7fffffff, 0xffffffff, 0x30, 0x80000000, 0xd0000030),
            )),
        }
        decoded, _ = offline_decode.decode(rom, cases)
        body = ''
        for pc, (word_sha256, register, inputs) in cases.items():
            width, _, words, asm = decoded[pc]   # opcode read from the user's ROM, pinned by SHA-256
            self.assertEqual((width, oracle_digest.words_digest(words)), (16, word_sha256))
            code = static_batch.emitter.emit_instruction(pc, width, asm, words, {pc+width}, {}, batch_forms=True)
            for dest, src, status, result, flags in inputs:
                body += (f'{{ s.next_pc=0x{pc:x}u; s.a[{register}]=0x{dest:x}u; s.a[10]=0x{src:x}u; '
                         f's.status=0x{status:x}u; const auto start=s.cycles; {{ {code} }} '
                         f'if(s.next_pc!=0x{pc+16:x}u || s.cycles!=start+1 || s.a[{register}]!=0x{result:x}u || '
                         f's.status!=0x{flags:x}u || s.a[10]!=0x{src:x}u || !out->bus.empty())return 1; }}\n')
        CoinPairPrimitiveTests.compile_and_run(self, body)

    def test_service_aot_reuses_the_authenticated_bitmap_text_primitive(self):
        from tools.mk2 import offline_decode, static_batch
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests

        pc = 0xffa592b0
        rom = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        decoded, _ = offline_decode.decode(rom, [pc])
        width, _, words, asm = decoded[pc]
        self.assertEqual(oracle_digest.words_digest(words),
                         '6fff9aef0d88c32b1e16a50833d2698afd0363ad3495673f8f92adfc4caad4f7')
        code = static_batch.emitter.emit_instruction(pc, width, asm, words, {pc+width}, {}, batch_forms=True)
        glyph = 0xffa58820
        offset = (glyph - offline_decode.BASE) // 8
        glyph_bytes = ','.join(str(byte) for byte in rom[offset:offset+8])
        body = f'''
        program.bytes.resize(0x100000);
        program.bytes[{(pc-offline_decode.BASE)//8}]={rom[(pc-offline_decode.BASE)//8]};
        program.bytes[{(pc-offline_decode.BASE)//8+1}]={rom[(pc-offline_decode.BASE)//8+1]};
        const uint8_t glyph[]={{{glyph_bytes}}};
        std::copy(std::begin(glyph),std::end(glyph),program.bytes.begin()+{offset});
        s.next_pc=0xffa592b0; s.status=8;
        s.board.io[8]=0xf010; s.board.io[11]=0x2c; s.board.io[20]=19; s.board.io[21]=8;
        s.board.WriteVideoControl(0x20);
        // Glyph source, pitches and size of the text primitive; XY, colour and the unread window registers are synthetic.
        s.b={{0xffa58820,8,0x004000d6,4096,0,0x5e000050,0x5e000060,0x00080006,0,0x303,0x5e0000a0}};
        {code}
        if(s.next_pc!=0xffa592c0 || s.cycles!=120 || s.status!=8 ||
           s.b[0]!=0xffa58860 || s.b[2]!=0x004800d6 ||
           out->execution.last_instruction_pc!=0xffa592b0 || out->bus.size()!=56 ||
           out->bus[0].address_bit!=0xffa58820 || out->bus[0].cycle!=0 ||
           out->bus[1].address_bit!=0x406b0 || out->bus[2].kind!='w')return 1;
        '''
        CoinPairPrimitiveTests.compile_and_run(self, body)

    def test_service_pixel_forms_preserve_word_bus_and_signed_coordinates(self):
        from tools.mk2 import offline_decode, static_batch
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests

        pcs = (0xffa58fd0, 0xffa58ff0, 0xffa58df0, 0xffa59900, 0xffa59070)
        rom = static_batch.emitter.load_program(static_batch.ROOT/'roms/mk2')
        decoded, _ = offline_decode.decode(rom, pcs)
        lines = {}
        self.assertEqual(oracle_digest.words_digest([decoded[pc][2][0] for pc in pcs]),
                         'c1c8e47049b18881cc7bad5f47df42805b95d19552c2d9122e72a0fa2c3a686d')
        for pc in pcs:
            width, _, words, asm = decoded[pc]
            self.assertEqual(len(words), 1)
            lines[pc] = static_batch.emitter.emit_instruction(pc, width, asm, words, {pc+width}, {}, batch_forms=True)

        body = f'''
        s.board.io[8]=0xf010; s.board.io[11]=0x2c; s.board.io[20]=19; s.board.io[21]=8;
        s.board.WriteVideoControl(0x20); out->video.dma_palette=0xabcd;
        s.status=0x20200030;
        s.next_pc=0xffa58fd0; s.a[3]=0x00b90038;
        {{ {lines[0xffa58fd0]} }}
        if(s.next_pc!=0xffa58fe0 || s.cycles!=3 || s.a[3]!=0x000b91c0 || !out->bus.empty())return 1;
        s.next_pc=0xffa58ff0; s.a[4]=0xffffffff; s.b[4]=0x3000;
        {{ {lines[0xffa58ff0]} }}
        if(s.next_pc!=0xffa59000 || s.cycles!=6 || s.a[4]!=0x1ff8 || !out->bus.empty())return 2;
        s.b[4]=0;
        const auto check=[&](uint32_t pc,uint32_t address,uint16_t write,uint64_t cycles){{
            return s.next_pc==pc+16 && s.cycles==cycles+4 && s.status==0x20200030 &&
                   out->bus.size()==2 && out->bus[0].kind=='r' && out->bus[1].kind=='w' &&
                   out->bus[0].pc==pc && out->bus[1].pc==pc &&
                   out->bus[0].address_bit==address && out->bus[1].address_bit==address &&
                   out->bus[0].value==0x7c5a && out->bus[1].value==write &&
                   out->bus[0].cycle==cycles && out->bus[1].cycle==cycles &&
                   out->video.vram[address/8]==(0xcd00|(write&0xff)) &&
                   out->video.vram[address/8+1]==(0xab00|(write>>8));
        }};
        s.next_pc=0xffa58df0; s.a[0]=0x001b00b7; s.a[1]=0x202;
        out->video.vram[0x1b5b0/8]=0x5a; out->video.vram[0x1b5b0/8+1]=0x7c;
        {{ {lines[0xffa58df0]} }}
        if(!check(0xffa58df0,0x1b5b0,0x025a,6) || s.a[0]!=0x001b00b7)return 3;
        out->bus.clear(); s.next_pc=0xffa59900; s.a[0]=0x002000b6; s.a[6]=0x100;
        {{ {lines[0xffa59900]} }}
        if(!out->bus.empty() || s.next_pc!=0xffa59910 || s.cycles!=14 || s.a[6]!=0x100)return 4;
        s.next_pc=0xffa59070; s.a[0]=0x00b90038; s.a[2]=1; s.b[9]=0x202;
        out->video.vram[0xb91c0/8]=0x5a; out->video.vram[0xb91c0/8+1]=0x7c;
        {{ {lines[0xffa59070]} }}
        if(!check(0xffa59070,0xb91c0,0x7c02,14) || s.a[0]!=0x00b90039 || s.a[2]!=1)return 5;
        '''
        CoinPairPrimitiveTests.compile_and_run(self, body)

    def test_direct_flow_does_not_use_invalid_words_or_fabricate_indirect_targets(self):
        from tools.mk2.static_batch import successors
        pc = 0xff800000
        self.assertEqual(successors(None, pc, 16, 'DW  0001h', 0)[0], ())
        self.assertEqual(successors(None, pc, 16, 'JUMP A0', 0)[0], ())
        self.assertEqual(successors(None, pc, 16, 'NOP', 0)[0], (pc+16,))

    def test_dsp_external_pc_keeps_both_authenticated_images(self):
        from tools.mk2.static_batch import dsp_sources, ROOT
        from tools.mk2 import coverage
        u2 = (ROOT/'roms/mk2/su2.l1').read_bytes()
        source, report = dsp_sources(u2)
        entries = list(coverage.dsp_entries(source,u2))
        variants = {(bank, offset, word) for pc,bank,offset,_,word in entries if pc == 0x836}
        self.assertEqual(variants, {('early', 0x8d8, int.from_bytes(u2[0x8d8:0x8db], 'big')),
                                    ('late', 0x20d8, int.from_bytes(u2[0x20d8:0x20db], 'big'))})
        self.assertTrue(all(0x800 <= pc < 0xa00 and 0x800 <= offset < 0x1000
                            for pc,bank,offset,_,_ in entries if bank == 'early'))
        self.assertTrue(all(0x800 <= pc < 0xb00 and 0x2000 <= offset < 0x2c00
                            for pc,bank,offset,_,_ in entries if bank == 'late'))
        # 00e3 and 00ea branch to 00f9. The preceding SYSCON write resets into low PM.
        self.assertIn('case 0x000f9:', source)
        self.assertIn({'from': 'boot:00f8', 'to': 'low:0000', 'rom_bank': 1, 'effect': 'SYSCON reset'},
                      report['mapping']['transitions'])
        self.assertIn('01d5', report['images']['late']['indirect_examples'])

    def test_authentic_boot_branches_emit_group_zero_loads_and_immediate_transfers(self):
        from tools.mk2.static_batch import dsp_sources, ROOT
        u2 = (ROOT/'roms/mk2/su2.l1').read_bytes()
        source, report = dsp_sources(u2)
        for pc, op, body in ((0x9b, '839e1a', 'ar = ReadData(0x39e1);'),
                             (0x9e, '1c130f', 'PushPc(); pc = 0x0130;'),
                             (0xa4, '4001d4', 'ay0 = 0x001d;')):
            line = next((line for line in source.splitlines() if line.startswith(f'case 0x{pc:05x}:')), '')
            self.assertIn(f'CheckOpcode(0x{op}); Advance();', line)
            self.assertIn(body, line)
        self.assertGreater(report['variants_by_image']['boot'], report['baseline_variants_by_image']['boot'])

    def test_boot_selftest_has_fixed_ops_for_the_alias_and_latch_paths(self):
        from tools.mk2.static_batch import dsp_sources, ROOT
        u2 = (ROOT/'roms/mk2/su2.l1').read_bytes()
        source, report = dsp_sources(u2)
        lines = {line.split(':')[0]: line for line in source.splitlines() if line.startswith('case ')}
        for pc, op, body in ((0xa6, '0d00a5', 'ar = ay1;'),
                             (0xae, '5000b1', 'mr0 = ReadProgramDag(4, 5);'),
                             (0xdc, '5800a1', 'WriteProgramDag(4, 5, ar);'),
                             (0x132, '934004', 'WriteData(0x3400, ay0);')):
            with self.subTest(pc=pc):
                line = lines.get(f'case 0x{pc:05x}', '')
                self.assertIn(f'CheckOpcode(0x{op}); Advance();', line)
                self.assertIn(body, line)
        self.assertEqual(report['images']['boot']['unsupported'], {})
        self.assertEqual(report['images']['boot']['unmapped'], [])

    def test_u2_command_headers_prove_bounded_late_parser_edge(self):
        from tools.mk2.static_batch import ROOT, dsp_sources
        rom = (ROOT/'roms/mk2/su2.l1').read_bytes()
        spans = []
        _, report = dsp_sources(rom, physical_map=spans)
        table = report['mapping']['command_headers']
        self.assertEqual(table['table_offsets'], [0x4048, 0x50b9])
        self.assertEqual(table['counts'], {'skipped': 213, '01': 1188, '02': 2})
        self.assertEqual(table['header_sha256'], 'e93d2bf543be65a072479bf9a71c645bb03ad348933eef67142ec51500684f5a')
        self.assertIn((0x4048, 0x50b9, 2), spans)
        self.assertIn((0x50bb, 0x50bc, 2), spans)
        self.assertIn((0x50bf, 0x50c0, 2), spans)

    def test_firmware_indirect_jump_has_all_sixteen_command_entries(self):
        from tools.mk2.static_batch import dsp_sources, ROOT
        from tools.mk2.coverage import dsp_entries
        u2 = (ROOT/'roms/mk2/su2.l1').read_bytes()
        source, report = dsp_sources(u2)
        entries = {pc: op for pc, image, _, _, op in dsp_entries(source, u2) if image == 'low'}
        table = [0x1d6, 0x1e7, 0x23a, 0x265, 0x268, 0x26d, 0x2ae, 0x2af,
                 0x2af, 0x2af, 0x2b5, 0x2b5, 0x2b5, 0x2e8, 0x2e9, 0x2ee]
        self.assertEqual([entries.get(pc) for pc in range(0x310, 0x320)],
                         [0x18000f | (target << 4) for target in table])
        self.assertTrue(set(table) <= entries.keys())
        self.assertEqual(report['images']['late']['unsupported'], {})
        self.assertEqual(report['images']['late']['unmapped'], [])
        self.assertEqual(report['images']['late']['register_jump_targets']['01d5'],
                         [f'{pc:04x}' for pc in range(0x310, 0x320)])
