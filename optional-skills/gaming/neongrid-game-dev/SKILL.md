---
name: neongrid-game-dev
description: "Build and test a tactical roguelite with a Python sim core."
version: 0.1.0
author: Jeffrey Watts (Onyx), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [gaming, tactical-rpg, python, simulation, ue5]
---
# NeonGrid Game Dev Skill

Build, review, and balance a Fire Emblem-style roguelite tactical game: a
Python simulation engine (hex grid, combat, campaign AI) with optional
Unreal Engine rendering fed by a generated-asset pipeline. The skill covers
the full loop — adversarial subsystem review, bug fixing, balance tuning to a
target win rate, and verification runs. It does not ship the game itself; the
project lives in the user's own checkout.

## When to Use

- Building or extending a hex-grid tactical roguelite in Python
- Running adversarial code reviews over game subsystems (combat, grid, engine)
- Tuning combat balance until simulation win rates land in a target band
- Wiring a Python sim's exported game data into a UE rendering pass
- Don't use for: emulator/ROM playback (see `pokemon-player`), Minecraft
  servers, or non-tactical genres

## Prerequisites

- Python 3.11+ and a project checkout with a `sim/` package (`grid.py`,
  `combat.py`, `engine.py`, `campaign.py`) and a `main.py` entry point
- UE 5.x project with Python scripting enabled (rendering pass only; the sim
  core needs no engine)
- No external credentials required

## How to Run

Invoke through the `terminal` tool from the project directory:

```bash
python main.py --demo            # single demo battle
python main.py --simulation 20   # N missions, prints win rate
python main.py --classes         # list unit classes
python main.py --weapons         # list weapons
python main.py --export neongrid_data.json
```

## Procedure

### 1. Adversarial subsystem review

Spawn subagents via `delegate_task`, one per subsystem (combat, grid,
engine/campaign). Each writes a report file; collect all findings and
prioritize by severity. Completion criterion: every modified subsystem has a
review report and every Critical finding has a linked fix.

### 2. Bug fixing

Fix in severity order. The recurring bug classes in this genre:

1. Enemy AI stuck after Turn 1 — end-of-turn cleanup never runs because the
   turn handler mutates game state before the branch that reads it
2. Status effects never expire — durations stored as a list, not a
   name-to-remaining-turns mapping
3. Advantage/weakness matrix is dead code — lookup keyed on the wrong field
   (unit class name instead of damage type)
4. Damage tracking always 0 — `damage_dealt`/`damage_taken` fields never
   written during resolution
5. Double-dipping modifiers — a status applied both in hit-rate and damage
   math
6. Pathfinding from an unwalkable start tile returns a path anyway —
   validate `is_walkable` before searching
7. `place_unit` leaves a stale unit id on the old tile
8. `move_unit` trusts the stored position without bounds validation

### 3. Balance tuning

Adjust player HP multiplier, enemy count scaling, and per-difficulty stat
scaling; cap difficulty growth. Completion criterion: `--simulation 20`
reports a win rate inside the target band (default 40-60%).

### 4. Asset generation (optional)

Generate prompts and a batch script from the game data export, run the
text-to-image → image-to-3D pipeline, then import. Completion criterion: every
unit class in the export has a corresponding asset manifest entry.

### 5. UE integration (optional)

Import assets and build the level from the exported JSON via the engine's
Python scripting entry point. Isometric camera: 35.264° pitch, 45° yaw, hex
grid in axial coordinates. Completion criterion: the level loads with one
blueprint per exported unit class.

## Pitfalls

- `find_path` returning `[]` for start == end is by design and is
  indistinguishable from "no path" — callers must pre-check
- Hex neighbor offsets assume even-r offset coordinates; changing them
  invalidates every neighbor link, re-verify after any grid edit
- Difficulty scaling above the cap makes enemies nearly unbeatable — always
  clamp before tuning stats
- Balance changes to HP multipliers silently change hit-time math; re-run the
  simulation after every tuning edit, never reason about balance in the head

## Verification

```bash
python main.py --simulation 20   # expected: win rate inside target band
python scripts/neongrid_review_checklist.py  # grid bug-fix assertions
```

The checklist script in `scripts/` asserts the eight grid/turn bug classes
above against a fresh `Grid`; run it from the project root so `sim/` is
importable.
