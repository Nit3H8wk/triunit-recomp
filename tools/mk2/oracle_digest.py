"""SHA-256 of expected Original states (plan 2026-11-15-conformidade-legal.md, 2.3).

The repository keeps only these digests; the raw values are regenerated locally by the oracle (pinned MAME + the
user's ROMs). Serialization, identical to native/mk2/mk2_oracle_digest.hpp: the values as consecutive 8-byte
little-endian unsigned words, lowercase hex.
"""
import hashlib

MASK = (1 << 64) - 1


def words_digest(values):
    return hashlib.sha256(b''.join((int(v) & MASK).to_bytes(8, 'little') for v in values)).hexdigest()


def cpu34_digest(row):
    """CPU34: next PC, ST, executed cycles, A0..A15, B0..B14."""
    if len(row) != 34: raise ValueError('CPU34 requires thirty-four words')
    return words_digest(row)


def dsp76_digest(registers, native_clock=False):
    """DSP76 = AdspBoot::Registers(); `native_clock` removes the executed-instruction cycle the MAME cache lags by."""
    values = list(registers)
    if native_clock and len(values) > 1: values[1] -= 1
    return words_digest(values)
