"""setup.py --verify-only, --progress and --requirements (no ROM needed; the ROM case runs only when roms/mk2 exists)."""
from pathlib import Path
from unittest import mock
import contextlib,hashlib,io,json,sys,tempfile,unittest,zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.setup import paths,setup


def row(name,data):
    return dict(path=name,size=len(data),crc32=f'{zlib.crc32(data)&0xffffffff:08x}',sha1=hashlib.sha1(data).hexdigest(),
                sha256=hashlib.sha256(data).hexdigest())


def quiet(argv):
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):return setup.main(argv)


class ReportTests(unittest.TestCase):
    def test_every_file_is_reported_without_stopping_at_the_first_error(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);roms=temp/'roms';roms.mkdir()
            good,short,changed=b'a'*64,b'b'*64,b'c'*64
            manifest=dict(revision='test',roms=[row('missing.bin',good),row('good.bin',good),row('short.bin',short),
                                                 row('changed.bin',changed)])
            (temp/'manifest.json').write_text(json.dumps(manifest))
            (roms/'good.bin').write_bytes(good);(roms/'short.bin').write_bytes(short[:10])
            (roms/'changed.bin').write_bytes(b'd'+changed[1:])
            with mock.patch.object(paths,'manifest',return_value=temp/'manifest.json'):found=setup.report('mk3',roms)
        self.assertEqual([f['status'] for f in found['files']],['missing','ok','size','crc32'])
        self.assertEqual(found['checks'],['size','crc32','sha1','sha256'])
        self.assertEqual((found['program'],found['ok']),('not checked',False))

    def test_a_folder_with_a_subfolder_per_game_finds_each_game(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);(temp/'manifest.json').write_text(json.dumps(dict(roms=[row('a.bin',b'a'),row('b.bin',b'b')])))
            for sub,names in (('mk3',('a.bin','b.bin')),('mk1',('a.bin',)),('mk',('a.bin','b.bin'))):
                (temp/sub).mkdir()
                for n in names:(temp/sub/n).write_bytes(b'x')
            (temp/'a.bin').write_bytes(b'x')
            with mock.patch.object(paths,'manifest',return_value=temp/'manifest.json'):
                self.assertEqual(setup.locate('mk3',temp),temp/'mk3')        # roms/<game>/ layout
                self.assertEqual(setup.locate('mk1',temp),temp/'mk')         # MAME set name holds more files than mk1/
                self.assertEqual(setup.locate('mk2',temp),temp)              # tie with nothing better: the folder itself
                self.assertEqual(setup.locate('mk3',temp/'mk3'),temp/'mk3')  # the game folder chosen directly

    @unittest.skipUnless((paths.ROOT/'roms/mk2').is_dir(),'needs the staged MK2 ROM files')
    def test_supported_revision_passes_with_the_program_check(self):
        found=setup.report('mk2',paths.ROOT/'roms/mk2')
        self.assertTrue(found['ok'],found);self.assertTrue(all(f['status']=='ok' for f in found['files']))


class ProgressTests(unittest.TestCase):
    def run_setup(self,*extra):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp);(temp/'roms').mkdir();file=temp/'progress.json'
            try:code=quiet(['--game','mk2','--roms',str(temp/'roms'),'--progress',str(file),*extra])
            except (ValueError,SystemExit) as error:code=error
            return code,json.loads(file.read_text('utf-8')),[p.name for p in temp.iterdir()]

    def test_verify_only_reports_and_writes_nothing_else(self):
        code,state,names=self.run_setup('--verify-only')
        self.assertEqual(code,1)
        self.assertEqual((state['mode'],state['state'],state['step'],state['code']),('verify','failed','verify','rom_mismatch'))
        self.assertTrue(all(f['status']=='missing' for f in state['report']['files']))
        self.assertEqual(sorted(names),['progress.json','roms'])   # no .partial left behind

    def test_failed_setup_names_its_step_and_message(self):
        code,state,_=self.run_setup('--no-compile')
        self.assertEqual(code,1)
        self.assertEqual((state['mode'],state['state'],state['step'],state['code']),('setup','failed','verify','rom_mismatch'))
        self.assertEqual(state['message'],'Your ROM files do not match the supported revision.')
        self.assertTrue(state['hint'] and state['detail'])

    def test_units_are_reported_with_the_current_step(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'p.json'
            with mock.patch.dict(setup.PROGRESS,file=file,state=dict(state='running')):
                setup.progress('compile');setup.units(3,9);state=json.loads(file.read_text('utf-8'))
                setup.progress('seed');after=json.loads(file.read_text('utf-8'))
        self.assertEqual((state['step'],state['units']),('compile',dict(done=3,total=9)))
        self.assertEqual((after['step'],after['units']),('seed',None))


class FailureTests(unittest.TestCase):
    """Every failure reaches the launcher as a code, one plain sentence and a hint; raw output only in the log."""
    def failure(self,built,version=setup.VALIDATED_CC):
        with mock.patch.object(setup,'compiler_version',return_value=version),contextlib.redirect_stderr(io.StringIO()) as log:
            error=setup.build_failed(built)
        self.assertIn(built.get('stdout',''),log.getvalue())   # the whole compiler output stays in the log
        for text in (error.message,error.hint):self.assertNotIn('{',text);self.assertNotIn('\n',text)
        return error

    def test_compile_link_timeout_and_disk_full_builds(self):
        compile_out='In file included from x.cpp:1:\nnative/src/a.cpp:12:5: error: unused variable [-Werror]\n'
        e=self.failure(dict(passed=False,exit_code=1,stdout=compile_out,source='a.cpp'),'16.2.0')
        self.assertEqual((e.code,e.detail),('compile_failed','native/src/a.cpp:12:5: error: unused variable [-Werror]'))
        self.assertEqual(e.message,f'The game could not be compiled with g++ 16.2.0 (tested: {setup.VALIDATED_CC}).')
        self.assertTrue(e.hint.startswith('This compiler is not the tested version.'))
        e=self.failure(dict(passed=False,exit_code=1,stdout='a.o: undefined reference to `f\ncollect2: error: ld returned 1 exit status'))
        self.assertEqual((e.code,e.message),('link_failed',f'The game could not be linked with g++ {setup.VALIDATED_CC}.'))
        self.assertEqual(self.failure(dict(passed=False,timed_out=True,stdout='Shared compilation deadline expired')).code,'timed_out')
        self.assertEqual(self.failure(dict(passed=False,stdout='x.s: Fatal error: No space left on device')).code,'disk_full')

    def test_other_exceptions_name_the_step(self):
        self.assertEqual(setup.classify(OSError(28,'No space left on device'),'generate').code,'disk_full')
        e=setup.classify(SystemExit('MK1 factory CMOS failed: trace'),'seed')
        self.assertEqual((e.code,e.message,e.detail),('internal','Something went wrong while creating the factory settings.',
                                                      'MK1 factory CMOS failed: trace'))
        stop=KeyboardInterrupt();self.assertIs(setup.classify(stop,'compile'),stop)
        self.assertIsInstance(setup.classify(SystemExit(0),'compile'),SystemExit)

    def test_setup_builds_drop_warnings_as_errors(self):
        from tools.quality import run as q
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(q,'WARNINGS_AS_ERRORS',False):
            ran=q.command([sys.executable,'-c','import sys;print(sys.argv[1:])','-Werror','-O2'],Path(temp))
        self.assertEqual(ran['stdout'].strip(),"['-O2']")


class InstallTests(unittest.TestCase):
    def test_mk3_reinstall_swaps_the_package_and_keeps_the_player_profile(self):
        import shutil
        from tools.setup import install
        from tools.mk3 import preview_install as package
        from tools.quality import run as q
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'out';out.mkdir();(out/'mk3.exe').write_bytes(b'new build')
            product=root/package.PRODUCT;(product/'profiles/player').mkdir(parents=True)
            (product/'profiles/player/cmos.bin').write_bytes(b'player save');(product/'mk3.exe').write_bytes(b'old build')
            (product/'package.ini').write_text('old');(product/'arcade-bezel.png').write_bytes(b'old neon frame')
            def write_product(exe,where,units):
                fresh=where/package.PRODUCT;(fresh/'profiles/player').mkdir(parents=True);shutil.copy2(exe,fresh/'mk3.exe')
                (fresh/'package.ini').write_text('new');(fresh/'profiles/player/cmos.bin').write_bytes(b'seed')
                return dict(executable_sha256=q.sha(fresh/'mk3.exe'),files=3)
            with mock.patch.object(install,'ROOT',root),mock.patch.object(package,'write_product',write_product):
                found=install.mk3(out)
            self.assertEqual(((product/'mk3.exe').read_bytes(),(product/'package.ini').read_text()),(b'new build','new'))
            self.assertEqual((product/'profiles/player/cmos.bin').read_bytes(),b'player save')
            self.assertFalse((product/'arcade-bezel.png').exists())   # the old frame image is retired
            self.assertEqual([p.name for p in (root/package.STAGE).iterdir()],['product'])   # temporary root removed
            self.assertEqual(found['executable_sha256'],q.sha(out/'mk3.exe'))


class VersionTests(unittest.TestCase):
    def test_setup_launcher_and_recomplauncher_share_the_setup_version(self):
        import re
        root=Path(__file__).resolve().parents[2]
        header=(root/'native/launcher/launcher_setup.hpp').read_text(encoding='utf-8')
        launcher=re.search(r'kSetupVersion="([^"]+)"',header).group(1)
        manifest=json.loads((root/'recomplauncher.json').read_text(encoding='utf-8'))['prepare']['version']
        self.assertEqual((setup.SETUP_VERSION,launcher),(manifest,manifest))


class RequirementsTests(unittest.TestCase):
    def test_missing_compiler_is_reported_not_raised(self):
        from tools.quality import run as q
        with mock.patch.object(q,'DEFAULT_CC',Path('Z:/absent/g++.exe')):found=setup.requirements()
        self.assertEqual((found['compiler']['version'],found['ok']),(None,False))
        self.assertEqual(found['compiler']['validated'],setup.VALIDATED_CC)


if __name__=='__main__':unittest.main()
