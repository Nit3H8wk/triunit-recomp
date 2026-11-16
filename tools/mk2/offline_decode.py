"""Authenticated TMS34010 decoding for reached PCs and aligned ROM inventory."""
import hashlib
import io
import json
import os
import subprocess
import time
from tools.mk2 import generate_video_irq as generated
from tools.quality import run as quality

BASE = 0xff800000
END = 0x100000000
PROBE = generated.ROOT / 'docs/investigation/decoder-research'


def mk2_program():
    """MK2 L3.1 identity, read at call time (tests substitute a synthetic digest)."""
    return {'sha256': generated.PROGRAM_SHA256, 'size': END-BASE >> 3, 'base': BASE}


def authenticate(rom, program=None):
    """program: {'sha256', 'size', 'base'} of the TMS34010 image (default MK2 L3.1). Both pinned
    decoders map one image at BASE up to END, so other geometries reject."""
    program = program or mk2_program()
    if (program['base'] != BASE or program['size'] != END-BASE >> 3 or len(rom) != program['size']
            or hashlib.sha256(rom).hexdigest() != program['sha256']):
        raise ValueError('Unauthenticated L3.1 program' if program['sha256'] == generated.PROGRAM_SHA256
                         else 'Unauthenticated TMS34010 program')
    return program


def parse_row(rom, line, expected, *, aligned_scan=False):
    address, bits, flags, words, asm = line.split('\t')
    pc, width, flags = int(address, 16), int(bits, 16), int(flags, 16)
    raw = tuple(int(word, 16) for word in words.split())
    asm = asm.strip()
    truncated = aligned_scan and width == 0 and pc >= END - 64 and not flags and not asm
    if pc != expected or not (BASE <= pc < END) or (not truncated and
            (width not in (16, 32, 48, 80) or not asm)) or len(raw) * 16 != (width or 16):
        raise ValueError('Invalid offline decoder row')
    offset = (pc - BASE) // 8
    actual = tuple(int.from_bytes(rom[n:n+2], 'little') for n in range(offset, offset + len(raw)*2, 2))
    if offset + len(raw)*2 > len(rom) or raw != actual:
        raise ValueError('Decoded words differ from authenticated ROM')
    return width, flags, raw, asm


def scan_aligned(rom, program=None):
    """Decode at every word boundary in one process. Width zero marks a truncated fetch."""
    program = authenticate(rom, program)
    from tools.setup import decoder as source_decoder
    inputs = source_decoder.inputs()
    cc = quality.DEFAULT_CC
    with quality.scratch_tree() as (scratch, cleanup):
        built = time.perf_counter()
        exe = source_decoder.tms34010(cc)   # compiled from the pinned sources, cached in generated/tools/
        compile_seconds = time.perf_counter() - built
        decoder_sha = quality.sha(exe)
        started = time.perf_counter()
        output = subprocess.run([str(exe), '--aligned-stdin'], input=rom, capture_output=True, timeout=90)
        if output.returncode or output.stderr:
            raise ValueError('Aligned offline decoder failed: ' + repr(output.stderr[-300:]))
        rows = {}
        with io.StringIO(output.stdout.decode('ascii'), newline=None) as lines:
            for pc, line in zip(range(BASE, END, 16), lines):
                rows[pc] = parse_row(rom, line.rstrip('\n'), pc, aligned_scan=True)
            if len(rows) != len(rom)//2 or lines.readline():
                raise ValueError('Incomplete or trailing aligned decoder output')
        decode_seconds = time.perf_counter() - started
    if cleanup['exists_after']:
        raise ValueError('Aligned offline decoder scratch retained')
    return rows, {'calls': 1, 'positions': len(rows), 'truncated': sum(not row[0] for row in rows.values()),
                  'program_sha256': program['sha256'], 'decoder_sha256': decoder_sha,
                  'decoder_inputs': inputs, 'compiler_sha256': quality.sha(cc), 'cleanup': cleanup,
                  'compile_seconds': compile_seconds, 'decode_seconds': decode_seconds}


def decode(rom,pcs,*,cache=None,batch_instructions=512,program=None):
    if type(batch_instructions) is not int or not 1<=batch_instructions<=8192:
        raise ValueError('Decoder batch must contain1..8192 instructions')
    authenticate(rom,program)
    wanted=tuple(pcs)
    if any(type(pc) is not int or pc&15 or not 0xff800000<=pc<=0xfffffff0 for pc in wanted):
        raise ValueError('Invalid reached PC')
    wanted=set(wanted)
    cached={} if cache is None else cache
    result={pc:cached[pc] for pc in wanted if pc in cached}
    wanted.difference_update(result)
    from tools.setup import decoder as source_decoder
    decoder=source_decoder.tms34010()   # pinned sources; same rows as the decoder that DECODER_SHA256 records
    proof={'calls':0,'decoded_rows':0,'selected_rows':0}
    with quality.scratch_tree() as (scratch,cleanup):
        proof['cleanup']=cleanup;image=scratch/'program.bin';image.write_bytes(rom)
        while wanted:
            start=min(wanted);offset=(start-0xff800000)//8
            # TMS34010's maximum instruction size is80 bits; remain inside the image.
            count=min(batch_instructions,max(1,(len(rom)-offset)//10))
            output=subprocess.run([str(decoder),str(image),'0xff800000',hex(start),str(count)],capture_output=True,text=True,timeout=10)
            proof['calls']+=1
            if output.returncode or output.stderr.strip():raise ValueError('Offline decoder failed: '+output.stderr[-300:])
            lines=output.stdout.splitlines()
            if len(lines)!=count:raise ValueError('Incomplete offline decoder batch')
            expected=start
            for line in lines:
                pc = expected
                row = parse_row(rom, line, pc)
                proof['decoded_rows']+=1
                cached[pc]=row
                if pc in wanted:
                    result[pc]=row;wanted.remove(pc)
                expected=pc+row[0]
            if start in wanted:raise ValueError('Decoder omitted requested entry')
    if cleanup['exists_after']:raise ValueError('Offline decoder scratch retained')
    proof['selected_rows']=len(result)
    return result,proof
