"""MK3 2.1 identity: accept only the driver's 26 ROMs; reject other revisions and altered bytes."""
import json,os,unittest
from pathlib import Path
from tools.quality import run as q
from tools.mk3 import roms

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'roms/mk3'

def linked_set(target):
    target.mkdir()
    for rom in roms.definition():os.link(SOURCE/rom['path'],target/rom['path'])
    return target

class RomIdentityTests(unittest.TestCase):
    def test_manifest_is_the_archived_driver_definition(self):
        manifest=json.loads(roms.MANIFEST.read_text('utf-8'))
        self.assertEqual(manifest['source_sha256'],q.sha(roms.SOURCE))
        self.assertEqual([{k:v for k,v in r.items() if k!='sha256'} for r in manifest['roms']],roms.definition())
        self.assertEqual((manifest['rom_count'],manifest['reset_vector']),(26,'0xff8148b0'))

    def test_local_revision_is_accepted(self):
        self.assertEqual(roms.verify(SOURCE)['verified'],26)

    def test_other_revision_altered_and_missing_roms_are_rejected(self):
        with q.scratch_tree() as (temp,cleanup):
            for case,(source,expected) in {'mk3r20':('mk3r20/mk320u54.bin','mismatch: mk321u54.bin'),
                                           'altered':(None,'mismatch: l1_mortal_kombat_3_u117'),'missing':(None,'ROM missing')}.items():
                directory=linked_set(temp/case)
                if case=='mk3r20':
                    (directory/'mk321u54.bin').unlink();os.link(SOURCE/source,directory/'mk321u54.bin')
                elif case=='altered':
                    name='l1_mortal_kombat_3_u117_game_rom.u117';data=bytearray((SOURCE/name).read_bytes());data[0x1234]^=1
                    (directory/name).unlink();(directory/name).write_bytes(data)
                else:(directory/'l1_mortal_kombat_3_u2_music_spch.u2').unlink()
                with self.assertRaisesRegex(ValueError,expected):roms.verify(directory)
            self.assertTrue(all(q.sha(SOURCE/r['path'])==r['sha256'] for r in json.loads(roms.MANIFEST.read_text('utf-8'))['roms']))
        self.assertFalse(cleanup['exists_after'])

if __name__=='__main__':unittest.main()
