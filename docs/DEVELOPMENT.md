# GodWarBridge developer notes

## Telemetry contract

The sole wire contract is protocol version 1: compact UTF-8 JSON, one object per line, TCP server `127.0.0.1:47654` in `tools/assetto_corsa_sender.py`, and a reconnecting TCP client in the Minecraft client source set. The receiver is deliberately strict: required field types, protocol version, session-state consistency, finite numbers, min/max bounds, three-element `ac_position`, age, and a 4 KiB framing limit are checked before updating the atomic telemetry snapshot.

To add a field:

1. Confirm the field and byte/units from the AC 1 shared-memory reference or SDK header; do not infer ctypes offsets from a viewer or from ACC.
2. Extend the packed `SPageFilePhysics` / `SPageFileGraphic` structure only after checking exact field order/types for AC 1.
3. Add the field to `TelemetrySample`, validate it in `sample_to_payload`, and include it in the v1 sender payload.
4. Add strict validation and a record field on the Java side, then update HUD/consumers.
5. Extend synthetic tests and update the protocol section in the README. If the shape is incompatible, define and version a new schema instead of silently changing v1.

The sender uses AC's `Local\\acpmf_physics` and `Local\\acpmf_graphics` mappings. Its structure definitions use `_pack_ = 4` and derive from the documented AC 1 pages. Position is read from graphics `carCoordinates`; heading, speed, pedals, steering, gear and RPM are read from physics. The physics gear is shifted by one for the conventional `-1` reverse / `0` neutral / positive forward values. No telemetry leaves localhost.

References used during implementation:

- [Assetto Corsa shared-memory reference](https://assettocorsamods.net/threads/doc-shared-memory-reference.58/), AC 1 structure and status definitions.
- [Established AC 1 reader](https://github.com/mdjarv/assettocorsasharedmemory/blob/master/AssettoCorsa.cs), `Local\\acpmf_physics`, `Local\\acpmf_graphics`, and `Local\\acpmf_static` map names.
- [AC shared-memory Python implementation](https://github.com/nasim-raj-laskar/AC-Datalogger/blob/main/src/shared_memory.py), four-byte-packed field order cross-check. The sender does not depend on this code/package.
- Assetto Corsa Competizione has a different interface and is not compatible with these pages.

## Coordinate calibration

`VehicleMapping` is a pure Java helper and is covered by JUnit tests for translation, scale, signs, heading conversion/wrapping, shortest-path angle interpolation, invalid values, and jump bounds. The client intentionally has no default anchor. `/gwb recenter` pairs current AC position and heading with the player's current Minecraft position/yaw. Axis signs and distance scale are configurable for the current client session; settings are not persisted.

Default axis signs and heading sign are provisional. Check them in a disposable local world: anchor the car, drive a short straight line, turn a small amount, then reverse any one sign that is wrong. A jump over 64 mapped blocks sets a recenter-required state; it does not teleport the entity. The current implementation maps AC vertical world position relative to the calibrated player Y. Model-origin and road contact are not automatically inferred or corrected.

Smoothing uses an exponential per-tick interpolation factor and angle deltas are wrapped before blending. Network disconnect marks telemetry offline; the entity is removed rather than continuing to interpolate toward an old target.

## Model conversion and runtime

BlendLib beta.3's 26.1.2 runtime requires its strict GLB 2.0 / external-PNG profile; `.blend` is not a runtime format. The checked-in Pagani GLB was inspected and found to have 198 meshes, 362 nodes, 59 materials, 41 embedded PNG images, and unsupported material extensions. It also names multiple wheel/tyre nodes. The conversion script retains the triangle meshes and UV0, removes unused image/texture buffers from the GLB, externalizes the 26 base-color PNGs used by material slots, and creates the strict descriptor at `assets/godwarbridge/blend_models/pagani_huayra.json`.

The selected renderer is BlendLib's public `BlendEntityRenderer.builder(...).staticRestPose()` path for a registered non-living Fabric entity. The visual entity is created only in the Minecraft client and therefore is not synchronized to other players. BlendLib's entity renderer owns resource lookup, immutable render snapshots, culling bounds, and rendering; the app does not parse GLB or perform socket work on the render thread. The entity type itself is registered in common code, while renderer registration and lifecycle are client-only.

The default strict material resolver for 26.1.2 accepts the chosen single-sided opaque path and cutout path with the runtime's fixed cutoff. It does not reproduce the source's PBR metallic/roughness response, clearcoat, transmission, specular, or IOR effects. The GLB source marked materials double-sided; opaque slots are set single-sided because the verified ordinary opaque path rejects double-sided materials. These are recorded conversion losses, not hidden compatibility assumptions.

To regenerate and structurally verify the conversion:

```powershell
py -3.12 tools\prepare_pagani_model.py
py -3.12 tools\prepare_pagani_model.py --verify-only
```

The converter refuses to replace different outputs unless `--force` is provided. Never point it at an original `.blend` destination. The generated report includes source/output hashes, texture hashes/sizes, node/mesh/material counts, and wheel-node names. A static pass is not proof of runtime load/render. In-game use `/blendlib inspect godwarbridge:pagani_huayra` and `/blendlib diagnostics godwarbridge:pagani_huayra` after resource reload.

For a fresh authoring export from the original `.blend`, use Blender 5.2.2 to re-export GLB, then run the converter on that GLB only after independently confirming input model identity and preserving the original source. The current export report does not establish which of the two repository `.blend` candidates was the GLB's input, so this repository does not claim that provenance as confirmed.

## Debugging and test boundaries

- Sender fails to find AC pages: check AC's General → Enable Shared Memory and the sender's `--physics-map` / `--graphics-map` options.
- TCP is occupied: the sender fails clearly when binding; the default interface is localhost only. Do not change to `0.0.0.0` or expose telemetry to a LAN.
- Receiver rejects a frame: confirm protocol version and exact key types; do not replace missing or malformed position with zero.
- Model missing: verify resource IDs against the descriptor paths, installed BlendLib version, JAR inclusion, and F3+T reload. Check BlendLib diagnostics before changing renderer code.
- Vehicle axis/origin wrong: first verify AC coordinate/heading signs using `/gwb axis-x`, `/gwb axis-z`, `/gwb yaw-sign`, and `/gwb heading`; re-anchor in a test world.
- Renderer crashes only with graphics mods: reproduce without Sodium/Iris first and capture complete Minecraft latest.log plus mod versions. No compatibility claim is made until that matrix is tested.

Automated checks are intentionally separated: Python unit tests use synthetic AC page objects; the model script validates bytes/descriptors/paths; the JAR check validates packaged resources. None launches Assetto Corsa or Minecraft. The current sandbox has no Java runtime or game/GPU, so the Gradle tasks, runtime loader, graphics, performance, reconnect-in-game, and Sodium/Iris checks must be read from the latest GitHub Actions or performed manually on Windows. Keep test reports truthful when adding results.
