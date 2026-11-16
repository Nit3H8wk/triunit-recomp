"""Second from-reset reference gate: full continuation after the preserved historical gate."""
from pathlib import Path
from collections import deque
import argparse
import json
import re
import struct
import sys
import threading
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2.oracle_digest import words_digest
from tools.mk2 import reference, run, generate_task_batch as generated
from tools.mk2.packed_trace import PackedRows
from tools.quality import run as quality

ROOT = run.ROOT
START, END = 1261260, 1487718
EXTENDED_END = 1716210
NEXT_END = 2173200
LARGER_END = 3087189
PAIR_FILE_WINDOWS = ((3658091,0xff80dd30,4341320,0xff808010),
                     (4341320,0xff808010,5077311,0xff80dd30))
MAME = Path('D:/Emuladores/Mame/mame2080/mame.exe')
MAME_SHA = '84b690dad588253139ea49ae5e3c9fcddf9df7bcd526fccd1724ec7e09120dec'
ARRAY_KEYS = tuple('batch_' + name for name in (
    'cpu', 'final_cpu', 'bus', 'main_ram', 'cmos', 'palette_ram', 'vram', 'shiftreg', 'io', 'dma',
    'display', 'dsp_trace', 'dsp_accesses', 'transfers', 'irq_events', 'pcm', 'dac', 'dsp_device',
    'dsp_pm', 'dsp_dm', 'dsp_external_pm', 'dsp_external_dm', 'dsp_control', 'dsp_final',
    'irq_state', 'inputs', 'ports', 'dma_reads', 'dma_positions'))


def dma_brackets(trace, transfers, *, terminal=None):
    pending, result = {}, {}
    for tick,pc,cycle,reg,first,after,count in transfers:
        if reg!=7 or count!=240 or (first,after) not in ((0x400,0x4f0),(0x4f0,0x400)):
            raise ValueError('Unqualified SPORT packet')
        if (pc,cycle) in pending: raise ValueError('Duplicate SPORT instruction bracket')
        pending[pc,cycle] = first,after
    i7, previous = reference.DSP_REGISTERS.index('i7'), None
    def bracket(pc, cycle, after_i7):
        key = pc,cycle
        if key in pending:
            first,after = pending.pop(key)
            if previous is None or previous[1]+1!=cycle or previous[i7]!=first or after_i7!=after:
                raise ValueError('Audio DMA lacks exact instruction brackets')
            result[key] = previous[1]
    for row in trace:
        if not pending: break
        bracket(row[0],row[1],row[i7])
        previous = row
    if pending and terminal is not None: bracket(*terminal)
    if pending: raise ValueError('Missing audio DMA instruction brackets')
    return result


def native_dma_reads(native):
    trace, transfers, pcm = native['batch_dsp_trace'], native['batch_transfers'], native['batch_pcm']
    if len(pcm)!=len(transfers)*240: raise ValueError('Incomplete native DMA/PCM packets')
    final = native['batch_dsp_final']
    brackets, result = dma_brackets(trace,transfers,terminal=(final[0],final[1],final[23])), []
    for packet,(tick,pc,cycle,reg,first,after,count) in enumerate(transfers):
        result.extend([tick,pc,brackets[pc,cycle],first+n,pcm[packet*240+n]&0xffff] for n in range(240))
    return result


def external_irq_bracket(before, after, lanes, annotation):
    """Recover a reference post-instruction bracket, retaining all ordinary lanes.

    Saved ST is an observation, not an independently proved instruction result.
    The native comparison must still check it and every ordinary data lane.
    """
    index, return_pc, line = annotation
    sp = after[18]
    if (index < 0 or line != 0 or return_pc & 15 or after[:2] != [0xff8045d0, 0x10] or
            after[2] <= before[2] + 16 or sp & 15 or not 0x01000000 <= sp <= 0x013fffc0 or
            len(lanes) < 6):
        raise ValueError('Invalid external INT1 CPU bracket')
    tail = lanes[-6:]
    if any(not 0 <= row[2] <= 0xffff for row in tail):
        raise ValueError('Invalid external INT1 word')
    status = tail[2][2] | tail[3][2] << 16
    if not status & 0x00200000:
        raise ValueError('External INT1 entered with IE clear')
    expected = [(return_pc, address, value, before[2], 16, before[0], write)
        for address, value, write in (
            (sp+32, return_pc & 0xffff, True), (sp+48, return_pc >> 16, True),
            (sp, status & 0xffff, True), (sp+16, status >> 16, True),
            (0xffffffc0, 0x45d0, False), (0xffffffd0, 0xff80, False))]
    if [tuple(row) for row in tail] != expected:
        raise ValueError('External INT1 physical entry differs')
    post = list(after)
    post[:3] = return_pc, status, after[2] - 16
    post[18] += 64
    return post


# Asynchronous display IRQs of the batch window: (source PC, cycle) -> (interrupted PC, end cycle, SHA-256 of the
# Original's pushed ST, ST before the instruction, SP before and SP at entry; oracle_digest.words_digest order).
# The ST/SP values come from the capture itself (CPU rows and push lanes) and must reproduce the digest.
IRQ_CONTEXTS = {
    (0xff807ef0,1599433):(0xff807e40,1599456,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c'),
    (0xff807ea0,1713676):(0xff807ed0,1713695,'8211b5bd25fba0b647a59450ec2fec02c6c6fd67c692611d3315d3f589aa7099'),
    (0xff807ef0,1827923):(0xff807e40,1827946,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c'),
    (0xff807ed0,1942167):(0xff807ee0,1942186,'d72fa17ae8f5c5b08dcc4701bf4c7ef8d18de376ff749e79bae7f8fa545d2606'),
    (0xff807ef0,2056411):(0xff807df0,2056434,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c'),
    (0xff807e20,2170658):(0xff807e70,2170677,'3abe137c858d96aaa2f314ecac6ea094119527c11c5fe2675649225bd487f019'),
    (0xff807e70,2284903):(0xff807ea0,2284922,'55209c21a7c5f78688335ef1f658561cb6580efb3260f415e107f783aaccc7f5'),
    (0xff807ef0,2399148):(0xff807e40,2399171,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c'),
    (0xff807e70,2513393):(0xff807ea0,2513412,'55209c21a7c5f78688335ef1f658561cb6580efb3260f415e107f783aaccc7f5'),
    (0xff807da0,2627639):(0xff807dd0,2627658,'2dcc39c84c88a8c6e7979edb9571070571c8c4da63e3f723c7b9858ad7daec20'),
    (0xff807e70,2741885):(0xff807ea0,2741904,'55209c21a7c5f78688335ef1f658561cb6580efb3260f415e107f783aaccc7f5'),
    (0xff807ef0,2856130):(0xff807df0,2856153,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c'),
    (0xff807df0,2970377):(0xff807e20,2970396,'2dcc39c84c88a8c6e7979edb9571070571c8c4da63e3f723c7b9858ad7daec20'),
    (0xff808070,3084616):(0xff807da0,3084639,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c'),
    (0xff807dd0,3198866):(0xff807e70,3198885,'3abe137c858d96aaa2f314ecac6ea094119527c11c5fe2675649225bd487f019'),
    (0xff807d30,3313103):(0xff807d50,3313149,'62ec44ad6cdf78d22a58235bf67e5dfcdd4a9d1ea3d78c3f30f327c82de6f281'),
    (0xff807ee0,3427357):(0xff807f00,3427375,'be3b3b3edd02a4975d1b4a86a9b7c4d2ffe375907547d6012fe358d15117ddf3'),
    (0xff807e70,3541603):(0xff807ea0,3541622,'55209c21a7c5f78688335ef1f658561cb6580efb3260f415e107f783aaccc7f5'),
    (0xff808070,3655846):(0xff807da0,3655869,'b652bda5cfc426c267d4f1ab38ba83234be968a9339f486f3ef9bcaa396a9d3c')}


def irq_state_digest(pushed_status, before_status, old_sp, sp):
    return words_digest([pushed_status, before_status, old_sp, sp])


def partition_accesses(rows, cpu, widths, opcode):
    """Cross-check the classifier against independently decoded, ordered execution fetches."""
    expected = deque()
    for index,row in enumerate(cpu):
        pc,status,cycle=row[:3]
        bits=widths[pc]
        # DSJ A9's zero exit skips the encoded displacement without reading it.
        if opcode(pc)==0x0d89 and row[12]==1:
            if (bits!=32 or index+1==len(cpu) or
                (cpu[index+1][0],cpu[index+1][1],cpu[index+1][2],cpu[index+1][12])!=(pc+32,status,cycle+2,0)):
                raise ValueError('Unqualified DSJ skipped-parameter CPU bracket')
            bits=16
        expected.extend((pc,cycle,pc+offset,opcode(pc+offset)) for offset in range(0,bits,16))
    interrupts = {}
    brackets = [(before, after) for before, after in zip(cpu, cpu[1:]) if (before[0], before[2]) in IRQ_CONTEXTS]
    keys = {(before[0], before[2]) for before, _ in brackets}
    pushes = {}
    for pc, address, value, cycle, size, source, write in rows:
        if write and (source, cycle) in keys: pushes.setdefault((source, cycle), {})[pc, address] = value   # last push
    for before, after in brackets:
        key = (before[0], before[2])
        target,end_cycle,state = IRQ_CONTEXTS[key]
        old_sp,sp = before[18],after[18]
        # Pushed ST: the capture's own ST push lanes at the entry SP; the ordered lane check below still applies.
        lanes = pushes.get(key, {})
        status = lanes.get((target,sp), -1) | lanes.get((target,sp+16), -1) << 16
        if ((after[0],after[1],after[2]) != (0xff816370,0x10,end_cycle) or status < 0 or
                irq_state_digest(status, before[1], old_sp, sp) != state):
            raise ValueError('Unqualified asynchronous display IRQ CPU brackets')
        # check_interrupt() pushes PC/ST and reads the vector while CURPC/cycles
        # still identify the prior instruction; RETS has already changed PC.
        interrupts[key] = deque((target,address,value,before[2],16,before[0],write)
            for address,value,write in ((sp+32,target&0xffff,True),(sp+48,target>>16,True),
                (sp,status&0xffff,True),(sp+16,status>>16,True),
                (0xfffffea0,opcode(0xfffffea0),False),(0xfffffeb0,opcode(0xfffffeb0),False)))
    data, count, fetches = [], 0, 0
    for pc, address, value, cycle, size, source, write in rows:
        count += 1
        irq = interrupts.get((source,cycle))
        if irq is not None and not irq:
            raise ValueError('Extra physical lanes after asynchronous display IRQ')
        # CALL pushes its return address between opcode/displacement fetches, before IRQ entry.
        fetching = expected and expected[0][:2] == (source,cycle)
        if (irq is not None and irq and not fetching and
                (len(irq)<6 or address==irq[0][1]) and (write or address in (0xfffffea0,0xfffffeb0))):
            if not irq or irq.popleft() != (pc,address,value,cycle,size,source,write):
                raise ValueError('Asynchronous display IRQ physical lanes differ')
            row = [119 if write else 114,source,address,value,cycle,size]
        else:
            row = reference.dispatcher_bus_row(pc, address, value, cycle, size, source, write, opcode)
        if row is None:
            if size != 16 or not expected or expected.popleft() != (source, cycle, address, value):
                raise ValueError('Physical instruction fetch differs from independently decoded execution')
            fetches += 1
        else: data.append(row)
    if expected: raise ValueError('Missing physical instruction fetch lanes')
    if any(interrupts.values()): raise ValueError('Missing asynchronous display IRQ physical lanes')
    return data, {'physical': count, 'fetch': fetches, 'data': len(data)}


def compare(native, observed, *, instruction_trace=True, protection=False):
    protection=protection or 'batch_protection' in native or 'batch_protection' in observed
    keys=ARRAY_KEYS+('batch_protection',) if protection else ARRAY_KEYS
    if protection:
        if set(native)!=set(keys) or set(observed)!=set(keys):
            return {'passed':False,'first_difference':'Protection observation schema differs'}
        if any(len(data['batch_protection'])!=1 or type(data['batch_protection'][0]) is not int or
               not 0<=data['batch_protection'][0]<=0xffff for data in (native,observed)):
            return {'passed':False,'first_difference':'Invalid protection word'}
    counts = {}
    for key in keys:
        if key in ('batch_dsp_trace', 'batch_irq_events') and not instruction_trace: continue
        if key not in native or key not in observed or len(native[key]) != len(observed[key]):
            return {'passed': False, 'first_difference': key + ' missing or different length',
                    'native_count': len(native.get(key, [])), 'reference_count': len(observed.get(key, []))}
        for index, (a, b) in enumerate(zip(native[key], observed[key])):
            # Same historical concurrent-debugger cycle cache exclusion; instruction trace cycles stay exact.
            if key == 'batch_dsp_final' and index == 1: continue
            if a != b:
                return {'passed': False, 'first_difference': key, 'index': index, 'native': a, 'reference': b}
        counts[key] = len(native[key])
    return {'passed': True, 'values_compared_in_full': counts,
            'full_dsp_instruction_trace': instruction_trace}


def decoded_rows(directory, manifest, pcs=generated.PCS):
    image = reference.factory_program_image(directory, manifest)
    from tools.mk2.offline_decode import decode
    rows, _ = decode(image, pcs)
    return rows, reference.factory_opcode_reader(image)


def join_pair_windows(first, second):
    """Consume adjacent FILE windows without dropping or duplicating any observed row."""
    if (not first['batch_cpu'] or not second['batch_cpu'] or
        first['batch_final_cpu'] != second['batch_cpu'][0] or
        first['batch_inputs'] != second['batch_inputs'][:len(first['batch_inputs'])]):
        raise ValueError('Coin pair FILE windows are not contiguous reproductions')
    access_offset=len(first['batch_dsp_accesses'])
    rows=('batch_cpu','batch_bus','batch_dsp_trace','batch_dsp_accesses','batch_transfers',
          'batch_irq_events','batch_pcm','batch_dma_reads','batch_dma_positions')
    for key in rows:
        for row in second[key]:
            first[key].append(row+access_offset if key=='batch_dma_positions' else row)
    for key in ARRAY_KEYS:
        if key not in rows: first[key]=second[key]
    return first


def capture_pair_file():
    """Keep the unchanged 2 GiB ceiling per owned FILE capture, joining exact adjacent intervals."""
    result={'windows':[]};observed=None;totals={}
    for window in PAIR_FILE_WINDOWS:
        with quality.scratch_tree() as (scratch,cleanup):
            part=capture(scratch,coin_pair=True,window=window)
            current=part.pop('observed');part['cleanup']=cleanup
            for key,value in part['access_partition'].items(): totals[key]=totals.get(key,0)+value
            observed=current if observed is None else join_pair_windows(observed,current)
        result['windows'].append(part)
    if (len(observed['batch_cpu'])!=485629 or totals.get('physical')!=1095374 or
        totals.get('irq')!=8466 or totals.get('external_irq_annotations')!=1399):
        raise ValueError('Incomplete joined coin pair FILE observations')
    result.update(observed=observed,access_partition=totals)
    return result


def decoded_widths(directory, manifest, pcs=generated.PCS):
    rows, opcode = decoded_rows(directory,manifest,pcs)
    return {pc: row[0] for pc, row in rows.items()}, opcode


class CaptureDone(Exception): pass


def validate_execution(execution):
    if not execution.get('passed') or execution.get('discarded_output_bytes',0):
        raise ValueError('Failed or incomplete MAME diagnostic output')
    for line in execution.get('stdout','').splitlines(): reference.reject_mame_diagnostic(line)


def cpu_row(fields):
    state = reference.cpu_snapshot(fields)
    return [state['pc'], state['status'], state['cycles'], *state['a'], *state['b']]


START_INPUT_LUA = r'''
local start_port=assert(machine.ioport.ports[":IN1"])
local start_button=assert(start_port.fields["1 Player Start"])
assert(start_button.mask==4)
local start_frame,start_previous=0,start_port:read()
mk2_start_frame_subscription=emu.add_machine_frame_notifier(function()
    start_frame=start_frame+1
    local tick=math.floor(machine.time:as_double()*100000000+0.5)
    local value=start_port:read()
    if (value & 4)~=(start_previous & 4) then
        input_events[#input_events+1]={tick,start_requested,value,5};start_previous=value
    end
    if start_frame==200 or start_frame==202 then
        start_requested=start_frame==200 and 1 or 0
        start_button:set_value(start_requested)
        input_events[#input_events+1]={tick,start_requested,start_port:read(),4}
    end
end)
'''


SELECTION_INPUT_LUA=r"""
local selection_frame=0
mk2_selection_input_subscription=emu.add_machine_frame_notifier(function()
    selection_frame=selection_frame+1
    if selection_frame==240 or selection_frame==242 then
        local tick=math.floor(machine.time:as_double()*100000000+0.5)
        requested=selection_frame==240 and 1 or 0
        button:set_value(requested)
        input_events[#input_events+1]={tick,requested,input_port:read(),0}
    end
end)
"""

DSP_SYMBOLS = tuple(reference.DSP_REGISTERS) + ('irq1', 'curpc')
COMPACT_DSP_READ = 'do :maincpu.pb@01ffffc0'


def compact_dsp_lua(streaming=False):
    """Read the same debugger symbols in explicit DSP context, then restore it."""
    fmt = 'DSP_STATE ' + ' '.join(['%X'] * len(DSP_SYMBOLS))
    parameters = ','.join(DSP_SYMBOLS)
    if streaming:
        from tools.mk2.stream_transport import FLUSH
        command = (FLUSH + ';logerror "@@MK2_STREAM_DIRECT %d 1\\n' + fmt +
                   '\\n@@MK2_STREAM_DIRECT_END %d\\n",(temp9=temp9+1),' + parameters + ',temp9')
    else:
        command = 'printf "' + fmt + '",' + parameters
    return '''
local compact_debug = assert(manager.machine.debugger)
local compact_dsp = assert(manager.machine.devices[":dcs:dcs"])
mk2_compact_dsp_tap = assert(manager.machine.devices[":maincpu"]).spaces["program"]:install_read_tap(
    0x01ffffc0,0x01ffffcf,"mk2-compact-dsp",function()
        local previous = assert(compact_debug.visible_cpu)
        compact_debug.visible_cpu = compact_dsp
        local ok, message = pcall(function()
            assert(compact_debug.visible_cpu == compact_dsp)
            compact_debug:command(''' + json.dumps(command) + ''')
        end)
        compact_debug.visible_cpu = previous
        assert(compact_debug.visible_cpu == previous)
        assert(ok,message)
    end)
'''


def capture(scratch, *, full=True, extended=False, streaming=False, next_batch=False,
            larger_batch=False, expected_dsp_trace=None, coin_queue=False, coin_accounting=False, coin_pair=False,
            window=None, start_wait=False, next_wait=False, prestart_window=None, start_input=False, start_release=False, selection_window=None, first_fight_window=None, compact_dsp=False):
    """Real reset, same legal inputs; only the suffix DSP trace needs a second log."""
    selected=None
    if first_fight_window is not None:
        from tools.mk2.generate_first_fight import interval
        selected=interval(first_fight_window)
        if any((extended,next_batch,larger_batch,coin_queue,coin_accounting,coin_pair,start_wait,next_wait,start_input,start_release)) or prestart_window is not None or window is not None or selection_window is not None:
            raise ValueError('Select one measured first-fight interval')
    if selection_window is not None:
        from tools.mk2.generate_selection import interval
        selected=interval(selection_window)
        if any((extended,next_batch,larger_batch,coin_queue,coin_accounting,coin_pair,start_wait,next_wait,start_input,start_release)) or prestart_window is not None or window is not None:
            raise ValueError('Select one measured selection interval')
    if start_release and (any((extended,next_batch,larger_batch,coin_queue,coin_accounting,coin_pair,start_wait,next_wait,start_input)) or prestart_window is not None or window is not None):
        raise ValueError('Select one Start release endpoint')
    if start_input and (any((extended,next_batch,larger_batch,coin_queue,coin_accounting,coin_pair,start_wait,next_wait)) or prestart_window is not None or window is not None):
        raise ValueError('Select one Start input endpoint')
    if prestart_window is not None:
        from tools.mk2.generate_prestart_wait import interval
        selected=interval(prestart_window)
        if any((extended,next_batch,larger_batch,coin_queue,coin_accounting,coin_pair,start_wait,next_wait)) or window is not None:
            raise ValueError('Select one measured waiting interval')
    if start_wait and next_wait:
        raise ValueError("Select one waiting endpoint")
    manifest = run.read_manifest()
    if (start_wait or next_wait) and window is not None:
        raise ValueError('Start wait uses its complete measured observation interval')
    if window is not None and (not coin_pair or window not in PAIR_FILE_WINDOWS or streaming):
        raise ValueError('Unsupported reference observation window')
    from tools.mk2 import generate_coin_queue as coin
    from tools.mk2 import generate_coin_accounting as accounting
    from tools.mk2 import generate_coin_pair as pair
    if first_fight_window is not None:
        from tools.mk2 import generate_first_fight as pair
        selected=pair.interval(first_fight_window)
        expected_window=(selected['start'],pair.END_PC,selected['end'],pair.END_PC)
        if window is not None and tuple(window)!=expected_window:raise ValueError('First-fight observation window differs')
        window=expected_window
        coin_pair=True
    elif selection_window is not None:
        from tools.mk2 import generate_selection as pair
        selected=pair.interval(selection_window)
        expected_window=(selected['start'],pair.END_PC,selected['end'],pair.END_PC)
        if window is not None and tuple(window)!=expected_window:raise ValueError('Selection observation window differs')
        window=expected_window
        coin_pair=True
    elif start_release:
        from tools.mk2 import generate_start_release as pair
        expected_window=(pair.START,pair.END_PC,pair.END,pair.END_PC)
        if window is not None and tuple(window)!=expected_window: raise ValueError('Start release observation window differs')
        window=expected_window
        coin_pair=True
    elif start_input:
        from tools.mk2 import generate_start_input as pair
        expected_window=(pair.START,pair.END_PC,pair.END,pair.END_PC)
        if window is not None and tuple(window)!=expected_window: raise ValueError('Start input observation window differs')
        window=expected_window
        coin_pair=True
    elif prestart_window is not None:
        from tools.mk2 import generate_prestart_wait as pair
        selected=pair.interval(prestart_window)
        expected_window=(selected['start'],pair.END_PC,selected['end'],pair.END_PC)
        if window is not None and tuple(window)!=expected_window: raise ValueError('Pre-Start observation window differs')
        window=expected_window
        coin_pair=True
    elif next_wait:
        from tools.mk2 import generate_next_wait as pair
        coin_pair = True
    elif start_wait:
        from tools.mk2 import generate_start_wait as pair
        coin_pair = True
    decoded, opcode = decoded_rows(ROOT / 'roms/mk2', manifest, pair.PCS if coin_pair else accounting.PCS if coin_accounting else coin.PCS if coin_queue else generated.PCS)
    widths = {pc:row[0] for pc,row in decoded.items()}
    original = quality.command
    result = {}

    def command(args, directory, **unused):
        if first_fight_window is not None or selection_window is not None or start_release or start_input or prestart_window is not None or next_wait:
            args=list(args)
            index=args.index('-seconds_to_run')+1
            if args[index]!='1': raise ValueError('Unexpected base virtual reference horizon')
            args[index]=str(max(20,(selected['end']*16+99999999)//100000000+1)) if first_fight_window is not None else '6' if selection_window is not None else '4' if start_release or start_input or prestart_window is not None else '2'  # Exact debugger stops delimit the measured interval.
        path = scratch / 'reset.cmd'
        source = path.read_text().splitlines()
        lines, dsp_breaks, bp_count = [], [], 0
        registers = [f'a{n}' for n in range(15)] + ['sp'] + [f'b{n}' for n in range(15)]
        fmt = 'BC %X %X %d ' + ' '.join(['%X']*31) + '\\n'
        snapshot = f'printf "{fmt}",pc,st,totalcycles,' + ','.join(registers)
        trace_snapshot = snapshot.replace('printf ', 'tracelog ', 1)
        start_cycle = pair.START if coin_pair else accounting.START if coin_accounting else coin.START if coin_queue else NEXT_END if larger_batch else START
        if window is not None: start_cycle=window[0]
        for line in source:
            if line == 'go': continue
            line = re.sub(r'wpclear [0-9a-fA-F,]+', 'wpclear', line)
            if line.startswith('bpset '):
                bp_count += 1
                if ':dcs:dcs,' in line and 'MK2_DSP_BEGIN' in line and 'MK2_DSP_IRQ1' not in line:
                    dsp_breaks.append(bp_count)
                    line = line.replace(';g}', ';printf "%X\\n",w@1a80000;g}')
            if 'MK2_CPU task_draw_ready ' in line:
                if not line.endswith(';quit}'): raise ValueError('Historical endpoint changed')
                tail = ';printf "BATCH_START\\n";' + snapshot
                tail += ';wpset 0:maincpu,ffffffff,r,1,{printf "NB r %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                tail += ';wpset 0:maincpu,ffffffff,w,1,{printf "NB w %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                for watch in source:
                    if watch.startswith('wpset ') and ':dcs:dcs:' in watch: tail += ';' + watch
                # Enable normal DSP snapshots only for the new interval; all historic IRQ hooks stay intact.
                if full: tail += ''.join(f';bpenable {n:04x}' for n in dsp_breaks)
                tail += f';trace batch-cpu.log,:maincpu,noloop,{{{trace_snapshot}}};g}}'
                if larger_batch or coin_queue or coin_accounting or coin_pair:
                    lines.append(line[:-6] + ';g}')
                    start_pc = coin.END_PC if coin_accounting else 0xff80dd30
                    if window is not None: start_pc=window[1]
                    line = f'bpset {start_pc:x},totalcycles=={start_cycle:x},{{' + tail[1:]
                else: line = line[:-6] + tail
            lines.append(line)
        lines += [f'bpdisable {n:04x}' for n in dsp_breaks]
        final = snapshot + ';trace off;wpclear;printf "BATCH_DSP_FINAL\\n";symlist :dcs:dcs'
        final += ';do :maincpu.pw@01ffffe0'
        final += ';save batch-main.bin,1000000,400000;save batch-cmos.bin,1400000,20000;save batch-palette.bin,1800000,80000'
        final += ';save batch-pm.bin,0:dcs:dcs,400;saved batch-dm.bin,3800:dcs:dcs,200;saved batch-control.bin,3fe0:dcs:dcs,20;save batch-external.bin,800:dcs:dcs,800;saved batch-external-dm.bin,0:dcs:dcs,800'
        final += ';printf "BATCH_END\\n";quit'
        end_cycle = pair.END if coin_pair else accounting.END if coin_accounting else coin.END if coin_queue else LARGER_END if larger_batch else NEXT_END if next_batch else EXTENDED_END if extended else END
        end_pc = accounting.END_PC if coin_accounting else coin.END_PC if coin_queue else 0xff80dd30
        if window is not None: end_cycle,end_pc=window[2:]
        lines += [f'bpset {end_pc:x},totalcycles=={end_cycle:x},{{{final}}}', 'go']
        path.write_text('\n'.join(lines)+'\n', encoding='ascii')
        lua = scratch / 'video.lua'
        lua.write_text(lua.read_text().replace('(pc == 0x136 or', '(pc == 0x130 or pc == 0x136 or') + r'''
local batch_irqs, batch_last_irq = {}, 0
local batch_irq_tap = main.spaces["program"]:install_read_tap(0x01a80000,0x01a8000f,"batch-irqs",function()
    local tick=math.floor(machine.time:as_double()*100000000+0.5)
    local state=irq_state:read(1)
    if tick > 20180160 and state ~= batch_last_irq then
        local dsp=machine.devices[":dcs:dcs"]
        batch_irqs[#batch_irqs+1]={tick,dsp.state["PC"].value,state}
    end
    batch_last_irq=state
end)
local batch_tap = main.spaces["program"]:install_read_tap(0x01ffffe0,0x01ffffef,"batch-final",function()
    assert(main.state["PC"].value == 0xff80dd30)
    local function dump(name,item,count,code)
        local file=assert(io.open("batch-"..name..".bin","wb"))
        for n=0,count-1 do assert(file:write(string.pack(code,assert(item:read(n))))) end
        file:close()
    end
    dump("vram",vram,524288,"<I2"); dump("shift",shiftreg,4096,"<I2")
    dump("dma",dma,18,"<I2"); dump("dac",dac_buffer,32768,"<I4")
    local file=assert(io.open("batch-device.bin","wb"))
    for _,item in ipairs(device_items) do assert(file:write(string.pack("<I8",assert(item:read(0))))) end
    file:close()
    file=assert(io.open("batch-inputs.bin","wb"))
    for _,row in ipairs(input_events) do assert(file:write(string.pack("<I8I8I8I8",table.unpack(row)))) end
    file:close()
    file=assert(io.open("batch-ports.bin","wb"))
    for _,name in ipairs({":IN0",":IN1",":IN2",":DSW"}) do
        assert(file:write(string.pack("<I2",assert(machine.ioport.ports[name]):read())))
    end
    assert(file:write(string.pack("<I2",requested))); file:close()
    file=assert(io.open("batch-audio-dma.bin","wb"))
    for n=2881,#dma_rows do assert(file:write(string.pack("<I8I8I8I8",table.unpack(dma_rows[n])))) end
    file:close()
    file=assert(io.open("batch-irq.bin","wb"))
    assert(file:write(string.pack("<I8I8",irq_state:read(1),irq_latch:read(1))))
    file:close()
    file=assert(io.open("batch-irq-events.bin","wb"))
    for _,row in ipairs(batch_irqs) do assert(file:write(string.pack("<I8I8I8",table.unpack(row)))) end
    file:close()
    file=assert(io.open("batch-io.bin","wb"))
    local io_regs=bind(main,"m_IOregs")
    for n=0,27 do assert(file:write(string.pack("<I2",assert(io_regs:read(n))))) end
    file:close()
    file=assert(io.open("batch-display.bin","wb"))
    assert(file:write(string.pack("<I2I2",main.spaces["program"]:read_u16(0xc00001d0),main.spaces["program"]:read_u16(0xc00001e0))))
    file:close()
end)
mk2_batch_stop_subscription=emu.add_machine_stop_notifier(function()
    batch_tap:remove(); batch_irq_tap:remove()
end)
''', encoding='ascii')
        if larger_batch or coin_queue or coin_accounting or coin_pair:
            lua.write_text(lua.read_text().replace('tick > 20180160', f'tick > {start_cycle*16}')
                           .replace('for n=2881,#dma_rows', f'for n={14881 if coin_pair else 13201 if coin_accounting else 12001 if coin_queue else 7441},#dma_rows'), encoding='ascii')
        if window is not None or start_wait or next_wait:
            text=lua.read_text().replace(
                'for n=14881,#dma_rows do assert(file:write(string.pack("<I8I8I8I8",table.unpack(dma_rows[n])))) end',
                f'for n=1,#dma_rows do if dma_rows[n][1]>{start_cycle*16} then assert(file:write(string.pack("<I8I8I8I8",table.unpack(dma_rows[n])))) end end')
            lua.write_text(text,encoding='ascii')
        if coin_queue or coin_accounting or coin_pair:
            source = lua.read_text().replace('assert(main.state["PC"].value == 0xff80dd30)',
                                             f'assert(main.state["PC"].value == 0x{end_pc:x})')
            source = source.replace('local batch_irqs,', 'local coin_requested=0\nlocal batch_irqs,')
            source = source.replace('assert(file:write(string.pack("<I2",requested))); file:close()',
                'assert(file:write(string.pack("<I2I2",requested,coin_requested))); file:close()')
            source += '''
local coin_port=assert(machine.ioport.ports[":IN1"])
local coin=assert(coin_port.fields["Coin 1"])
assert(coin.mask==1)
local coin_frame,coin_previous=0,coin_port:read()
mk2_coin_frame_subscription=emu.add_machine_frame_notifier(function()
    coin_frame=coin_frame+1
    local tick=math.floor(machine.time:as_double()*100000000+0.5)
    local value=coin_port:read()
    if value~=coin_previous then
        input_events[#input_events+1]={tick,coin_requested,value,3}; coin_previous=value
    end
    if coin_frame==28 or coin_frame==30 then
        coin_requested=coin_frame==28 and 1 or 0
        coin:set_value(coin_requested)
        input_events[#input_events+1]={tick,coin_requested,coin_port:read(),2}
    end
end)
'''
            if coin_pair:
                source=source.replace('if coin_frame==28 or coin_frame==30 then',
                    'if coin_frame==28 or coin_frame==30 or coin_frame==34 or coin_frame==36 then')
                source=source.replace('coin_requested=coin_frame==28 and 1 or 0',
                    'coin_requested=(coin_frame==28 or coin_frame==34) and 1 or 0')
            lua.write_text(source,encoding='ascii')
        if start_input or start_release or (selection_window is not None or first_fight_window is not None):
            source=lua.read_text()
            if source.count('if value~=coin_previous then')!=1: raise ValueError('Missing original Coin notifier')
            source=source.replace('if value~=coin_previous then','if (value & 1)~=(coin_previous & 1) then')
            source=source.replace('local batch_irqs,','local start_requested=0\nlocal batch_irqs,',1)
            token='string.pack("<I2I2",requested,coin_requested)'
            if source.count(token)!=1: raise ValueError('Missing original input port snapshot')
            source=source.replace(token,'string.pack("<I2I2I2",requested,coin_requested,start_requested)')
            lua.write_text(source+START_INPUT_LUA,encoding='ascii')
        if start_release or (selection_window is not None or first_fight_window is not None):
            source=lua.read_text()
            source=source.replace('local batch_irqs,','local protection=bind(assert(machine.devices[":"]),"m_mk2_prot_data")\nassert(protection.size==2 and protection.count==1)\nlocal batch_irqs,',1)
            token='dump("vram",vram,524288,"<I2"); dump("shift",shiftreg,4096,"<I2")'
            if source.count(token)!=1: raise ValueError('Missing final video/device snapshot')
            source=source.replace(token,token+'\n    dump("protection",protection,1,"<I2")')
            lua.write_text(source,encoding='ascii')
        if selection_window is not None or first_fight_window is not None:
            with lua.open('a',encoding='ascii') as stream:stream.write(SELECTION_INPUT_LUA)
        if compact_dsp:
            script=path.read_text()
            if 'symlist :dcs:dcs' not in script: raise ValueError('Missing DSP symbol observations')
            path.write_text(script.replace('symlist :dcs:dcs',COMPACT_DSP_READ),encoding='ascii')
            lua.write_text(compact_dsp_lua(streaming)+lua.read_text(),encoding='ascii')
        if streaming:
            from tools.mk2 import stream_transport
            path.write_text(stream_transport.instrument_script(path.read_text()),encoding='ascii')
            lua.write_text(stream_transport.lua_source()+lua.read_text(),encoding='ascii')
            args = [arg for arg in args if str(arg) != '-debuglog'] + ['-oslog']
        stopped, exceeded, children = threading.Event(), [], []
        popen = quality.subprocess.Popen
        def launch(*a, **k):
            child = popen(*a, **k); children.append(child); return child
        def watch():
            while not stopped.wait(.1):
                total = sum(p.stat().st_size for p in scratch.iterdir() if p.is_file())
                if total > reference.REFERENCE_LOG_LIMIT_BYTES:
                    exceeded.append(total)
                    for child in children:
                        if child.poll() is None: child.kill()
                    return
        thread = threading.Thread(target=watch, daemon=True); thread.start()
        try:
            with patch.object(quality.subprocess, 'Popen', side_effect=launch):
                if streaming:
                    parser = DebugParser(start_cycle=start_cycle,end_cycle=end_cycle,expected_dsp_trace=expected_dsp_trace)
                    execution = stream_transport.command(args,scratch,parser.feed,reference.reject_mame_diagnostic)
                    raw = parser.finish()
                else:
                    execution = original(args, directory, timeout=2400, cwd=scratch)
        finally: stopped.set(); thread.join()
        result['execution'] = quality.compact(execution)
        result['streaming_transport'] = streaming
        result['live_dsp_rows_checked'] = len(raw['trace']) if streaming and expected_dsp_trace is not None else 0
        result['script_sha256'] = quality.sha(path)
        validate_execution(execution)
        if not execution['passed'] or exceeded: raise RuntimeError('Batch MAME execution failed or exceeded storage limit')
        result['observed'], result['access_partition'] = read_observations(
            scratch, widths, opcode, full, extended=extended, next_batch=next_batch,
            larger_batch=larger_batch, coin_queue=coin_queue, coin_accounting=coin_accounting,
            coin_pair=coin_pair, decoded=decoded, window=window, raw=raw if streaming else None,
            start_wait=start_wait, next_wait=next_wait, prestart_window=prestart_window,start_input=start_input,start_release=start_release,selection_window=selection_window,first_fight_window=first_fight_window)
        if window is not None: result['window']=window
        result['log_bytes'] = (scratch / 'debug.log').stat().st_size if not streaming else 0
        result['debug_spool_used'] = not streaming
        result['cpu_log_bytes'] = (scratch / 'batch-cpu.log').stat().st_size
        raise CaptureDone()
    try:
        with patch.object(quality, 'command', side_effect=command):
            reference._capture(scratch, MAME, ROOT / 'roms/mk2', manifest)
    except CaptureDone: pass
    return result


class DebugParser:
    """The same strict parser accepts live records without a debugger-log spool."""
    def __init__(self, *, start_cycle=START, end_cycle=END, expected_dsp_trace=None):
        self.records = _parse_debug_records(start_cycle=start_cycle,end_cycle=end_cycle, expected_dsp_trace=expected_dsp_trace)
        self.closed = False
        next(self.records)

    def feed(self, line):
        if self.closed or not isinstance(line, str): raise ValueError('Debug parser is closed or record is not text')
        try: self.records.send(line)
        except Exception:
            self.closed = True
            raise

    def finish(self):
        if self.closed: raise ValueError('Debug parser already closed')
        self.closed = True
        try: self.records.send(None)
        except StopIteration as done: return done.value
        raise ValueError('Debug parser did not terminate')


def parse_debug_lines(stream, *, start_cycle=START, end_cycle=END):
    parser = DebugParser(start_cycle=start_cycle,end_cycle=end_cycle)
    for line in stream: parser.feed(line)
    return parser.finish()


def _parse_debug_records(*, start_cycle=START, end_cycle=END, expected_dsp_trace=None):
    start, end, physical, trace, accesses, dma_raw, final_dsp = None, None, [], PackedRows(), [], [], None
    active, symbols, irq_hooks, previous_irq, dma_positions = None, {}, [], 0, []
    def finish():
        nonlocal active, symbols, final_dsp, previous_irq
        if active is None: return
        if any(key not in symbols for key in reference.DSP_REGISTERS):
            raise ValueError('Incomplete batch DSP snapshot')
        row = [symbols[key] & (0x3fff if re.fullmatch(r'm[0-7]', key) else 0xffffffffffffffff)
               for key in reference.DSP_REGISTERS]
        if active[0] == 'MK2_DSP_BEGIN':
            if ((row[0]==0x829 and (len(active)!=2 or active[1].upper() not in ('D0CB0','0D0CB0','806114'))) or
                    (row[0]!=0x829 and len(active)!=1)):
                raise ValueError('Malformed DSP instruction opcode observation')
            if expected_dsp_trace is not None:
                index = len(trace)
                if index >= len(expected_dsp_trace) or row != expected_dsp_trace[index]:
                    raise ValueError(f'Live DSP instruction differs at row {index}')
            trace.append(row)
            if 'irq1' not in symbols: raise ValueError('Missing DSP IRQ1 symbol')
            if symbols['irq1'] != previous_irq:
                irq_hooks.append([row[0],row[1],symbols['irq1']]); previous_irq = symbols['irq1']
        elif active[0] == 'BATCH_DSP_FINAL':
            if final_dsp is not None: raise ValueError('Duplicate final DSP state')
            final_dsp = row
        elif active[0] == 'MK2_DSP_ACCESS':
            if len(active) != 4 or 'curpc' not in symbols: raise ValueError('Incomplete DSP access')
            access = [int(active[1],16), symbols['curpc'], int(active[2],16), int(active[3],16), symbols['totalcycles']]
            if access[0] == 114 and 0x400 <= access[2] < 0x5e0 and symbols['pc'] in range(0x130,0x139):
                if len(dma_raw)%240==0: dma_positions.append(len(accesses))
                elif dma_positions[-1]!=len(accesses): raise ValueError('CPU access interrupts an audio DMA packet')
                dma_raw.append([symbols['pc'], *access])
            else: accesses.append(access)
        active, symbols = None, {}
    in_batch, ended = False, False
    tags = {'MK2_DSP_BEGIN','MK2_DSP_ACCESS','BATCH_DSP_FINAL','NB','BC','BATCH_END'}
    while True:
        line = yield
        if line is None: break
        line = line.rstrip('\r\n'); reference.reject_mame_diagnostic(line)
        if line == 'BATCH_START':
            if in_batch: raise ValueError('Duplicate batch start')
            in_batch = True
            continue
        if not in_batch:
            if line.startswith('BATCH_'): raise ValueError('Malformed batch start')
            continue
        if line.startswith(('MK2_', 'BATCH_', 'NB', 'BC')):
            if ended: raise ValueError('Observation after batch end')
            fields = line.split()
            if fields[0] not in tags: raise ValueError('Unknown batch observation')
            finish()
            if fields[0] in ('MK2_DSP_BEGIN','MK2_DSP_ACCESS'):
                if start is None or end is not None: raise ValueError('DSP observation outside batch interval')
                active = fields
            elif fields[0] == 'BATCH_DSP_FINAL':
                if len(fields)!=1 or end is None or final_dsp is not None:
                    raise ValueError('Malformed or misplaced final DSP boundary')
                active = fields
            elif fields[0] == 'NB':
                if len(fields) != 8 or fields[1] not in ('r','w'):
                    raise ValueError('Malformed physical batch access')
                if start is None or end is not None: raise ValueError('Physical access outside batch interval')
                physical.append((int(fields[2],16),int(fields[3],16),int(fields[4],16),
                                 int(fields[5]),int(fields[6]),int(fields[7],16),fields[1]=='w'))
            elif fields[0] == 'BC':
                row = cpu_row(fields[1:])
                if row[2] == start_cycle:
                    if start is not None: raise ValueError('Duplicate initial CPU boundary')
                    start = row
                elif row[2] == end_cycle:
                    if start is None or end is not None: raise ValueError('Misplaced final CPU boundary')
                    end = row
                else: raise ValueError('Unexpected debugger CPU boundary')
            elif fields[0] == 'BATCH_END':
                if len(fields)!=1 or start is None or end is None or final_dsp is None:
                    raise ValueError('Malformed or premature batch end')
                ended = True
        else:
            if line.startswith('DSP_STATE'):
                values=line.split()
                if (active is None or ended or symbols or values[0]!='DSP_STATE' or
                    len(values)!=len(DSP_SYMBOLS)+1 or
                    any(re.fullmatch('[0-9A-F]{1,16}',value) is None for value in values[1:])):
                    raise ValueError('Malformed, duplicate or unframed compact DSP snapshot')
                symbols=dict(zip(DSP_SYMBOLS,(int(value,16) for value in values[1:])))
                continue
            match = re.fullmatch(r'([a-z0-9_]+) = ([0-9A-F]+)(?:  \(read-only\))?',line)
            if match:
                if active is None or ended: raise ValueError('Unframed DSP symbol outside batch record')
                if match[1] in symbols: raise ValueError('Duplicate DSP symbol')
                symbols[match[1]] = int(match[2],16)
    finish()
    if not start or not end or not ended or final_dsp is None: raise ValueError('Incomplete batch endpoints')
    if expected_dsp_trace is not None and len(trace) != len(expected_dsp_trace):
        raise ValueError('Incomplete live DSP instruction comparison')
    return {'start':start, 'end':end, 'physical':physical, 'trace':trace, 'accesses':accesses, 'dma_raw':dma_raw, 'final_dsp':final_dsp, 'irq_hooks':irq_hooks, 'dma_positions':dma_positions}


def parse_cpu_trace(stream, start, end, *, end_cycle=END, irq_annotations=None):
    cpu = [start]
    row, disassembled, terminal = None, None, False
    annotations, pending_irq = [], False
    for line in stream:
        reference.reject_mame_diagnostic(line)
        line = line.strip()
        if not line: continue
        if terminal: raise ValueError('CPU trace observation after terminal boundary')
        if line.startswith('(interrupted '):
            event=re.fullmatch(r'\(interrupted at ([0-9A-Fa-f]{8}), IRQ (0)\)',line)
            if event is None: raise ValueError('Unsupported CPU trace IRQ annotation')
            if irq_annotations is None: raise ValueError('CPU trace IRQ annotation requires explicit event capture')
            if row is not None or disassembled is not None or pending_irq:
                raise ValueError('Misplaced or duplicate CPU trace IRQ annotation')
            annotations.append((len(cpu)-1,int(event[1],16),int(event[2])))
            pending_irq=True
            continue
        if line.startswith('BC '):
            if row is not None: raise ValueError('Duplicate CPU snapshot without disassembly')
            row = cpu_row(line.split()[1:])
        else:
            match = re.fullmatch(r'([0-9A-Fa-f]{8}):\s*\S.*',line)
            if match is None or disassembled is not None: raise ValueError('Unknown or duplicate CPU trace record')
            disassembled = int(match[1],16)
        if row is not None and disassembled is not None:
            if row[0]!=disassembled or not cpu[-1][2]<row[2]<=end_cycle:
                raise ValueError('CPU trace PC or cycle order differs')
            if row[2]==end_cycle:
                if row!=end: raise ValueError('Trace and debugger final CPU differ')
                terminal = True
            else: cpu.append(row)
            row, disassembled = None, None
            pending_irq=False
    if not terminal or row is not None or disassembled is not None or pending_irq:
        raise ValueError('Incomplete CPU trace terminal pair')
    if irq_annotations is not None: irq_annotations.extend(annotations)
    return cpu


def read_observations(scratch, widths, opcode, full, *, extended=False, next_batch=False, larger_batch=False, raw=None, coin_queue=False, coin_accounting=False, coin_pair=False, decoded=None, window=None, start_wait=False, next_wait=False, prestart_window=None, start_input=False, start_release=False, selection_window=None, first_fight_window=None):
    from tools.mk2 import generate_coin_queue as coin
    from tools.mk2 import generate_coin_accounting as accounting
    from tools.mk2 import generate_coin_pair as pair
    if first_fight_window is not None:
        from tools.mk2 import generate_first_fight as pair
        selected=pair.interval(first_fight_window)
        expected_window=(selected['start'],pair.END_PC,selected['end'],pair.END_PC)
        if window is not None and tuple(window)!=expected_window:raise ValueError('First-fight observation window differs')
        window=expected_window
        coin_pair=True
    elif selection_window is not None:
        from tools.mk2 import generate_selection as pair
        selected=pair.interval(selection_window)
        expected_window=(selected['start'],pair.END_PC,selected['end'],pair.END_PC)
        if window is not None and tuple(window)!=expected_window:raise ValueError('Selection observation window differs')
        window=expected_window
        coin_pair=True
    elif start_release:
        from tools.mk2 import generate_start_release as pair
        expected_window=(pair.START,pair.END_PC,pair.END,pair.END_PC)
        if window is not None and tuple(window)!=expected_window: raise ValueError('Start release observation window differs')
        window=expected_window
        coin_pair=True
    elif start_input:
        from tools.mk2 import generate_start_input as pair
        expected_window=(pair.START,pair.END_PC,pair.END,pair.END_PC)
        if window is not None and tuple(window)!=expected_window: raise ValueError('Start input observation window differs')
        window=expected_window
        coin_pair=True
    elif prestart_window is not None:
        from tools.mk2 import generate_prestart_wait as pair
        selected=pair.interval(prestart_window)
        expected_window=(selected['start'],pair.END_PC,selected['end'],pair.END_PC)
        if window is not None and tuple(window)!=expected_window: raise ValueError('Pre-Start observation window differs')
        window=expected_window
        coin_pair=True
    elif next_wait:
        from tools.mk2 import generate_next_wait as pair
        coin_pair = True
    elif start_wait:
        from tools.mk2 import generate_start_wait as pair
        coin_pair = True
    end_cycle = pair.END if coin_pair else accounting.END if coin_accounting else coin.END if coin_queue else LARGER_END if larger_batch else NEXT_END if next_batch else EXTENDED_END if extended else END
    start_cycle = pair.START if coin_pair else accounting.START if coin_accounting else coin.START if coin_queue else NEXT_END if larger_batch else START
    if window is not None: start_cycle,end_cycle=window[0],window[2]
    if raw is None:
        with (scratch/'debug.log').open(encoding='utf-8') as stream:
            raw=parse_debug_lines(stream,start_cycle=start_cycle,end_cycle=end_cycle)
    start,end,physical,trace,accesses,dma_raw,final_dsp,irq_hooks,dma_positions = (raw[key] for key in ('start', 'end', 'physical', 'trace', 'accesses', 'dma_raw', 'final_dsp', 'irq_hooks', 'dma_positions'))
    annotations=[] if coin_pair else None
    with (scratch/'batch-cpu.log').open(encoding='utf-8') as stream: cpu=parse_cpu_trace(stream,start,end,end_cycle=end_cycle,irq_annotations=annotations)
    if first_fight_window is not None and (len(cpu)!=selected['cpu_rows'] or words_digest(start)!=selected['start_cpu34_sha256'] or words_digest(end)!=selected['end_cpu34_sha256'] or
            ('physical_rows' in selected and len(physical)!=selected['physical_rows'])):
        raise ValueError('Incomplete measured first-fight CPU/physical interval')
    if start_release and (len(cpu)!=389582 or len(physical)!=727879):
        raise ValueError('Incomplete measured Start release CPU/physical interval')
    if start_input and (len(cpu)!=439431 or len(physical)!=813947):
        raise ValueError('Incomplete measured Start input CPU/physical interval')
    if (prestart_window is not None or selection_window is not None) and (len(cpu)!=selected['cpu_rows'] or len(physical)!=selected['physical_rows']):
        raise ValueError('Incomplete selected pre-Start CPU/physical interval')
    if not cpu or not physical or (window is None and (len(cpu) != (392474 if next_wait else 425616 if start_wait else 485629 if coin_pair else 75020 if coin_accounting else 50320 if coin_queue else 202812 if larger_batch else 202367 if next_batch else 100962 if extended else 50260) or len(physical) != (728042 if next_wait else 798990 if start_wait else 1095374 if coin_pair else 247028 if coin_accounting else 159442 if coin_queue else 614842 if larger_batch else 614019 if next_batch else 306602 if extended else 152893))):
        raise ValueError(f'Incomplete batch CPU/physical lanes: {len(cpu)}/{len(physical)}, first={cpu[:1]}, last={cpu[-1:]}')
    if coin_pair:
        from tools.mk2.physical_fetch import partition as partition_pair
        bus, partition = partition_pair(physical,cpu,end,decoded,opcode,annotations)
        partition['external_irq_annotations']=len(annotations)
    else:
        bus, partition = partition_accesses(physical,cpu,widths,opcode)
    observed = dict(batch_cpu=cpu,batch_final_cpu=end,batch_bus=bus,batch_dsp_trace=trace,
                    batch_dsp_accesses=accesses,batch_dsp_final=final_dsp)
    for key, filename, count, code in (
        ('main_ram','main',262144,'H'),('cmos','cmos',8192,'H'),('palette_ram','palette',32768,'H'),
        ('vram','vram',524288,'H'),('shiftreg','shift',4096,'H'),('io','io',28,'H'),('dma','dma',18,'H'),
        ('display','display',2,'H'),('dac','dac',32768,'I'),('dsp_device','device',17,'Q'),
        ('dsp_pm','pm',1024,'I'),('dsp_dm','dm',512,'H'),('dsp_control','control',32,'H'),
        ('dsp_external_pm','external',2048,'I'),('dsp_external_dm','external-dm',2048,'H'),
        ('irq_state','irq',2,'Q'),('ports','ports',7 if start_input or start_release or (selection_window is not None or first_fight_window is not None) else 6 if coin_queue or coin_accounting or coin_pair else 5,'H')):
        raw = (scratch / ('batch-'+filename+'.bin')).read_bytes()
        if len(raw) != struct.calcsize('<'+code)*count: raise ValueError('Incomplete batch '+key)
        observed['batch_'+key] = list(struct.unpack('<'+str(count)+code,raw))
    observed['batch_pcm'], observed['batch_transfers'], observed['batch_irq_events'] = [], [], []
    observed['batch_dma_reads'], observed['batch_dma_positions'] = [], dma_positions
    raw = (scratch/'batch-inputs.bin').read_bytes()
    if len(raw)!=(selected['input_events']*32 if (selection_window is not None or first_fight_window is not None) else 512 if start_release else 480 if start_input else 384 if coin_pair else 256 if coin_accounting else 192 if coin_queue else 128): raise ValueError('Incomplete batch input history')
    observed['batch_inputs']=[list(row) for row in struct.iter_unpack('<QQQQ',raw)]
    if start_release or (selection_window is not None or first_fight_window is not None):
        raw=(scratch/'batch-protection.bin').read_bytes()
        if len(raw)!=2: raise ValueError('Incomplete protection latch snapshot')
        observed['batch_protection']=[struct.unpack('<H',raw)[0]]
    # The CPU watchpoint records and the independent Lua DMA tap must agree for every lane.
    raw = (scratch / 'batch-audio-dma.bin').read_bytes()
    lua_dma = list(struct.iter_unpack('<QQQQ',raw))
    if len(lua_dma) != len(dma_raw) or len(lua_dma)%240:
        raise ValueError(f'DSP watchpoint/Lua DMA count differs: {len(dma_raw)}/{len(lua_dma)}')
    for first in range(0,len(lua_dma),240):
        group, hooks = lua_dma[first:first+240], dma_raw[first:first+240]
        tick, pc, address, _ = group[0]
        cycle = hooks[0][-1]
        if any(row[:3] != (tick,pc,address+n) or hook[0] != pc or hook[3:] != [address+n,row[3],cycle]
               for n,(row,hook) in enumerate(zip(group,hooks))): raise ValueError('Noncontiguous or mismatched audio DMA')
        after = 0x400 if address == 0x4f0 else 0x4f0
        observed['batch_transfers'].append([tick,pc,cycle+1,7,address,after,240])
        observed['batch_dma_reads'].extend([tick,pc,cycle,offset,value] for _,_,offset,value in group)
        observed['batch_pcm'].extend(value if value<0x8000 else value-0x10000 for _,_,_,value in group)
    if full:
        # The event clock is from matched DMA hooks; retain the concurrent cached final cycle unchanged.
        packets = observed['batch_transfers']
        terminal = (final_dsp[0],packets[-1][2],final_dsp[23]) if packets else None
        dma_brackets(trace,packets,terminal=terminal)
        events = list(struct.iter_unpack('<QQQ',(scratch/'batch-irq-events.bin').read_bytes()))
        if len(events) != len(irq_hooks): raise ValueError('Lua and debugger IRQ1 event counts differ')
        for (tick,pc,state),(hook_pc,cycle,hook_state) in zip(events,irq_hooks):
            if pc != hook_pc or state != hook_state: raise ValueError('Lua and debugger IRQ1 states differ')
            observed['batch_irq_events'].append([tick,pc,cycle,state])
    return observed, partition


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--micro', action='store_true')
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--extended', action='store_true')
    parser.add_argument('--next-batch', action='store_true')
    parser.add_argument('--larger-batch', action='store_true')
    parser.add_argument('--coin-queue', action='store_true')
    parser.add_argument('--coin-accounting', action='store_true')
    parser.add_argument('--coin-pair', action='store_true')
    parser.add_argument('--start-wait', action='store_true')
    parser.add_argument('--next-wait', action='store_true')
    parser.add_argument('--prestart-window',type=int,choices=range(16))
    parser.add_argument('--start-input',action='store_true')
    parser.add_argument('--start-release',action='store_true')
    parser.add_argument('--selection-window',type=int,choices=range(6))
    from tools.mk2.generate_first_fight import WINDOWS
    parser.add_argument('--first-fight-window',type=int,choices=range(len(WINDOWS)))
    parser.add_argument('--compare-transports', action='store_true',
                        help='Experimental full observation equivalence; streaming parses without a debugger spool')
    parser.add_argument('--sanitizer', choices=('none','undefined','address'), default='none')
    args = parser.parse_args()
    if sum((args.extended,args.next_batch,args.larger_batch,args.coin_queue,args.coin_accounting,args.coin_pair,args.start_wait,args.next_wait,args.start_input,args.start_release))+(args.prestart_window is not None)+(args.selection_window is not None)+(args.first_fight_window is not None)>1: parser.error('Select one batch endpoint')
    if args.compare_transports and (args.native_only or args.micro):
        parser.error('--compare-transports requires both integral reference captures')
    array_keys=ARRAY_KEYS+('batch_protection',) if args.start_release or (args.selection_window is not None or args.first_fight_window is not None) else ARRAY_KEYS
    files = sorted(set(run.SOURCES + run.HEADERS + run.VERIFIERS +
                       ['tools/mk2/batch_reference.py','tools/mk2/test_task_batch.py']))
    entry = {name:quality.sha(__import__('tools.setup.mk2',fromlist=['source']).source(name)) for name in files}
    receipt = {'passed':False,'entry':entry,'roms':run.verify_roms(ROOT/'roms/mk2'),
               'sanitizer':args.sanitizer,'extended':args.extended,'next_batch':args.next_batch,'larger_batch':args.larger_batch,'coin_queue':args.coin_queue,'coin_accounting':args.coin_accounting,
               'coin_pair':args.coin_pair,
               'start_wait':args.start_wait,
               'next_wait':args.next_wait,
               'prestart_window':args.prestart_window,
               'start_input':args.start_input,
               'start_release':args.start_release,
               'selection_window':args.selection_window,'first_fight_window':args.first_fight_window,
               'compare_transports':args.compare_transports,'full_dsp_instruction_trace':not args.micro}
    native = {}
    def observations(data):
        receipt['native_decodes'] = receipt.get('native_decodes',0) + 1
        native.update({key:data[key] for key in array_keys if key!='batch_dma_reads'})
        native['batch_dma_reads']=native_dma_reads(native)
        return data
    try:
        if quality.sha(MAME) != MAME_SHA: raise ValueError('MAME identity changed')
        reset = run.run('reset',ROOT/'roms/mk2',sanitizer=args.sanitizer,batch=True,
                        extended_batch=args.extended,next_batch=args.next_batch,larger_batch=args.larger_batch,coin_queue=args.coin_queue,coin_accounting=args.coin_accounting,
                        coin_pair=args.coin_pair,
                        start_wait=args.start_wait,next_wait=args.next_wait,prestart_window=args.prestart_window,start_input=args.start_input,start_release=args.start_release,selection_window=args.selection_window,first_fight_window=args.first_fight_window,
                        stream_native=True,observation_consumer=observations)
        receipt['native_execution'] = reset
        receipt['native_output_bytes'] = reset.get('native_output_bytes')
        if not reset['passed']: raise RuntimeError('Native batch failed: '+reset.get('error',''))
        receipt['native_counts'] = {key:len(native[key]) for key in array_keys}
        receipt['native_projection'] = {'counts':receipt['native_counts'], **{key:native[key] for key in
            ('batch_final_cpu','batch_dsp_final','batch_transfers','batch_irq_events','batch_dma_positions',
             'batch_ports','batch_inputs','batch_dsp_device')}}
        if args.start_release or (args.selection_window is not None or args.first_fight_window is not None): receipt['native_projection']['batch_protection']=native['batch_protection']
        if not args.native_only:
            with quality.scratch_tree() as (scratch, cleanup):
                receipt['cleanup'] = cleanup
                captured = capture_pair_file() if args.coin_pair and not args.micro else capture(scratch,full=not args.micro,extended=args.extended,next_batch=args.next_batch,larger_batch=args.larger_batch,coin_queue=args.coin_queue,coin_accounting=args.coin_accounting,coin_pair=args.coin_pair,start_wait=args.start_wait,next_wait=args.next_wait,prestart_window=args.prestart_window,start_input=args.start_input,start_release=args.start_release,selection_window=args.selection_window,first_fight_window=args.first_fight_window)
                observed = captured.pop('observed')
                receipt['reference'] = captured
                receipt['comparison'] = compare(native,observed,instruction_trace=not args.micro,protection=args.start_release or (args.selection_window is not None or args.first_fight_window is not None))
                if not receipt['comparison']['passed']: raise RuntimeError('Batch comparison failed')
            if args.compare_transports:
                with quality.scratch_tree() as (scratch, cleanup):
                    receipt['stream_cleanup'] = cleanup
                    captured = capture(scratch,full=True,extended=args.extended,streaming=True,next_batch=args.next_batch,
                                       larger_batch=args.larger_batch,coin_queue=args.coin_queue,coin_accounting=args.coin_accounting,coin_pair=args.coin_pair,start_wait=args.start_wait,next_wait=args.next_wait,prestart_window=args.prestart_window,start_input=args.start_input,start_release=args.start_release,selection_window=args.selection_window,first_fight_window=args.first_fight_window,expected_dsp_trace=native['batch_dsp_trace'])
                    streamed = captured.pop('observed')
                    receipt['stream_reference'] = captured
                    receipt['stream_comparison'] = compare(native,streamed,protection=args.start_release or (args.selection_window is not None or args.first_fight_window is not None))
                    receipt['transports_equal_in_full'] = observed == streamed
                    if not receipt['stream_comparison']['passed'] or not receipt['transports_equal_in_full']:
                        raise RuntimeError('Experimental transport observations differ in full')
        receipt['passed'] = True
    except Exception as error: receipt['error'] = str(error)
    finally:
        receipt['exit'] = {name:quality.sha(__import__('tools.setup.mk2',fromlist=['source']).source(name)) for name in files}
        receipt['inputs_equal'] = receipt['entry']==receipt['exit']
        receipt['passed'] = receipt['passed'] and receipt['inputs_equal']
        suffix = '-native' if args.native_only else '-micro' if args.micro else '-full'
        suffix += '' if args.sanitizer=='none' else '-'+args.sanitizer
        if args.compare_transports: suffix += '-transports'
        target = ROOT / ('build/native/mk2/batch'+('-first-fight-'+str(args.first_fight_window) if args.first_fight_window is not None else '-selection-'+str(args.selection_window) if args.selection_window is not None else '-start-release' if args.start_release else '-start-input' if args.start_input else '-prestart-'+str(args.prestart_window) if args.prestart_window is not None else '-next-wait' if args.next_wait else '-start-wait' if args.start_wait else '-coin-pair' if args.coin_pair else '-coin-accounting' if args.coin_accounting else '-coin' if args.coin_queue else '-larger' if args.larger_batch else '-next' if args.next_batch else '-extended' if args.extended else '')+suffix+'.json')
        target.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:receipt.get(key) for key in ('passed','error','comparison','native_counts','cleanup')},indent=2))
    raise SystemExit(0 if receipt['passed'] else 1)
