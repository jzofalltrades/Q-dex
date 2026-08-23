# Q-dex — CAD Files

3D-printable enclosure for the Q-dex handheld Pokédex, designed in Autodesk Fusion 360.

## Files

| File | Purpose |
|------|---------|
| `STL/` | Ready-to-print meshes — load straight into your slicer. |
| `pokedexV4.step` | Editable, software-neutral CAD — open and modify in any CAD program. |
| `pokedexV4.f3d` | Original Fusion 360 project with full design history. |

## Parts (STL folder)

**Main body & lid**
- `LeftTub.stl` — main front body; holds the display, ESP32 keypad and buttons
- `BackPlate.stl` — back panel; mounts the Arduino UNO Q (brass-insert bosses)
- `RightLid.stl` — the right-hand lid of the clamshell
- `LidFacePlate.stl` — face plate for the lid
- `ScreenBezel.stl` — frames the 2.8" display
- `LCDCrossPlate.stl` — internal display support plate

**Buttons & caps**
- `Cap_DPad.stl` — one-piece D-pad cross cap
- `Cap_btn9.stl`, `Cap_Select.stl`, `Cap_Back.stl` — action-button caps
- `Cap_pillA.stl`, `Cap_pillB.stl` — pill-shaped button caps

**Lens**
- `Dome_Ring.stl` — ring that holds the clear dome lens (print the lens itself in clear PETG)

**Right-panel dummy inserts** (cosmetic, non-functional — they fill the decorative right panel)
- `DummyBtn_Mute_rightpanel.stl`, `DummyKey_rightpanel_x10.stl`, `DummyPill_rightpanel_x2.stl`,
  `Dummy_Screen_Right panel.stl`, `Dummy_bottom_rectangle_rightpanel_x2.stl`,
  `Dummy_bottomsquare_x2_rightpanel.stl`

## Print settings

- **Material:** PLA for every part **except** the dome lens, printed in **clear PETG** so the WS2812 lens LED shines through.
- **Layer height:** 0.20 mm for all parts.
- **Total print time:** approximately 25+ hours across the full set.
- **Hinge:** printed-in — there is no separate metal hinge pin.
- **Inserts / screws:** M2 and M3 brass heat-set inserts; screws M2×3 / M2×6 / M2×8 to match.

Print one button cap and its matching hole first as a quick fit test before committing to the long shell prints.

## Assembly

See the full build guide at **https://jzofalltrades.github.io/Q-dex/** (Phase 4 — Print & Assembly) and the interactive 3D model at **https://jzofalltrades.github.io/Q-dex/viewer.html**.
