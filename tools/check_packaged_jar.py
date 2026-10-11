from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAR_PATH = ROOT / "build/libs/godwarbridge-1.0.0.jar"
EXPECTED = {
    "com/godwarbridge/GodWarBridge.class",
    "com/godwarbridge/GodWarBridgeClient.class",
    "com/godwarbridge/VehicleMapping.class",
    "fabric.mod.json",
    "assets/godwarbridge/blend_models/pagani_huayra.json",
    "assets/godwarbridge/models3d/pagani_huayra.glb",
}


def main() -> int:
    if not JAR_PATH.is_file():
        raise FileNotFoundError(f"Expected mod JAR not found: {JAR_PATH}")
    with zipfile.ZipFile(JAR_PATH) as jar:
        names = jar.namelist()
        duplicate_names = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicate_names:
            raise ValueError(f"JAR contains duplicate resource names: {duplicate_names}")
        missing = sorted(EXPECTED.difference(names))
        if missing:
            raise ValueError(f"JAR is missing required entries: {missing}")
        descriptor = json.loads(jar.read("assets/godwarbridge/blend_models/pagani_huayra.json"))
        texture_resources = {
            "assets/godwarbridge/" + material["base_color"].split(":", 1)[1]
            for material in descriptor["materials"].values()
        }
        missing_textures = sorted(texture_resources.difference(names))
        if missing_textures:
            raise ValueError(f"JAR is missing model textures: {missing_textures}")
        if not texture_resources:
            raise ValueError("Model descriptor has no external base-color textures")
        if descriptor.get("mesh") != "godwarbridge:models3d/pagani_huayra.glb":
            raise ValueError("JAR model descriptor has an unexpected GLB reference")
        unexpected_absolute_paths = (
            b"C:\\Projects\\GodWarBridge",
            b"D:\\SteamLibrary\\steamapps\\common\\assettocorsa",
        )
        for name in names:
            if name.endswith((".class", ".json")):
                data = jar.read(name)
                if any(path in data for path in unexpected_absolute_paths):
                    raise ValueError(f"JAR entry {name} contains a developer-specific absolute path")
        model_entries = sorted(name for name in names if name.startswith("assets/godwarbridge/"))
    print(f"PASS jar={JAR_PATH.relative_to(ROOT)} model_resources={len(model_entries)} textures={len(texture_resources)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"JAR verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
