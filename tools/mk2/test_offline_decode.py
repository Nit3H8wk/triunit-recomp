"""Pinned decoder batching controls; no generated native source is changed."""
import sys,importlib.util,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.mk2 import generate_video_irq as g
p=ROOT/'tools/mk2/offline_decode.py'
class GuardTests(unittest.TestCase):
 def test_unauthenticated_images_reject_before_decoder_or_tool_access(self):
  from tools.mk2 import offline_decode as m
  with patch.object(m.quality,'sha',side_effect=AssertionError('tool reached')),patch.object(m.subprocess,'run',side_effect=AssertionError('process reached')):
   for image in (b'',bytes(0xfffff),bytes(0x100000)):
    with self.subTest(size=len(image)),self.assertRaises(ValueError):m.decode(image,(0xff804110,))
 def test_invalid_pc_types_reject_before_deduplication_or_tool_access(self):
  from tools.mk2 import offline_decode as m
  # Synthetic image exercises PC validation only; it does not authenticate a game ROM.
  image=bytes(0x100000)
  with patch.object(m.generated,'PROGRAM_SHA256',m.hashlib.sha256(image).hexdigest()),patch.object(m.quality,'sha',side_effect=AssertionError('tool reached')):
   for pcs in ((float(0xff804110),),(0xff804110,float(0xff804110)),(True,),('ff804110',),([],),(0xff804111,),(0xff7ffff0,),(0x100000000,)):
    with self.subTest(pcs=pcs),self.assertRaises(ValueError):m.decode(image,pcs)

class DecodeTests(unittest.TestCase):
 def test_full_aligned_scan_keeps_overlaps_and_accounts_for_the_rom_tail(self):
  from tools.mk2 import offline_decode as m
  image=g.load_program(ROOT/'roms/mk2')
  rows,proof=m.scan_aligned(image)
  self.assertEqual(list(rows),list(range(0xff800000,0x100000000,16)))
  self.assertEqual(proof['calls'],1)
  self.assertFalse(proof['cleanup']['exists_after'])
  samples=(0xff804110,0xff804120,0xffa54ea0)
  baseline,_=m.decode(image,samples)
  self.assertEqual({pc:rows[pc] for pc in samples},baseline)
  self.assertEqual(rows[0xff804110][0],32)
  self.assertEqual(rows[0xff804120][2][0],0x1bc0)
  self.assertEqual(rows[0xfffffff0][2][0],int.from_bytes(image[-2:],'little'))

 def module(self):
  self.assertTrue(p.exists(),'batch decoder helper missing');spec=importlib.util.spec_from_file_location('decode_batch',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 def test_real_words_widths_and_requested_pcs_only(self):
  m=self.module();rows,proof=m.decode(g.load_program(ROOT/'roms/mk2'),(0xff804110,0xffa54ea0))
  self.assertEqual(set(rows),{0xff804110,0xffa54ea0});self.assertEqual(rows[0xff804110][:3],(32,0x80000000,(0x09a3,0x1bc0)))
  self.assertEqual(rows[0xffa54ea0][0],32);self.assertEqual(rows[0xffa54ea0][2],(0x0d89,0xff9e));self.assertFalse(proof['cleanup']['exists_after'])
 def test_rejects_wrong_rom_and_misaligned_target(self):
  m=self.module();rom=g.load_program(ROOT/'roms/mk2')
  for image,pcs in ((rom[:-1],(0xff804110,)),(bytes((rom[0]^1,))+rom[1:],(0xff804110,)),(rom,(0xff804111,))):
   with self.assertRaises(ValueError):m.decode(image,pcs)
 def test_rejects_a_real_decoder_row_after_opcode_mutation(self):
  m=self.module();real=subprocess.run
  def changed(*args,**kwargs):
   result=real(*args,**kwargs);lines=result.stdout.splitlines();fields=lines[0].split('\t');words=fields[3].split();words[0]='ffff';fields[3]=' '.join(words)+' ';lines[0]='\t'.join(fields);result.stdout='\n'.join(lines)+'\n';return result
  with patch.object(m.subprocess,'run',side_effect=changed),self.assertRaises(ValueError):m.decode(g.load_program(ROOT/'roms/mk2'),(0xff804110,))
 def test_generated_source_batches_real_calls_without_changing_output(self):
  from tools.mk2 import offline_decode
  real=subprocess.run;calls=[]
  rom=g.load_program(ROOT/'roms/mk2')
  decode=offline_decode.decode
  with patch.object(offline_decode,'decode',side_effect=lambda rom,pcs:decode(rom,pcs,batch_instructions=1)):
   baseline=g.generate(rom)
  def counted(*args,**kwargs):calls.append(args[0]);return real(*args,**kwargs)
  with patch.object(subprocess,'run',side_effect=counted):
   source=g.generate(rom)
  self.assertEqual(source,baseline)
  self.assertLessEqual(len(calls),64,'generation still launches one process per instruction')
 def test_reference_widths_batch_real_calls_and_keep_literal_widths(self):
  from tools.mk2 import batch_reference,run
  real=subprocess.run;calls=[];pcs=set(g.PCS)|{0xff804110,0xffa54ea0}
  def counted(*args,**kwargs):calls.append(args[0]);return real(*args,**kwargs)
  with patch.object(subprocess,'run',side_effect=counted):
   widths,opcode=batch_reference.decoded_widths(ROOT/'roms/mk2',run.read_manifest(),pcs)
  self.assertEqual(set(widths),pcs);self.assertEqual(widths[0xff804110],32);self.assertEqual(widths[0xffa54ea0],32)
  self.assertEqual(opcode(0xff804110),0x09a3)
  self.assertLessEqual(len(calls),64,'reference still launches one process per instruction')
if __name__=='__main__':unittest.main()
