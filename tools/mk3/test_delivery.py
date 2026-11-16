"""K10 front C: tools/mk3/delivery.py. The form certificate on the real image (one scan and one in-memory generation, no
build, no Original): every count closes, a never-exercised form is absent from every route-verified block, and the
negative: a form taken out of the exercised set shows up as never exercised. The delivery report reads the receipts on
disk only and never counts the residue as verified."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import delivery,generate


class Forms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.forms,cls.asm,cls.residue,cls.route=delivery.inputs()

    def test_mould_masks_operand_values_only(self):
        self.assertEqual(delivery.mould('o.Block(0xff800000u); s.a[1]=8; o.Finish(0xff800010u,1);'),'R=N; o.Finish(N,N);')
        self.assertEqual(delivery.mould('o.Shift(s.b[5],15,true,0xff92f410u);'),delivery.mould('o.Shift(s.a[0],22,true,0xffaeeb50u);'))
        self.assertNotEqual(delivery.mould('o.MultiplySigned(s.a[1],14,false,0xff92f390u);'),delivery.mould('o.MultiplySigned(s.b[2],2,true,0xff92f1a0u);'))

    def test_certificate_closes(self):
        c=delivery.certificate(self.forms,self.asm,self.residue,self.route);never=c['never_exercised']
        self.assertGreater(c['residue']['pcs'],0);self.assertFalse(self.residue&self.route)
        self.assertEqual(c['route']['blocks'],len(generate.route_keys()['keys']['TmsBlock']))
        self.assertEqual(c['residue_forms_exercised_on_routes']['pcs']+never['translated']['pcs']+never['untranslated']['pcs'],c['residue']['pcs'])
        self.assertEqual(c['residue_forms_exercised_on_routes']['forms']+len(never['forms']),c['residue']['forms'])
        ran={self.forms[pc] for pc in self.route}
        for r in never['forms']:
            self.assertNotIn((r['form'],r['bits'],r['mould']),ran);self.assertLessEqual(len(r['examples']),3)
            self.assertIn(int(r['examples'][0][:8],16),self.residue)

    def test_negative_form_removed_from_the_exercised_set(self):
        base=delivery.certificate(self.forms,self.asm,self.residue,self.route)
        ran={self.forms[pc] for pc in self.route}
        key=max((k for k in {self.forms[pc] for pc in self.residue} if k in ran),key=lambda k:(sum(self.forms[pc]==k for pc in self.residue),k))
        cut=delivery.certificate(self.forms,self.asm,self.residue,{pc for pc in self.route if self.forms[pc]!=key})
        row=[r for r in cut['never_exercised']['forms'] if (r['form'],r['bits'],r['mould'])==key]
        self.assertEqual(len(row),1);self.assertEqual(row[0]['pcs'],sum(self.forms[pc]==key for pc in self.residue))
        self.assertEqual(len(cut['never_exercised']['forms']),len(base['never_exercised']['forms'])+1)
        self.assertEqual(cut['residue_pcs_with_every_form_exercised'],base['residue_pcs_with_every_form_exercised']-row[0]['pcs'])


class Report(unittest.TestCase):
    def test_report_from_receipts_keeps_the_residue_apart(self):
        md,data=delivery.delivery(delivery.M2/'no-such-forms.json')
        rv=json.loads(generate.ROUTES.read_text('utf-8'))
        self.assertEqual(data['verified_on_routes'],{k:len(rv.get(k,[])) for k in generate.KINDS})
        self.assertEqual(len(data['routes']),len(rv['routes']));self.assertEqual(data['residue']['counted_as'],'not verified')
        self.assertEqual(data['residue']['classified']['pcs']+data['residue']['unclassified']['pcs'],data['residue']['pcs'])
        self.assertNotIn(data['residue']['pcs'],data['verified_on_routes'].values())
        self.assertIn('## Resíduo (não verificado)',md);self.assertIn('Classe não é verificação.',md)
        self.assertTrue(any('missing' in s for s in data['stale']));self.assertIsNone(data['forms'])   # negative: no certificate, said so
        self.assertEqual(len(data['limits']),2)   # F1/D2 renamed the preview identifiers, so that limit is gone


if __name__=='__main__':unittest.main()
