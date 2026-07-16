"""Extract material color summaries from GLB files."""

from __future__ import annotations

import json
import struct
from json import JSONDecodeError
from typing import Any


def extract_glb_material_color_summary(config: dict[str, Any], file_bytes: bytes) -> dict[str, Any]:
    gltf = read_glb_json(config, file_bytes)
    materials = gltf.get(config["json_keys"]["materials"], [])
    material_usages = primitive_material_usages(config, gltf)
    total_face_count = sum(usage["faceCount"] for usage in material_usages.values())
    colors = [
        material_color_entry(config, materials, material, usage, total_face_count)
        for material, usage in material_usages.items()
    ]
    return {
        "source": config["color_summary"]["source"],
        "colors": colors,
        config["metadata_keys"]["has_base_color_texture"]: any(
            color[config["metadata_keys"]["has_base_color_texture"]] for color in colors
        ),
        config["metadata_keys"]["texture_sampling_status"]: config["color_summary"]["not_processed"],
    }


def read_glb_json(config: dict[str, Any], file_bytes: bytes) -> dict[str, Any]:
    glb_config = config["glb"]
    if len(file_bytes) < int(glb_config["header_length"]):
        raise ValueError(config["errors"]["invalid_glb"])
    try:
        magic, version, declared_length = struct.unpack_from(glb_config["header_struct"], file_bytes)
    except struct.error as error:
        raise ValueError(config["errors"]["invalid_glb"]) from error
    if magic.decode(glb_config["binary_encoding"]) != glb_config["magic"]:
        raise ValueError(config["errors"]["invalid_glb"])
    if version != int(glb_config["version"]):
        raise ValueError(config["errors"]["invalid_glb"])
    if declared_length != len(file_bytes):
        raise ValueError(config["errors"]["invalid_glb"])

    offset = int(glb_config["header_length"])
    while offset < len(file_bytes):
        try:
            chunk_length, chunk_type = struct.unpack_from(glb_config["chunk_header_struct"], file_bytes, offset)
        except struct.error as error:
            raise ValueError(config["errors"]["invalid_glb"]) from error
        offset += int(glb_config["chunk_header_length"])
        chunk_end = offset + chunk_length
        if chunk_end > len(file_bytes):
            raise ValueError(config["errors"]["invalid_glb"])
        if chunk_type == int(glb_config["json_chunk_type"]):
            try:
                return json.loads(file_bytes[offset:chunk_end].decode(glb_config["json_encoding"]))
            except (JSONDecodeError, UnicodeDecodeError) as error:
                raise ValueError(config["errors"]["invalid_glb"]) from error
        offset = chunk_end
    raise ValueError(config["errors"]["invalid_glb"])


def primitive_material_usages(config: dict[str, Any], gltf: dict[str, Any]) -> dict[int, dict[str, int]]:
    keys = config["json_keys"]
    accessors = gltf.get(keys["accessors"], [])
    usages: dict[int, dict[str, int]] = {}
    for mesh in gltf.get(keys["meshes"], []):
        for primitive in mesh.get(keys["primitives"], []):
            material_index = int(primitive.get(keys["material"], config["color_summary"]["fallback_material_index"]))
            if material_index not in usages:
                usages[material_index] = {"faceCount": 0}
            usages[material_index]["faceCount"] += primitive_face_count(config, primitive, accessors)
    if not usages:
        usages[int(config["color_summary"]["fallback_material_index"])] = {"faceCount": 0}
    return usages


def primitive_face_count(
    config: dict[str, Any],
    primitive: dict[str, Any],
    accessors: list[dict[str, Any]],
) -> int:
    keys = config["json_keys"]
    glb_config = config["glb"]
    if int(primitive.get(keys["mode"], glb_config["triangles_mode"])) != int(glb_config["triangles_mode"]):
        return 0
    if keys["indices"] in primitive:
        index_accessor = accessors[int(primitive[keys["indices"]])]
        return int(index_accessor[keys["count"]]) // int(glb_config["indices_per_triangle"])
    attributes = primitive.get(keys["attributes"], {})
    if glb_config["position_attribute"] not in attributes:
        return 0
    position_accessor = accessors[int(attributes[glb_config["position_attribute"]])]
    return int(position_accessor[keys["count"]]) // int(glb_config["indices_per_triangle"])


def material_color_entry(
    config: dict[str, Any],
    materials: list[dict[str, Any]],
    material_index: int,
    usage: dict[str, int],
    total_face_count: int,
) -> dict[str, Any]:
    material = material_by_index(config, materials, material_index)
    factor = material_base_color_factor(config, material)
    face_count = usage["faceCount"]
    coverage_ratio = 0
    if total_face_count > 0:
        coverage_ratio = round(face_count / total_face_count, int(config["color_summary"]["coverage_decimals"]))
    return {
        "hex": rgba_to_hex(config, factor),
        "rgba": [
            round(float(channel), int(config["color_summary"]["rgba_decimals"]))
            for channel in factor
        ],
        "materialName": material["name"],
        "faceCount": face_count,
        "coverageRatio": coverage_ratio,
        config["metadata_keys"]["has_base_color_texture"]: material[config["metadata_keys"]["has_base_color_texture"]],
    }


def material_by_index(
    config: dict[str, Any],
    materials: list[dict[str, Any]],
    material_index: int,
) -> dict[str, Any]:
    keys = config["json_keys"]
    if material_index < 0 or material_index >= len(materials):
        return {
            keys["name"]: config["color_summary"]["default_material_name"],
            config["metadata_keys"]["has_base_color_texture"]: False,
        }
    material = materials[material_index]
    return {
        keys["name"]: material.get(keys["name"], config["color_summary"]["default_material_name"]),
        keys["pbr"]: material.get(keys["pbr"], {}),
        config["metadata_keys"]["has_base_color_texture"]: keys["base_color_texture"]
        in material.get(keys["pbr"], {}),
    }


def material_base_color_factor(config: dict[str, Any], material: dict[str, Any]) -> list[float]:
    keys = config["json_keys"]
    pbr = material.get(keys["pbr"], {})
    return [
        float(channel)
        for channel in pbr.get(
            keys["base_color_factor"],
            config["color_summary"]["default_color_factor"],
        )
    ]


def rgba_to_hex(config: dict[str, Any], factor: list[float]) -> str:
    multiplier = int(config["color_summary"]["hex_multiplier"])
    return config["color_summary"]["hex_template"].format(
        red=round(factor[0] * multiplier),
        green=round(factor[1] * multiplier),
        blue=round(factor[2] * multiplier),
    )
