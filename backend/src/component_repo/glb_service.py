"""Build compact binary glTF previews from Component Repo mesh payloads."""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from typing import Any


GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK_TYPE = 0x4E4F534A
BIN_CHUNK_TYPE = 0x004E4942
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT = 5126
UNSIGNED_INT = 5125


def build_meshopt_glb(preview: dict[str, Any], config: dict[str, Any]) -> bytes:
    """Create a GLB and compress its geometry buffer views with meshoptimizer."""
    glb = build_glb(preview, config)
    preview_config = config["preview"]
    workspace_root = Path(__file__).resolve().parents[3]
    optimizer_script = workspace_root / preview_config["meshopt_script"]
    encoder_module = workspace_root / preview_config["meshopt_encoder_module"]
    try:
        result = subprocess.run(
            [
                preview_config["node_binary"],
                str(optimizer_script),
                str(encoder_module),
            ],
            input=glb,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=int(preview_config["meshopt_timeout_seconds"]),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("component_repo.preview_unavailable") from error
    if not result.stdout.startswith(GLB_MAGIC):
        raise ValueError("component_repo.preview_unavailable")
    return result.stdout


def build_glb(preview: dict[str, Any], config: dict[str, Any]) -> bytes:
    """Serialize the preview as a standards-based, uncompressed GLB 2.0 file."""
    binary = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    mesh_accessors: dict[str, tuple[int, int]] = {}

    for mesh in preview["meshes"]:
        positions = [float(value) for value in mesh["positions"]]
        indices = [int(value) for value in mesh["indices"]]
        position_bytes = struct.pack(f"<{len(positions)}f", *positions)
        position_view = append_buffer_view(
            binary,
            buffer_views,
            position_bytes,
            ARRAY_BUFFER,
            byte_stride=12,
        )
        vertex_count = len(positions) // 3
        position_accessor = len(accessors)
        axes = [positions[index::3] for index in range(3)]
        accessors.append(
            {
                "bufferView": position_view,
                "componentType": FLOAT,
                "count": vertex_count,
                "type": "VEC3",
                "min": [min(axis) for axis in axes],
                "max": [max(axis) for axis in axes],
            }
        )
        index_bytes = struct.pack(f"<{len(indices)}I", *indices)
        index_view = append_buffer_view(
            binary,
            buffer_views,
            index_bytes,
            ELEMENT_ARRAY_BUFFER,
        )
        index_accessor = len(accessors)
        accessors.append(
            {
                "bufferView": index_view,
                "componentType": UNSIGNED_INT,
                "count": len(indices),
                "type": "SCALAR",
                "min": [min(indices)],
                "max": [max(indices)],
            }
        )
        mesh_accessors[str(mesh["partRef"])] = (position_accessor, index_accessor)

    color_codes = list(dict.fromkeys(str(part["colorCode"]) for part in preview["parts"]))
    materials = [material_for_color(color_code, index) for index, color_code in enumerate(color_codes)]
    material_index = {color_code: index for index, color_code in enumerate(color_codes)}
    gltf_meshes: list[dict[str, Any]] = []
    mesh_index: dict[tuple[str, str], int] = {}
    for part in preview["parts"]:
        part_ref = str(part["partRef"])
        color_code = str(part["colorCode"])
        key = (part_ref, color_code)
        if key in mesh_index:
            continue
        position_accessor, index_accessor = mesh_accessors[part_ref]
        mesh_index[key] = len(gltf_meshes)
        gltf_meshes.append(
            {
                "name": f"{part_ref}:{color_code}",
                "primitives": [
                    {
                        "attributes": {"POSITION": position_accessor},
                        "indices": index_accessor,
                        "material": material_index[color_code],
                        "mode": 4,
                    }
                ],
            }
        )

    nodes: list[dict[str, Any]] = [
        {
            "name": "component-root",
            "scale": [0.05, -0.05, 0.05],
            "children": list(range(1, len(preview["parts"]) + 1)),
        }
    ]
    for part in preview["parts"]:
        transform = part["transform"]
        matrix = [float(value) for value in transform["matrix"]]
        position = transform["position"]
        nodes.append(
            {
                "name": str(part["instanceId"]),
                "mesh": mesh_index[(str(part["partRef"]), str(part["colorCode"]))],
                "matrix": [
                    matrix[0], matrix[3], matrix[6], 0.0,
                    matrix[1], matrix[4], matrix[7], 0.0,
                    matrix[2], matrix[5], matrix[8], 0.0,
                    float(position["x"]), float(position["y"]), float(position["z"]), 1.0,
                ],
            }
        )

    document = {
        "asset": {
            "version": "2.0",
            "generator": config["preview"]["generator_version"],
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": gltf_meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(binary)}],
    }
    return encode_glb(document, bytes(binary))


def append_buffer_view(
    binary: bytearray,
    buffer_views: list[dict[str, Any]],
    content: bytes,
    target: int,
    *,
    byte_stride: int | None = None,
) -> int:
    while len(binary) % 4:
        binary.append(0)
    view = {
        "buffer": 0,
        "byteOffset": len(binary),
        "byteLength": len(content),
        "target": target,
    }
    if byte_stride is not None:
        view["byteStride"] = byte_stride
    buffer_views.append(view)
    binary.extend(content)
    return len(buffer_views) - 1


def material_for_color(color_code: str, fallback_index: int) -> dict[str, Any]:
    known_colors = {
        "0": "17212b",
        "1": "1e5aa8",
        "2": "2f8f4e",
        "4": "c91a09",
        "7": "a0a5a9",
        "14": "f2cd37",
        "15": "ffffff",
    }
    palette = ["d9271c", "1f73c9", "f2c230", "2f9e62", "8b5cf6", "ef7d23"]
    color = known_colors.get(color_code, palette[fallback_index % len(palette)])
    rgb = [int(color[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    return {
        "name": f"ldraw-color-{color_code}",
        "pbrMetallicRoughness": {
            "baseColorFactor": [*rgb, 1.0],
            "metallicFactor": 0.0,
            "roughnessFactor": 0.34,
        },
        "doubleSided": True,
    }


def encode_glb(document: dict[str, Any], binary: bytes) -> bytes:
    json_bytes = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
    binary += b"\x00" * ((-len(binary)) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    return b"".join(
        (
            struct.pack("<4sII", GLB_MAGIC, GLB_VERSION, total_length),
            struct.pack("<II", len(json_bytes), JSON_CHUNK_TYPE),
            json_bytes,
            struct.pack("<II", len(binary), BIN_CHUNK_TYPE),
            binary,
        )
    )
