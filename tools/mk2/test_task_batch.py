"""Independent physical-fetch accounting and complete batch comparison controls."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import batch_reference as b


class BatchTests(unittest.TestCase):
    def test_external_irq_trace_annotation_requires_explicit_lossless_event_capture(self):
        start=[0xf0,0x00200030,10]+[0]*31
        before=[0x100,0x00200030,11]+[0]*31
        handler=[0xff8045d0,0x10,28]+[0]*31
        end=[0x110,0x00200030,39]+[0]*31
        def bc(row):return 'BC '+f'{row[0]:X} {row[1]:X} {row[2]} '+' '.join(f'{x:X}' for x in row[3:])
        trace=[bc(before),'00000100: NOP','   (interrupted at 00000110, IRQ 0)',
               bc(handler),'FF8045D0: RETI',bc(end),'00000110: NOP']
        annotations=[]
        try:cpu=b.parse_cpu_trace(trace,start,end,end_cycle=39,irq_annotations=annotations)
        except (TypeError,ValueError) as error:self.fail('External IRQ trace cannot be captured: '+str(error))
        self.assertEqual(cpu,[start,before,handler])
        self.assertEqual(annotations,[(1,0x110,0)])
        with self.assertRaises(ValueError):b.parse_cpu_trace(trace,start,end,end_cycle=39)
        for bad in (trace[:3]+trace[2:],trace[:1]+trace[2:3]+trace[1:],
                    [line.replace('IRQ 0','IRQ 1') for line in trace],
                    [line.replace('00000110, IRQ 0','110, IRQ 0') for line in trace],
                    trace[:3],trace+trace[2:3]):
            events=[]
            with self.assertRaises(ValueError):b.parse_cpu_trace(bad,start,end,end_cycle=39,irq_annotations=events)
            self.assertEqual(events,[])

    def test_dsj_a9_parameter_fetch_depends_on_original_counter_and_cpu_bracket(self):
        for counter,target,cost,fetch_parameter in ((2,0x80,3,True),(1,0x120,2,False)):
            before=[0x100,0x60200030,1]+[0]*31;before[12]=counter
            after=[target,0x60200030,1+cost]+[0]*31;after[12]=counter-1
            words={0x100:0x0d89,0x110:0xfff6,target:0x5600}
            widths={0x100:32,target:16}
            first=(0x110,0x100,0x0d89,1,16,0x100,False)
            parameter=(0x110,0x110,0xfff6,1,16,0x100,False)
            following=(target+16,target,0x5600,1+cost,16,target,False)
            rows=[first]+([parameter] if fetch_parameter else [])+[following]
            try:data,counts=b.partition_accesses(rows,[before,after],widths,words.__getitem__)
            except ValueError as error:self.fail('Original DSJ fetch protocol rejected: '+str(error))
            self.assertEqual(data,[])
            self.assertEqual(counts,dict(physical=3 if fetch_parameter else 2,fetch=3 if fetch_parameter else 2,data=0))
            for bad in ([first,following] if fetch_parameter else [first,parameter,following],rows[:-1],list(reversed(rows))):
                with self.assertRaises(ValueError):b.partition_accesses(bad,[before,after],widths,words.__getitem__)
            if not fetch_parameter:
                for field in (0,1,2,12):
                    bad_after=list(after);bad_after[field]^=1
                    with self.assertRaises(ValueError):b.partition_accesses(rows,[before,bad_after],widths,words.__getitem__)

    def test_dma_brackets_require_both_exact_instruction_states_for_every_packet(self):
        rows = []
        for pc,cycle,i7 in ((0x130,8,0x400),(0x130,9,0x4f0),(0x136,10,0x4f0),(0x136,11,0x400)):
            row = [0]*76; row[0],row[1],row[23] = pc,cycle,i7; rows.append(row)
        transfers = [[100,0x130,9,7,0x400,0x4f0,240],[200,0x136,11,7,0x4f0,0x400,240]]
        self.assertEqual(b.dma_brackets(rows,transfers),{(0x130,9):8,(0x136,11):10})
        for index,field in ((0,1),(0,23),(1,23),(2,1),(3,0),(3,23)):
            bad = [list(row) for row in rows]; bad[index][field] ^= 1
            with self.subTest(index=index,field=field), self.assertRaises(ValueError): b.dma_brackets(bad,transfers)
        for packets in (transfers+transfers[:1], [transfers[0][:3]+[6]+transfers[0][4:]]):
            with self.assertRaises(ValueError): b.dma_brackets(rows,packets)

    def test_terminal_dma_boundary_is_separate_from_instruction_rows_and_cannot_fill_an_interior_gap(self):
        rows=[]
        for pc,cycle,i7 in ((0x130,8,0x400),(0x130,9,0x4f0),(0x137,10,0x4f0)):
            row=[0]*76;row[0],row[1],row[23]=pc,cycle,i7;rows.append(row)
        packets=[[100,0x130,9,7,0x400,0x4f0,240],[200,0x138,11,7,0x4f0,0x400,240]]
        with self.assertRaises(ValueError):b.dma_brackets(rows,packets)
        try:actual=b.dma_brackets(rows,packets,terminal=(0x138,11,0x400))
        except (TypeError,ValueError) as error:self.fail('Real terminal DMA boundary rejected: '+str(error))
        self.assertEqual(actual,{(0x130,9):8,(0x138,11):10})
        self.assertEqual(len(rows),3)
        for terminal in ((0x137,11,0x400),(0x138,10,0x400),(0x138,12,0x400),(0x138,11,0x4f0)):
            with self.subTest(terminal=terminal),self.assertRaises(ValueError):b.dma_brackets(rows,packets,terminal=terminal)
        for bad in (rows[:1]+rows[2:],rows[:-1],rows+[rows[-1][:1]+[12]+rows[-1][2:]]):
            with self.assertRaises(ValueError):b.dma_brackets(bad,packets,terminal=(0x138,11,0x400))

    def test_native_dma_reads_use_real_terminal_clock_and_preserve_all_pcm_and_trace_rows(self):
        rows=[]
        for pc,cycle,i7 in ((0x130,8,0x400),(0x130,9,0x4f0),(0x137,10,0x4f0)):
            row=[0]*76;row[0],row[1],row[23]=pc,cycle,i7;rows.append(row)
        terminal=[0]*76;terminal[0],terminal[1],terminal[23]=0x138,11,0x400
        native={'batch_dsp_trace':rows,'batch_dsp_final':terminal,
                'batch_transfers':[[100,0x130,9,7,0x400,0x4f0,240],[200,0x138,11,7,0x4f0,0x400,240]],
                'batch_pcm':[-1]*240+[-32768]*240}
        try:reads=b.native_dma_reads(native)
        except ValueError as error:self.fail('Native terminal packet rejected: '+str(error))
        self.assertEqual(len(reads),480)
        self.assertEqual([reads[i] for i in (0,239,240,479)],
                         [[100,0x130,8,0x400,65535],[100,0x130,8,0x4ef,65535],
                          [200,0x138,10,0x4f0,32768],[200,0x138,10,0x5df,32768]])
        self.assertEqual(len(rows),3)
        for field in (0,1,23):
            bad=list(terminal);bad[field]^=1
            with self.subTest(field=field),self.assertRaises(ValueError):b.native_dma_reads({**native,'batch_dsp_final':bad})

    def test_original_dsp_observer_covers_independently_authenticated_later_sound_paths(self):
        import json
        for filename in ('start_release_dsp_path.json','selection_dsp_path.json','first_fight_dsp_path.json'):
            observed=json.loads(Path(__file__).with_name(filename).read_text(encoding='utf-8'))
            missing={int(pc,16) for pc in observed['pcs']}-set(b.reference.DSP_PCS)
            self.assertEqual(missing,set(),filename+' contains original instructions absent from the observer')

    def test_larger_reti_destinations_authenticate_without_admitting_async_entries(self):
        for target in (0xff807da0,0xff807e20,0xff807ea0):
            self.assertIn(target,b.generated.SUCCESSORS[0xff816e90])
        for source in (0xff807da0,0xff807df0,0xff807e20,0xff807e70,0xff807ea0,0xff807ed0,0xff807ef0,0xff808070):
            self.assertNotIn(0xff816370,b.generated.SUCCESSORS[source])

    def test_larger_endpoint_uses_previous_final_boundary_as_start(self):
        debug,_,start,end,bc = self.protocol()
        start = list(start); start[2] = 2173200
        end = list(end); end[2] = 3087189
        debug[1],debug[3] = bc(start),bc(end)
        # All physical records in this fixture must belong to the newly observed interval.
        debug[2] = debug[2].replace('1261260', '2173200')
        with self.assertRaises(ValueError): b.parse_debug_lines(debug,end_cycle=3087189)
        result = b.parse_debug_lines(debug,start_cycle=2173200,end_cycle=3087189)
        self.assertEqual((result['start'],result['end']), (start,end))

    def test_compact_native_trace_preserves_uint64_order_and_rejects_invalid_rows(self):
        from tools.mk2.packed_trace import PackedRows, load_native
        import json
        rows = [[0, 2**64-1] + [0]*74, [7, 9] + [1]*74]
        output = json.dumps({'dsp_trace':rows, 'batch_dsp_trace':rows[::-1], 'other':[-1,{'a':3}]})
        parsed = load_native(output)
        self.assertIsInstance(parsed['dsp_trace'], PackedRows)
        self.assertEqual(list(parsed['dsp_trace']), rows)
        self.assertEqual(parsed['dsp_trace'][-1], rows[-1])
        self.assertEqual(parsed['dsp_trace'][:1], rows[:1])
        self.assertEqual(parsed['dsp_trace'].nbytes, 2*76*8)
        self.assertEqual(parsed['batch_dsp_trace'], rows[::-1])
        self.assertEqual(parsed['other'], [-1,{'a':3}])
        for bad in ([1], [-1]*76, [2**64]*76, [True]*76, [1.5]*76):
            with self.subTest(bad=bad[:2]), self.assertRaises(ValueError):
                load_native(json.dumps({'dsp_trace':[bad]}))
        for bad in ('{}{}','{"a":1,"a":2}', '{"dsp_trace":[', '{"dsp_trace":[[]]}',
                    '{"dsp_trace":null}', '{"a":1,}', '[]', '{"dsp_trace":[],}', '{\v"a":1}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): load_native(bad)

    def test_live_trace_comparison_rejects_field_changes_order_missing_and_extra(self):
        debug,_,_,_,_ = self.protocol()
        row = [0x130 if key=='pc' else 744144 if key=='totalcycles' else 0
               for key in b.reference.DSP_REGISTERS]
        symbols = [f'{key} = {value:X}' for key,value in zip(b.reference.DSP_REGISTERS,row)]
        records = debug[:3] + ['MK2_DSP_BEGIN',*symbols,'irq1 = 0'] + debug[3:]
        parser = b.DebugParser(expected_dsp_trace=[row])
        for line in records: parser.feed(line)
        self.assertEqual(list(parser.finish()['trace']), [row])
        for field in range(76):
            bad = list(row); bad[field] ^= 1
            parser = b.DebugParser(expected_dsp_trace=[bad])
            with self.subTest(field=field), self.assertRaises(ValueError):
                for line in records: parser.feed(line)
                parser.finish()

        for expected in ([], [row,row], [list(reversed(row)),row]):
            parser = b.DebugParser(expected_dsp_trace=expected)
            with self.subTest(count=len(expected)), self.assertRaises(ValueError):
                for line in records: parser.feed(line)
                parser.finish()
        following = list(row); following[0] += 1; following[1] += 1
        more = ['MK2_DSP_BEGIN',*[f'{key} = {value:X}' for key,value in
                zip(b.reference.DSP_REGISTERS,following)],'irq1 = 0']
        two = records[:-len(debug[3:])] + more + debug[3:]
        parser = b.DebugParser(expected_dsp_trace=[row,following])
        for line in two: parser.feed(line)
        self.assertEqual(list(parser.finish()['trace']),[row,following])
        for expected in ([following,row],[row,row],[row]):
            parser = b.DebugParser(expected_dsp_trace=expected)
            with self.assertRaises(ValueError):
                for line in two: parser.feed(line)
                parser.finish()

    def test_compact_loader_equals_standard_json_for_every_field_in_varying_rows(self):
        from tools.mk2.packed_trace import load_native
        import json
        rows = [[((index << 32) + field*0x123456789abcdef) & ((1<<64)-1)
                 for field in range(76)] for index in range(1000)]
        output = json.dumps({'dsp_trace':rows, 'batch_dsp_trace':rows[::-1], 'other':{'a':[-3,4]}})
        self.assertEqual(load_native(output), json.loads(output))

    def test_next_batch_translation_keeps_instruction_and_hardware_edges_separate(self):
        for pc in (0xff80c760, 0xff80ca40):
            self.assertIn(pc, b.generated.PCS)
        for pc, successor in ((0xff80c750, 0xff80c760), (0xff80c760, 0xff80c790),
                              (0xff80ca30, 0xff80ca40), (0xff80ca40, 0xff80ca70),
                              (0xff816e90, 0xff807df0), (0xff816e90, 0xff807e70)):
            self.assertIn(successor, b.generated.SUCCESSORS.get(pc, ()))
        self.assertNotIn(0xff816370, b.generated.SUCCESSORS[0xff807e20])

    def test_async_irq_transitions_are_not_instruction_return_destinations(self):
        for pc in (0xff807da0,0xff807ea0,0xff807ed0,0xff807ef0):
            with self.subTest(pc=hex(pc)):
                self.assertNotIn(0xff816370,b.generated.SUCCESSORS[pc])

    def test_extended_translation_preserves_original_and_new_measured_edges(self):
        g = b.generated
        for pc, successor in ((0xff80e9d0, 0xff80e9e0), (0xff80e9e0, 0xff80ea10),
                              (0xff816d40, 0xff816d50), (0xff816d50, 0xff816d60),
                              (0xff816d60, 0xff816d90), (0xff816d90, 0xff816dc0),
                              (0xff816dc0, 0xff816df0), (0xff816df0, 0xff816e20),
                              (0xff816e20, 0xff816e50), (0xff816e90, 0xff807e40),
                              (0xff816e90, 0xff807ed0)):
            with self.subTest(pc=hex(pc), successor=hex(successor)):
                self.assertIn(pc, g.PCS)
                self.assertIn(successor, g.SUCCESSORS.get(pc, ()))
        self.assertIn(0xff80ea10, g.SUCCESSORS[0xff80e9d0])

    def test_reached_irq_classes_keep_fetches_and_adjacent_rom_data_distinct(self):
        for opcode, width in ((0x0ba0,48),(0x5600,16),(0x0580,48),(0x05a0,48),(0x0bc0,48),
                              (0x09e3,48),(0x09e0,48)):
            source, cycle = 0xff800100, 7
            words = {source:opcode, source+16:2, source+32:0, source+width:0x1234}
            rows = [(source+(16 if not offset else width), source+offset, words[source+offset],
                     cycle,16,source,False) for offset in range(0,width,16)]
            rows.append((source+width,source+width,words[source+width],cycle,16,source,False))
            with self.subTest(opcode=hex(opcode)):
                data, counts = b.partition_accesses(rows,[[source,0,cycle]],{source:width},words.__getitem__)
                self.assertEqual(counts,dict(physical=width//16+1,fetch=width//16,data=1))
                self.assertEqual(data,[[114,source,source+width,words[source+width],cycle,16]])
                for index in range(width//16):
                    for field in (0,1,2,3,4,5):
                        bad = list(rows)
                        lane = list(bad[index]); lane[field] ^= 1; bad[index] = tuple(lane)
                        with self.subTest(lane=index,field=field), self.assertRaises((ValueError,KeyError)):
                            b.partition_accesses(bad,[[source,0,cycle]],{source:width},words.__getitem__)

    @staticmethod
    def protocol():
        start = [0xff80dd30,0x00200030,b.START]+[0]*31
        end = [0xff80dd30,0xe0200030,b.END]+[0]*31
        def bc(row): return 'BC '+' '.join([f'{row[0]:X}',f'{row[1]:X}',str(row[2]),*[f'{n:X}' for n in row[3:]]])
        symbols = [f'{key} = {0x130 if key=="pc" else 744144 if key=="totalcycles" else 0:X}'
                   for key in b.reference.DSP_REGISTERS]
        debug = ['BATCH_START',bc(start),'NB r FF80DD40 106B840 0 1261260 16 FF80DD30',
                 bc(end),'BATCH_DSP_FINAL',*symbols,'BATCH_END']
        middle = [0xff80dd40,0x00200030,b.START+3]+[0]*31
        trace = [bc(middle),'FF80DD40: MOVE A0,A1,0',bc(end),'FF80DD30: MOVE *A13,A13,1']
        return debug,trace,start,end,bc

    def test_debug_protocol_requires_exact_ordered_control_records(self):
        debug,_,_,_,_ = self.protocol()
        self.assertEqual(b.parse_debug_lines(debug)['end'][2],b.END)
        mutations = [debug[:-1]+['BATCH_END garbage'],
                     [line+' garbage' if line=='BATCH_DSP_FINAL' else line for line in debug],
                     debug[:2]+['MK2_BOGUS']+debug[2:],
                     debug[:3]+['BATCH_END']+debug[3:-1],
                     debug+['MK2_BOGUS'],debug+['pc = 130']]
        for lines in mutations:
            with self.subTest(lines=lines[:4]), self.assertRaises(ValueError): b.parse_debug_lines(lines)

    def test_incremental_debug_parser_matches_file_and_rejects_incomplete_or_late_records(self):
        debug, _, _, _, _ = self.protocol()
        parser = b.DebugParser()
        for line in debug: parser.feed(line + '\n')
        self.assertEqual(parser.finish(), b.parse_debug_lines(debug))
        with self.assertRaises(ValueError): parser.feed('BATCH_END\n')
        with self.assertRaises(ValueError): parser.finish()
        for limit in range(len(debug)):
            parser = b.DebugParser()
            for line in debug[:limit]: parser.feed(line)
            with self.subTest(limit=limit), self.assertRaises(ValueError): parser.finish()

    def test_extended_endpoint_is_explicit_and_old_endpoint_still_required(self):
        debug,trace,start,end,bc = self.protocol()
        later = list(end); later[2] = 1716210
        debug = [bc(later) if line == bc(end) else line for line in debug]
        trace = [bc(later) if line == bc(end) else line for line in trace]
        with self.assertRaises(ValueError): b.parse_debug_lines(debug)
        self.assertEqual(b.parse_debug_lines(debug,end_cycle=1716210)['end'],later)
        self.assertEqual(len(b.parse_cpu_trace(trace,start,later,end_cycle=1716210)),2)
        with self.assertRaises(ValueError): b.parse_cpu_trace(trace,start,end)

    def test_post_return_irq_requires_cpu_brackets_and_all_six_physical_lanes(self):
        import hashlib, json
        from unittest.mock import patch
        from tools.mk2 import generate_video_irq as g
        from tools.mk2.offline_decode import decode
        # batch_reference's qualified IRQ table (PCs, cycles and the digest of the Original ST/SP) is pinned here
        # with the opcode at each source, read from the user's ROM. The fixture lanes use synthetic ST/SP values
        # (IE set, aligned stacks); the table is patched with their digests, so the classifier runs unchanged.
        rom = g.load_program(g.ROOT/'roms/mk2')
        decoded, _ = decode(rom, {source for source, _ in b.IRQ_CONTEXTS})
        pinned = json.dumps([[source, cycle, *context, decoded[source][2][0]]
                             for (source, cycle), context in sorted(b.IRQ_CONTEXTS.items())], separators=(',', ':'))
        self.assertEqual(hashlib.sha256(pinned.encode('ascii')).hexdigest(),
                         'bada3fce054e1b412ba5666f098766004540f347e9e61729258c1bb1fd5febf6')
        synthetic = {}
        for n, ((source, cycle), (target, end_cycle, _)) in enumerate(sorted(b.IRQ_CONTEXTS.items())):
            status = 0x00200000 | (n << 26 & 0xfc000000) | (0x1350 + 16*n)
            before_status = status ^ (0x40000000 if n % 3 == 0 else 0)
            old_sp = 0x01080000 + 0x400*n
            # Entry SP below every stack lane of the interrupted form (MMTM stores twelve registers first).
            sp = old_sp - {'MMTM': 0x120, 'CALLR': 0x60}.get(decoded[source][3].split()[0], 0x40 + 0x20*(n % 2))
            synthetic[source, cycle] = (status, before_status, old_sp, sp)
        table = {key: (target, end_cycle, b.irq_state_digest(*synthetic[key]))
                 for key, (target, end_cycle, _) in b.IRQ_CONTEXTS.items()}
        with patch.object(b, 'IRQ_CONTEXTS', table):
            self.post_return_irq_lanes(decoded, synthetic)

    def post_return_irq_lanes(self, decoded, synthetic):
        for (source,cycle),(target,end_cycle,_) in b.IRQ_CONTEXTS.items():
            status,before_status,old_sp,sp = synthetic[source,cycle]
            width, _, (op, *_), asm = decoded[source]
            form = asm.split()[0]
            before = [source,before_status,cycle]+[0]*31
            after = [0xff816370,0x10,end_cycle]+[0]*31
            before[18],after[18] = old_sp,sp
            words = {source:op,source+16:0,source+32:0x8000,0xff816370:0x09e0,0xff816380:0,0xff816390:0}
            rows = [(source+(16 if not offset or form=='CALLR' else width),source+offset,words[source+offset],cycle,16,source,False)
                    for offset in range(0,width,16)]
            if form == 'RETS':
                rows += [(source+16,old_sp,0x7e40,cycle,16,source,False),
                         (source+16,old_sp+16,0xff80,cycle,16,source,False)]
            elif form == 'CALLR':
                rows[1:1] = [(source+16,old_sp-32,(source+32)&0xffff,cycle,16,source,True),
                             (source+16,old_sp-16,0xff80,cycle,16,source,True)]
            elif form == 'MMTM':
                rows += [(source+32,old_sp-16-n*16,n,cycle,16,source,True) for n in range(12)]
            irq = [(target,sp+32,target&0xffff,cycle,16,source,True),
                   (target,sp+48,0xff80,cycle,16,source,True),
                   (target,sp,status&0xffff,cycle,16,source,True),
                   (target,sp+16,status>>16,cycle,16,source,True),
                   (target,0xfffffea0,0x6370,cycle,16,source,False),
                   (target,0xfffffeb0,0xff81,cycle,16,source,False)]
            words.update({0xfffffea0:0x6370,0xfffffeb0:0xff81})
            # The following handler opcode is 16 bits in this synthetic classifier fixture.
            words[0xff816370] = 0x5600
            tail = [(0xff816380,0xff816370,0x5600,end_cycle,16,0xff816370,False)]
            cpu,widths = [before,after],{source:width,0xff816370:16}
            data,counts = b.partition_accesses(rows+irq+tail,cpu,widths,words.__getitem__)
            lanes = len(rows)+len(irq)+len(tail)
            self.assertEqual(counts,dict(physical=lanes,fetch=width//16+1,data=lanes-width//16-1))
            self.assertEqual(data[12 if form=='MMTM' else 2 if form in ('RETS','CALLR') else 0:],[[(119 if x[6] else 114),x[5],x[1],x[2],x[3],x[4]] for x in irq])
            for index in range(6):
                for field in range(7):
                    bad = list(irq); lane = list(bad[index]); lane[field] ^= 1; bad[index] = tuple(lane)
                    with self.subTest(lane=index,field=field), self.assertRaises((ValueError,KeyError)):
                        b.partition_accesses(rows+bad+tail,cpu,widths,words.__getitem__)
            for bad in (irq[:-1],irq+irq[-1:],list(reversed(irq))):
                with self.assertRaises(ValueError): b.partition_accesses(rows+bad+tail,cpu,widths,words.__getitem__)
            bad_after = list(after); bad_after[18] ^= 16
            with self.assertRaises(ValueError): b.partition_accesses(rows+irq+tail,[before,bad_after],widths,words.__getitem__)

    def test_cpu_trace_requires_one_terminal_pair_and_checks_diagnostics(self):
        _,trace,start,end,bc = self.protocol()
        self.assertEqual(len(b.parse_cpu_trace(trace,start,end)),2)
        for lines in (trace+trace[-2:],trace[:-2],trace+['[LUA ERROR] observer failed'],
                      trace+['unexpected trace record'],[trace[0],'FF80DD50: MOVE A0,A1,0',*trace[2:]]):
            with self.subTest(lines=lines[-2:]), self.assertRaises(ValueError): b.parse_cpu_trace(lines,start,end)

    def test_stdout_diagnostics_and_discarded_bytes_reject_successful_producer(self):
        for output,discarded in (('[LUA ERROR] observer failed\n',0),('',1)):
            with self.assertRaises(ValueError):
                b.validate_execution({'passed':True,'stdout':output,'discarded_output_bytes':discarded})
        b.validate_execution({'passed':True,'stdout':'MAME ready\n','discarded_output_bytes':0})

    def test_raw_parser_rejects_unknown_physical_direction(self):
        from tools.quality import run as quality
        with quality.scratch_tree() as (scratch,cleanup):
            (scratch/'debug.log').write_text('BATCH_START\nNB x FF800110 FF800100 482D 1 16 FF800100\n')
            with self.assertRaisesRegex(ValueError,'Malformed physical batch access'):
                b.read_observations(scratch,{},lambda _:0,False)
        self.assertFalse(cleanup['exists_after'])

    def test_fetch_partition_requires_every_rom_lane_in_execution_order(self):
        cpu = [[0xff800100, 0, 1], [0xff800130, 0, 4]]
        widths = {0xff800100: 48, 0xff800130: 16}
        words = {0xff800100: 0x0bc0, 0xff800110: 4, 0xff800120: 0, 0xff800130: 0x482d}
        rows = [(0xff800110, 0xff800100, 0x0bc0, 1, 16, 0xff800100, False),
                (0xff800130, 0xff800110, 4, 1, 16, 0xff800100, False),
                (0xff800130, 0xff800120, 0, 1, 16, 0xff800100, False),
                (0xff800130, 0xff800130, 0x482d, 1, 16, 0xff800100, False),
                (0xff800140, 0xff800130, 0x482d, 4, 16, 0xff800130, False)]
        data, counts = b.partition_accesses(rows, cpu, widths, words.__getitem__)
        self.assertEqual(counts, {"physical": 5, "fetch": 4, "data": 1})
        self.assertEqual(data, [[114, 0xff800100, 0xff800130, 0x482d, 1, 16]])
        for corrupt in (rows[:-1], rows[:2]+rows[1:], [rows[1], rows[0], *rows[2:]]):
            with self.assertRaises(ValueError): b.partition_accesses(corrupt, cpu, widths, words.__getitem__)

    def test_complete_comparison_rejects_missing_extra_reordered_and_mutated(self):
        native = {key: [list(range(width)), list(range(width, 2*width))]
                  for key, width in (("batch_cpu", 34), ("batch_dsp_trace", 76), ("batch_bus", 6))}
        native.update({key: [0, 1] for key in b.ARRAY_KEYS if key not in native})
        self.assertTrue(b.compare(native, native)["passed"])
        import copy
        for key in native:
            for mutation in ("missing", "extra", "reverse", "value"):
                bad = copy.deepcopy(native)
                if mutation == "missing": bad[key].pop()
                elif mutation == "extra": bad[key].append(bad[key][-1])
                elif mutation == "reverse": bad[key].reverse()
                elif isinstance(bad[key][0], list): bad[key][0][-1] ^= 1
                else: bad[key][0] ^= 1
                self.assertFalse(b.compare(native, bad)["passed"], (key, mutation))
        for field in range(76):
            bad = copy.deepcopy(native)
            bad['batch_dsp_trace'][0][field] ^= 1
            self.assertFalse(b.compare(native,bad)['passed'], field)


if __name__ == "__main__": unittest.main()

