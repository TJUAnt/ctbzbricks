"""Analyze GLB mesh geometry for model fitting."""

from __future__ import annotations

import json
import struct
from json import JSONDecodeError
from typing import Any


def analyze_glb_geometry(config: dict[str, Any], file_bytes: bytes) -> dict[str, Any]:
    gltf, binary_chunk = read_glb_payload(config, file_bytes)
    primitives = mesh_primitives(config, gltf)
    positions = [
        primitive_position_bounds(config, gltf, binary_chunk, primitive)
        for primitive in primitives
    ]
    target_bbox = combined_bbox(config, positions)
    return {
        config["json_keys"]["target_bbox"]: target_bbox,
        config["json_keys"]["mesh_stats"]: mesh_stats(config, gltf, primitives),
    }


def read_glb_payload(
    config: dict[str, Any],
    file_bytes: bytes,
) -> tuple[dict[str, Any], bytes]:
    glb_config = config["glb"]
    if len(file_bytes) < int(glb_config["header_length"]):
        raise ValueError(config["errors"]["invalid_glb"])
    try:
        magic, version, declared_length = struct.unpack_from(
            glb_config["header_struct"],
            file_bytes,
        )
    except struct.error as error:
        raise ValueError(config["errors"]["invalid_glb"]) from error
    if magic.decode(glb_config["binary_encoding"]) != glb_config["magic"]:
        raise ValueError(config["errors"]["invalid_glb"])
    if version != int(glb_config["version"]):
        raise ValueError(config["errors"]["invalid_glb"])
    if declared_length != len(file_bytes):
        raise ValueError(config["errors"]["invalid_glb"])

    offset = int(glb_config["header_length"])
    json_chunk = None
    binary_chunk = b""
    while offset < len(file_bytes):
        try:
            chunk_length, chunk_type = struct.unpack_from(
                glb_config["chunk_header_struct"],
                file_bytes,
                offset,
            )
        except struct.error as error:
            raise ValueError(config["errors"]["invalid_glb"]) from error
        offset += int(glb_config["chunk_header_length"])
        chunk_end = offset + chunk_length
        if chunk_end > len(file_bytes):
            raise ValueError(config["errors"]["invalid_glb"])
        chunk_payload = file_bytes[offset:chunk_end]
        if chunk_type == int(glb_config["json_chunk_type"]):
            json_chunk = chunk_payload
        if chunk_type == int(glb_config["bin_chunk_type"]):
            binary_chunk = chunk_payload
        offset = chunk_end
    if json_chunk is None:
        raise ValueError(config["errors"]["invalid_glb"])
    try:
        return json.loads(json_chunk.decode(glb_config["json_encoding"])), binary_chunk
    except (JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(config["errors"]["invalid_glb"]) from error


def mesh_primitives(config: dict[str, Any], gltf: dict[str, Any]) -> list[dict[str, Any]]:
    keys = config["json_keys"]
    primitives = []
    for mesh in gltf.get(keys["meshes"], []):
        primitives.extend(mesh.get(keys["primitives"], []))
    return primitives


def primitive_position_bounds(
    config: dict[str, Any],
    gltf: dict[str, Any],
    binary_chunk: bytes,
    primitive: dict[str, Any],
) -> dict[str, Any]:
    keys = config["json_keys"]
    position_accessor_index = primitive.get(keys["attributes"], {}).get(
        config["glb"]["position_attribute"]
    )
    if position_accessor_index is None:
        raise ValueError(config["errors"]["missing_position_accessor"])
    accessor = gltf[keys["accessors"]][int(position_accessor_index)]
    if keys["min"] in accessor and keys["max"] in accessor:
        return bbox_from_min_max(config, accessor[keys["min"]], accessor[keys["max"]])
    return accessor_binary_bounds(config, gltf, binary_chunk, accessor)


def bbox_from_min_max(
    config: dict[str, Any],
    min_values: list[float],
    max_values: list[float],
) -> dict[str, Any]:
    keys = config["json_keys"]
    return {
        keys["min_x"]: float(min_values[0]),
        keys["min_y"]: float(min_values[1]),
        keys["min_z"]: float(min_values[2]),
        keys["max_x"]: float(max_values[0]),
        keys["max_y"]: float(max_values[1]),
        keys["max_z"]: float(max_values[2]),
    }


def accessor_binary_bounds(
    config: dict[str, Any],
    gltf: dict[str, Any],
    binary_chunk: bytes,
    accessor: dict[str, Any],
) -> dict[str, Any]:
    keys = config["json_keys"]
    glb = config["glb"]
    accessor_type = accessor[keys["type"]]
    if accessor_type != glb["vec3_type"]:
        raise ValueError(
            config["errors"]["unsupported_accessor_type"].format(
                accessor_type=accessor_type,
            )
        )
    component_type = str(accessor[keys["component_type"]])
    if component_type not in glb["component_type_struct"]:
        raise ValueError(
            config["errors"]["unsupported_accessor_component_type"].format(
                component_type=component_type,
            )
        )
    buffer_view = gltf[keys["buffer_views"]][int(accessor[keys["buffer_view"]])]
    vector_values = accessor_vectors(config, binary_chunk, accessor, buffer_view)
    return bbox_from_vectors(config, vector_values)


def accessor_vectors(
    config: dict[str, Any],
    binary_chunk: bytes,
    accessor: dict[str, Any],
    buffer_view: dict[str, Any],
) -> list[tuple[float, float, float]]:
    keys = config["json_keys"]
    glb = config["glb"]
    component_type = str(accessor[keys["component_type"]])
    component_count = int(glb["accessor_type_components"][accessor[keys["type"]]])
    component_size = int(glb["component_type_size"][component_type])
    item_size = component_count * component_size
    stride = int(buffer_view.get(keys["byte_stride"], item_size))
    base_offset = int(buffer_view.get(keys["byte_offset"], 0)) + int(
        accessor.get(keys["byte_offset"], 0)
    )
    unpack_format = (
        glb["struct_endian_prefix"]
        + glb["component_type_struct"][component_type] * component_count
    )
    return [
        tuple(
            float(value)
            for value in struct.unpack_from(
                unpack_format,
                binary_chunk,
                base_offset + index * stride,
            )
        )
        for index in range(int(accessor[keys["count"]]))
    ]


def bbox_from_vectors(
    config: dict[str, Any],
    vectors: list[tuple[float, float, float]],
) -> dict[str, Any]:
    axis_values = list(zip(*vectors))
    return bbox_from_min_max(
        config,
        [min(values) for values in axis_values],
        [max(values) for values in axis_values],
    )


def combined_bbox(config: dict[str, Any], boxes: list[dict[str, Any]]) -> dict[str, Any]:
    keys = config["json_keys"]
    bbox = {
        keys["min_x"]: min(box[keys["min_x"]] for box in boxes),
        keys["min_y"]: min(box[keys["min_y"]] for box in boxes),
        keys["min_z"]: min(box[keys["min_z"]] for box in boxes),
        keys["max_x"]: max(box[keys["max_x"]] for box in boxes),
        keys["max_y"]: max(box[keys["max_y"]] for box in boxes),
        keys["max_z"]: max(box[keys["max_z"]] for box in boxes),
    }
    bbox[keys["width"]] = bbox[keys["max_x"]] - bbox[keys["min_x"]]
    bbox[keys["height"]] = bbox[keys["max_y"]] - bbox[keys["min_y"]]
    bbox[keys["depth"]] = bbox[keys["max_z"]] - bbox[keys["min_z"]]
    return bbox


def mesh_stats(
    config: dict[str, Any],
    gltf: dict[str, Any],
    primitives: list[dict[str, Any]],
) -> dict[str, int]:
    keys = config["json_keys"]
    accessors = gltf.get(keys["accessors"], [])
    return {
        keys["mesh_count"]: len(gltf.get(keys["meshes"], [])),
        keys["primitive_count"]: len(primitives),
        keys["vertex_count"]: sum(
            primitive_vertex_count(config, primitive, accessors)
            for primitive in primitives
        ),
        keys["triangle_count"]: sum(
            primitive_triangle_count(config, primitive, accessors)
            for primitive in primitives
        ),
    }


def primitive_vertex_count(
    config: dict[str, Any],
    primitive: dict[str, Any],
    accessors: list[dict[str, Any]],
) -> int:
    keys = config["json_keys"]
    position_accessor_index = primitive.get(keys["attributes"], {}).get(
        config["glb"]["position_attribute"]
    )
    if position_accessor_index is None:
        return 0
    return int(accessors[int(position_accessor_index)][keys["count"]])


def primitive_triangle_count(
    config: dict[str, Any],
    primitive: dict[str, Any],
    accessors: list[dict[str, Any]],
) -> int:
    keys = config["json_keys"]
    glb = config["glb"]
    if int(primitive.get(keys["mode"], glb["triangles_mode"])) != int(
        glb["triangles_mode"]
    ):
        return 0
    if keys["indices"] in primitive:
        return int(accessors[int(primitive[keys["indices"]])][keys["count"]]) // int(
            glb["indices_per_triangle"]
        )
    return primitive_vertex_count(config, primitive, accessors) // int(
        glb["indices_per_triangle"]
    )
