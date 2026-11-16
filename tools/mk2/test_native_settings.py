"""Read the existing Launcher INI into the finite MK2 DX12 diagnostic."""
import os
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native
from tools.quality import run as quality


class NativeSettingsTests(unittest.TestCase):
    def settings(self,text):
        self.assertTrue(hasattr(native,'read_settings'),'native diagnostic cannot read Launcher Settings')
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'launcher.ini'
            path.write_text(text,encoding='utf-8')
            result=native.read_settings(path)
        self.assertFalse(cleanup['exists_after'])
        return result

    def test_launcher_profile_maps_visual_settings_without_mame_restrictions(self):
        settings=self.settings('[Launcher]\nFullscreen=0\nFPS=240\nVSync=0\nReducedMotion=1\n'
            '[MK2]\nScanlines=5\nFilter=1\nSync=1\nColor=2\nBrightness=120\n'
            'Bezel=0\nHighRefresh=1\nAudioLatency=2\nRemastered=0\n')
        self.assertEqual(settings['environment'],{
            'MK1_SCALEFX':'0','MK1_SCANLINES':'0','MK1_FILTER':'nearest','MK1_CRT_PRESET':'bvm-4k',
            'MK1_SYNC':'vrr','MK1_COLOR':'warm','MK1_BRIGHTNESS':'120',
            'MK1_BEZEL':'0','MK1_HIGH_REFRESH':'1','MK1_FULLSCREEN':'0','MK1_GAME_VOLUME':'100'})
        self.assertEqual(settings['launcher_only'],{'fps':240,'vsync':0,'reducedmotion':1,'uivolume':0})
        self.assertEqual(settings['audio_latency'],{'requested':'safe','applied':False,'reason':'audio_playback_not_connected'})

    def test_every_launcher_preset_and_legacy_scanline_amount_reaches_presenter(self):
        expected=[('0','off'),('0.25','off'),('0.5','off'),('0.75','off'),
                  ('0','bvm-1080'),('0','bvm-4k'),('0','bvm-soft'),('0','energy'),('0','pvm')]
        for index,(amount,preset) in enumerate(expected):
            with self.subTest(index=index):
                settings=self.settings(f'[MK2]\nScanlines={index}\nFilter=1\n')
                self.assertEqual(settings['environment']['MK1_SCANLINES'],amount)
                self.assertEqual(settings['environment']['MK1_CRT_PRESET'],preset)
                self.assertEqual(settings['environment']['MK1_FILTER'],'linear' if index<4 else 'nearest')

    def test_invalid_or_unimplemented_settings_are_rejected_without_normalisation(self):
        for text in ('[MK2]\nScanlines=9','[MK2]\nSync=3','[MK2]\nBrightness=101',
                     '[MK2]\nAudioLatency=0','[MK2]\nRemastered=2','[MK2]\nHighRefresh=2',
                     '[MK2]\nFilter=1\nfilter=0','[MK1]\nFilter=1',
                     '[MK2]\nBrightness=100\x00','[MK2]\nUnknown=1',
                     '[Launcher]\nFPS=144\n[MK2]\nFilter=0',
                     '[Launcher]\nUIVolume=101\n[MK2]\nFilter=0',
                     '[MK2]\n'+(';'*8192)):
            with self.subTest(text=text[:70]),self.assertRaises(ValueError):
                self.settings(text)

    def test_remastered_profile_selects_stereo_music_and_explicit_product_directory(self):
        settings=self.settings('[MK2]\nRemastered=1\n')
        self.assertEqual(settings['environment']['MK1_MUSIC_MODE'],'remastered')
        self.assertEqual(Path(settings['environment']['MK1_MUSIC_DIRECTORY']),quality.ROOT/'custom_audio/mk2')

    def test_modern_video_sections_follow_the_saved_edition(self):
        ini=('[Video.Remastered]\nScanlines=9\nFilter=3\nScaleFX=1\nScaleFXAmount=37\n'
             'ScaleMode=5\nCAS=40\nBilateral=70\nSMAA=1\nFullscreen=0\n'
             '[Launcher]\nFullscreen=1\n[MK2]\nColor=2\nGameVolume=55\nRemastered={edition}\n'
             '[Video.Original]\nFilter=2\nScaleMode=1\nBrightness=90\n')
        for edition, expected in (
            (0, ('original','off','sharp-bilinear','0','1','0','0','0','1','90','warm','55')),
            (1, ('remastered','phosphor','bicubic','37','5','40','70','1','0','100','warm','55')),
        ):
            with self.subTest(edition=edition):
                env=native.environment(self.settings(ini.format(edition=edition)))
                fields=('MUSIC_MODE','CRT_PRESET','FILTER','SCALEFX','SCALE_MODE','CAS','BILATERAL','SMAA',
                        'FULLSCREEN','BRIGHTNESS','COLOR','GAME_VOLUME')
                self.assertEqual(tuple(env['MK1_'+field] for field in fields),expected)

    def test_modern_video_validates_inactive_profile_too(self):
        for invalid in ('Filter=4','ScaleMode=6','CAS=101','Bilateral=-1','SMAA=2','Fullscreen=2','Brightness=101'):
            with self.subTest(invalid=invalid),self.assertRaisesRegex(ValueError,'outside validated range'):
                self.settings('[MK2]\nRemastered=0\n[Video.Remastered]\n'+invalid+'\n')

    def test_new_launcher_keys_preserve_volume_and_physical_dip_selection(self):
        settings=self.settings('[MK2]\nScanlines=8\nGameVolume=37\nBlood=0\nViolence=1\nCmosCoinage=1\n')
        self.assertEqual(settings['environment']['MK1_GAME_VOLUME'],'37')
        self.assertEqual(settings['environment']['MK1_CRT_PRESET'],'pvm')
        self.assertEqual(settings['dsw_word'],0xbc7d)
        for key,value in (('GameVolume',101),('GameVolume',-1),('Blood',2),('Violence',-1),('CmosCoinage',2)):
            with self.subTest(key=key),self.assertRaises(ValueError):self.settings(f'[MK2]\n{key}={value}\n')

    def test_scalefx_percentage_is_validated_and_reaches_environment(self):
        for amount in (0,1,37,100):
            settings=self.settings(f'[MK2]\nScaleFX=1\nScaleFXAmount={amount}\nFilter=1\n')
            self.assertEqual(settings['environment']['MK1_SCALEFX'],str(amount))
            self.assertEqual(settings['environment']['MK1_FILTER'],'nearest' if amount else 'linear')
        disabled=self.settings('[MK2]\nScaleFX=0\nScaleFXAmount=37\n')
        self.assertEqual(disabled['environment']['MK1_SCALEFX'],'0')
        for key,value in (('ScaleFX',2),('ScaleFXAmount',-1),('ScaleFXAmount',101)):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                self.settings(f'[MK2]\n{key}={value}\n')

    def test_explicit_profile_isolated_from_ambient_visual_and_pacing_overrides(self):
        settings=self.settings('[MK2]\nColor=1\n')
        with patch.dict(os.environ,{'MK1_COLOR':'warm','MK1_CRT_GAIN':'1.3',
                                    'MK1_DIAGNOSTIC_LEGACY_PACING':'1','MK1_GRAPHICS_VALIDATE':'0'}):
            env=native.environment(settings)
        self.assertEqual(env['MK1_COLOR'],'vivid')
        self.assertEqual(env['MK1_GRAPHICS_VALIDATE'],'1')
        self.assertNotIn('MK1_CRT_GAIN',env)
        self.assertNotIn('MK1_DIAGNOSTIC_LEGACY_PACING',env)

    def test_profile_requires_window_before_rom_loading_or_building(self):
        result=native.run(quality.ROOT/'missing-roms',settings=quality.ROOT/'unused-settings.ini')
        self.assertFalse(result['passed'])
        self.assertIn('Settings requires --window',result['error'])
        self.assertNotIn('build',result)

    def test_audio_requires_window_before_rom_loading_or_building(self):
        result=native.run(quality.ROOT/'missing-roms',audio=True)
        self.assertFalse(result['passed'])
        self.assertIn('Audio playback requires --window',result['error'])
        self.assertNotIn('build',result)

    def test_audio_events_are_preserved_and_unknown_runtime_output_is_rejected(self):
        observed={'scope':'mk2-native-first-draw-check','audio_playback':True,'audio':{'underruns':1}}
        event={'audio_underrun_sample':3840,'producer_gap_ms':125}
        text=json.dumps(event)+'\n'+json.dumps(observed)+'\n'
        self.assertEqual(native.diagnostic_output(text),(observed,[event]))
        for invalid in ('unexpected\n'+json.dumps(observed),json.dumps(observed),
                        json.dumps({'audio_underrun_sample':-1,'producer_gap_ms':0})+'\n'+json.dumps(observed),
                        text+json.dumps(observed)):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                native.diagnostic_output(invalid)


class NativeSettingsGpuTests(unittest.TestCase):
    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir() and quality.DEFAULT_CC.is_file(),
                         'requires authenticated MK2 ROMs, compiler and DX12')
    def test_real_profile_reaches_dx12_and_declares_finite_execution(self):
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'launcher.ini'
            path.write_text('[Launcher]\nFullscreen=0\n[MK2]\nScanlines=5\nFilter=1\n'
                            'Sync=1\nColor=2\nBrightness=120\nBezel=0\nHighRefresh=1\n',encoding='utf-8')
            before=quality.sha(path)
            receipt=native.run(quality.ROOT/'roms/mk2',window=True,settings=path)
            self.assertTrue(receipt['passed'],{key:receipt.get(key) for key in ('error','execution','build')})
            self.assertEqual(before,quality.sha(path),'diagnostic must not mutate Launcher profile')
            observed=receipt['native']
            self.assertEqual(observed.get('termination'),'finite_diagnostic_complete')
            self.assertEqual(observed.get('frontier_pc'),0xff80dd30)
            self.assertIs(observed.get('execution_continues'),False)
            self.assertFalse(observed['audio_playback'])
            self.assertFalse(observed['presentation']['vrr_driver_monitor_verified'])
        self.assertFalse(cleanup['exists_after'])

    @unittest.skipUnless((quality.ROOT/'roms/mk2').is_dir() and quality.DEFAULT_CC.is_file(),
                         'requires authenticated MK2 ROMs, compiler, DX12 and Windows PCM')
    def test_audio_uses_original_timeline_and_shared_sink_without_changing_game_state(self):
        with quality.scratch_tree() as (scratch,cleanup):
            path=scratch/'launcher.ini'
            path.write_text('[Launcher]\nFullscreen=0\n[MK2]\nScanlines=0\nAudioLatency=1\n',encoding='utf-8')
            before=quality.sha(path)
            configured=native.run(quality.ROOT/'roms/mk2',window=True,settings=path,audio=True)
            self.assertTrue(configured['passed'],{key:configured.get(key) for key in ('error','execution','build')})
            control=native.run(quality.ROOT/'roms/mk2')
            self.assertTrue(control['passed'],control.get('error'))
            self.assertEqual(before,quality.sha(path))
            observed=configured['native'];plain=control['native']
            self.assertEqual(observed['cpu34'],plain['cpu34'])
            self.assertEqual(observed['frame_sha256'],plain['frame_sha256'])
            self.assertTrue(observed['audio_playback'])
            audio=observed['audio']
            self.assertEqual((audio['source_rate'],audio['output_rate'],audio['channels']),(31250,48000,1))
            self.assertEqual(audio['submitted'],audio['completed'])
            self.assertEqual(audio['submitted'],audio['output_samples'])
            self.assertGreaterEqual(audio['submitted'],9601)
            self.assertEqual(audio['underruns'],0)
            self.assertEqual((audio['queue_capacity_ms'],audio['startup_reserve_ms']),(100,80))
            self.assertTrue(configured['settings']['audio_latency']['applied'])
            self.assertFalse(plain['audio_playback'])
            self.assertIsNone(plain['audio'])
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
