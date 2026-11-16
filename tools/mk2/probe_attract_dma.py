"""Observe the actual attract MMTM DMA writer in pinned Original, from reset."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import batch_reference as batch, native, profile, run
from tools.mk2 import generate_video_irq as emitter
from tools.mk2.offline_decode import decode
from tools.quality import run as q


def check_observations(rows, cycle=783609560, command=0x9008):
    before_rows = [row for row in rows if row.startswith('BEFORE ')]
    after_rows = [row for row in rows if row.startswith('AFTER ')]
    assert len(before_rows) == len(after_rows) == 1
    before = [int(value, 16) for value in before_rows[0].split()[1:]]
    after = [int(value, 16) for value in after_rows[0].split()[1:]]
    assert len(before) == len(after) == 34
    assert before[:3] == [0xff805240, 0x00200030, cycle] and before[10] == 0x01a800c0
    assert before[15] >> 16 == command
    expected = before.copy()
    expected[0] = 0xff805260
    expected[2] += 26
    expected[10] -= 192
    assert after == expected
    addresses = [0x01a800a0, 0x01a800b0, 0x01a80080, 0x01a80090, 0x01a80060, 0x01a80070,
                 0x01a80040, 0x01a80050, 0x01a80020, 0x01a80030, 0x01a80000, 0x01a80010]
    values = [part for reg in (6, 8, 9, 10, 11, 12)
              for part in (before[3 + reg] & 0xffff, before[3 + reg] >> 16)]
    writes = [[int(value, 16) for value in row.split()[1:]] for row in rows if row.startswith('DMAW ')]
    assert writes == [[0xff805260, address, value, cycle, 16, 0xff805240]
                      for address, value in zip(addresses, values)]
    return {'passed': True, 'CPU34_fields_compared': 34, 'ordered_16bit_write_lanes_compared': 12,
            'MMTM_cycles': 26, 'final_command': f'{command:04x}',
            'DMA_dimensions': [before[12] & 0x3ff, (before[12] >> 16) & 0x3ff]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--cycle', type=int, default=783609560)
    parser.add_argument('--command', type=lambda value: int(value, 16), default=0x9008)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Preserve the existing receipt')
    report = {'passed': False, 'scope': 'Original from factory reset with released inputs; exact MMTM CPU brackets and DMA write observations only.'}
    try:
        assert q.sha(batch.MAME) == batch.MAME_SHA
        seed = profile.FACTORY_SEED.read_bytes()
        assert hashlib.sha256(seed).hexdigest() == profile.FACTORY_SHA256
        program = emitter.load_program(q.ROOT / 'roms/mk2')
        rows, proof = decode(program, [0xff805240])
        report.update(mame_sha256=batch.MAME_SHA, program_sha256=emitter.PROGRAM_SHA256,
                      factory_cmos_sha256=profile.FACTORY_SHA256, instruction=rows[0xff805240], decoder=proof)
        with q.scratch_tree() as (scratch, cleanup):
            report['cleanup'] = cleanup
            native.prepare_reference_roms(q.ROOT / 'roms/mk2', scratch / 'mk2', run.read_manifest())
            nv = scratch / 'nvram/mk2'
            nv.mkdir(parents=True)
            (nv / 'nvram').write_bytes(seed)
            regs = ','.join([f'a{n}' for n in range(15)] + ['sp'] + [f'b{n}' for n in range(15)])
            fmt = ' '.join(['%X'] * 34) + r'\n'
            command = 'focus :maincpu\n'
            command += f'bpset ff805240,totalcycles=={args.cycle:x},{{printf "BEFORE {fmt}",pc,st,totalcycles,{regs};'
            command += 'wpset 1a80000,120,w,1,{printf "DMAW %X %X %X %X %X %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};'
            command += f'bpset ff805260,1,{{printf "AFTER {fmt}",pc,st,totalcycles,{regs};quit}};g}}\ngo\n'
            (scratch / 'observe.cmd').write_text(command, encoding='ascii')
            report['observer_sha256'] = hashlib.sha256(command.encode('ascii')).hexdigest()
            env = {'PATH': str(q.DEFAULT_CC.parent) + os.pathsep + os.environ['PATH'], 'TEMP': str(scratch), 'TMP': str(scratch)}
            options = [batch.MAME, 'mk2', '-noreadconfig', '-nowriteconfig', '-rompath', scratch,
                       '-video', 'none', '-sound', 'none', '-nothrottle', '-skip_gameinfo', '-noplugins', '-frameskip', '0',
                       '-keyboardprovider', 'none', '-mouseprovider', 'none', '-lightgunprovider', 'none', '-joystickprovider', 'none',
                       '-debug', '-debugger', 'windows', '-debuglog', '-debugscript', 'observe.cmd',
                       '-nvram_directory', scratch / 'nvram', '-cfg_directory', scratch / 'cfg', '-homepath', scratch / 'home', '-seconds_to_run', str(args.cycle // 6250000 + 10)]
            result = q.command(options, scratch, cwd=scratch, env=env, timeout=240)
            report['execution'] = q.compact(result)
            log = (scratch / 'debug.log').read_text() if (scratch / 'debug.log').exists() else ''
            report['observations'] = [line for line in log.splitlines() if line.startswith(('BEFORE ', 'DMAW ', 'AFTER '))]
            report['debug_tail'] = log[-1200:]
            report['observation_contract'] = check_observations(report['observations'], args.cycle, args.command)
            report['passed'] = result['passed'] and report['observation_contract']['passed']
    except Exception as error:
        report['error'] = repr(error)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
