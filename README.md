# GodWarBridge

GodWarBridge is a client-side bridge from Assetto Corsa (Windows) to Minecraft Java Edition. A local Python process reads AC's documented shared-memory pages and streams validated newline-delimited JSON over localhost. The Fabric client maps the live AC world position to a calibrated Minecraft anchor and asks BlendLib to render the packaged Pagani Huayra GLB as a local-only entity.

**Status:** the sender, protocol, coordinate mapping, strict-v1 asset conversion, renderer registration, HUD, and client commands are implemented. Automated Python/model checks are available below. A real AC session, Minecraft world render, wheel spin, and Sodium/Iris compatibility have not been tested in this environment. See the test matrix and limitations before using this as a finished game integration.

## Supported target

- Minecraft Java Edition 26.1.2, Java 25.
- Fabric Loader 0.19.5 or newer and Fabric API 0.155.3+26.1.2 or newer for this Minecraft version.
- BlendLib `1.0.0-beta.3+26.1.2` is a required separate mod dependency; install its matching runtime JAR beside GodWarBridge. BlendLib is not shaded into this mod.
- Windows 10/11 for the AC shared-memory sender; Python 3.10+ (standard library only).
- Assetto Corsa (original game), with Shared Memory enabled. ACC is not the target.

## Architecture and data flow

```text
Assetto Corsa 1 shared memory
  Local\\acpmf_physics + Local\\acpmf_graphics
       ↓ Python sender (20 Hz, standard library, bounded NDJSON)
  127.0.0.1:47654 TCP server
       ↓ Minecraft client receiver thread (schema/range validation, reconnect)
  immutable telemetry snapshot → client tick coordinate mapping/interpolation
       ↓
  client-only BridgeCarEntity → BlendLib strict GLB 2.0 entity renderer
```

The sender uses the AC 1 shared-memory structures with four-byte field packing: physics provides speed, RPM, gear, pedals, steering, heading, and a packet counter; graphics provides the AC session state and the player's `carCoordinates`. The shared-memory layout and names are based on the Assetto Corsa shared-memory reference and established direct readers (links in [developer notes](docs/DEVELOPMENT.md)). The sender is local-only by default, creates no external connection, and has no Python package dependencies. It listens before AC is running and reconnects after game/session restarts.

There is one active telemetry protocol: UTF-8 newline-delimited JSON, protocol version `1`, on `127.0.0.1:47654`. The Minecraft client is the TCP client; the Python sender is the TCP server. Frames are limited to 4,096 bytes. Required fields are `protocol_version`, `sender_status`, `connected`, `ac_status`, `speed_kmh`, `rpm`, `gear_raw`, `throttle`, `brake`, `steering`, `heading`, `ac_position` (three coordinates), `physics_packet`, and `telemetry_age_ms`. AC gear values are normalized by subtracting one from the shared-memory value (reverse `-1`, neutral `0`, first `1`). `heading` is in radians; positions are AC world coordinates in metres as exposed by `carCoordinates`.

Bridge status distinguishes a missing sender, an invalid protocol frame, a connected sender waiting for an AC live session, fresh live data, and stale/disconnected telemetry. Frames are validated for types, finite numbers, schema version, field bounds, frame size, freshness, and coordinate envelope before they reach the game tick. Network reads run on a daemon receiver thread, never the render/tick thread. The entity is removed when telemetry is not fresh.

## Coordinate mapping and calibration

The client only maps the car after an explicit calibration, preventing raw AC track coordinates from teleporting it to an arbitrary Minecraft location. In the current mapping, the calibrated AC origin is aligned with the player's Minecraft position:

- `minecraftX = anchorX + (acX - originX) × scale × xSign`
- `minecraftY = anchorY + (acY - originY) × scale`
- `minecraftZ = anchorZ + (acZ - originZ) × scale × zSign`
- `minecraftYaw = wrap(degrees(acHeading) × yawSign + headingOffset)`

The initial signs are `+1`; the AC-to-Minecraft axis signs and yaw convention still require a real-world direction check. `/gwb recenter` anchors the current AC position to the player's location and aligns heading to the player's current yaw. Use `/gwb axis-x -1`, `/gwb axis-z -1`, or `/gwb yaw-sign -1` to flip an axis if the in-game direction check shows it is reversed. `/gwb heading <degrees>` adds an offset. `/gwb map-scale <value>` changes mapped track distance in blocks per AC unit. `/gwb smoothing <factor>` controls tick interpolation (`0.35` default; higher tracks telemetry faster). Coordinate jumps over 64 mapped blocks stop the entity and require recentering instead of accepting a potentially corrupt position.

Mapping and visibility settings currently live for the current Minecraft client session; they are not persisted. A world/dimension change clears the mapping and requires a fresh `/gwb recenter`. The GLB descriptor uses `units_per_block: 1.0`; **map scale affects distance, not the car's geometry size**. To resize the model, change `units_per_block` in its descriptor and reload resources (F3+T); a runtime model-scale command is not implemented.

## Pagani asset pipeline

The source assets are retained under `assets/Cars_Blender/`; the original `.blend` files are not modified. The current conversion starts from the checked-in Blender 5.2.2 GLB export at `assets/GodWarBridgeExport/pagani_huayra.glb`, because Blender is not installed in the build environment. `tools/prepare_pagani_model.py` deterministically:

1. extracts the base-color PNGs actually used by the model;
2. removes embedded image/texture/sampler data and compacts GLB geometry buffer views;
3. removes material extensions rejected by BlendLib's strict loader;
4. maps all 59 named material slots to external PNGs in a strict `blendlib:rigid_v1` descriptor;
5. validates the descriptor, material mapping, geometry attributes, texture references, budgets, and output structure.

The packaged model has 198 meshes, 362 nodes, 132,952 vertices, and 26 unique referenced external PNGs (about 5.5 MB GLB + 8.3 MB PNG). Seven alpha-mask materials remain cutout. Source wheel/tyre node names are recorded in `assets/GodWarBridgeExport/blendlib_conversion_report.json`; those nodes are preserved but not currently animated.

This is a documented, measured conversion, not a claim of full visual equivalence. BlendLib's verified standard 26.1.2 material path uses a base-color PNG rather than full PBR: metallic/roughness lighting and clearcoat/transmission/specular/IOR effects are not reproduced. The original source marked every material double-sided; opaque material slots are configured single-sided because BlendLib rejects opaque double-sided rendering. Blender's original export was not regenerated from a `.blend` in this environment, and the selected source `.blend` identity was not independently confirmed from the export report.

Run the converter (no Blender or Python dependencies required for the existing GLB):

```powershell
py -3.12 tools\prepare_pagani_model.py
py -3.12 tools\prepare_pagani_model.py --verify-only
```

It refuses to replace non-identical generated outputs unless `--force` is supplied. Never target or overwrite the original `.blend` files. BlendLib's format/profile/descriptor behavior is described in its [26.1.2 developer tutorial](https://github.com/LIy-hub/BlendLib-Public/blob/main/docs/release/developer-tutorial-26.1.2.md) and [Blender export checklist](https://github.com/LIy-hub/BlendLib-Public/blob/main/docs/release/blender-export-checklist-v1.md).

## Windows installation and startup

1. Install Minecraft Java 26.1.2 with Java 25, Fabric Loader 0.19.5+, Fabric API 0.155.3+26.1.2, and BlendLib `1.0.0-beta.3+26.1.2` in the same game profile.
2. Enable Assetto Corsa shared memory in AC's settings (General → Enable Shared Memory). Do not edit or replace AC game files.
3. Install Python 3.10+ if needed. No `pip install` step is required; the sender uses only the standard library.
4. From a PowerShell window in the repository root, run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\Start-GodWarBridge.ps1
   ```

   Or run the sender directly:

   ```powershell
   py -3.12 tools\assetto_corsa_sender.py
   ```

   Keep the console open. It shows sender/connect diagnostics; press Ctrl+C to stop cleanly. The sender enforces a single process using a Windows named mutex, binds to localhost, and does not request elevation.
5. Start Minecraft with the mod and enter a world. The HUD should change from “sender not running” to “waiting for AC live session” once the sender connects.
6. Start Assetto Corsa, enter a driving session, and confirm the HUD reports live telemetry.
7. In Minecraft, stand at the desired placement point and run `/gwb recenter`. The Pagani should appear at the calibrated anchor. Drive/turn in AC and check translation and yaw; use the axis-sign and heading commands if directions do not match.
8. Stop and restart the sender with Ctrl+C to verify the HUD reports disconnect/stale data and reconnects when relaunched. The client vehicle is removed during stale/disconnected periods.

The installer/launcher does not edit the AC installation or Minecraft profile. Do not put the mod into a dedicated server to obtain shared multiplayer rendering: this bridge is intentionally client-local and does not synchronize telemetry or the vehicle to other players.

## Client commands

| Command | Effect |
|---|---|
| `/gwb show` / `/gwb hide` | Show or remove the local vehicle representation. |
| `/gwb hud` | Toggle the telemetry HUD. |
| `/gwb recenter` | Set the AC origin to the current AC position and Minecraft anchor to the player's position; requires fresh live AC telemetry. |
| `/gwb map-scale <0.01..16>` | Adjust mapped world distance. |
| `/gwb axis-x <-1..1>` / `/gwb axis-z <-1..1>` | Set AC X/Z direction sign; only `-1` and `1` are accepted. |
| `/gwb yaw-sign <-1..1>` | Set AC heading direction sign; only `-1` and `1` are accepted. |
| `/gwb heading <-3600..3600>` | Set additive yaw offset in degrees. |
| `/gwb smoothing <0.05..1>` | Set interpolation factor (default 0.35). |
| `/gwb debug` | Show receiver/mapping diagnostics in the HUD. |

These are client commands. Servers may define commands with the same root; command precedence is controlled by Fabric/Minecraft command dispatch and can differ between server configurations.

## Build, tests, and CI artifact

On a configured Java 25 machine:

```powershell
.\gradlew.bat compileJava compileClientJava test build
python -m py_compile tools\assetto_corsa_sender.py tools\prepare_pagani_model.py tools\check_packaged_jar.py tests\python\test_assetto_corsa_sender.py
python -m unittest discover -s tests\python -v
python tools\prepare_pagani_model.py --verify-only
python tools\check_packaged_jar.py
```

The GitHub Actions workflow runs those Python/model checks, Gradle `compileJava`, `compileClientJava`, `test`, and `build`, then checks the mod JAR for both initializers, metadata, descriptor, GLB, every referenced PNG, duplicate ZIP names, hardcoded developer paths, and backup files; it also verifies that the sources JAR contains no backup files. Successful workflow runs expose downloadable JARs under the Actions run's **Artifacts** section, named `GodWarBridge-<commit-sha>` (14-day retention). The expected local output is `build/libs/godwarbridge-1.0.0.jar`.

## Verification matrix

| Check | Status |
|---|---|
| Python sender syntax and eight synthetic protocol/shared-memory extraction tests | PASS in the v0 sandbox. |
| Conversion from the existing GLB; external PNGs and strict descriptor/resource validation | PASS in the v0 sandbox. This is structural validation, not a BlendLib runtime load. |
| Java `compileJava`, `compileClientJava`, JUnit coordinate tests, full Gradle build, mod and sources JAR verification, artifact upload | PASS on GitHub Actions for implementation commit `d515a1f` ([run #38113847615](https://github.com/Shreeman-Agarwal/God-of-war-X-asseto-corsa-bridge/actions/runs/38113847615)); uploaded archives were inspected and contain no backup files. |
| Live Assetto Corsa shared-memory reception | NOT RUN; requires the user's Windows AC installation and shared memory. |
| Pagani rendered/moved in a running Minecraft world | NOT RUN; requires Minecraft 26.1.2, the matching Fabric/BlendLib runtime, and a graphics device. |
| Wheel spin, long-session/performance measurements, Sodium/Iris compatibility | NOT RUN. |

## Troubleshooting

- **Sender says shared-memory pages are missing:** start AC and confirm “Enable Shared Memory” is enabled; restart AC after changing that setting. The Python process may remain open while waiting.
- **Minecraft says sender not running:** keep the sender console open; ensure another process is not occupying `127.0.0.1:47654`. The sender defaults to that port and only accepts local addresses.
- **Connected but waiting for AC:** enter a live driving session rather than the main menu, garage, replay, or paused state.
- **Stale data/disconnected:** check the sender console and AC session; close/reopen the sender if AC was restarted. The mod drops the entity rather than leaving it drifting.
- **Car points/moves in the wrong direction:** run `/gwb recenter`, then test `/gwb axis-x -1`, `/gwb axis-z -1`, and `/gwb yaw-sign -1` one at a time. Correct the heading with `/gwb heading <degrees>`.
- **Car appears too far from the player:** recenter, then use `/gwb map-scale <value>`; this changes movement scale, not the model's physical dimensions.
- **BlendLib reports a missing model/material:** use `/blendlib inspect godwarbridge:pagani_huayra` and `/blendlib diagnostics godwarbridge:pagani_huayra`; confirm the matching BlendLib runtime JAR is installed and resource reload completed (F3+T).
- **Collecting logs:** retain the sender console output and Minecraft `logs/latest.log`, then include the current commit SHA and AC/Minecraft versions. Do not upload telemetry to an external service; the bridge is localhost-only.

## Known limitations

- No real AC or Minecraft runtime has been tested here; yaw sign, axis sign, model origin/ground offset, visual fidelity, and actual FPS remain to be checked on the target Windows setup.
- The visual entity exists only in the local client; server-authoritative or multiplayer synchronization is not implemented.
- The supported static BlendLib path does not animate wheels. Source wheel/tyre nodes are retained, but telemetry does not yet rotate them.
- The model conversion preserves geometry, UVs, base-color images, and cutout intent, but loses PBR material effects and changes opaque back-face culling as described above.
- Model scale is adjusted through the descriptor/resource reload rather than a runtime command; mapping scale is command-configurable.
- Blender is not required for the existing-GLB conversion; a fresh export from an original `.blend` and independent source-file provenance check remain outstanding.
- Sodium/Iris rendering compatibility, long-session memory behavior, and performance are not verified.

See [developer notes](docs/DEVELOPMENT.md) for protocol maintenance, model debugging, and test boundaries.
