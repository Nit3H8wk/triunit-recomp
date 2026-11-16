"""Incremental native JSON with exact uint64 DSP rows; requires orjson."""
import codecs,json,re,orjson
from tools.mk2.packed_trace import PackedRows

class ExactDspRows(PackedRows):
    def append(self,row):
        if not isinstance(row,list) or len(row)!=self.width:raise ValueError('Invalid DSP width')
        # The raw row grammar excludes bool/float/sign; the C array enforces uint64 range.
        old=len(self.values)
        try:self.values.extend(row)
        except (TypeError,OverflowError) as error:
            del self.values[old:]
            raise ValueError('Invalid exact uint64 DSP row') from error

class NativeDecoder:
    block_byte_limit=4096
    pending_value_byte_limit=1024*1024
    def __init__(self):
        self.result={}; self.pending=''; self.pos=0; self.state='start'; self.key=None
        self.items=None; self.empty=True; self.closed=False; self.ended=False
        self.utf8=codecs.getincrementaldecoder('utf-8')('strict'); self.json=json.JSONDecoder()
        self.peak_pending_bytes=0; self.bytes=0; self.lines=0
        self.frames=self.direct_frames=self.diagnostics=0
    def feed(self,block):
        if self.closed or len(block)>self.block_byte_limit:raise ValueError('Native JSON block outside open 4-KiB transport')
        self.bytes+=len(block);self.lines+=block.count(b'\n')
        self.pending+=self.utf8.decode(block)
        self.peak_pending_bytes=max(self.peak_pending_bytes,len(self.pending.encode('utf-8')))
        self.drain()
    def raw(self):
        if self.state=='array' and self.key in ('dsp_trace','batch_dsp_trace'):
            end=self.pending.find(']',self.pos)
            if end<0:return None
            raw=self.pending[self.pos:end+1]
            if not re.fullmatch(r'\[[0-9, \t\r\n]*\]',raw):raise ValueError('Invalid unsigned DSP JSON row')
            return orjson.loads(raw),end+1
        try:value,end=self.json.raw_decode(self.pending,self.pos)
        except json.JSONDecodeError:return None
        tail=end
        while tail<len(self.pending) and self.pending[tail] in ' \t\r\n':tail+=1
        # A number split as 12|34 must not publish 12 as a complete value.
        if tail==len(self.pending):return None
        if self.pending[tail] not in ',]}':return None
        return value,end
    def drain(self):
        while True:
            while self.pos<len(self.pending) and self.pending[self.pos] in ' \t\r\n':self.pos+=1
            if self.pos==len(self.pending):break
            char=self.pending[self.pos]
            if self.state=='start':
                if char!='{':raise ValueError('Native JSON requires one object')
                self.pos+=1;self.state='key';self.empty=True
            elif self.state=='key':
                if char=='}' and self.empty:self.pos+=1;self.state='end';continue
                if char!='"':raise ValueError('Native JSON key or trailing comma')
                try:key,end=self.json.raw_decode(self.pending,self.pos)
                except json.JSONDecodeError:break
                if key in self.result:raise ValueError('Duplicate native JSON key')
                self.key=key;self.pos=end;self.state='colon'
            elif self.state=='colon':
                if char!=':':raise ValueError('Missing native JSON colon')
                self.pos+=1;self.state='value'
            elif self.state=='value':
                if self.key in ('dsp_trace','batch_dsp_trace') and char!='[':raise ValueError('DSP trace requires an array')
                if char=='[':
                    self.items=ExactDspRows() if self.key in ('dsp_trace','batch_dsp_trace') else []
                    self.pos+=1;self.state='array';self.empty=True
                else:
                    item=self.raw()
                    if item is None:break
                    value,self.pos=item;self.result[self.key]=value;self.state='outer'
            elif self.state=='array':
                if char==']':
                    if not self.empty:raise ValueError('Trailing native JSON array comma')
                    self.pos+=1;self.result[self.key]=self.items;self.items=None;self.state='outer';continue
                item=self.raw()
                if item is None:break
                value,self.pos=item;self.items.append(value);self.state='array_delimiter'
            elif self.state=='array_delimiter':
                if char==',':self.pos+=1;self.state='array';self.empty=False
                elif char==']':self.pos+=1;self.result[self.key]=self.items;self.items=None;self.state='outer'
                else:raise ValueError('Invalid native JSON array delimiter')
            elif self.state=='outer':
                if char==',':self.pos+=1;self.state='key';self.empty=False
                elif char=='}':self.pos+=1;self.state='end'
                else:raise ValueError('Invalid native JSON object delimiter')
            else:raise ValueError('Trailing native JSON content')
        self.pending=self.pending[self.pos:];self.pos=0
        if len(self.pending.encode('utf-8'))>self.pending_value_byte_limit:raise ValueError('Native JSON value exceeds1MiB pending budget')
    def finish(self):
        if self.closed:raise ValueError('Native JSON already finished')
        self.pending+=self.utf8.decode(b'',final=True);self.drain();self.closed=True
        if self.pending or self.state!='end':raise ValueError('Incomplete native JSON')
        self.ended=True
