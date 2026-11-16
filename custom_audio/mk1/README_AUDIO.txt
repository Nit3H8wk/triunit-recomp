Remastered music slots for this game (optional, your own files)

Slots (sound-board music selector; loops unless noted)
  music-01.wav  selector 19 (plays once)
  music-02.wav  selector 20
  music-03.wav  selector 1
  music-04.wav  selector 3
  music-05.wav  selector 7
  music-06.wav  selector 13
  music-07.wav  selector 25
  music-08.wav  selector 27
  music-09.wav  selector 10
  music-10.wav  selector 21
  music-11.wav  selector 6
  music-12.wav  selector 2
  music-13.wav  selector 31

Format
  RIFF/WAVE, PCM 16-bit little-endian, 48000 Hz, mono or stereo.
  Any other format, a damaged file or a linked path counts as missing.

Fallback
  A missing or unreadable slot plays the arcade's original music for its selector.
  The Arcade Original edition never reads this folder.

slots.json (optional, same folder; times in seconds)
  {"slots": {"music-03": {"file": "music-03.wav", "begin": 0, "end": 60,
                          "loop": true, "loop_begin": 12, "loop_end": 60, "gain_db": 0}}}
  file        another file name in this folder (no paths); default <slot>.wav
  begin/end   part of the file that plays; default the whole file
  loop        repeat after the end; default as listed above
  loop_begin  start and end of the repeated part; default begin and end
  loop_end
  gain_db     -60 to +24; default 0
  An invalid slots.json is ignored; an invalid entry leaves only its slot on the original music.
