"""Incremental native JSON preparation controls; no large output artifact."""
import importlib.util,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.mk2 import stream_transport
from tools.quality import run as q
p=ROOT/'tools/mk2/native_json.py'
class NativeStreamTests(unittest.TestCase):
 def decoder(self):
  self.assertTrue(p.exists(),'incremental native JSON decoder is missing')
  spec=importlib.util.spec_from_file_location('native_json_stream',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m.NativeDecoder()
 def test_exact_rows_and_unicode_across_every_chunk_boundary(self):
  expected={'name':'acao-\u00e7','dsp_trace':[[0,2**64-1]+[n]*74 for n in range(3)],'batch_dsp_trace':[[9]*76],'tail':12345,'empty':[]}
  raw=json.dumps(expected,ensure_ascii=False,separators=(',',':')).encode()
  for width in (1,2,3,7,4096):
   d=self.decoder()
   for offset in range(0,len(raw),width):d.feed(raw[offset:offset+width])
   d.finish();self.assertTrue(d.ended);self.assertEqual(d.result['name'],expected['name']);self.assertEqual(d.result['tail'],12345)
   self.assertEqual(list(d.result['dsp_trace']),expected['dsp_trace']);self.assertEqual(list(d.result['batch_dsp_trace']),expected['batch_dsp_trace']);self.assertEqual(d.result['empty'],[])
 def test_rejects_incomplete_duplicate_trailing_and_invalid_rows(self):
  for raw in (b'',b'{',b'{"a":1',b'{"a":1,}',b'{"a":[1,]}',b'{"a":1,"a":2}',b'{}{}',b'{}'+bytes((194,160)),b'{"dsp_trace":[[1]]}',b'{"dsp_trace":{}}',b'{"batch_dsp_trace":null}',*[b'{"dsp_trace":[['+x+b',0'*75+b']]}' for x in (b'true',b'1.0',b'18446744073709551616',b'01')],b'{"dsp_trace":[[-1'+b',0'*75+b']]}'):
   with self.subTest(raw=raw[:40]),self.assertRaises(ValueError):
    d=self.decoder();d.feed(raw);d.finish()
 def test_buffer_is_released_while_exact_observations_remain(self):
  d=self.decoder();d.feed(b'{"dsp_trace":[')
  row=json.dumps([17]*76,separators=(',',':')).encode()
  for n in range(10000):d.feed((b',' if n else b'')+row)
  d.feed(b'],"tail":99}');d.finish()
  self.assertEqual(len(d.result['dsp_trace']),10000);self.assertEqual(d.result['dsp_trace'][9999],[17]*76);self.assertEqual(d.result['tail'],99)
  self.assertLessEqual(d.peak_pending_bytes,8192)
 def test_existing_owned_transport_accepts_raw_json_decoder_and_reaps_failures(self):
  expected={'dsp_trace':[[7]*76],'tail':12345};payload=json.dumps(expected,separators=(',',':'))
  cases=[("import os;assert os.environ['MK2_NATIVE_TEST']=='active';os.write(1,"+repr(payload.encode())+")",True),
         ("import os;os.write(1,"+repr(payload.encode())+");raise SystemExit(7)",False),
         ("import os,subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']);os.write(1,b'BROKEN');time.sleep(20)",False)]
  for source,want in cases:
   d=self.decoder()
   with q.scratch_tree() as (scratch,cleanup):
    result=stream_transport.command([sys.executable,'-B','-c',source],scratch,lambda line:None,lambda line:None,timeout=5,decoder=d,env={'MK2_NATIVE_TEST':'active'})
    self.assertEqual(result['passed'],want,result);self.assertTrue(result['owned_job_empty']);self.assertEqual(result['queued_byte_limit'],8192)
    self.assertIsNone(result['line_byte_limit'])
    if 'BROKEN' in source:self.assertIn('BROKEN',result.get('stdout',''))
   self.assertFalse(cleanup['exists_after'])
   if want:self.assertEqual(list(d.result['dsp_trace']),expected['dsp_trace']);self.assertEqual(d.result['tail'],12345)
if __name__=='__main__':unittest.main()
