import bpy
import os
import re
import csv
import glob
import traceback

SOURCE = r"D:\SteamLibrary\steamapps\common\assettocorsa\content\cars"
ASSETS = r"C:\Projects\GodWarBridge\assets"
OUTPUT = os.path.join(ASSETS, "Cars_Blender")
LOG = os.path.join(OUTPUT, "batch_import_log.csv")
ADDON_DIR = os.path.join(
    os.environ.get("APPDATA", ""),
    "Blender Foundation", "Blender", "5.2",
    "extensions", "blender_org", "kn5_blender_tools"
)

os.makedirs(OUTPUT, exist_ok=True)

def importer_available():
    if hasattr(bpy.ops.import_scene, "assetto_corsa_kn5"):
        return True

    # Try enabling the installed extension/add-on under common module names.
    for module in (
        "bl_ext.blender_org.kn5_blender_tools",
        "kn5_blender_tools",
        "kn5_blender_tools.addon",
    ):
        try:
            bpy.ops.preferences.addon_enable(module=module)
        except Exception:
            pass
        if hasattr(bpy.ops.import_scene, "assetto_corsa_kn5"):
            return True

    # Report the installation location if Blender cannot register the importer.
    print("KN5 importer operator was not registered.")
    print("Expected extension folder:", ADDON_DIR)
    if os.path.isdir(ADDON_DIR):
        for root, dirs, files in os.walk(ADDON_DIR):
            for name in files:
                if name in ("blender_manifest.toml", "__init__.py", "addon.py"):
                    print("Found:", os.path.join(root, name))
    return False

def clean_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    # Remove unused data blocks between cars to reduce file cross-contamination.
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                       bpy.data.cameras, bpy.data.lights):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

def find_main_kn5(car_dir):
    files = []
    for root, dirs, names in os.walk(car_dir):
        dirs[:] = [d for d in dirs if d.lower() not in
                   ("__pycache__", ".git")]
        for name in names:
            if name.lower().endswith(".kn5"):
                files.append(os.path.join(root, name))

    if not files:
        return None

    car_name = os.path.basename(os.path.normpath(car_dir)).lower()
    exact = [
        f for f in files
        if os.path.splitext(os.path.basename(f))[0].lower() == car_name
    ]
    if exact:
        return max(exact, key=os.path.getsize)

    excluded = ("lod", "collider", "shadow", "driver", "tyre",
                "tire", "wheel", "damage")
    candidates = [
        f for f in files
        if not any(word in os.path.basename(f).lower() for word in excluded)
    ]
    if not candidates:
        return None

    return max(candidates, key=os.path.getsize)

def safe_name(name):
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return name or "unnamed_car"

def main():
    if not os.path.isdir(SOURCE):
        raise RuntimeError("Assetto Corsa source folder missing: " + SOURCE)

    if not importer_available():
        raise RuntimeError(
            "Blender cannot find import_scene.assetto_corsa_kn5. "
            "Enable the installed KN5 Tools extension in Blender, then rerun."
        )

    cars = sorted(
        (os.path.join(SOURCE, d) for d in os.listdir(SOURCE)
         if os.path.isdir(os.path.join(SOURCE, d))),
        key=str.lower
    )

    rows = []
    total = len(cars)
    print("Found", total, "car folders.")
    print("Output:", OUTPUT)

    for index, car_dir in enumerate(cars, 1):
        car_id = os.path.basename(car_dir)
        target = os.path.join(OUTPUT, safe_name(car_id) + ".blend")
        print(f"\n[{index}/{total}] {car_id}")

        # Preserve the existing F40 work; don't create another F40 blend.
        if car_id.lower() == "ferrari_f40" and os.path.isfile(
            os.path.join(ASSETS, "Ferrari_F40_Working.blend")
        ):
            print("Skipping: existing Ferrari F40 project preserved.")
            rows.append([car_id, "", target, "SKIPPED_EXISTING_F40", ""])
            continue

        if os.path.isfile(target):
            print("Skipping: output already exists.")
            rows.append([car_id, "", target, "SKIPPED_OUTPUT_EXISTS", ""])
            continue

        kn5 = find_main_kn5(car_dir)
        if not kn5:
            print("No suitable main KN5 found.")
            rows.append([car_id, "", target, "NO_MAIN_KN5", ""])
            continue

        try:
            clean_scene()
            bpy.ops.import_scene.assetto_corsa_kn5(filepath=kn5)

            # Give imported objects a clear car-specific collection.
            collection = bpy.data.collections.new(car_id)
            bpy.context.scene.collection.children.link(collection)
            for obj in list(bpy.context.scene.objects):
                for old_collection in list(obj.users_collection):
                    old_collection.objects.unlink(obj)
                collection.objects.link(obj)

            bpy.ops.wm.save_as_mainfile(filepath=target)
            print("Saved:", target)
            rows.append([car_id, kn5, target, "SUCCESS", ""])

        except Exception as exc:
            message = str(exc).replace("\n", " ")[:1000]
            print("FAILED:", message)
            traceback.print_exc()
            rows.append([car_id, kn5, target, "FAILED", message])
            try:
                clean_scene()
            except Exception:
                pass

    with open(LOG, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["car_folder", "source_kn5", "output_blend",
                         "status", "error"])
        writer.writerows(rows)

    counts = {}
    for row in rows:
        counts[row[3]] = counts.get(row[3], 0) + 1

    print("\n===== BATCH COMPLETE =====")
    print("Car folders:", total)
    for status, count in sorted(counts.items()):
        print(status + ":", count)
    print("Log:", LOG)

main()
