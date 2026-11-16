"""Exact DSP rows without one Python object per retained register value."""
from array import array
from collections.abc import Sequence
import json
import re


class PackedRows(Sequence):
    def __init__(self, width=76):
        self.width = width
        self.values = array('Q')

    def append(self, row):
        if (not isinstance(row, list) or len(row) != self.width or
                any(type(value) is not int or not 0 <= value < 2**64 for value in row)):
            raise ValueError('Invalid exact uint64 DSP row')
        self.values.extend(row)

    def __len__(self):
        return len(self.values) // self.width

    def __getitem__(self, index):
        if isinstance(index, slice): return [self[n] for n in range(*index.indices(len(self)))]
        if index < 0: index += len(self)
        if not 0 <= index < len(self): raise IndexError(index)
        start = index * self.width
        return self.values[start:start+self.width].tolist()

    def __eq__(self, other):
        if isinstance(other, PackedRows): return self.width == other.width and self.values == other.values
        return isinstance(other, Sequence) and len(self) == len(other) and all(a == b for a,b in zip(self,other))

    @property
    def nbytes(self):
        return len(self.values) * self.values.itemsize


def load_native(output):
    """Decode the native object once, decoding large DSP arrays one row at a time."""
    decoder, position, result = json.JSONDecoder(), 0, {}

    def skip_space():
        nonlocal position
        position = re.compile(r'[ \t\r\n]*').match(output, position).end()

    def take(token):
        nonlocal position
        skip_space()
        if not output.startswith(token, position): raise ValueError('Malformed native JSON delimiter')
        position += len(token)

    def value():
        nonlocal position
        skip_space()
        item, position = decoder.raw_decode(output, position)
        return item

    take('{'); skip_space()
    if not output.startswith('}', position):
        while True:
            key = value()
            if not isinstance(key, str) or key in result: raise ValueError('Invalid or duplicate native JSON key')
            take(':')
            if key in ('dsp_trace', 'batch_dsp_trace'):
                rows = PackedRows(); take('['); skip_space()
                if not output.startswith(']', position):
                    while True:
                        rows.append(value()); skip_space()
                        if output.startswith(']', position): break
                        take(',')
                take(']'); result[key] = rows
            else: result[key] = value()
            skip_space()
            if output.startswith('}', position): break
            take(',')
    take('}'); skip_space()
    if position != len(output): raise ValueError('Trailing native JSON content')
    return result
