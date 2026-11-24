# Widescreen 16:9 (MK1 and MK2 Remastered)

The Remastered edition of MK1 rev 5.0 and MK2 L3.1 can show a 16:9 picture: the arcade's own 400 columns in the
middle and 67 more on each side. It is purely visual. The game runs exactly as in 4:3, and the picture's 400 centre
columns are the arcade frame, bit for bit.

## Turning it on

In the launcher, **Video → Remastered → SCREEN → Widescreen** (MK1 and MK2 only). The launcher starts the game with
`MK1_WIDESCREEN=1` or `MK2_WIDESCREEN=1`. Without it, or in the Original edition, the game shows the arcade's 4:3 frame,
which is also the safe fallback. Widescreen leaves out the TV frame. The CRT and Phosphor filters work at the new width
and keep whole scanlines.

## How the margins are made

- **Width.** The arcade shows 400×254 pixels on a 4:3 screen. A 16:9 screen holds 400 × (16/9) ÷ (4/3) = 533.3 of those
  pixels, so the picture is 534 columns: 400 + 67 + 67. The pixel's shape does not change.
- **The game's own draws.** Once per frame a *shadow pass* runs the frame's display-list walk again with the game's
  clip widened to the 16:9 window, plus 112 columns on each side. It uses the code the setup generated from your ROM,
  runs on a journal of RAM that is undone afterwards, and spends no cycles. The game's objects (scenery blocks,
  fighters, projectiles, blood) are built and drawn there at the x the game gives them, with each layer's own parallax
  scroll. The game's culling and scenery streamer run with the wider clip, so objects just outside the 4:3 screen are
  drawn too.
- **No wraparound.** The margins live in a layer 534 columns wide, separate from the board's 512-column video RAM. A
  draw at x = −40 lands in the left margin, never on the other side. Samplers in the D3D12 presentation clamp; none wraps.
- **The centre is the arcade's.** The arcade's 400 columns come from the real frame (MK1: the real draws; MK2: the
  shadow's draws, checked against the real frame). The HUD stays in screen space, centred on those 400 columns.

## Edge policy (where there is no art)

Each arena's art is finite, and the arcade's camera stops before showing its ends. With 67 more columns on each side,
the margins can reach past the art near an arena's ends. Nothing is invented there: no mirroring, repeating, stretching
or stale video memory.

- A *scenery layer* is one list of the game's display walk (a far plane, the world, the front plane) or, in MK2, one
  callback such as the floor. On each line where a layer's pixels cover all 400 arcade columns, the margin columns past
  the layer's outermost pixel on that line show **black**, unless something nearer (a fighter, a projectile) is drawn
  there. A side where one of the layer's draws reaches past the 534 columns is left as drawn.
- A margin pixel that no draw wrote since its page came plain from video RAM shows black.
- On a line the frame redrew across all 400 arcade columns, a margin pixel the frame did not redraw shows black. This
  stops an older pose of a fighter from staying in the margin.
- Screens without an arena (menus, story, select) show only what their draws put in the margins. The rest is the page's
  clear colour or black.

A separate render camera clamped to the art (keeping the margins full at the ends) was rejected: it moves the 400 centre
columns away from the arcade frame.

## Debug mode

Set `TRIUNIT_WIDE_DEBUG=1` before the game starts. Each margin pixel then records which draw wrote it, the kind of
write and the columns the draw meant to cover (from the game's own x, before the board's 10-bit wrap). A margin pixel
no draw wrote shows magenta instead of black. Each shown frame gets a margin audit (`mk5wide::Audit`): sentinel,
masked, outside (a pixel its draw never meant to cover), generated (written by no draw of the game) and stale pixels.
The layer also keeps each build's scenery draws (`notes_done`) and measured layers (`bands_done`) for the parallax check
and the coverage table.

## Acceptance tests

```powershell
python tools/widescreen/acceptance.py
```

The command needs the ROMs and the setup's generated code for both games. `--game mk1` or `--game mk2` runs one game.
`--all` adds the long replays (MK1 `campaign-prefix`, MK2's full campaign, which visits every arena). Each legal replay
runs without and with widescreen, and the command checks:

1. **Same game in every frame.** MK1 compares CPU, cycles, RAM, VRAM and palette per frame. MK2 compares VRAM and
   palette per frame, and RAM, CPU and cycles at every live chunk (about 17 frames). Shown frames, PCM and CMOS must
   also match.
2. **Centre.** The 400 centre columns equal the arcade frame bit for bit in every frame. MK1 compares the presented
   frames (its wide layer takes the floor stains at presentation, so the raw layer alone differs where blood lies).
3. **Sentinel.** No fight frame (the game's mode word: the fight, a round's start or end, a finisher) shows a margin
   pixel no draw wrote. Masked pixels are counted, and MK2's replays must reach a scenery layer's edge in a fight
   (the mask at work).
4. **No duplication.** Every margin pixel belongs to a draw meant to cover that column, and no fight frame shows a
   margin pixel older than the frame on a line the frame redrew.
5. **Parallax.** For each scenery layer and each frame where the layer's list camera moved and its centre draws moved by
   minus that amount, the most frequent move of its draws in the margins is the same. A comparison needs at least 3
   draws sharing the move on each side, so objects moving on their own (fighters, flying objects) are not taken for
   scenery.

The command also prints the edge coverage table: for each arena (its camera limits) and scenery layer, the fewest
margin columns its art covered and the camera range seen. Replays: MK1 `versus-walls` (both walls of the Courtyard)
and `versus-corner-win` (a fight won near the Courtyard's right end); MK2 `finisher_replays/case00`, `case05` and
`natural-f01-stage-a`.
