"""C++ profile interoperability and two actual guest resets; no real window or audio."""
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native,profile,run as foundation
from tools.quality import run as quality
ROOT=quality.ROOT
FIXTURE=ROOT/'native/tests/mk2_profile_tests.cpp'

@unittest.skipUnless(sys.platform=='win32'and quality.DEFAULT_CC.is_file(),'requires Windows C++ toolchain')
class CppProfileTests(unittest.TestCase):
    def environment(self):
        return {'PATH':str(quality.DEFAULT_CC.parent)+os.pathsep+os.environ.get('PATH','')}

    def command(self,argv,scratch,*,success=True,timeout=30):
        result=quality.command(argv,scratch,cwd=ROOT,env=self.environment(),timeout=timeout,output_limit=256*1024)
        self.assertEqual(result['passed'],success,quality.compact(result))
        self.assertEqual(result['discarded_output_bytes'],0)
        return result['stdout'].strip()

    def test_cpp_storage_interoperability_exact_bytes_conflicts_and_writer_locks(self):
        seed_before=quality.sha(profile.FACTORY_SEED)
        with quality.scratch_tree()as(scratch,cleanup):
            executable=scratch/'profile.exe'
            self.command([quality.DEFAULT_CC,'-std=c++17','-O2','-municode','-Wall','-Wextra','-Werror',
                '-I'+str(ROOT),'-I'+str(ROOT/'native/include'),FIXTURE,ROOT/'native/mk2/mk2_profile.cpp',
                ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',executable],scratch,timeout=90)
            directory=scratch/'profile';seed=profile._read(profile.FACTORY_SEED,factory=True)
            self.assertIn('PASS',self.command([executable,'unit',scratch/'C++-unit',profile.FACTORY_SEED],scratch))
            profile.prepare(directory)
            self.assertEqual(self.command([executable,'load',directory],scratch),hashlib.sha256(seed).hexdigest())
            self.command([executable,'prepare',scratch/'native-prepared',profile.FACTORY_SEED],scratch)
            self.assertEqual(profile.load(scratch/'native-prepared'),seed)
            rng=random.Random(681007);image=bytes(rng.randrange(256)for _ in range(profile.SIZE))
            self.assertEqual(len(set(image[1::2])),256,'high bytes must exercise every value')
            payload=scratch/'image.bin';payload.write_bytes(image)
            digest=self.command([executable,'save',directory,payload,hashlib.sha256(seed).hexdigest()],scratch)
            self.assertEqual(profile.load(directory),image)
            changed=bytes(value^0x5a for value in image)
            digest=profile.save(directory,changed,expected_sha256=digest)
            output=scratch/'loaded.bin'
            self.assertEqual(self.command([executable,'load',directory,output],scratch),digest)
            self.assertEqual(output.read_bytes(),changed)
            self.command([executable,'save',directory,payload,hashlib.sha256(seed).hexdigest()],scratch,success=False)
            self.assertEqual(profile.load(directory),changed)
            for size in (profile.SIZE-1,profile.SIZE+1):
                payload.write_bytes(b'\x80'*size)
                self.command([executable,'save',directory,payload,digest],scratch,success=False)
                self.assertEqual(profile.load(directory),changed)
            payload.write_bytes(image)
            with profile._writer(directory):
                self.command([executable,'save',directory,payload,digest],scratch,success=False)
                self.command([executable,'prepare',directory,profile.FACTORY_SEED],scratch,success=False)
                self.assertTrue((directory/'.cmos.lock').exists())
            holder=subprocess.Popen([str(executable),'hold',str(directory)],cwd=ROOT,
                env={**os.environ,**self.environment()},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(),'LOCKED')
                with self.assertRaises(FileExistsError):profile.save(directory,image,expected_sha256=digest)
                with self.assertRaises(FileExistsError):profile.prepare(directory)
            finally:
                try:
                    holder.communicate('\n',timeout=10)
                finally:
                    if holder.poll()is None:holder.kill();holder.wait(timeout=10)
            self.assertEqual(holder.returncode,0)
            lock=directory/'.cmos.lock';lock.write_bytes(b'foreign stale owner')
            self.assertEqual(self.command([executable,'load',directory],scratch),digest)
            self.command([executable,'save',directory,payload,digest],scratch,success=False)
            self.assertEqual(lock.read_bytes(),b'foreign stale owner');lock.unlink()
            unowned=scratch/'unowned';unowned.mkdir();(unowned/'keep').write_bytes(b'owned elsewhere')
            self.command([executable,'prepare',unowned,profile.FACTORY_SEED],scratch,success=False)
            self.assertEqual({p.name for p in unowned.iterdir()},{'keep'})
            missing=scratch/'missing';self.command([executable,'load',missing],scratch,success=False)
            self.assertFalse(missing.exists())
            (directory/'factory-seed.bin').write_bytes(b'\0'*profile.SIZE)
            for args in (['load',directory],['prepare',directory,profile.FACTORY_SEED],['save',directory,payload,digest]):
                self.command([executable,*args],scratch,success=False)
            self.assertEqual((directory/'cmos.bin').read_bytes(),changed)
            (directory/'factory-seed.bin').write_bytes(seed)
            payload.write_bytes(b'\xff'*profile.SIZE)
            self.command([executable,'save',directory,payload,digest],scratch)
            self.assertEqual(profile.load(directory),b'\xff'*profile.SIZE,'storage must not normalize invalid game checksums')
            self.assertEqual((directory/'factory-seed.bin').read_bytes(),seed)
            self.assertEqual({p.name for p in directory.iterdir()},{'cmos.bin','factory-seed.bin'})
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(quality.sha(profile.FACTORY_SEED),seed_before)

    @unittest.skipUnless((ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_direct_native_two_resets_reload_exact_cmos_and_preserve_raw_transport(self):
        foundation.verify_roms(ROOT/'roms/mk2')
        seed_before=quality.sha(profile.FACTORY_SEED)
        with quality.scratch_tree()as(scratch,cleanup):
            executable=scratch/'native-profile.exe'
            sources=[ROOT/name for name in foundation.SOURCES if '/tests/'not in name]
            sources+=[ROOT/'native/mk2/mk2_native_check.cpp',ROOT/'native/mk2/mk2_music.cpp',ROOT/'native/src/mk5_audio_output.cpp',
                      ROOT/'native/tests/mk2_host_close_window.cpp']
            self.command([quality.DEFAULT_CC,'-std=c++17','-O1','-municode','-pthread','-Wall','-Wextra','-Werror',
                '-Wno-unused-parameter','-Wno-missing-field-initializers','-I'+str(ROOT/'native/include'),
                *sources,'-lbcrypt','-luser32','-lgdi32','-lwinmm','-o',executable],scratch,timeout=180)
            directory=scratch/'profile';initial=profile.prepare(directory)
            expected=list(struct.unpack('<8192H',initial));previous=initial
            for audit in (1,2):
                observed=json.loads(self.command([executable,ROOT/'roms/mk2','--through','cmos-draw','--profile',directory],scratch))
                saved=profile.load(directory)
                expected[0xf0:0xf6]=[0,0,0,audit,255,255-audit]
                self.assertEqual(saved,struct.pack('<8192H',*expected))
                self.assertTrue(native.frontier_matches(observed['cpu34'],native.frontier('cmos-draw')))
                self.assertEqual(observed['profile'],{'loaded_sha256':hashlib.sha256(previous).hexdigest(),
                    'saved_sha256':hashlib.sha256(saved).hexdigest(),'committed':True})
                self.assertNotIn('cmos_hex',observed)
                if audit==1:first=saved
                previous=saved
            image=scratch/'first-image.bin';image.write_bytes(first)
            observed=json.loads(self.command([executable,ROOT/'roms/mk2','--through','cmos-draw','--cmos-image',image],scratch))
            self.assertNotIn('profile',observed)
            self.assertEqual(bytes.fromhex(observed['cmos_hex']),previous)
            self.assertEqual(profile.load(directory),previous,'raw diagnostic must not update the profile')
            self.assertEqual(image.read_bytes(),first)
            self.assertEqual((directory/'factory-seed.bin').read_bytes(),initial)
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(quality.sha(profile.FACTORY_SEED),seed_before)

if __name__=='__main__':unittest.main()
