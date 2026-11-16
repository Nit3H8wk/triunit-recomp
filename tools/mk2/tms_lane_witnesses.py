"""Synthetic TMS34010 lane components checked against the pinned MAME 0.280, one instruction per step.

The repository keeps, per segment: the instruction PCs and the PC reached (addresses), the cycle count of each step,
a synthetic start state (sentinel registers, synthetic RAM pointers, code addresses), synthetic RAM seeds, the ROM
lanes the segment reads (addresses; bytes from the user's ROM), the masked-interrupt I/O of the scenario, and the
SHA-256 of each state MAME reached from that start (tools/mk2/oracle_digest.py) and of the ordered bus lanes.

    python tools/mk2/tms_lane_witnesses.py --from-raw DIR   # DIR holds the old raw tms_<group>_witnesses.json

--from-raw rebuilds the file from a local raw capture (CPU34 rows and bus lanes of real contexts): the raw values are
used only to choose which registers and words the segment reads and to check the result; none is written out. Every
step then runs in MAME from the synthetic state (tools/oracle/mame_step.py, decision D9: synthetic state, the
authentic ROM); MAME must reach the observed PCs with the observed cycle counts, and the written words must be the
raw ones under the same address and value mapping.
"""
from pathlib import Path
import argparse
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g
from tools.mk2 import oracle_digest

PATH = Path(__file__).with_name('tms_lane_witnesses.json')
GROUPS = ('call', 'callback', 'mmfm', 'pit_callback', 'scheduler', 'round6_jump')
FORMAT = 'MK2_TMS_SYNTHETIC_LANES_V1'
NAMES = [f'a{n}' for n in range(15)] + ['sp'] + [f'b{n}' for n in range(15)]
RAM, RAM_END, ROM = 0x01000000, 0x01400000, 0xff800000
SYNTHETIC_RAM, SPACING = 0x01200000, 0x8000
IRQ_IO = (16, 17, 18)   # HSTCTLH, INTENB, INTPEND


def load():
    data = json.loads(PATH.read_text(encoding='utf8'))
    if data['format'] != FORMAT or data['program_sha256'] != g.PROGRAM_SHA256:
        raise ValueError('TMS synthetic lane identity differs')
    return data


def immediate(rows, pc):
    """Value of the immediate operand of the instruction at pc (read from the user's ROM)."""
    match = re.search(r'\b([0-9A-F]+)h\b', rows[pc][3])
    if match is None:
        raise ValueError(f'no immediate at {pc:08x}')
    return int(match.group(1), 16)


def resolve(value, rows):
    return immediate(rows, value['imm']) if isinstance(value, dict) else value


# ---------------------------------------------------------------- conversion from a local raw capture
def named(asm):
    _, _, operands = asm.partition(' ')
    out = set()
    for first, last in re.findall(r'\b([AB]\d{1,2})-([AB]\d{1,2})\b', operands):
        out |= {f'{first[0]}{n}'.lower() for n in range(int(first[1:]), int(last[1:])+1)}
    out |= {r.lower() for r in re.findall(r'\b([AB]1[0-4]|[AB]\d|SP)\b', operands)}
    if asm.split()[0] in ('CALL', 'CALLA', 'RETS'):
        out.add('sp')
    return {'sp' if r in ('a15', 'b15') else r for r in out}


def absolutes(asms):
    found = set()
    for asm in asms:
        for value in re.findall(r'@([0-9A-F]+)h', asm):
            found |= {int(value, 16), int(value, 16)+16}
    return found


def immediates(asms):
    return {int(v, 16) for asm in asms for v in re.findall(r'\b([0-9A-F]+)h\b', asm.partition(' ')[2])}


def is_code(value):
    return ROM <= value and not value & 15


def convert(raw_dir, rom, rows_for):
    from tools.oracle import mk2_oracle
    groups = {}
    for group in GROUPS:
        data = json.loads((Path(raw_dir)/f'tms_{group}_witnesses.json').read_text(encoding='utf8'))
        groups[group] = [s for scene in data['scenes'] for s in scene['segments']] if 'scenes' in data \
            else data['segments']
    pcs = {row[0] for segs in groups.values() for s in segs for row in s['cpu34'][:-1]}
    rows = rows_for(pcs)
    # RAM pointers (registers the code names, RAM lanes it addresses, pointer words it moves) are clustered and each
    # cluster is placed at its own synthetic base: offsets inside a cluster (stack steps, field offsets) are code facts.
    pointers = set()
    for segs in groups.values():
        for s in segs:
            asms = [rows[r[0]][3] for r in s['cpu34'][:-1]]
            used = set().union(*map(named, asms))
            fixed = absolutes(asms)
            for r in s['cpu34'][:1]:
                pointers |= {r[3+NAMES.index(n)] for n in used if RAM <= r[3+NAMES.index(n)] < RAM_END}
            for k, (kind, address, value) in enumerate(s['bus']):
                if RAM <= address < RAM_END and address not in fixed:
                    pointers.add(address)
                if k+1 < len(s['bus']) and s['bus'][k+1][:2] == [kind, address+16]:
                    word = value | s['bus'][k+1][2] << 16
                    if RAM <= word < RAM_END:
                        pointers.add(word)
    clusters = []
    for value in sorted(pointers):
        if clusters and value - clusters[-1][-1] <= 0x1000:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    if any(c[-1]-c[0] >= SPACING//2 for c in clusters) or SYNTHETIC_RAM + len(clusters)*SPACING > RAM_END:
        raise ValueError('synthetic RAM layout does not fit')
    def relocate(value):
        for index, cluster in enumerate(clusters):
            if cluster[0]-0x400 <= value <= cluster[-1]+0x400:
                return SYNTHETIC_RAM + index*SPACING + 0x400 + value - cluster[0]
        raise ValueError(f'unclustered RAM pointer {value:x}')

    out, vectors, sentinel = {}, [], 0
    for group, segs in groups.items():
        out[group] = []
        for index, s in enumerate(segs):
            raw = s['cpu34']
            asms = [rows[r[0]][3] for r in raw[:-1]]
            used, fixed, imms = set().union(*map(named, asms)), absolutes(asms), immediates(asms)
            imm_pc = {immediate(rows, r[0]): r[0] for r in raw[:-1] if re.search(r'\b[0-9A-F]+h\b', rows[r[0]][3])}
            def data(value, bits):
                nonlocal sentinel
                if value == 0:
                    return 0
                if bits == 32 and is_code(value):
                    return value
                if bits == 32 and RAM <= value < RAM_END:
                    return relocate(value)
                if value in imms and value in imm_pc:
                    return {'imm': imm_pc[value]}
                sentinel += 1
                return (0x3c5a0000 | sentinel*0x111) & (0xffffffff if bits == 32 else 0x7fff)
            regs = []
            for n, name in enumerate(NAMES):
                value = raw[0][3+n]
                if name not in used:
                    if any(r[3+n] != value for r in raw):
                        raise ValueError(f'{group}[{index}] {name} changes but is not named')
                    regs.append(0x5e000000 | (index & 0xff) << 12 | n << 4)
                else:
                    regs.append(data(value, 32))
            irq = s.get('irq')
            st = (index % 16) << 28 | 0x30 | (0x200000 if irq else 0)
            mapped = lambda a: a if not RAM <= a < RAM_END or a in fixed else relocate(a)
            ram, first, lanes = {}, {}, []
            bus = s['bus']
            k = 0
            while k < len(bus):
                kind, address, value = bus[k]
                pair = (k+1 < len(bus) and bus[k+1][0] == kind and bus[k+1][1] == address+16)
                word = value | bus[k+1][2] << 16 if pair else value
                width = 2 if pair else 1
                for j in range(width):
                    lanes.append((kind, mapped(bus[k+j][1])))
                if RAM <= address < RAM_END and address not in first:
                    first[address] = kind
                    if kind == 'r':
                        seed = data(word, 32 if pair else 16)
                        seed = resolve(seed, rows)
                        ram[mapped(address)] = seed & 0xffff
                        if pair:
                            ram[mapped(address)+16] = seed >> 16
                    else:
                        for j in range(width):
                            ram[mapped(address)+16*j] = 0xa5a5 ^ (len(ram) + 1)
                k += width
            seg = dict(pcs=[r[0] for r in raw], cycles=[r[2]-raw[0][2] for r in raw[1:]],
                       start=dict(st=st, a=regs[:16], b=regs[16:]),
                       ram=sorted([a, v] for a, v in ram.items()),
                       program_reads=sorted({a for kind, a in lanes if a >= ROM}))
            if irq is not None:
                if irq[0] != irq[1]:
                    raise ValueError('interrupt I/O changes')
                seg['irq_io'] = list(irq[0])
            seg['_raw'] = s
            seg['_lanes'] = lanes
            seg['_mapped'] = mapped
            out[group].append(seg)

    # MAME, one instruction per step; step k starts from MAME's step k-1 result and memory.
    state = {}
    for group, segs in out.items():
        for index, seg in enumerate(segs):
            start = seg['start']
            regs = [resolve(v, rows) for v in start['a'] + start['b']]
            state[group, index] = dict(regs=dict(zip(NAMES, regs)), st=start['st'], pc=seg['pcs'][0],
                                       mem={a: v for a, v in seg['ram']}, digests=[], cycles=0,
                                       watch=sorted({a for _, a in seg['_lanes'] if RAM <= a < RAM_END}))
    depth = max(len(seg['pcs'])-1 for segs in out.values() for seg in segs)
    receipts = []
    for step in range(depth):
        vectors = []
        for (group, index), st in state.items():
            seg = out[group][index]
            if step < len(seg['pcs'])-1:
                vectors.append(dict(id=f'{group}.{index}.{step}', pc=st['pc'], st=st['st'], regs=st['regs'],
                                    mem=dict(st['mem']), watch=st['watch'], allow_ie='irq_io' in seg))
        results, receipt, cleanup = mk2_oracle.mame([vectors], workers=1, timeout=900)
        receipts.append(dict(step=step, vectors=len(vectors), cleanup_exists_after=cleanup.get('exists_after'),
                             wall_seconds=sum(r.get('wall_seconds', 0) for r in receipt)))
        for v in vectors:
            group, index, _ = v['id'].split('.')
            index = int(index)
            seg, st, r = out[group][index], state[group, index], results[v['id']]
            if r.get('error'):
                raise ValueError(f'{v["id"]}: {r["error"]}')
            st['cycles'] += r['cycles']
            if r['pc'] != seg['pcs'][step+1] or st['cycles'] != seg['cycles'][step]:
                raise ValueError(f'{v["id"]}: MAME reached {r["pc"]:08x} after {st["cycles"]} cycles')
            st['pc'], st['st'], st['regs'] = r['pc'], r['st'], r['regs']
            st['mem'].update(r['mem'])
            row = [r['pc'], r['st'], st['cycles']] + [r['regs'][n] for n in NAMES]
            st['digests'].append(oracle_digest.cpu34_digest(row))
            st.setdefault('writes', 0)
            st['writes'] += r['writes']
    result = {}
    for group, segs in out.items():
        result[group] = []
        for index, seg in enumerate(segs):
            st = state[group, index]
            raw, lanes, mapped = seg.pop('_raw'), seg.pop('_lanes'), seg.pop('_mapped')
            seen, values = set(), []
            for (kind, address), (_, raw_address, raw_value) in zip(lanes, raw['bus']):
                if address >= ROM:
                    offset = (address-ROM)//8
                    value = int.from_bytes(rom[offset:offset+2], 'little')
                elif kind == 'w':
                    if address in seen:
                        raise ValueError('address written twice in one segment')
                    seen.add(address)
                    value = st['mem'][address]
                else:
                    if address in seen:
                        raise ValueError('address read after a write in one segment')
                    value = dict(seg['ram'])[address]
                values.append(value)
            if sum(1 for kind, _ in lanes if kind == 'w') != st['writes']:
                raise ValueError(f'{group}[{index}]: MAME write count differs')
            # Same mapping as the start state: written words must be the raw ones (code addresses kept, pointer
            # halves relocated); data words are synthetic on both sides.
            for (kind, address), value, (_, raw_address, raw_value), k in zip(lanes, values, raw['bus'],
                                                                                 range(len(lanes))):
                if kind == 'w' and k+1 < len(lanes) and lanes[k+1] == ('w', address+16):
                    raw_word = raw_value | raw['bus'][k+1][2] << 16
                    word = value | values[k+1] << 16
                    if is_code(raw_word) and word != raw_word:
                        raise ValueError(f'{group}[{index}]: written code address differs')
                    if RAM <= raw_word < RAM_END and word != mapped(raw_word):
                        raise ValueError(f'{group}[{index}]: written pointer differs')
            seg['cpu34_sha256'] = st['digests']
            seg['lanes_sha256'] = oracle_digest.words_digest(
                [x for (kind, address), value in zip(lanes, values) for x in (ord(kind), address, value)])
            seg['lane_count'] = len(lanes)
            result[group].append(seg)
    return dict(format=FORMAT, program_sha256=g.PROGRAM_SHA256, groups=result), receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--from-raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=PATH)
    args = parser.parse_args()
    from tools.mk2.offline_decode import decode
    rom = g.load_program(g.ROOT/'roms/mk2')
    data, receipts = convert(args.from_raw, rom, lambda pcs: decode(rom, pcs)[0])
    text = json.dumps(data, separators=(',', ':'))
    text = text.replace('{"pcs"', '\n{"pcs"').replace(']}]', ']}\n]')
    args.output.write_text(text + '\n', encoding='utf8')
    print(json.dumps(dict(output=str(args.output), receipts=receipts), indent=1))


if __name__ == '__main__':
    main()
