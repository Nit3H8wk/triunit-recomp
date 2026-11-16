# MAME sources

TriUnit Recomp distributes unmodified MAME files, all under BSD-3-Clause (each file keeps its `license:` and
`copyright-holders:` header), only where a project tool compiles or reads them:

- `docs/investigation/decoder-research/upstream/` (MAME commit `4f9dcc832cc0089de2451696320f671e87da79f4`, pins in
  `sources.json`, `adsp-sources.json`, `field-sources.json`, `graphics-sources.json` of that folder):
  `34010dsm.cpp/.h` are compiled by the setup into the offline TMS34010 decoder (`tools/setup/decoder.py`); the MK3
  generator reads the opcode table `34010tbl.hxx`; MK2 tests compile the DAC/sound headers and pin the CPU core files
  as reference identities. Notice: `docs/investigation/decoder-research/upstream/LICENSE-BSD-3-Clause.txt`.
- `docs/investigation/sources/` (board drivers and devices of the same revision, `machine.cpp` from tag `mame0280`):
  read by tests as behavioural contracts (video, I/O, protection, DCS). Same license and notice.

MAME files that no tool used were removed; `sources.json` in this folder lists each one by its former repository path,
size and SHA-256 so it can be fetched from the pinned MAME revision and compared.

Parts of the native hardware models were adapted from MAME code under BSD-3-Clause; their headers name the source and
the copyright holders, and `native/audio/LICENSE.txt` carries the notice.
