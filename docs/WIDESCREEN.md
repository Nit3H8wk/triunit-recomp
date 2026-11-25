# Widescreen 16:9 (MK1 and MK2 Remastered)

The Remastered edition of MK1 rev 5.0 and MK2 L3.1 can show a 16:9 picture: the arcade's own 400 columns in the
middle and 67 more on each side. It is purely visual: the game runs exactly as in 4:3. The picture's 400 centre columns
are the arcade frame, bit for bit, except near an arena's ends in a fight, where the wide picture stops at the end of
the arena's art instead of showing black beside it (see *Arena ends* below).

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
- **The centre is the arcade's.** While the wide camera is the arcade's, the arcade's 400 columns come from the real
  frame (MK1: the real draws; MK2: the shadow's draws, checked against the real frame). The HUD stays in screen space,
  centred on those 400 columns, always.

## Arena ends: the limited wide camera

Each arena's art is finite, and the arcade's camera stops when the 4:3 screen reaches its ends. A 16:9 picture centred
on that camera would then show 67 columns past the art on one side. Three things cannot all hold there: a centre always
equal to the arcade frame, full margins, and nothing invented. Up to v0.9.0 the margins gave way (black). Now the
centre does, and only there:

- **The wide camera stops with the art.** In a fight the wide picture's camera is the arcade's, limited to the arena's
  own camera limits moved in by 67 columns. Away from the ends nothing changes. Within 67 camera columns of an end the
  whole world (scenery, fighters, projectiles, blood) is shown up to 67 columns off the centre, and the picture stays
  full. The offset depends on the camera alone: no ramp, no delay, nothing moves while the camera stands still.
- **Far planes stop at their own ends.** A far plane (sky, walls, crowd) scrolls slower than the world and its art can
  end sooner. The plane's ratio to the world is measured from the game's own scroll velocities, and its art's ends are
  measured from its draws on a canvas wider than the screen. The plane then eases into the camera position where its
  art's end meets the wide screen's edge and stays there.
- **Such frames come from the shadow's draws.** In a frame whose wide camera is not the arcade's, the world of the whole
  picture comes from the shadow pass, and the HUD from the real draws. The acceptance tests count these frames apart.
- **After the fight.** The finisher, the round's end and the fade keep the fight's last offset while the camera stays.
- **Free-camera arenas.** An arena without camera limits from its start stays centred.
- **Attract demos.** The attract has one mode word for its demo fights and its other screens. A demo fight is told by
  two things: its camera limits are an arena's (not the ones the game gives a screen without an arena), and the last
  frame's scenery went on past the 4:3 screen (24 columns or more of a margin, on 32 lines or more). Its window then
  follows the camera like a fight's.
- Any other screen stays centred.

## Edge policy (where there is still no art)

Art can still fall short of the edge: a layer narrower than the wide screen, an arena narrower than 534 columns. No
object of the game is mirrored, repeated or stretched there, and no stale video memory is shown.

- A *scenery layer* is one list of the game's display walk (a far plane, the world, the front plane) or, in MK2, one
  callback such as the floor. It is measured on each line where its pixels cover all 400 arcade columns. A side where
  one of the layer's draws reaches past the 534 columns is left as drawn.
- **A line's own pattern goes on.** Past the layer's outermost pixel on a line, the line's last columns are repeated to
  the screen's edge in two cases: most of the layer's short lines on that side (3 in 5) end flat or in a two-column
  dither (a sky's gradient), or they end on one straight edge (9 in 10 at the same column, over 32 lines or more: a
  backdrop picture narrower than the wide screen). All the layer's lines are treated alike. A gap of at most 24 columns
  takes the columns next to it (a floor's texture a few columns on). Only an arena's lines are continued (a fight, or
  a screen with a far plane's picture): a menu's textured background would come out as streaks.
- **Anything else shows black**, unless something nearer (a fighter, a projectile) is drawn there.
- A margin pixel that no draw wrote since its page came plain from video RAM shows black.
- On a line the frame redrew across all 400 arcade columns, a margin pixel the frame did not redraw shows black. This
  stops an older pose of a fighter from staying in the margin.

## Screens without an arena

Menus, story and biography screens, the select screen and the like often draw nothing past the 400 columns: their
backgrounds are single pictures the size of the 4:3 screen, or a little wider. When such a screen leaves its margins
unfilled, both margins get **soft sides**: each margin line takes the average colour of the last 4 columns of the
arcade line beside it, blurred over 10 lines up and down and dimmed from 59% beside the picture to 23% at the screen's
edge. Nothing of the picture is copied, so no object can appear twice. A screen whose draws do fill the margins (a
title, an arena shown outside a fight) keeps them as drawn.

Some pictures are drawn with no display walk at all, straight to the page (a story picture after an attract demo).
After 3 frames without a walk, with something written meanwhile, the pages drop the window the last walk left on them:
the picture is centred and gets soft sides.

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
2. **Centre.** The 400 centre columns equal the arcade frame bit for bit in every frame whose wide camera is the
   arcade's. MK1 compares the presented frames (its wide layer takes the floor stains at presentation, so the raw layer
   alone differs where blood lies). Frames with an offset window or a held far plane are counted apart.
3. **Sentinel.** No fight frame (the game's mode word: the fight, a round's start or end, a finisher) shows a margin
   pixel no draw wrote. Masked pixels are counted, and MK2's replays must reach a scenery layer's edge in a fight
   (the mask at work).
4. **No duplication.** Every margin pixel belongs to a draw meant to cover that column, and no fight frame shows a
   margin pixel older than the frame on a line the frame redrew.
5. **Parallax.** For each scenery layer and each frame where the layer's list camera moved and its centre draws moved by
   minus that amount, the most frequent move of its draws in the margins is the same. A comparison needs at least 3
   draws sharing the move on each side, so objects moving on their own (fighters, flying objects) are not taken for
   scenery.
6. **Still camera.** In MK1, with the camera still, every scenery list's camera is still: a plane's place depends on
   the camera alone.

Continued lines and soft sides are derived from the picture's own edge colours, not drawn by the game; criterion 4
covers the game's draws.

The command also prints the edge coverage table: for each arena (its camera limits) and scenery layer, the fewest
margin columns its art covered and the camera range seen. Replays: MK1 `versus-walls` (both walls of the Courtyard)
and `versus-corner-win` (a fight won near the Courtyard's right end); MK2 `finisher_replays/case00`, `case05` and
`natural-f01-stage-a`.
