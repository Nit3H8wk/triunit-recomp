"""Exact CMOS storage: failed or stale saves must preserve the previous bytes."""
import hashlib
import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality


class NativeProfileTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.mk2.profile'),
                             'native MK2 has no isolated CMOS storage')
        self.profile=importlib.import_module('tools.mk2.profile')

    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 ROMs')
    def test_native_cmos_image_preserves_both_bytes_and_loads_before_reset(self):
        source=r'''
#include "native/mk2/mk2_cmos_image.hpp"
#include "native/mk2/mk2_executor.hpp"
#include "native/mk2/mk2_adsp.hpp"
#include <fstream>
#include <iterator>
#include <stdexcept>
void check(bool ok) { if(!ok) throw std::runtime_error("CMOS image/reset contract"); }
int main(int argc,char** argv) {
    check(argc==3);
    std::vector<uint8_t> image(16384);
    for(size_t n=0;n<image.size();++n) image[n]=uint8_t(n*37+n/256);
    const auto original=image;
    const auto words=mk2::DecodeCmosImage(image);
    check(words.size()==8192 && words[0]==0x2500 && words[1]==0x6f4a);
    check(mk2::EncodeCmosImage(words)==image && image==original);
    for(const size_t size:{size_t(0),size_t(16383),size_t(16385)}) {
        bool rejected=false;
        try { mk2::DecodeCmosImage(std::vector<uint8_t>(size)); }
        catch(const std::runtime_error&) { rejected=true; }
        check(rejected);
    }
    for(const size_t size:{size_t(0),size_t(8191),size_t(8193)}) {
        bool rejected=false;
        try { mk2::EncodeCmosImage(std::vector<uint16_t>(size)); }
        catch(const std::runtime_error&) { rejected=true; }
        check(rejected);
    }
    const auto program=mk2::LoadProgram(argv[1]);
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    // Generated closure: the reset prefix ends at the first DCS status read (ff811150).
    mk2::DcsBootMachine cold_prefix_machine(boot,rom),persisted_machine(boot,rom);
    mk2::GeneratedBoot cold_prefix(program,cold_prefix_machine,nullptr,0xfc7d);
    mk2::GeneratedBoot persisted_prefix(program,persisted_machine,&image,0xfc7d);
    cold_prefix.RunToPc(0xff811150);persisted_prefix.RunToPc(0xff811150);
    const auto& cold=cold_prefix.State().ready;const auto& persisted=persisted_prefix.State().ready;
    check(persisted.cmos==words && image==original);
    check(persisted.a==cold.a && persisted.b==cold.b && persisted.status==cold.status &&
          persisted.cycles==cold.cycles && persisted.instructions==cold.instructions &&
          persisted.next_pc==cold.next_pc && persisted_prefix.State().main_ram==cold_prefix.State().main_ram);
    check(cold.cmos==std::vector<uint16_t>(8192));
    mk2::DcsBootMachine machine(boot,rom);
    const auto registers=machine.dsp.Registers();
    const auto device=machine.dsp.DeviceState();
    const std::vector<uint8_t> bad(16383);
    bool rejected=false;
    try { mk2::GeneratedBoot invalid(program,machine,&bad,0xfc7d); }
    catch(const std::runtime_error&) { rejected=true; }
    check(rejected && machine.dsp.Registers()==registers &&
          machine.dsp.DeviceState()==device && machine.dsp.trace.empty() &&
          machine.dsp.accesses.empty());
    std::ifstream input(argv[2],std::ios::binary);
    check(bool(input));
    const std::vector<uint8_t> seed{std::istreambuf_iterator<char>(input),{}};
    mk2::DcsBootMachine valid_machine(boot,rom),cold_machine(boot,rom);
    mk2::GeneratedBoot valid_boot(program,valid_machine,&seed,0xfc7d),cold_boot(program,cold_machine,nullptr,0xfc7d);
    // Sound check returns to ff8111f0; the valid image skips the cold record write (3 cycles, 2 instructions).
    valid_boot.RunToPc(0xff8111f0);cold_boot.RunToPc(0xff8111f0);
    struct { const mk2::ResetTrace& returned; } valid{valid_boot.State().ready},cold_sound{cold_boot.State().ready};
    const auto word=(0x010b95a0-0x01000000)/16;
    check(valid_boot.State().main_ram.at(word)==0 && cold_boot.State().main_ram.at(word)==1);
    check(valid.returned.next_pc==0xff8111f0 &&
          valid.returned.cycles+3==cold_sound.returned.cycles &&
          valid.returned.instructions+2==cold_sound.returned.instructions);
    const auto seed_words=mk2::DecodeCmosImage(seed);
    for(size_t n=0;n<seed_words.size();++n) {
        check((valid.returned.cmos[n]&0xff00)==(seed_words[n]&0xff00));
        if(n<0xf0 || n>0xf5) check(valid.returned.cmos[n]==seed_words[n]);
    }
    check(valid.returned.cmos[0xf0]==0 && valid.returned.cmos[0xf1]==0 &&
          valid.returned.cmos[0xf2]==0 && valid.returned.cmos[0xf3]==1 &&
          valid.returned.cmos[0xf4]==0xff && valid.returned.cmos[0xf5]==0xfe);
}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'cmos.cpp';path.write_text(source,encoding='utf-8')
            executable=scratch/'cmos.exe';compiler=quality.DEFAULT_CC
            env={'PATH':str(compiler.parent)+os.pathsep+os.environ.get('PATH','')}
            from tools.mk2 import run as foundation
            sources=foundation.EXECUTOR_SOURCES
            build=quality.command([compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),path,
                *[quality.ROOT/p for p in sources],'-lbcrypt','-o',executable],scratch,env=env,timeout=600)
            self.assertTrue(build['passed'],build)
            result=quality.command([executable,quality.ROOT/'roms/mk2',self.profile.FACTORY_SEED],scratch,env=env)
            self.assertTrue(result['passed'],result)
        self.assertFalse(cleanup['exists_after'])

    def test_seed_authentication_exact_roundtrip_and_independent_profiles(self):
        with quality.scratch_tree() as (scratch,cleanup):
            one,two=scratch/'one',scratch/'two'
            seed=self.profile.prepare(one)
            self.assertEqual(hashlib.sha256(seed).hexdigest(),
                'f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f')
            self.assertEqual(len(seed),16384)
            self.assertNotEqual(seed,bytes(16384),'factory seed is not native cold DEFAULT_ALL_0')
            self.profile.prepare(two)
            data=bytes(range(256))*64
            digest=self.profile.save(one,data,expected_sha256=hashlib.sha256(seed).hexdigest())
            self.assertEqual(digest,hashlib.sha256(data).hexdigest())
            self.assertEqual(self.profile.load(one),data)
            self.assertEqual(self.profile.prepare(one),data,'prepare must not reset persisted state')
            self.assertEqual(self.profile.load(two),seed)
            self.assertEqual((one/'factory-seed.bin').read_bytes(),seed)
        self.assertFalse(cleanup['exists_after'])

    def test_stale_writer_and_held_lock_preserve_previous_state(self):
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'one';seed=self.profile.prepare(path)
            old=hashlib.sha256(seed).hexdigest();data=b'\x5a\xa5'*8192
            self.profile.save(path,data,expected_sha256=old)
            with self.assertRaisesRegex(ValueError,'changed'):
                self.profile.save(path,seed,expected_sha256=old)
            (path/'.cmos.lock').write_bytes(b'held')
            with self.assertRaises(FileExistsError):
                self.profile.save(path,seed,expected_sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual((path/'.cmos.lock').read_bytes(),b'held')
            self.assertEqual(self.profile.load(path),data)
        self.assertFalse(cleanup['exists_after'])

    def test_fsync_or_replace_failure_preserves_old_state_and_cleans_own_temps(self):
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'one';seed=self.profile.prepare(path)
            for operation in ('fsync','replace'):
                with self.subTest(operation=operation),patch.object(self.profile.os,operation,side_effect=OSError('disk failure')):
                    with self.assertRaises(OSError):
                        self.profile.save(path,b'\x01'*16384,expected_sha256=hashlib.sha256(seed).hexdigest())
                self.assertEqual(self.profile.load(path),seed)
                self.assertEqual(sorted(p.name for p in path.iterdir()),['cmos.bin','factory-seed.bin'])
        self.assertFalse(cleanup['exists_after'])

    def test_bad_seed_or_existing_unowned_directory_does_not_initialize(self):
        with quality.scratch_tree() as (scratch,cleanup):
            bad=scratch/'bad-seed';bad.write_bytes(bytes(16384))
            target=scratch/'new'
            with self.assertRaisesRegex(ValueError,'seed'):
                self.profile.prepare(target,seed=bad)
            self.assertFalse(target.exists())
            target.mkdir();(target/'launcher.ini').write_text('[MK1]')
            with self.assertRaises(ValueError):self.profile.prepare(target)
            self.assertEqual([p.name for p in target.iterdir()],['launcher.ini'])
        self.assertFalse(cleanup['exists_after'])

    def test_corrupt_seed_state_and_wrong_save_size_are_not_normalized(self):
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'one';seed=self.profile.prepare(path)
            for size in (0,16383,16385):
                with self.subTest(size=size),self.assertRaises(ValueError):
                    self.profile.save(path,bytes(size),expected_sha256=hashlib.sha256(seed).hexdigest())
            self.assertEqual(self.profile.load(path),seed)
            (path/'cmos.bin').write_bytes(b'broken')
            with self.assertRaises(ValueError):self.profile.prepare(path)
            self.assertEqual((path/'cmos.bin').read_bytes(),b'broken')
            (path/'factory-seed.bin').write_bytes(bytes(16384))
            with self.assertRaises(ValueError):self.profile.load(path)
        self.assertFalse(cleanup['exists_after'])

    def test_junction_is_rejected_without_following_or_writing(self):
        import subprocess
        with quality.scratch_tree() as (scratch,cleanup):
            original=scratch/'original';original.mkdir();alias=scratch/'alias'
            result=subprocess.run(['cmd','/c','mklink','/J',str(alias),str(original)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            try:
                with self.assertRaises(ValueError):self.profile.prepare(alias/'profile')
                self.assertEqual(list(original.iterdir()),[])
            finally:
                alias.rmdir() # Remove only the junction itself; never recurse through it.
        self.assertFalse(cleanup['exists_after'])

    def test_windows_open_file_denies_replace_without_losing_current_cmos(self):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
            wintypes.LPVOID,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'one';seed=self.profile.prepare(path)
            handle=kernel.CreateFileW(str(path/'cmos.bin'),0x80000000,1,None,3,0,None)
            self.assertNotEqual(handle,wintypes.HANDLE(-1).value)
            try:
                with self.assertRaises(PermissionError):
                    self.profile.save(path,b'\x01'*16384,expected_sha256=hashlib.sha256(seed).hexdigest())
                self.assertEqual(self.profile.load(path),seed)
                self.assertEqual(sorted(p.name for p in path.iterdir()),['cmos.bin','factory-seed.bin'])
            finally:kernel.CloseHandle(handle)
        self.assertFalse(cleanup['exists_after'])

    def test_missing_persisted_state_is_not_replaced_with_factory_seed(self):
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'one';self.profile.prepare(path)
            (path/'cmos.bin').unlink()
            with self.assertRaises(FileNotFoundError):self.profile.prepare(path)
            self.assertFalse((path/'cmos.bin').exists())
        self.assertFalse(cleanup['exists_after'])

    def test_failed_initial_state_write_rolls_back_only_new_seed_and_can_retry(self):
        with quality.scratch_tree() as (scratch,cleanup):
            for operation in ('fsync','replace'):
                path=scratch/operation;original=getattr(self.profile.os,operation);calls=0
                def fail_second(*args,**kwargs):
                    nonlocal calls
                    calls+=1
                    if calls==2:raise OSError('initial state write failed')
                    return original(*args,**kwargs)
                with self.subTest(operation=operation),patch.object(self.profile.os,operation,side_effect=fail_second):
                    with self.assertRaises(OSError):self.profile.prepare(path)
                self.assertEqual(list(path.iterdir()),[])
                self.assertEqual(len(self.profile.prepare(path)),16384)
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
