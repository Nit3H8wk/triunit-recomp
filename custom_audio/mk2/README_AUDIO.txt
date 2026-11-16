Remastered music slots for this game (optional, your own files)

Slots
  music-01.wav  sound commands 1, 2, 3, 4
  music-02.wav  sound commands 5, 6
  music-03.wav  sound commands 9, 10
  music-04.wav  sound commands 13, 14
  music-05.wav  sound commands 17, 18
  music-06.wav  sound commands 21, 22
  music-07.wav  sound commands 25, 26
  music-08.wav  sound commands 66, 61

Format
  RIFF/WAVE, PCM 16-bit little-endian, 48000 Hz, mono or stereo.
  Any other format, a damaged file or a linked path counts as missing.

Fallback
  A missing or unreadable slot plays the arcade's original music for its commands.
  The Arcade Original edition never reads this folder.

slots.json (optional, same folder; times in seconds)
  {"slots": {"music-01": {"file": "music-01.wav", "begin": 0, "end": 60,
                          "loop": true, "loop_begin": 12, "loop_end": 60, "gain_db": 0}}}
  file        another file name in this folder (no paths); default <slot>.wav
  begin/end   part of the file that plays; default the whole file
  loop        repeat after the end; default true
  loop_begin  start and end of the repeated part; default begin and end
  loop_end
  gain_db     -60 to +24; default 0
  Every command of a slot starts at the slot's begin.
  An invalid slots.json is ignored; an invalid entry leaves only its slot on the original music.
