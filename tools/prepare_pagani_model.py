from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/GodWarBridgeExport/pagani_huayra.glb"
RESOURCE_ROOT = ROOT / "src/main/resources/assets/godwarbridge"
MODEL_KEY = "godwarbridge:pagani_huayra"
MODEL_PATH = RESOURCE_ROOT / "models3d/pagani_huayra.glb"
DESCRIPTOR_PATH = RESOURCE_ROOT / "blend_models/pagani_huayra.json"
TEXTURE_ROOT = RESOURCE_ROOT / "textures/blendlib"
REPORT_PATH = ROOT / "assets/GodWarBridgeExport/blendlib_conversion_report.json"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942


def read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    if len(raw) < 20:
        raise ValueError(f"{path} is too short to be a GLB")
    magic, version, declared_size = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2 or declared_size != len(raw):
        raise ValueError(f"{path} is not a complete GLB 2.0 file")
    cursor = 12
    document: dict[str, Any] | None = None
    binary: bytes | None = None
    while cursor < len(raw):
        if cursor + 8 > len(raw):
            raise ValueError("Truncated GLB chunk header")
        length, kind = struct.unpack_from("<II", raw, cursor)
        cursor += 8
        end = cursor + length
        if end > len(raw):
            raise ValueError("GLB chunk length exceeds the file boundary")
        chunk = raw[cursor:end]
        cursor = end
        if kind == CHUNK_JSON:
            if document is not None:
                raise ValueError("GLB contains duplicate JSON chunks")
            document = json.loads(chunk.rstrip(b" \t\r\n\0"))
        elif kind == CHUNK_BIN:
            if binary is not None:
                raise ValueError("GLB contains duplicate binary chunks")
            binary = chunk
    if document is None or binary is None:
        raise ValueError("GLB requires JSON and BIN chunks")
    if document.get("asset", {}).get("version") != "2.0":
        raise ValueError("GLB asset.version must be 2.0")
    return document, binary


def encode_glb(document: dict[str, Any], binary: bytes) -> bytes:
    document["buffers"] = [{"byteLength": len(binary)}]
    json_chunk = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    padded_binary = binary + b"\0" * ((-len(binary)) % 4)
    total = 12 + 8 + len(json_chunk) + 8 + len(padded_binary)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(json_chunk), CHUNK_JSON) + json_chunk + struct.pack("<II", len(padded_binary), CHUNK_BIN) + padded_binary


def png_rgba(rgba: tuple[int, int, int, int]) -> bytes:
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    red, green, blue, alpha = rgba
    pixel = bytes((red, green, blue, alpha))
    return PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\0" + pixel)) + chunk(b"IEND", b"")


def safe_name(name: str) -> str:
    result = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    return result or "material"


def make_assets(source: Path) -> tuple[bytes, dict[str, bytes], dict[str, Any], dict[str, Any]]:
    document, source_binary = read_glb(source)
    images = document.get("images", [])
    old_views = document.get("bufferViews", [])
    image_view_ids: set[int] = set()
    image_pngs: dict[int, bytes] = {}
    for index, image in enumerate(images):
        if "uri" in image:
            raise ValueError("External or data-URI source images are not supported by this repeatable converter")
        view_id = image.get("bufferView")
        if not isinstance(view_id, int) or view_id < 0 or view_id >= len(old_views):
            raise ValueError(f"Image {index} has no valid embedded bufferView")
        if image.get("mimeType") != "image/png":
            raise ValueError(f"Image {index} is not PNG; converting it would require a verified image tool")
        view = old_views[view_id]
        if view.get("buffer", 0) != 0:
            raise ValueError(f"Image {index} references an unsupported buffer")
        start = view.get("byteOffset", 0)
        end = start + view["byteLength"]
        data = source_binary[start:end]
        if not data.startswith(PNG_SIGNATURE):
            raise ValueError(f"Image {index} bufferView is not PNG data")
        image_view_ids.add(view_id)
        image_pngs[index] = data

    old_textures = document.get("textures", [])
    material_table = document.get("materials", [])
    if not material_table:
        raise ValueError("Source GLB has no named material slots")
    material_names = [material.get("name") for material in material_table]
    if any(not isinstance(name, str) or not name.strip() for name in material_names):
        raise ValueError("Every source GLB material must have a non-empty name")
    if len(set(material_names)) != len(material_names):
        raise ValueError("Source GLB material names must be unique")

    external_textures: dict[str, bytes] = {}
    descriptor_materials: dict[str, dict[str, Any]] = {}
    texture_path_by_image: dict[int, str] = {}
    for material in material_table:
        name = material["name"]
        pbr = material.get("pbrMetallicRoughness", {})
        base_texture = pbr.get("baseColorTexture")
        if not isinstance(base_texture, dict) or "index" not in base_texture:
            raise ValueError(f"Material {name!r} has no base-color image; refusing a fabricated fallback")
        if base_texture.get("extensions"):
            raise ValueError(f"Material {name!r} uses a base-color texture transform that this converter cannot bake")
        texture_index = base_texture["index"]
        if not isinstance(texture_index, int) or not 0 <= texture_index < len(old_textures):
            raise ValueError(f"Material {name!r} has an invalid base-color texture index")
        texture = old_textures[texture_index]
        image_index = texture.get("source")
        if not isinstance(image_index, int) or image_index not in image_pngs:
            raise ValueError(f"Material {name!r} has no supported embedded base-color PNG")
        if image_index not in texture_path_by_image:
            relative = f"textures/blendlib/pagani_huayra__texture_{image_index:03d}.png"
            texture_path_by_image[image_index] = relative
            external_textures[relative] = image_pngs[image_index]
        if "baseColorFactor" in pbr and pbr["baseColorFactor"] != [1, 1, 1, 1]:
            raise ValueError(f"Material {name!r} has a non-white baseColorFactor that must be baked into its PNG")
        if "metallicRoughnessTexture" in pbr:
            raise ValueError(f"Material {name!r} uses an unsupported metallic/roughness texture")
        alpha_mode = material.get("alphaMode", "OPAQUE")
        if alpha_mode not in ("OPAQUE", "MASK"):
            raise ValueError(f"Material {name!r} uses unsupported alpha mode {alpha_mode!r}")
        material_mode = "cutout" if alpha_mode == "MASK" else "opaque"
        definition: dict[str, Any] = {
            "base_color": f"godwarbridge:{texture_path_by_image[image_index]}",
            "mode": material_mode,
            "emissive": any(float(component) > 0 for component in material.get("emissiveFactor", [])),
            # BlendLib's 26.1.2 ordinary opaque layer has no verified double-sided path.
            "double_sided": bool(material.get("doubleSided", False)) if material_mode == "cutout" else False,
        }
        descriptor_materials[name] = definition
        material.pop("extensions", None)
        pbr.pop("baseColorTexture", None)
        pbr.pop("metallicRoughnessTexture", None)

    # Compact the GLB buffer after removing image views; all remaining view offsets are rewritten.
    remap: dict[int, int] = {}
    compact = bytearray()
    new_views: list[dict[str, Any]] = []
    for old_id, view in enumerate(old_views):
        if old_id in image_view_ids:
            continue
        if view.get("buffer", 0) != 0:
            raise ValueError(f"bufferView {old_id} references an unsupported buffer")
        old_offset = view.get("byteOffset", 0)
        length = view.get("byteLength")
        if not isinstance(length, int) or length < 0 or old_offset < 0 or old_offset + length > len(source_binary):
            raise ValueError(f"bufferView {old_id} has an invalid byte range")
        compact.extend(b"\0" * ((-len(compact)) % 4))
        new_view = dict(view)
        new_view.pop("buffer", None)
        new_view["byteOffset"] = len(compact)
        remap[old_id] = len(new_views)
        compact.extend(source_binary[old_offset:old_offset + length])
        new_views.append(new_view)
    for accessor in document.get("accessors", []):
        if "bufferView" in accessor:
            old_id = accessor["bufferView"]
            if old_id not in remap:
                raise ValueError("An accessor references an image bufferView")
            accessor["bufferView"] = remap[old_id]
        if "sparse" in accessor:
            raise ValueError("Strict BlendLib v1 does not support sparse accessors")
    document["bufferViews"] = new_views
    document.pop("images", None)
    document.pop("textures", None)
    document.pop("samplers", None)
    document.pop("extensionsUsed", None)
    document.pop("extensionsRequired", None)

    for mesh in document.get("meshes", []):
        if "weights" in mesh:
            raise ValueError("Strict BlendLib v1 does not support morph weights")
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4:
                raise ValueError("Strict BlendLib v1 only supports triangle primitives")
            attributes = primitive.get("attributes", {})
            if set(attributes) != {"POSITION", "NORMAL", "TEXCOORD_0"}:
                raise ValueError(f"Unsupported GLB vertex attributes: {sorted(attributes)}")
            if "targets" in primitive or primitive.get("extensions"):
                raise ValueError("Strict BlendLib v1 does not support morph targets or primitive extensions")
    for accessor in document.get("accessors", []):
        if "sparse" in accessor:
            raise ValueError("Strict BlendLib v1 does not support sparse accessors")
    descriptor = {
        "format_version": 1,
        "profile": "blendlib:rigid_v1",
        "mesh": "godwarbridge:models3d/pagani_huayra.glb",
        "units_per_block": 1.0,
        "materials": descriptor_materials,
    }
    converted = encode_glb(document, bytes(compact))
    try:
        source_label = source.relative_to(ROOT).as_posix()
    except ValueError:
        source_label = source.name
    position_accessors = []
    triangle_count = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            position_accessors.append(primitive["attributes"]["POSITION"])
            triangle_count += document["accessors"][primitive["indices"]]["count"] // 3
    wheel_nodes = sorted({
        node["name"] for node in document.get("nodes", [])
        if isinstance(node.get("name"), str)
        and any(part in node["name"].lower() for part in ("wheel", "tyre", "tire"))
    })
    report = {
        "source": source_label,
        "source_material_extensions": sorted({
            extension
            for material in read_glb(source)[0].get("materials", [])
            for extension in material.get("extensions", {})
        }),
        "mesh_names": [mesh.get("name") for mesh in document.get("meshes", [])],
        "wheel_or_tyre_nodes": wheel_nodes,
        "geometry": {
            "nodes": len(document.get("nodes", [])),
            "meshes": len(document.get("meshes", [])),
            "vertices": sum(document["accessors"][index]["count"] for index in position_accessors),
            "triangles": triangle_count,
        },
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "runtime_format": "GLB 2.0 strict blendlib:rigid_v1; external PNG base-color images",
        "coordinate_assumption": "Blender +Z up / -Y forward; scale 1 Blender unit per block; axis mapping to Minecraft is the exporter boundary.",
        "losses": [
            "BlendLib's standard material path consumes a base-color PNG and does not reproduce Metallic/Roughness PBR response.",
            "Opaque materials are made single-sided because the verified 26.1.2 opaque double-sided path is unsupported.",
            "KHR_materials_clearcoat, KHR_materials_transmission, KHR_materials_specular, and KHR_materials_ior are removed; the runtime rejects material extensions.",
        ],
        "source_materials": len(material_table),
        "external_pngs": len(external_textures),
        "source_images": len(images),
        "source_image_bytes": sum(len(value) for value in image_pngs.values()),
        "converted_glb_bytes": len(converted),
        "converted_glb_sha256": hashlib.sha256(converted).hexdigest(),
        "textures": {
            relative: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for relative, data in sorted(external_textures.items())
        },
        "material_modes": {
            "cutout": sum(item["mode"] == "cutout" for item in descriptor_materials.values()),
            "opaque": sum(item["mode"] == "opaque" for item in descriptor_materials.values()),
        },
    }
    return converted, external_textures, descriptor, report


def validate_packaged_assets() -> dict[str, Any]:
    glb, binary = read_glb(MODEL_PATH)
    descriptor = json.loads(DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    if descriptor.get("format_version") != 1 or descriptor.get("profile") != "blendlib:rigid_v1":
        raise ValueError("Descriptor does not declare the supported strict rigid_v1 profile")
    if descriptor.get("mesh") != "godwarbridge:models3d/pagani_huayra.glb":
        raise ValueError("Descriptor mesh id does not match the packaged GLB")
    if glb.get("images") or glb.get("textures") or glb.get("samplers"):
        raise ValueError("Strict BlendLib GLB must not include images, textures, or samplers")
    if glb.get("extensionsRequired"):
        raise ValueError("Strict BlendLib GLB declares an unsupported required extension")
    if len(glb.get("nodes", [])) > 512:
        raise ValueError("Model exceeds the documented node budget")
    material_names = [item.get("name") for item in glb.get("materials", [])]
    if len(material_names) != len(set(material_names)) or set(material_names) != set(descriptor.get("materials", {})):
        raise ValueError("GLB material slots and descriptor mappings do not match exactly")
    if len(material_names) > 128:
        raise ValueError("Model exceeds the documented material-slot budget")
    if len(glb.get("meshes", [])) > 512:
        raise ValueError("Model exceeds the documented mesh budget")
    required_views = set()
    for mesh in glb.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode", 4) != 4 or set(primitive.get("attributes", {})) != {"POSITION", "NORMAL", "TEXCOORD_0"}:
                raise ValueError("A primitive violates the strict rigid_v1 vertex/triangle contract")
            required_views.add(primitive["indices"])
            required_views.update(primitive["attributes"].values())
    accessors = glb.get("accessors", [])
    total_vertices = 0
    for mesh in glb.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            total_vertices += accessors[primitive["attributes"]["POSITION"]]["count"]
    if total_vertices > 1_000_000:
        raise ValueError("Model exceeds the documented vertex limit")
    buffer_views = glb.get("bufferViews", [])
    for accessor in accessors:
        if "bufferView" in accessor:
            required_views.add(accessor["bufferView"])
        if "sparse" in accessor:
            raise ValueError("Sparse accessors are not supported")
    for view_index in required_views:
        if not 0 <= view_index < len(buffer_views):
            raise ValueError(f"Accessor references missing bufferView {view_index}")
        view = buffer_views[view_index]
        start = view.get("byteOffset", 0)
        end = start + view["byteLength"]
        if end > len(binary):
            raise ValueError(f"bufferView {view_index} exceeds the GLB binary chunk")
    if not descriptor.get("materials"):
        raise ValueError("Descriptor has no material mappings")
    texture_ids: set[str] = set()
    for material_name, definition in descriptor["materials"].items():
        texture_id = definition.get("base_color", "")
        if not texture_id.startswith("godwarbridge:textures/") or not texture_id.endswith(".png"):
            raise ValueError(f"Material {material_name!r} has an invalid external PNG resource ID")
        relative = texture_id.split(":", 1)[1]
        texture_path = RESOURCE_ROOT / relative
        if not texture_path.is_file() or not texture_path.read_bytes().startswith(PNG_SIGNATURE):
            raise ValueError(f"Material {material_name!r} references a missing/non-PNG texture: {texture_path}")
        texture_ids.add(texture_id)
    if len(texture_ids) != len({path.name for path in TEXTURE_ROOT.glob("*.png")}):
        raise ValueError("Resource texture set contains a missing or unused PNG")
    if sum(item["mode"] == "cutout" for item in descriptor["materials"].values()) != 7:
        raise ValueError("Expected the source's seven alpha-mask slots to remain cutout")
    return {
        "vertices": total_vertices,
        "meshes": len(glb.get("meshes", [])),
        "nodes": len(glb.get("nodes", [])),
        "materials": len(material_names),
        "textures": len(texture_ids),
        "glb_bytes": MODEL_PATH.stat().st_size,
        "texture_bytes": sum(path.stat().st_size for path in TEXTURE_ROOT.glob("*.png")),
    }


def write_if_new(path: Path, contents: bytes, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == contents:
            return
        if not force:
            raise FileExistsError(f"Refusing to replace non-identical generated output: {path}; pass --force after review")
    path.write_bytes(contents)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert the checked-in Pagani GLB to BlendLib's verified strict-v1 resource profile.")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--force", action="store_true", help="replace generated output files after reviewing the conversion")
    parser.add_argument("--verify-only", action="store_true", help="validate packaged resources without modifying files")
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps({"status": "PASS", **validate_packaged_assets()}, indent=2))
        return 0

    converted, textures, descriptor, report = make_assets(args.source.resolve())
    descriptor_bytes = (json.dumps(descriptor, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_if_new(MODEL_PATH, converted, args.force)
    write_if_new(DESCRIPTOR_PATH, descriptor_bytes, args.force)
    for relative, contents in textures.items():
        write_if_new(RESOURCE_ROOT / relative, contents, args.force)
    for old_png in TEXTURE_ROOT.glob("*.png"):
        if old_png.relative_to(RESOURCE_ROOT).as_posix() not in textures and not args.force:
            raise FileExistsError(f"Unused generated texture exists; review and pass --force before removing: {old_png}")
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_if_new(REPORT_PATH, report_bytes, args.force)
    print(json.dumps({"status": "CONVERTED", **validate_packaged_assets()}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"Model preparation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
