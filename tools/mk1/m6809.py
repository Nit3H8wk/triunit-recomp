"""Motorola MC6809 instruction decoder (project source, written from the MC6809 programming manual opcode map).

decode(code, pc) reads one instruction at `pc` through `code(address) -> byte` and returns an Instruction: raw bytes,
mnemonic, addressing mode, operand fields and the assembler text used in the comments of the generated audio graph
(mnemonic padded to 7 columns; `<$nn` direct, `$nnnn` extended, `>$00nn` extended below 0x100, `#$..` immediate,
indexed forms `$n,R` `-$n,R` `,R+` `,--R` `A,R` `[..]`, register lists high-to-low for pushes and low-to-high for
pulls with A+B shown as D). Illegal opcodes raise ValueError. No ROM content lives here.
"""
from dataclasses import dataclass, field

# Addressing modes
INH, IMM8, IMM16, DIR, EXT, IDX, REL8, REL16, REG, STACK = 'inh', 'imm8', 'imm16', 'dir', 'ext', 'idx', 'rel8', 'rel16', 'reg', 'stack'

_page1 = {}
_page2 = {}
_page3 = {}


def _group(table, base, names, modes):
    for i, name in enumerate(names):
        if name:
            for mode, offset in modes:
                table[base + offset + i] = (name, mode)


# Page 1: 0x00-0x0f direct read-modify-write, 0x40/0x50 inherent A/B, 0x60 indexed, 0x70 extended.
_rmw = ['NEG', None, None, 'COM', 'LSR', None, 'ROR', 'ASR', 'ASL', 'ROL', 'DEC', None, 'INC', 'TST', 'JMP', 'CLR']
for i, n in enumerate(_rmw):
    if n:
        _page1[0x00 + i] = (n, DIR)
        _page1[0x60 + i] = (n, IDX)
        _page1[0x70 + i] = (n, EXT)
        if n != 'JMP':
            _page1[0x40 + i] = (n + 'A', INH)
            _page1[0x50 + i] = (n + 'B', INH)
_page1.update({0x12: ('NOP', INH), 0x13: ('SYNC', INH), 0x16: ('LBRA', REL16), 0x17: ('LBSR', REL16), 0x19: ('DAA', INH),
               0x1a: ('ORCC', IMM8), 0x1c: ('ANDCC', IMM8), 0x1d: ('SEX', INH), 0x1e: ('EXG', REG), 0x1f: ('TFR', REG),
               0x30: ('LEAX', IDX), 0x31: ('LEAY', IDX), 0x32: ('LEAS', IDX), 0x33: ('LEAU', IDX),
               0x34: ('PSHS', STACK), 0x35: ('PULS', STACK), 0x36: ('PSHU', STACK), 0x37: ('PULU', STACK),
               0x39: ('RTS', INH), 0x3a: ('ABX', INH), 0x3b: ('RTI', INH), 0x3c: ('CWAI', IMM8), 0x3d: ('MUL', INH),
               0x3f: ('SWI', INH), 0x8d: ('BSR', REL8)})
_branches = ['BRA', 'BRN', 'BHI', 'BLS', 'BCC', 'BCS', 'BNE', 'BEQ', 'BVC', 'BVS', 'BPL', 'BMI', 'BGE', 'BLT', 'BGT', 'BLE']
for i, n in enumerate(_branches):
    _page1[0x20 + i] = (n, REL8)
    if i:
        _page2[0x20 + i] = ('L' + n, REL16)
# 0x80-0xff: A/B accumulator groups (imm, dir, idx, ext at +0x00/+0x10/+0x20/+0x30).
_acc = ['SUB', 'CMP', 'SBC', None, 'AND', 'BIT', 'LD', 'ST', 'EOR', 'ADC', 'OR', 'ADD', None, None, None, None]
for base, reg in ((0x80, 'A'), (0xc0, 'B')):
    for i, n in enumerate(_acc):
        if not n:
            continue
        for off, mode in ((0x00, IMM8), (0x10, DIR), (0x20, IDX), (0x30, EXT)):
            if n == 'ST' and mode == IMM8:
                continue
            _page1[base + off + i] = (n + reg, mode)
for off, mode in ((0x00, IMM16), (0x10, DIR), (0x20, IDX), (0x30, EXT)):
    _page1[0x83 + off] = ('SUBD', mode)
    _page1[0x8c + off] = ('CMPX', mode)
    _page1[0x8e + off] = ('LDX', mode)
    _page1[0xc3 + off] = ('ADDD', mode)
    _page1[0xcc + off] = ('LDD', mode)
    _page1[0xce + off] = ('LDU', mode)
    _page2[0x83 + off] = ('CMPD', mode)
    _page2[0x8c + off] = ('CMPY', mode)
    _page2[0x8e + off] = ('LDY', mode)
    _page2[0xce + off] = ('LDS', mode)
    _page3[0x83 + off] = ('CMPU', mode)
    _page3[0x8c + off] = ('CMPS', mode)
    if mode != IMM16:
        _page1[0x8f + off] = ('STX', mode)
        _page1[0xcd + off] = ('STD', mode)
        _page1[0xcf + off] = ('STU', mode)
        _page2[0x8f + off] = ('STY', mode)
        _page2[0xcf + off] = ('STS', mode)
for off, mode in ((0x10, DIR), (0x20, IDX), (0x30, EXT)):
    _page1[0x8d + off] = ('JSR', mode)
_page2.update({0x3f: ('SWI2', INH)})
_page3.update({0x3f: ('SWI3', INH)})

REGISTERS = {0: 'D', 1: 'X', 2: 'Y', 3: 'U', 4: 'S', 5: 'PC', 8: 'A', 9: 'B', 10: 'CC', 11: 'DP'}
INDEX = ('X', 'Y', 'U', 'S')
_STACK_BITS = ((0, 'CC'), (1, 'A'), (2, 'B'), (3, 'DP'), (4, 'X'), (5, 'Y'), (6, None), (7, 'PC'))


@dataclass
class Indexed:
    post: int                    # postbyte
    base: str                    # X Y U S or PC (PC relative)
    kind: str                    # 'off5' 'off8' 'off16' 'inc1' 'inc2' 'dec1' 'dec2' 'zero' 'accA' 'accB' 'accD' 'pcr8' 'pcr16' 'ext'
    offset: int = 0              # signed offset or extended address
    indirect: bool = False
    size: int = 0                # bytes after the postbyte


@dataclass
class Instruction:
    pc: int
    raw: bytes
    page: int                    # 0, 0x10 or 0x11
    opcode: int
    mnemonic: str
    mode: str
    value: int = 0               # immediate / direct low byte / extended address / branch target / register postbyte
    index: Indexed = None
    text: str = field(default='')

    @property
    def length(self):
        return len(self.raw)

    @property
    def next(self):
        return (self.pc + len(self.raw)) & 0xffff


def _hex(n, digits):
    return '$' + format(n, f'0{digits}X')


def _signed(n, digits):
    return ('-' + _hex(-n, digits)) if n < 0 else _hex(n, digits)


def _indexed(code, address):
    post = code(address)
    base = INDEX[(post >> 5) & 3]
    if not post & 0x80:
        offset = post & 0x1f
        offset = offset - 32 if offset & 0x10 else offset
        return Indexed(post, base, 'off5', offset), 1
    mode = post & 0x0f
    indirect = bool(post & 0x10)
    size = 0
    if mode == 0x0:
        kind = 'inc1'
    elif mode == 0x1:
        kind = 'inc2'
    elif mode == 0x2:
        kind = 'dec1'
    elif mode == 0x3:
        kind = 'dec2'
    elif mode == 0x4:
        kind = 'zero'
    elif mode == 0x5:
        kind = 'accB'
    elif mode == 0x6:
        kind = 'accA'
    elif mode == 0x8:
        kind, size = 'off8', 1
    elif mode == 0x9:
        kind, size = 'off16', 2
    elif mode == 0xb:
        kind = 'accD'
    elif mode == 0xc:
        kind, size, base = 'pcr8', 1, 'PC'
    elif mode == 0xd:
        kind, size, base = 'pcr16', 2, 'PC'
    elif mode == 0xf and indirect:
        kind, size, base = 'ext', 2, ''
    else:
        raise ValueError(f'illegal indexed postbyte {post:02x}')
    if (kind in ('inc1', 'dec1')) and indirect:
        raise ValueError(f'illegal indexed postbyte {post:02x}')
    offset = 0
    if size == 1:
        offset = code(address + 1)
        offset = offset - 256 if offset & 0x80 else offset
    elif size == 2:
        offset = (code(address + 1) << 8) | code(address + 2)
        if kind != 'ext':
            offset = offset - 65536 if offset & 0x8000 else offset
    return Indexed(post, base, kind, offset, indirect, size), 1 + size


def _indexed_text(ix, end):
    if ix.kind == 'off5':
        body = f'{_signed(ix.offset, 1)},{ix.base}'
    elif ix.kind == 'off8':
        body = f'{_signed(ix.offset, 2)},{ix.base}'
    elif ix.kind == 'off16':
        body = f'{_signed(ix.offset, 4)},{ix.base}'
    elif ix.kind == 'inc1':
        body = f',{ix.base}+'
    elif ix.kind == 'inc2':
        body = f',{ix.base}++'
    elif ix.kind == 'dec1':
        body = f',-{ix.base}'
    elif ix.kind == 'dec2':
        body = f',--{ix.base}'
    elif ix.kind == 'zero':
        body = f',{ix.base}'
    elif ix.kind in ('accA', 'accB', 'accD'):
        body = f'{ix.kind[3]},{ix.base}'
    elif ix.kind in ('pcr8', 'pcr16'):
        body = f'{_hex((end + ix.offset) & 0xffff, 4)},PCR'
    else:
        body = _hex(ix.offset, 4)
    return f'[{body}]' if ix.indirect else body


def _stack_text(mnemonic, post):
    other = 'U' if mnemonic.endswith('S') else 'S'
    names = [(bit, name or other) for bit, name in _STACK_BITS if post & (1 << bit)]
    if post & 6 == 6:   # A and B together are printed as D
        names = [(bit, name) for bit, name in names if bit not in (1, 2)] + [(1.5, 'D')]
    names.sort(key=lambda x: x[0], reverse=mnemonic.startswith('PSH'))
    return ','.join(name for _, name in names)


def decode(code, pc):
    """One instruction at `pc`; `code(address)` returns the byte at a 16-bit address of the current bank."""
    pc &= 0xffff
    at = pc
    first = code(at)
    page = 0
    table = _page1
    if first in (0x10, 0x11):
        page = first
        table = _page2 if first == 0x10 else _page3
        at += 1
        opcode = code(at)
    else:
        opcode = first
    at += 1
    if opcode not in table:
        raise ValueError(f'illegal opcode {"%02x " % page if page else ""}{opcode:02x} at {pc:04x}')
    mnemonic, mode = table[opcode]
    value = 0
    index = None
    if mode in (IMM8, DIR, REG, STACK):
        value = code(at)
        at += 1
    elif mode in (IMM16, EXT):
        value = (code(at) << 8) | code(at + 1)
        at += 2
    elif mode == IDX:
        index, size = _indexed(code, at)
        at += size
    elif mode == REL8:
        rel = code(at)
        at += 1
        value = (at + (rel - 256 if rel & 0x80 else rel)) & 0xffff
    elif mode == REL16:
        rel = (code(at) << 8) | code(at + 1)
        at += 2
        value = (at + (rel - 65536 if rel & 0x8000 else rel)) & 0xffff
    raw = bytes(code(a) for a in range(pc, at))
    end = at & 0xffff
    if mode == INH:
        arg = ''
    elif mode == IMM8:
        arg = '#' + _hex(value, 2)
    elif mode == IMM16:
        arg = '#' + _hex(value, 4)
    elif mode == DIR:
        arg = '<' + _hex(value, 2)
    elif mode == EXT:
        arg = ('>' if value < 0x100 else '') + _hex(value, 4)
    elif mode == IDX:
        arg = _indexed_text(index, end)
    elif mode in (REL8, REL16):
        arg = _hex(value, 4)
    elif mode == REG:
        src, dst = REGISTERS.get(value >> 4), REGISTERS.get(value & 15)
        if src is None or dst is None:
            raise ValueError(f'illegal register postbyte {value:02x} at {pc:04x}')
        arg = f'{src},{dst}'
    else:
        arg = _stack_text(mnemonic, value)
    text = f'{mnemonic:<7}{arg}' if arg else mnemonic
    return Instruction(pc, raw, page, opcode, mnemonic, mode, value, index, text)


def u3_reader(u3, bank):
    """Byte reader of the sound CPU address space backed by U3: 0x4000-0xbfff is the 32 KB bank `bank`,
    0xc000-0xffff the last 16 KB of the ROM (Williams ADPCM board, midtunit.cpp/williams.cpp mapping)."""
    def code(address):
        address &= 0xffff
        if address >= 0xc000:
            return u3[len(u3) - 0x10000 + address]
        if address >= 0x4000:
            return u3[bank * 0x8000 + address - 0x4000]
        raise ValueError(f'sound CPU fetch outside ROM: {address:04x}')
    return code


def u3_offset(bank, pc, size=0x40000):
    return size - 0x10000 + pc if pc >= 0xc000 else bank * 0x8000 + pc - 0x4000
