"""EBU R128 loudness meter (ffmpeg ebur128) used by the MK2 music checks; PCM stays in memory.

The 15/11/2026 calibration against the former reference recordings is not reproducible any more: those files were
third-party music and left the project (plan 2026-11-15-conformidade-legal.md, Fase 5). Its results remain as
constants: RemasteredMix::original_gain (+14.45 dB) and the default music gain in native/mk2/mk2_music.cpp.
"""
import re,subprocess
import numpy as np


def loudness(stereo,rate):
    result=subprocess.run(['ffmpeg','-hide_banner','-nostats','-f','f32le','-ar',str(rate),
        '-ac','2','-i','-','-af','ebur128=framelog=verbose:peak=true','-f','null','-'],
        input=np.asarray(stereo,dtype='<f4').tobytes(),capture_output=True,check=True,timeout=60)
    summary=result.stderr.decode().split('Summary:')[-1]
    return {key:float(re.search(pattern,summary).group(1))for key,pattern in {
        'lufs':r'I:\s+([-\d.]+) LUFS','true_peak_dbfs':r'Peak:\s+([-\d.]+) dBFS'}.items()}
