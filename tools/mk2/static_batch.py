"""Experimental L3.1 batch AOT build. The installed core and its receipts are independent."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import time

from tools.mk2 import coverage, generate_adsp, generate_architectural as architectural, oracle_digest
from tools.mk2 import generate_static_cfg as cfg, generate_video_irq as emitter
from tools.mk2 import package_native as package, run
from tools.mk2.offline_decode import BASE, END, authenticate, scan_aligned
from tools.quality import cpp_build, run as quality

ROOT = emitter.ROOT
NATIVE = ROOT / 'native/mk2'
LEGACY = NATIVE / 'mk2_first_fight.inc'
RUNTIME = NATIVE / 'mk2_task_batch.cpp'
LINK_FLAGS = ['-l'+name for name in ('bcrypt', 'user32', 'gdi32', 'winmm', 'd3d12',
                                    'dxgi', 'd3dcompiler', 'dxguid')] + ['-Wl,--no-insert-timestamp']
OBSERVED_ROOTS = {
    0xff804630: 'MK2_ROM_COVERAGE.md, Original D002/8423 bus watchpoint',
    0xff805240: 'MK2_ROM_COVERAGE.md, Original MMTM bus watchpoint',
    0xff8cdac0: 'test_architectural_dispatch.py, Original checksum return',
    0xff9b3d60: 'MK2_ROM_COVERAGE.md, JAN at reported Pit II crash',
    0xffa0ecd0: 'test_architectural_dispatch.py, Original checksum entry',
}


# (range-check PC, table base in bits, first index used by JUMP, entry count).
# The field-1 loads read 32-bit addresses at table base + (index << 5).
BOUNDED_JUMP_TABLES = {
    0xff836e10: (0xff836d70, 0xff836e30, 0, 3),  # 1..3 followed by DEC.
    0xff83bbf0: (0xff83bb10, 0xff83bc00, 1, 10),  # 0 returns, 1..9 jump.
    0xff9b6bf0: (0xff9b6b60, 0xff9b6c30, 0, 3),  # Clamp to 2.
    0xffa49cb0: (0xffa49c10, 0xffa49cc0, 0, 5),  # high32(random * 5).
    0xffa51fb0: (0xffa51f20, 0xffa521d0, 0, 9),  # Clamp to 8.
}

# Original 1P/2P dispatches, with only the observed slot admitted as data.
# These sites keep their computed:JUMP frontier for every other selector.
OBSERVED_JUMP_SLOTS = {
    0xff81a320: (0xff81a330, 0xff81a3b0),
    0xff878130: (0xff8781e0, 0xff86bc60),
    0xff888df0: (0xff888fa0, 0xff892e70),
}

# These selectors pop the encoded CALL continuation before reading the inline
# longwords. The bool says whether another path jumps past the inline data.
INLINE_POINTER_SELECTORS = {
    0xff83d710: (1, True),  # FF83D8A0 / FF83D8D0 -> FF83D900.
    0xff83d7e0: (1, True),  # Inverted actor C/D test, same shared tail.
    0xff9c9b80: (2, True),  # FF9C9C40 / FF9C9C60.
    0xff9c9ca0: (2, False),  # FF9C9FF0 reads slot 0 or 1, FF9CA000 jumps.
}


# The first producer dominates each transfer. The second either adds to the
# loaded address or replaces it on the conditional path before the CALL.
REGISTER_TRANSFERS = {
    0xff814770: (0xff8146f0, 0xff814740),
    0xff819bf0: (0xff819b90, 0xff819bc0),
    0xff830bb0: (0xff830b20, 0xff830b80),
    0xff876830: (0xff876790, 0xff876800),
    0xff8cdab0: (0xff8cda50, 0xff8cda80),
    0xffa0ef10: (0xffa0eeb0, 0xffa0eee0),
}

# EXGPC writes its lexical successor to the register; it does not execute it.
# These two successors are read as data by independently decoded consumers.
DATA_READS = {
    0xff9e0830: (12, 0xff9e0100, 0xff9e0130),  # Address table -> A5, then field loads.
    0xffa4ee10: (20, 0xffa4ec80, 0xffa2ea20),  # MMFM reads five longwords from A8.
}

# Original CPU Board Test and Burn-In, byte spans read by FFA59180.
# Adjacent terminated strings share spans; padding between labels stays separate.
SERVICE_TEXT_READS = (
    (0xffa5dcb0, 16), (0xffa5dde0, 14), (0xffa5e0e0, 27), (0xffa5e640, 35),
    (0xffa5e760, 9), (0xffa6feb0, 9), (0xffa6ff00, 5), (0xffa6ff30, 5),
    (0xffa6ff60, 5), (0xffa6ff90, 5), (0xffa6ffc0, 5), (0xffa6fff0, 5),
    (0xffa70020, 5), (0xffa70050, 5), (0xffa70080, 9), (0xffa700d0, 5),
    (0xffa70100, 5), (0xffa70130, 5), (0xffa70160, 5), (0xffa70190, 5),
    (0xffa701c0, 5), (0xffa701f0, 5), (0xffa70220, 5), (0xffa70250, 5),
    (0xffa70280, 21), (0xffa70330, 5), (0xffa70360, 5), (0xffa70390, 5),
    (0xffa703c0, 5), (0xffa703f0, 5), (0xffa70420, 5), (0xffa70450, 5),
    (0xffa70480, 5), (0xffa704b0, 3), (0xffa704d0, 7), (0xffa70510, 23),
    (0xffa705d0, 7), (0xffa70610, 20), (0xffa70c90, 22),
)


def boot_text_data(rom):
    # FFA59180 reads the text; FFA591A0–FFA591F0 selects its font descriptor.
    def offset(address, width):
        at = (address - BASE) // 8
        if address & 7 or not 0 <= at <= len(rom) - width:
            raise ValueError('Boot text data outside the authenticated image')
        return at

    texts = {0xffa401c0: b'REVISION 3.1\0', 0xffa6abb0: b'CMOS OK\0',
             0xffa6a6c0: b'USING CMOS COINAGE\0'}
    spans = []
    for address, text in texts.items():
        at = offset(address, len(text))
        if rom[at:at+len(text)] != text:
            raise ValueError(f'Boot text differs at {address:08x}')
        spans.append((address, len(text), 0xffa59180))
    service_text = bytearray()
    for address, size in SERVICE_TEXT_READS:
        at = offset(address, size)
        service_text.extend(rom[at:at+size])
        spans.append((address, size, 0xffa59180))
    if hashlib.sha256(service_text).hexdigest() != 'baf07d5abb7c486b9507e4d8a8eb242101138ca45264b69abe2d43374ab36aa8':
        raise ValueError('Service text differs from the observed L3.1 reads')
    for char in sorted((set(b''.join(texts.values())) | set(service_text)) - {0}):
        table = 0xffa577d0 + (char - 32) * 32
        at = offset(table, 4)
        descriptor = int.from_bytes(rom[at:at+4], 'little')
        at = offset(descriptor, 8)
        width = int.from_bytes(rom[at:at+2], 'little')
        height = int.from_bytes(rom[at+2:at+4], 'little')
        glyph = int.from_bytes(rom[at+4:at+8], 'little')
        if not 1 <= width <= 16 or height != 8:
            raise ValueError('Boot glyph outside the qualified font')
        size = ((width + 7) // 8) * height
        offset(glyph, size)
        spans.extend(((table, 4, 0xffa591f0), (descriptor, 8, 0xffa59200), (glyph, size, 0xffa592b0)))
    return spans


def dcs_data_group(rom_directory, roms, evidence):
    name = evidence['rom']
    entry = next((rom for rom in roms if rom['path'] == name and rom['region'] == 'dcs'), None)
    if entry is None or evidence['rom_sha256'] != entry['sha256']:
        raise ValueError('DCS data evidence ROM identity differs')
    image = (rom_directory/name).read_bytes()
    spans, previous_end = [], 0
    digest = hashlib.sha256()
    for start, end in evidence['physical_intervals']:
        if type(start) is not int or type(end) is not int or not previous_end <= start < end <= len(image):
            raise ValueError('DCS data evidence interval is invalid')
        # The same bytes elsewhere in the ROM are not evidence for a physical interval.
        digest.update(start.to_bytes(4, 'little'))
        digest.update(end.to_bytes(4, 'little'))
        digest.update(image[start:end])
        spans.append((start, end, 2))
        previous_end = end
    if len(image) != entry['size'] or not spans or digest.hexdigest() != evidence['intervals_and_bytes_sha256']:
        raise ValueError('DCS data evidence offsets or bytes differ')
    return name, spans


def dcs_data_spans(rom_directory, roms):
    directory = Path(__file__).parent
    groups = {}
    for filename, format_name, rom in (
            ('dcs_data_reads.json', 'MK2_DCS_ROM_DATA_READS_V1', 'su3.l1'),
            ('dcs_voice_script_reads.json', 'MK2_DCS_VOICE_SCRIPT_READS_V1', 'su2.l1')):
        evidence = json.loads((directory/filename).read_text(encoding='utf8'))
        if evidence['format'] != format_name or evidence['rom'] != rom:
            raise ValueError('DCS data evidence ROM identity differs')
        name, spans = dcs_data_group(rom_directory, roms, evidence)
        groups[name] = spans
    return groups


def dcs_playback_spans(rom_directory, roms):
    evidence = json.loads((Path(__file__).parent/'dcs_playback_reads.json').read_text(encoding='utf8'))
    if (evidence['format'] != 'MK2_DCS_PLAYBACK_READS_V1' or
            tuple(group['rom'] for group in evidence['groups']) != tuple(f'su{socket}.l1' for socket in range(2,8))):
        raise ValueError('DCS playback evidence sockets differ')
    return dict(dcs_data_group(rom_directory, roms, group) for group in evidence['groups'])


def tms_replay_data(rom):
    evidence = json.loads((Path(__file__).parent/'tms_data_reads.json').read_text(encoding='utf8'))
    if (evidence['format'] != 'MK2_TMS_ROM_DATA_READS_V1'
            or evidence['program_sha256'] != emitter.PROGRAM_SHA256 or len(rom) != (END-BASE)//8):
        raise ValueError('TMS replay data ROM identity differs')
    spans, previous_end = [], -1
    digest = hashlib.sha256()
    for start, end in evidence['loaded_intervals']:
        if (type(start) is not int or type(end) is not int or (start | end) & 1
                or not previous_end < start < end <= (0xfffffc00-BASE)//8):
            raise ValueError('TMS replay data interval is invalid')
        digest.update(start.to_bytes(4, 'little') + end.to_bytes(4, 'little'))
        digest.update(rom[start:end])
        spans.append((start, end, 2))
        previous_end = end
    if not spans or digest.hexdigest() != evidence['intervals_and_bytes_sha256']:
        raise ValueError('TMS replay data offsets or bytes differ')
    roots = tuple(int(pc, 16) for pc in evidence['reader_roots_bits'])
    if not roots or tuple(sorted(set(roots))) != roots or any(pc & 15 or not BASE <= pc < END for pc in roots):
        raise ValueError('TMS replay reader roots are invalid')
    return spans, roots


def tms_observed_transfers(rows):
    evidence = json.loads((Path(__file__).parent/'tms_observed_transfers.json').read_text(encoding='utf8'))
    if (evidence['format'] != 'MK2_TMS_OBSERVED_TRANSFERS_V1'
            or evidence['program_sha256'] != emitter.PROGRAM_SHA256):
        raise ValueError('TMS observed transfer program identity differs')
    transfers = {}
    previous_pc = BASE-16
    for entry in evidence['sites']:
        pc, word = entry['pc'], entry['word']
        row = rows.get(pc)
        if (type(pc) is not int or pc <= previous_pc or row is None or row[0] != 16 or row[2] != (word,)
                or row[3].split()[0] not in ('JUMP', 'CALL', 'RETS')
                or pc in BOUNDED_JUMP_TABLES or pc in REGISTER_TRANSFERS):
            raise ValueError(f'TMS observed transfer source differs at {pc!r}')
        targets = tuple(entry['targets'])
        if (not targets or any(type(target) is not int or target not in rows or not rows[target][0]
                               or rows[target][3].startswith('DW') for target in targets)
                or tuple(sorted(set(targets))) != targets):
            raise ValueError(f'TMS observed transfer targets differ at {pc:08x}')
        transfers[pc] = targets
        previous_pc = pc
    return transfers


def register_targets(rows, pc):
    first, second = REGISTER_TRANSFERS[pc]
    op, reg = rows[pc][3].split()
    first_op, first_args = rows[first][3].split()
    second_op, second_args = rows[second][3].split()
    a, first_reg = first_args.split(',')
    b, second_reg = second_args.split(',')
    if first_op != 'MOVI' or second_op != {'CALL': 'MOVI', 'JUMP': 'ADDI'}[op] or (
            first_reg != reg or second_reg != reg or rows[first][0] != 48 or rows[second][0] != 48):
        raise ValueError(f'Register transfer provenance differs at {pc:08x}')
    a, b = emitter.immediate(a), emitter.immediate(b)
    if op == 'CALL':
        return tuple(sorted({a & ~15, b & ~15, pc + rows[pc][0]}))
    return (((a + b) & 0xfffffff0),)


def translator_inputs():
    directory = Path(__file__).parent
    names = ('static_batch.py', 'offline_decode.py', 'generate_architectural.py', 'generate_video_irq.py',
             'generate_static_cfg.py', 'generate_adsp.py', 'coverage.py', 'dsp_branch_closure.json',
             'first_fight_path.json', 'static_cfg_path.json', 'roms-l31.json', 'dcs_data_reads.json',
             'tms_data_reads.json', 'dcs_playback_reads.json', 'tms_observed_transfers.json',
             'dcs_voice_script_reads.json')
    return {name: quality.sha(directory/name) for name in names}


def successors(rom, pc, width, asm, trap_one, *, mk2=True):
    op = asm.split()[0]
    if op == 'DW':
        return (), None
    try:
        targets = architectural.closure_targets(pc, width, asm, trap_one, rom=rom, mk2=mk2)
    except ValueError:
        return (), None
    if mk2 and op in ('CALLA', 'CALLR'):
        callee = emitter.transfer_target(op, asm.split()[1])
        if callee in INLINE_POINTER_SELECTORS:
            count, skips = INLINE_POINTER_SELECTORS[callee]
            inline = pc + width
            offset = (inline - BASE)//8
            end = offset + count*4
            if not 0 <= offset < end <= len(rom):
                raise ValueError(f'Inline pointer data extends outside ROM at {pc:08x}')
            targets = {callee, *(int.from_bytes(rom[at:at+4], 'little')
                                for at in range(offset, end, 4))}
            if skips:
                targets.add(inline + count*32)
            return tuple(sorted(targets)), (offset, end)
    return targets, None


def tms_graph(rom, rows, *, reader_roots=(), witnessed_transfers=None, program=None):
    """program: identity of another authenticated image (offline_decode.authenticate); its roots are the
    vectors plus reader_roots, and none of the MK2 L3.1 roots, data reads or transfer tables apply."""
    mk2 = program is None
    if not mk2:
        authenticate(rom, program)
    # The TMS34010 trap table also includes the reset and hardware IRQ vectors.
    vectors = {pc: int.from_bytes(rom[(pc-BASE)//8:(pc-BASE)//8+4], 'little')
               for pc in range(0xfffffc00, END, 32)}
    data = {(0xfffffc00-BASE)//8: len(rom)}
    # Original data reads. These spans preserve any overlapping code evidence.
    for address, width in ((0xffa03fc0, 12), (0xffa04320, 96),  # Observed stream record and command list.
                           (0xff85dd10, 52), (0xff85deb0, 234),  # Pit II callback stream and record table.
                           (0xffa65c20, 40),  # Switch Test: two 18-byte records and sentinel.
                           (0xffa5f0d0, 2), (0xffa5f0f0, 2)) if mk2 else ():  # Observed indexed reads, slots 1 and 3.
        offset = (address-BASE)//8
        data[offset] = offset + width
    for address, (width, _, _) in DATA_READS.items() if mk2 else ():
        offset = (address-BASE)//8
        data[offset] = offset + width
    for address, width, _ in boot_text_data(rom) if mk2 else ():
        offset = (address-BASE)//8
        data[offset] = offset + width
    trap_one = vectors[0xffffffc0]
    witnessed_transfers = witnessed_transfers or {}
    pending = set(reader_roots) | witnessed_transfers.keys()
    if mk2:
        from tools.mk2.generate_first_fight import BASE_PCS
        pending |= set(BASE_PCS) | OBSERVED_ROOTS.keys()
    pending.update(target & ~15 for target in vectors.values() if target >= BASE)
    tables = (BOUNDED_JUMP_TABLES, OBSERVED_JUMP_SLOTS, REGISTER_TRANSFERS, DATA_READS) if mk2 else ({},) * 4
    bounded, slots, transfers, reads = tables
    graph = {}
    exchanges = defaultdict(set)
    open_edges = defaultdict(set)
    while pending:
        pc = pending.pop()
        if pc in graph:
            continue
        width, _, _, asm = rows[pc]
        targets, interval = successors(rom, pc, width, asm, trap_one, mk2=mk2) if width else ((), None)
        if pc in bounded:
            _, base, first, count = bounded[pc]
            offset = (base-BASE)//8
            end = offset + count*4
            targets = tuple(sorted({int.from_bytes(rom[at:at+4], 'little')
                                    for at in range(offset + first*4, end, 4)}))
            if asm.split() != ['JUMP', 'A0'] or any(target not in rows for target in targets):
                raise ValueError(f'Bounded jump table provenance differs at {pc:08x}')
            interval = (offset, end)
        elif pc in slots:
            slot, target = slots[pc]
            offset = (slot-BASE)//8
            if (asm.split() != ['JUMP', 'A0'] or target not in rows
                    or int.from_bytes(rom[offset:offset+4], 'little') != target):
                raise ValueError(f'Observed jump table provenance differs at {pc:08x}')
            targets = (target,)
            interval = (offset, offset+4)
        elif pc in transfers:
            targets = register_targets(rows, pc)
        elif width and asm.startswith('EXGPC') and pc+width in reads:
            targets = ()
        if pc in witnessed_transfers:
            targets = tuple(sorted(set(targets).union(witnessed_transfers[pc])))
        if interval:
            data[interval[0]] = interval[1]
        if (width and asm.split()[0] in cfg.DYNAMIC and pc not in bounded
                and pc not in transfers):
            open_edges['computed:'+asm.split()[0]].add(pc)
        graph[pc] = targets
        if width == 48 and asm.startswith('MOVI ') and targets == (pc + width,):
            value, register = asm.split()[1].split(',')
            exchange = pc + width
            target = emitter.immediate(value) & 0xfffffff0
            # The contiguous MOVI establishes this destination only for its incoming edge.
            if (exchange in rows and rows[exchange][3].split() == ['EXGPC', register]
                    and target in rows and rows[target][0]):
                exchanges[exchange].add(target)
                pending.add(target)
        for target in targets:
            if target in rows:
                if target not in graph:
                    pending.add(target)
            else:
                open_edges['outside_aligned_rom'].add((pc, target))
    for exchange, targets in exchanges.items():
        graph[exchange] = tuple(sorted(set(graph[exchange]) | targets))
    return graph, data, vectors, open_edges


def tms_sources(rom, rows, scratch, pcs, lanes, *, physical_map=None):
    started = time.perf_counter()
    replay_spans, reader_roots = tms_replay_data(rom)
    if any(rows[pc][3].split()[0] not in ('MOVE', 'MOVB', 'MMFM') for pc in reader_roots):
        raise ValueError('TMS replay reader opcode differs')
    witnessed_transfers = tms_observed_transfers(rows)
    graph, data, vectors, open_edges = tms_graph(rom, rows, reader_roots=reader_roots,
                                                witnessed_transfers=witnessed_transfers)
    inventory = Counter((asm.split()[0] if width else 'truncated') for width, _, _, asm in rows.values())
    source = LEGACY.read_text(encoding='utf8')
    blocks = {int(match[1], 16): match[0]+'\n' for match in coverage.CASE.finditer(source)}
    legacy = {pc: (asm, kind) for pc, _, asm, kind in coverage.blocks(source)}
    for pc, (asm, _) in legacy.items():
        if rows[pc][3] != asm:
            raise ValueError(f'Baseline C++ annotation differs from ROM at {pc:08x}')
    # A ROM-shaped value elsewhere is an address candidate, without an execution edge.
    pointers = {int.from_bytes(rom[offset:offset+4], 'little')
                for offset in range(0, len(rom)-3, 2)}
    pointers = {pc for pc in pointers if pc in rows}
    spans = [(begin, end, 2) for begin, end in data.items()] + replay_spans
    data_offsets = {offset for begin,end,_ in spans for offset in range(begin,end)}
    overlapping_starts, code_end = 0, 0
    for pc in sorted(graph.keys() | legacy.keys()):
        width, _, _, asm = rows[pc]
        if width:
            offset = (pc-BASE)//8
            kind = 1 if pc in graph and asm.split()[0] != 'DW' else 4
            spans.append((offset, offset+width//8, kind))
            if kind == 1:
                overlapping_starts += offset < code_end
                code_end = max(code_end, offset+width//8)
    counts = Counter()
    for _, length, mask in coverage.partition(len(rom), spans):
        counts[str(mask)] += length
    analyzed = time.perf_counter()

    added, baseline_emission = Counter(), Counter()
    exceptions = defaultdict(list)
    stop_classes = Counter({'static_code_candidate': 0, 'identified_data': 0, 'ambiguous': 0})
    states = {}

    def count_stop(pc, op):
        if (pc-BASE)//8 in data_offsets and pc not in graph:
            stop_classes['identified_data'] += 1
        elif pc in graph and op not in ('DW', 'truncated'):
            stop_classes['static_code_candidate'] += 1
        else:
            stop_classes['ambiguous'] += 1

    admitted = graph.keys() | legacy.keys()
    for pc in sorted(admitted):
        width, _, words, asm = rows[pc]
        op = asm.split()[0] if asm else 'truncated'
        if pc in legacy:
            maturity = legacy[pc][1]
            upgrade = (maturity == 'explicit_stop' and pc in graph and
                       (op in ('REV', 'ZEXT', 'DSJEQ', 'DSJNE', 'EXGF', 'SUBB', 'CVXYL', 'DRAV') or
                        (op in ('PIXBLT', 'PIXT') and pc in (0xffa592b0, 0xffa58df0, 0xffa598d0))))
            if not upgrade:
                states[pc] = maturity
                if maturity == 'explicit_stop':
                    count_stop(pc, op)
                if maturity != 'generated':
                    exceptions[(op, width, maturity, pc in graph)].append(pc)
                if maturity != 'explicit_stop':
                    try:
                        targets = cfg.direct_targets(pc, width, asm, vectors[0xffffffc0]) or ()
                        code = emitter.emit_instruction(pc, width, asm, words, legacy, {pc: targets}, end=0xff80dd30, mame_table=True)
                        generated = f'case 0x{pc:08x}u: {{ // {asm}\n    {code}\n    break;\n}}\n'
                    except ValueError:
                        generated = None
                    if generated == blocks[pc]:
                        blocks[pc] = generated
                        baseline_emission['reproduced'] += 1
                    else:
                        baseline_emission['retained_body'] += 1
                continue
        try:
            if not width or op == 'DW':
                raise ValueError('no decoded instruction')
            targets = cfg.direct_targets(pc, width, asm, vectors[0xffffffc0]) or ()
            code = emitter.emit_instruction(pc, width, asm, words, admitted, {pc: targets}, batch_forms=True, mame_table=True)
        except ValueError as error:
            states[pc] = 'explicit_stop'
            count_stop(pc, op)
            exceptions[(op, width, str(error).split(':')[0].replace(f'{pc:08x}', 'PC'), True)].append(pc)
            code = f'throw std::runtime_error("MK2 untranslated instruction {pc:08x}");'
        else:
            added[op] += 1
            guarded = 'throw std::runtime_error(' in code
            states[pc] = 'partial' if guarded else 'generated'
            if guarded:
                exceptions[(op, width, 'partial', True)].append(pc)
        blocks[pc] = f'case 0x{pc:08x}u: {{ // {asm or op}\n    {code}\n    break;\n}}\n'

    if physical_map is not None:
        physical_map.extend(spans)
        for pc, state in states.items():
            width, _, _, asm = rows[pc]
            if not width:
                continue
            offset = (pc-BASE)//8
            end = offset+width//8
            if not asm.startswith('DW '):
                physical_map.append((offset, end, 8))
            physical_map.append((offset, end, {'generated': 16, 'partial': 32, 'explicit_stop': 64}[state]))

    shards = {}
    dispatcher = architectural.partition(''.join(blocks[pc] for pc in sorted(blocks)), shards=shards)
    header = '// Offline TMS34010 AOT, MK2 L3.1 SHA256 '+emitter.PROGRAM_SHA256+'\n'
    sources = {f'mk2_tms_{base:08x}.cpp': header+'#include "mk2_boot_ops.hpp"\nnamespace mk2 {\n'+body+'}\n'
               for base, body in shards.items()}
    runtime = RUNTIME.read_text(encoding='utf8')
    include = '#include "mk2_first_fight_main.inc"'
    if runtime.count(include) != 1:
        raise ValueError('MK2 architectural dispatcher include site changed')
    sources[RUNTIME.name] = runtime.replace(include, '#include "mk2_tms_dispatch.inc"')
    sources['mk2_tms_dispatch.inc'] = header+dispatcher
    for name, cpp in sources.items():
        (scratch/name).write_text(cpp, encoding='utf8', newline='\n')

    def physical(offset, width):
        return [{'rom': entry['path'], 'sha256': entry['sha256'], 'offsets': [a,b], 'lane': base, 'stride': entry['stride_bytes']}
                for entry in lanes for a,b,base in coverage.physical_slices(entry, offset, width)]

    def data_origin(offset, width):
        return {'address_bits': f'{BASE+offset*8:08x}', 'bytes': width,
                'physical': physical(offset, width)}

    inline_sites = {}
    immediate_exchanges = {}
    for pc in sorted(graph):
        width, _, _, asm = rows[pc]
        producer = pc - 48
        if width and asm.startswith('EXGPC ') and graph.get(producer) == (pc,):
            size, _, words, source = rows[producer]
            if size == 48 and source.startswith('MOVI '):
                value, register = source.split()[1].split(',')
                target = emitter.immediate(value) & 0xfffffff0
                if asm.split() == ['EXGPC', register] and target in graph[pc] and target != pc + width:
                    immediate_exchanges[f'{pc:08x}'] = {
                        'producer_pc_bits': f'{producer:08x}',
                        'producer_words': [f'{word:04x}' for word in words],
                        'targets_bits': [f'{target:08x}']}
        if width and (op := asm.split()[0]) in ('CALLA', 'CALLR'):
            callee = emitter.transfer_target(op, asm.split()[1])
            if callee in INLINE_POINTER_SELECTORS:
                count, skips = INLINE_POINTER_SELECTORS[callee]
                offset = (pc+width-BASE)//8
                inline_sites[f'{pc:08x}'] = {
                    'selector_bits': f'{callee:08x}', 'skips_inline': skips,
                    **data_origin(offset, count*4),
                    'successors_bits': [f'{target:08x}' for target in graph[pc]]}

    queries = []
    for pc in pcs:
        width, flags, words, asm = rows[pc]
        offset = (pc-BASE)//8
        unit = f'mk2_tms_{pc & ~0x7ffff:08x}.cpp'
        label = f'case 0x{pc:08x}u:'
        line = next((n for n, text in enumerate(sources.get(unit, '').splitlines(), 1)
                     if text.startswith(label)), None)
        queries.append({'pc_bits': f'{pc:08x}', 'width_bits': width, 'flags': flags,
            'words': [f'{word:04x}' for word in words], 'asm': asm, 'loaded_offset': offset,
            'physical': physical(offset, max(2,width//8)),
            'evidence': ('identified_data' if offset in data_offsets and pc not in graph else
                         'static_edge_or_root' if pc in graph else 'baseline_only' if pc in legacy else 'inventory_only'),
            'successors_bits': [f'{target:08x}' for target in graph.get(pc, ())],
            'cpp': unit if line else None, 'line': line, 'maturity': states.get(pc)})
    return [scratch/name for name in sources if name.endswith('.cpp')], {
        'analysis_seconds': analyzed-started, 'generation_seconds': time.perf_counter()-analyzed,
        'dispatch_cases': len(blocks), 'baseline_cases': len(legacy), 'static_edge_or_root': len(graph),
        'inventory_mnemonics': dict(sorted(inventory.items())), 'baseline_emission': dict(baseline_emission),
        'observed_roots': {f'{pc:08x}': evidence for pc, evidence in OBSERVED_ROOTS.items()},
        'physical_lanes': lanes, 'vectors': {f'{pc:08x}': f'{target:08x}' for pc,target in vectors.items()},
        'inline_pointer_sites': len(inline_sites), 'unadmitted_rom_pointer_candidates': len(pointers-admitted),
        'explicit_stops_by_evidence': dict(stop_classes),
        'static_control_evidence': {
            'bounded_jump_tables': {f'{pc:08x}': {
                'range_check_bits': f'{check:08x}', 'first_jump_index': first, 'entries': count,
                **data_origin((base-BASE)//8, count*4),
                'successors_bits': [f'{target:08x}' for target in graph[pc]]}
                for pc, (check, base, first, count) in BOUNDED_JUMP_TABLES.items() if pc in graph},
            'register_transfers': {f'{pc:08x}': {
                'producer_pcs_bits': [f'{producer:08x}' for producer in producers],
                'successors_bits': [f'{target:08x}' for target in graph[pc]]}
                for pc, producers in REGISTER_TRANSFERS.items() if pc in graph},
            'inline_selectors': inline_sites,
            'immediate_exchanges': immediate_exchanges,
            'observed_register_exchanges': {f'{pc:08x}': {'register': register,
                'successors_bits': [f'{target:08x}' for target in targets]}
                for pc, (register, targets) in architectural.EXCHANGE_EVIDENCE.items() if pc in graph},
            'boot_text_data': [{**data_origin((address-BASE)//8, width), 'reader_pc_bits': f'{reader:08x}'}
                               for address, width, reader in boot_text_data(rom)],
            'replay_data_reads': {'intervals': len(replay_spans), 'bytes': sum(end-start for start,end,_ in replay_spans),
                                  'reader_roots_bits': [f'{pc:08x}' for pc in reader_roots]},
            'observed_transfers': {'sites': len(witnessed_transfers),
                                   'edges': sum(map(len, witnessed_transfers.values()))},
            'other_data_reads': [{**data_origin((address-BASE)//8, width),
                'producer_pc_bits': f'{producer:08x}', 'reader_pc_bits': f'{reader:08x}'}
                for address, (width, producer, reader) in DATA_READS.items()]},

        'overlapping_code_starts': overlapping_starts,
        'generated_additions': dict(added), 'dispatch_units': len(shards),
        'loaded_byte_classes': {'bits': {'1':'static edge or root','2':'identified data','4':'ambiguous baseline or invalid'},
                                'bytes_by_mask': dict(counts)},
        'open_edges': {kind: {'count': len(sites), 'examples': sorted(sites)[:8]} for kind, sites in sorted(open_edges.items())},
        'exceptions': [{'mnemonic': op, 'width_bits': width, 'dependency': reason,
                        'static_edge_or_root': supported, 'count': len(sites),
                        'examples': [f'{pc:08x}' for pc in sites[:8]]}
                       for (op,width,reason,supported),sites in sorted(exceptions.items())],
        'source_sha256': {name: hashlib.sha256(cpp.encode()).hexdigest() for name, cpp in sources.items()},
        'queries': queries}


def dsp_sources(u2, pcs=(), *, physical_map=None):
    """Extend finite U2 images, keeping opcode checks on writable PM."""
    started = time.perf_counter()
    baseline = generate_adsp.generate(u2)
    if baseline != (NATIVE/'mk2_adsp_boot.inc').read_text(encoding='utf8'):
        raise ValueError('Baseline ADSP C++ differs from the authenticated generator')
    manifest_path = Path(__file__).with_name('dsp_branch_closure.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    original = defaultdict(dict)
    for pc, bank, _, _, op in coverage.dsp_entries(baseline, u2):
        original[bank][pc] = op
    late = original['low'] | original['late']
    pcs = [int(pc, 16) for pc in manifest['pcs']]
    if manifest['u2']['sha256'] != hashlib.sha256(u2).hexdigest() or any(pc not in late for pc in pcs) or (
            oracle_digest.words_digest(late[pc] for pc in pcs) != manifest['words_sha256']):
        raise ValueError('Late ADSP direct closure provenance changed')

    def offset(bank, pc):
        image = 'low' if bank != 'boot' and pc < 0x400 else bank
        return coverage.dsp_physical_offset(u2, image, pc)

    def rom_word(bank, pc):
        at = offset(bank, pc)
        return int.from_bytes(u2[at:at+3], 'big')

    # 034b reads one U2 byte through DM and strips the high byte at 0350–0352.
    # 01c9 selects values below 0x10, and 01cf adds 0x0310 before 01d5 jumps via I4.
    command_table = range(0x310, 0x320)
    # PCs only; their U2 words are checked by SHA-256 (8-byte little-endian words, PC order).
    command_path = (0x1c6, 0x1c7, 0x1c8, 0x1c9, 0x1ce, 0x1cf, 0x1d0, 0x1d5, 0x34b, 0x34c, 0x34d, 0x34e, 0x34f, 0x350, 0x351, 0x352, 0x353, 0x354, 0x355, 0x356, 0x357, 0x358, 0x359, 0x35a, 0x35b, 0x35c, 0x35d)
    if oracle_digest.words_digest(rom_word('late', pc) for pc in command_path) != (
            '83ecb04b09a1e1028b8b8c1db990808eaa7ec3edd0e452b5a174461a1f31064f') or any(
            rom_word('late', pc) & 0xfc000f != 0x18000f for pc in command_table):
        raise ValueError('ADSP command jump table provenance changed')

    generated = defaultdict(dict)
    images = {}
    for bank in ('boot', 'early', 'late'):
        existing = original[bank] if bank == 'boot' else original['low'] | original[bank]
        pending = set(original['early'] if bank == 'early' else existing)
        visited, indirect, returns, unmapped = set(), set(), set(), set()
        register_jump_targets, unsupported = {}, defaultdict(list)
        while pending:
            pc = pending.pop()
            if pc in visited:
                continue
            visited.add(pc)
            at = offset(bank, pc)
            if at is None:
                unmapped.add(pc)
                continue
            op = rom_word(bank, pc)
            if pc not in existing:
                try:
                    code = generate_adsp.translate(op, batch_forms=True)
                except ValueError:
                    unsupported[op >> 16].append((pc, op))
                    continue
                generated[pc | (0 if bank == 'boot' else 0x10000)][op] = code
            if (bank, pc) in (('boot', 0xf8), ('late', 0x1cd)):
                # Both paths set the boot bank and assert SYSCON reset.
                continue
            top = op >> 16
            target = (op >> 4) & 0x3fff
            if 0x18 <= top <= 0x1f:
                pending.add(target)
                if top < 0x1c and op & 15 == 15:
                    continue
            if top == 0x0a:
                returns.add(pc)
                if op & 15 == 15:
                    continue
            if top == 0x0b:
                indirect.add(pc)
                if (bank, pc) == ('late', 0x1d5):
                    pending.update(command_table)
                    register_jump_targets[f'{pc:04x}'] = [f'{target:04x}' for target in command_table]
                if op & 15 == 15 and not op & 0x10:
                    continue
            if top == 3:
                pending.add((target & 0xfff) | ((op & 12) << 10))
            pending.add(pc+1)
        images[bank] = {'visited': len(visited), 'existing': len(existing), 'indirect': len(indirect),
                        'indirect_examples': [f'{pc:04x}' for pc in sorted(indirect)[:16]],
                        'register_jump_targets': register_jump_targets,
                        'unresolved_register_jumps': [f'{pc:04x}' for pc in sorted(indirect)
                                                      if f'{pc:04x}' not in register_jump_targets],
                        'return_sites': [f'{pc:04x}' for pc in sorted(returns)],
                        'unmapped': [f'{pc:04x}' for pc in sorted(unmapped)],
                        'unsupported': {f'{family:02x}': {'count': len(sites),
                            'examples': [[f'{pc:04x}', f'{op:06x}', offset(bank, pc)] for pc, op in sorted(sites)[:8]]}
                            for family, sites in sorted(unsupported.items())}}

    analyzed = time.perf_counter()
    lines = []
    for line in baseline.splitlines():
        match = re.match(r'(case 0x([0-9a-f]+): )(.*)', line)
        if match and (variants := generated.pop(int(match[2], 16), {})):
            extra = ''.join(f'if (ReadProgram(pc) == 0x{op:06x}) {{ CheckOpcode(0x{op:06x}); '
                            f'Advance(); {code} break; }} ' for op, code in sorted(variants.items()))
            line = match[1] + extra + match[3]
        lines.append(line)
    for key, variants in sorted(generated.items()):
        bodies = ''.join(f'if (ReadProgram(pc) == 0x{op:06x}) {{ CheckOpcode(0x{op:06x}); '
                         f'Advance(); {code} break; }} ' for op, code in sorted(variants.items()))
        lines.append(f'case 0x{key:05x}: {bodies}throw std::runtime_error("ADSP untranslated PC " + '
                     'std::to_string(pc) + "; opcode " + std::to_string(ReadProgram(pc)));')
    source = '\n'.join(lines)+'\n'
    variants = list(coverage.dsp_entries(source, u2))
    early_copies = (
        (0x900, 0x80, 0x834, 0x700), (0x980, 0x80, 0x83a, 0x780),
        (0x8f0, 0x10, 0x840, 0x62d), (0x8d5, 0x10, 0x846, 0x398c),
        (0x8ec, 0x04, 0x84c, 0x39f9), (0x8e5, 0x07, 0x852, 0x614),
    )
    # Early PM 088e–0893 copies this bound; late PM 0047–0054 reads each header through 034b.
    table_start = int.from_bytes(u2[0x4040:0x4043], 'big')
    command_count = int.from_bytes(u2[0x4046:0x4048], 'big')
    table_end = table_start + 3*command_count
    if (table_start, command_count) != (0x4048, 0x57b) or table_end > len(u2):
        raise ValueError('U2 command table layout differs')
    header_counts = Counter()
    headers = set()
    for at in range(table_start, table_end, 3):
        pointer = int.from_bytes(u2[at:at+3], 'big')
        if pointer >> 16 == 0xff:
            header_counts['skipped'] += 1
            continue
        if not table_end <= pointer < len(u2) or u2[pointer] not in (1, 2):
            raise ValueError('U2 command header exceeds the proved parser domain')
        headers.add(pointer)
        header_counts[f'{u2[pointer]:02x}'] += 1
    if physical_map is not None:
        for _, _, at, _, _ in variants:
            physical_map.extend((at, at+3, bit) for bit in (1, 8, 16))
        early_data = [(0x8ae, 0x27), *((pc, count) for pc, count, _, _ in early_copies)]
        for first, count in early_data:
            begin = offset('early', first)
            physical_map.extend((at, at+3, 2) for at in range(begin, begin+4*count, 4))
        physical_map.extend(((3, 4, 2), (0x1003, 0x1004, 2)))
        physical_map.extend(((0x4040, 0x4043, 2), (0x4046, 0x4048, 2), (table_start, table_end, 2)))
        physical_map.extend((at, at+1, 2) for at in headers)
    pm_images = {}
    for image, (base, count, first) in {
        'boot': (0, (u2[3]+1)*8, 0),
        'low': (0x1000, (u2[0x1003]+1)*8, 0),
        **{name: (*layout, 0x800) for name, layout in coverage.DCS_EXTERNAL.items()},
    }.items():
        pm_images[image] = {'physical_offset': base, 'first_pc': first, 'words': count,
                            'packed_pm24_sha256': hashlib.sha256(b''.join(
                                u2[at:at+3] for at in range(base, base+4*count, 4))).hexdigest()}
    return source, {'analysis_seconds': analyzed-started, 'generation_seconds': time.perf_counter()-analyzed,
        'u2_sha256': manifest['u2']['sha256'], 'closure_sha256': quality.sha(manifest_path),
        'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'baseline_variants_by_image': {bank: len(rows) for bank, rows in original.items()},
        'variants_by_image': dict(Counter(bank for _,bank,_,_,_ in variants)),
        'queries': [{'pc_words': f'{pc:04x}', 'image': bank, 'rom': 'su2.l1', 'physical_offset': at,
                     'physical_bytes': 3, 'rom_sha256': manifest['u2']['sha256'],
                     'word': f'{word:06x}', 'cpp': 'mk2_adsp_boot.inc', 'line': line, 'maturity': 'generated',
                     'opcode_guarded': True}
                    for pc, bank, at, line, word in variants if pc in pcs],
        'images': images, 'mapping': {
            'boot_words': (u2[3]+1)*8, 'low_words': (u2[0x1003]+1)*8,
            'external_image_rom_base_and_word_count': coverage.DCS_EXTERNAL,
            'external_start_pc': 0x800, 'physical_bytes_per_pm_word': 4,
            'low_source': 'U2 0x1000, ROM bank 1, loaded by software boot',
            'external_source': 'Copy routine 03e8–03f5, early call 0015 and late call 001a',
            'pm_images': pm_images,
            'command_headers': {
                'table_offsets': [table_start, table_end], 'counts': dict(header_counts),
                'unique_headers': len(headers),
                'table_sha256': hashlib.sha256(u2[table_start:table_end]).hexdigest(),
                'header_sha256': hashlib.sha256(bytes(u2[at] for at in sorted(headers))).hexdigest(),
                'proof_scope': 'Initialized U2 command header path at 0047–0054 with bound 057B; '
                               'the separate active-voice fallthrough at 01C9 remains open.',
            },
            'transitions': [
                {'from': 'boot:00f8', 'to': 'low:0000', 'rom_bank': 1, 'effect': 'SYSCON reset'},
                {'from': 'low:01cd', 'to': 'boot:0000', 'rom_bank': 0, 'effect': 'SYSCON reset'},
                {'from': 'low:0016', 'to': 'early:0800', 'effect': 'call after early PM copy'},
                {'from': 'early:0896', 'to': 'low:0017', 'effect': 'return to loader after early call'},
                {'from': 'early:08ad', 'to': [f'early:{pc:04x}' for pc in range(0x858, 0x881, 4)],
                 'effect': 'return from 0897 to its eleven early callers'},
            ],
            'early_padding': {'first_pc': 0x8ae, 'words': 0x27, 'word': 'ffffff'},
            'early_data_copies': [
                {'source_pc': src, 'physical_offset': offset('early', src), 'words': count,
                 'pm_read_pc': reader, 'dm_write_pc': reader+1, 'destination_dm': dest}
                for src, count, reader, dest in early_copies
            ],
        },
        'writable_pm': {
            'boot_source': 'AdspBoot::LoadBootPage accepts authenticated U2 banks zero and one',
            'explicit_writer': 'AdspBoot::WriteProgram writes internal or external PM as 24-bit words',
            'program_mirrors': [[0x800, 0xfff], [0x1000, 0x17ff], [0x1800, 0x1fff]],
            'data_alias': 'AdspBoot::WriteData below 0x2000 writes the high 16 bits of external PM[DM & 0x7ff]',
            'boot_vector_copies': [
                {'writer_pc': 0x39, 'source_pc': 0x1c+n, 'physical_offset': 4*(0x1c+n),
                 'destination_pc': 4+4*n, 'word': f'{rom_word("boot", 0x1c+n):06x}'}
                for n in range(6)
            ],
            'boot_external_data_writers': [0x4e, 0x71, 0xdc, 0xfe, 0x101, 0x10b, 0x10e],
            'external_rom_writer': 0x3f4,
            'executed_mutations': 'unmeasured by the static scan'},
        'remaining': ['runtime PM writes and DM aliases can produce additional executable words',
                      'the runtime checks fixed word variants for each PC',
                      'return contexts, residual PM after reload and executable mirror destinations require evidence']}


def prepare(scratch, rom_directory, receipt, pcs=(), dsp_pcs=(), *, physical_map=False):
    receipt['translator_inputs'] = translator_inputs()
    receipt['native_compile_contract'] = native_compile_contract()
    manifest = run.read_manifest()
    receipt['roms'] = run.verify_roms(rom_directory, manifest)
    lanes = coverage.program_lanes(manifest['roms'])
    rom = emitter.load_program(rom_directory)
    rows, receipt['aligned_scan'] = scan_aligned(rom)
    tms_map = [] if physical_map else None
    dsp_map = [] if physical_map else None
    sources, receipt['tms'] = tms_sources(rom, rows, scratch, pcs, lanes, physical_map=tms_map)
    u2 = (rom_directory/'su2.l1').read_bytes()
    dsp, receipt['dcs'] = dsp_sources(u2, dsp_pcs, physical_map=dsp_map)
    if physical_map:
        physical_spans = {entry['path']: [(0, entry['size'], 2)] for entry in manifest['roms']
                          if entry['region'] == 'video'}
        physical_spans['su2.l1'] = dsp_map
        playback_spans = dcs_playback_spans(rom_directory, manifest['roms'])
        receipt['dcs']['playback_data_bytes'] = {name: sum(end-start for start,end,_ in spans)
                                                for name, spans in playback_spans.items()}
        for evidence in (dcs_data_spans(rom_directory, manifest['roms']), playback_spans):
            for name, spans in evidence.items():
                physical_spans.setdefault(name, []).extend(spans)
        receipt['physical_inventory'] = coverage.physical_inventory(
            manifest['roms'], {'maincpu': tms_map}, physical_spans)
        if receipt['roms'] != run.verify_roms(rom_directory, manifest):
            raise ValueError('ROM inputs changed during physical inventory')
    (scratch/'mk2_adsp_boot.inc').write_text(dsp, encoding='utf8', newline='\n')
    runtime = scratch/'mk2_adsp.cpp'
    runtime.write_bytes((NATIVE/runtime.name).read_bytes())
    sources.append(runtime)
    if receipt['translator_inputs'] != translator_inputs():
        raise ValueError('Translator sources changed during generation')
    return sources


def native_compile_contract():
    return {
        'compiler_sha256': quality.sha(quality.DEFAULT_CC),
        'compile_flags': [*package.FLAGS, '-Inative/mk2', '-static'],
        'link_flags': list(LINK_FLAGS),
        'translation_units': list(package.SOURCES),
        'recipe_inputs': {name: quality.sha(ROOT/name) for name in
                          ('tools/mk2/package_native.py', 'tools/quality/cpp_build.py')},
    }


def compile_candidate(scratch, sources, output, env, *, replay_source=None):
    contract = native_compile_contract()
    replaced = {source.name for source in sources}
    paths = [ROOT/name for name in contract['translation_units'] if Path(name).name not in replaced
             and (replay_source is None or name != 'native/mk2/mk2_native_check.cpp')]
    if replay_source is not None:
        paths.append(replay_source)
    flags = ['-I'+str(ROOT/flag[2:]) if flag.startswith('-I') else flag for flag in contract['compile_flags']]
    return cpp_build.build(quality.DEFAULT_CC, flags, [*paths, *sources], contract['link_flags'],
                           output, scratch, env=env, timeout=900,
                           compile_from_scratch=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--build', action='store_true', help='Compile and link in temporary storage')
    parser.add_argument('--physical-map', action='store_true', help='Count every physical ROM byte by evidence and maturity')
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--pc', type=cfg.address, action='append', default=[])
    parser.add_argument('--dsp-pc', type=lambda value: int(value, 16), action='append', default=[])
    args = parser.parse_args()
    if any(not 0 <= pc < 0x4000 for pc in args.dsp_pc):
        parser.error('DSP PC must be within the 14-bit word address space')
    report = args.report.absolute()
    output = args.executable.absolute() if args.executable else None
    for path in (report, output):
        if path is None:
            continue
        package.unlinked(path)
        if path.exists() or not path.parent.resolve().is_relative_to(ROOT/'build/native'):
            parser.error('Choose unused output paths under build/native')
    if output is not None and (output.suffix.lower() != '.exe' or output == report):
        parser.error('Choose a separate .exe path')
    receipt = {'format': 'MK2_L31_STATIC_BATCH_V1', 'built': False, 'comparison_seconds': None}
    try:
        with quality.scratch_tree() as (scratch, cleanup):
            receipt['cleanup'] = cleanup
            env = {'PATH': str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
            receipt['runtime_inputs'] = package.identities(scratch, env)
            sources = prepare(scratch, ROOT/'roms/mk2', receipt, args.pc, args.dsp_pc, physical_map=args.physical_map)
            if args.build or output is not None:
                exe = scratch/'mk2-static-batch.exe'
                build = compile_candidate(scratch, sources, exe, env)
                receipt['build'] = quality.compact(build)
                if not build['passed']:
                    raise ValueError('Candidate compilation or link failed')
                if receipt['runtime_inputs'] != package.identities(scratch, env):
                    raise ValueError('Runtime source changed during build')
                if receipt['translator_inputs'] != translator_inputs():
                    raise ValueError('Translator sources changed during build')
                if receipt['native_compile_contract'] != native_compile_contract():
                    raise ValueError('Native compiler or build recipe changed during build')
                exe_sha256 = quality.sha(exe)
                if output is not None:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    os.link(exe, output)
                    receipt['executable'] = str(output)
                receipt.update(built=True, executable_sha256=exe_sha256)
    except Exception as error:
        receipt['error'] = repr(error)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('x', encoding='utf8') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'built': receipt['built'], 'report': str(report), 'error': receipt.get('error')}))
    return int('error' in receipt)


if __name__ == '__main__':
    raise SystemExit(main())
