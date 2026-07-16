"""Build connector_instances from imported LDCad Shadow metadata."""
import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.orm import sessionmaker

from src.config.db_config import get_db_url
from src.model.models import (
    ConnectorInstance,
    LDrawShadowFile,
    LDrawShadowMetaRaw,
)
from src.tools.create_ldraw_tables import create_ldraw_tables


REQUIRED_CONFIG_KEYS = (
    "batch_size",
    "shadow_source_type",
    "snap_cyl_meta_type",
    "connector_kind_cyl",
    "unknown_connector_type",
    "default_confidence",
    "default_orientation",
    "default_position",
    "direction",
    "param_keys",
    "grid",
    "include",
    "section_profile_tokens",
    "normalized_rules",
)


def _load_config(config_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_CONFIG_KEYS if key not in config]
    if missing_keys:
        raise KeyError(
            f"Missing connector generation config keys: {', '.join(missing_keys)}"
        )
    return config


def _chunks(records: list[dict], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _bool_param(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False


def _param(params: dict, config: dict, key: str):
    param_keys = config["param_keys"]
    value = params.get(param_keys[key])
    if value is None and key == "id":
        value = params.get(param_keys["alternate_id"])
    return value


def _section_pairs(secs: list) -> list[tuple[str, float, float]]:
    pairs = []
    index = 0
    while index + 2 < len(secs):
        profile = secs[index]
        radius = secs[index + 1]
        length = secs[index + 2]
        if isinstance(profile, str) and isinstance(radius, (int, float)):
            pairs.append((profile, float(radius), float(length)))
        index += 3
    return pairs


def _contains_technic_hole_profile_radii(secs: list, config: dict) -> bool:
    sequence = [
        tuple(item)
        for item in config["normalized_rules"]["female_technic_hole_profile_radii"]
    ]
    pairs = [(profile, radius) for profile, radius, _ in _section_pairs(secs)]
    if len(pairs) < len(sequence):
        return False

    for start in range(0, len(pairs) - len(sequence) + 1):
        if pairs[start : start + len(sequence)] == sequence:
            return True
    return False


def _normalize_connector_type(params: dict, config: dict) -> str:
    gender = _param(params, config, "gender")
    secs = _param(params, config, "secs") or []
    profiles = config["section_profile_tokens"]
    rules = config["normalized_rules"]
    pairs = _section_pairs(secs)

    if any(profile == profiles["axle"] for profile, _, _ in pairs):
        return rules["axle_profile"].get(gender, config["unknown_connector_type"])

    if gender == "F" and _contains_technic_hole_profile_radii(secs, config):
        return rules["female_technic_hole_type"]

    if not pairs:
        return config["unknown_connector_type"]

    first_profile, first_radius, _ = pairs[0]
    radius_key = str(int(first_radius))
    if gender == "M" and first_profile == profiles["round"]:
        return rules["male_round_radius"].get(
            radius_key,
            config["unknown_connector_type"],
        )
    if gender == "F" and first_profile == profiles["round"]:
        return rules["female_round_radius"].get(
            radius_key,
            config["unknown_connector_type"],
        )
    if gender == "F" and first_profile == profiles["square"]:
        return rules["female_square_radius"].get(
            radius_key,
            config["unknown_connector_type"],
        )

    return config["unknown_connector_type"]


def _radius_and_length(params: dict, config: dict) -> tuple[float | None, float | None]:
    secs = _param(params, config, "secs") or []
    pairs = _section_pairs(secs)
    if not pairs:
        return None, None
    _, radius, length = pairs[0]
    return radius, length


def _grid_offsets(params: dict, config: dict) -> list[tuple[float, float, float]]:
    grid = _param(params, config, "grid")
    if not grid:
        return [(0.0, 0.0, 0.0)]

    grid_config = config["grid"]
    if len(grid) == grid_config["compact_length"]:
        return _compact_grid_offsets(grid, grid_config)
    if len(grid) == grid_config["extended_length"]:
        return _extended_grid_offsets(grid, grid_config)
    if len(grid) != grid_config["expected_length"]:
        return [(0.0, 0.0, 0.0)]

    x_mode = grid[grid_config["x_mode_index"]]
    x_count = int(grid[grid_config["x_count_index"]])
    z_mode = grid[grid_config["z_mode_index"]]
    z_count = int(grid[grid_config["z_count_index"]])
    x_step = float(grid[grid_config["x_step_index"]])
    z_step = float(grid[grid_config["z_step_index"]])

    x_offsets = _axis_offsets(x_mode, x_count, x_step, grid_config["center_token"])
    z_offsets = _axis_offsets(z_mode, z_count, z_step, grid_config["center_token"])
    return [(x, 0.0, z) for x in x_offsets for z in z_offsets]


def _compact_grid_offsets(grid: list, grid_config: dict) -> list[tuple[float, float, float]]:
    center_token = grid_config["center_token"]
    if grid[0] == center_token:
        x_mode = grid[0]
        x_count = int(grid[1])
        z_mode = 1
        z_count = int(grid[2])
        x_step = float(grid[3])
        z_step = float(grid[4])
    else:
        x_mode = 1
        x_count = int(grid[0])
        z_mode = grid[1]
        z_count = int(grid[2])
        x_step = float(grid[3])
        z_step = float(grid[4])

    x_offsets = _axis_offsets(x_mode, x_count, x_step, center_token)
    z_offsets = _axis_offsets(z_mode, z_count, z_step, center_token)
    return [(x, 0.0, z) for x in x_offsets for z in z_offsets]


def _extended_grid_offsets(grid: list, grid_config: dict) -> list[tuple[float, float, float]]:
    center_token = grid_config["center_token"]
    if grid[1] == center_token:
        x_offsets = _axis_offsets(1, int(grid[0]), float(grid[4]), center_token)
        y_offsets = _axis_offsets(grid[1], int(grid[2]), float(grid[5]), center_token)
        z_offsets = _axis_offsets(1, int(grid[3]), float(grid[6]), center_token)
    elif grid[2] == center_token:
        x_offsets = _axis_offsets(1, int(grid[0]), float(grid[4]), center_token)
        y_offsets = _axis_offsets(1, int(grid[1]), float(grid[5]), center_token)
        z_offsets = _axis_offsets(grid[2], int(grid[3]), float(grid[6]), center_token)
    else:
        return [(0.0, 0.0, 0.0)]
    return [(x, y, z) for x in x_offsets for y in y_offsets for z in z_offsets]


def _axis_offsets(mode, count: int, step: float, center_token: str) -> list[float]:
    if count <= 0:
        return [0.0]
    if mode == center_token:
        start = -((count - 1) * step) / 2.0
        return [start + index * step for index in range(count)]
    return [index * step for index in range(count)]


def _matrix_vector_mul(matrix: list[float], vector: list[float]) -> list[float]:
    return [
        matrix[0] * vector[0] + matrix[1] * vector[1] + matrix[2] * vector[2],
        matrix[3] * vector[0] + matrix[4] * vector[1] + matrix[5] * vector[2],
        matrix[6] * vector[0] + matrix[7] * vector[1] + matrix[8] * vector[2],
    ]


def _matrix_mul(left: list[float], right: list[float]) -> list[float]:
    return [
        left[0] * right[0] + left[1] * right[3] + left[2] * right[6],
        left[0] * right[1] + left[1] * right[4] + left[2] * right[7],
        left[0] * right[2] + left[1] * right[5] + left[2] * right[8],
        left[3] * right[0] + left[4] * right[3] + left[5] * right[6],
        left[3] * right[1] + left[4] * right[4] + left[5] * right[7],
        left[3] * right[2] + left[4] * right[5] + left[5] * right[8],
        left[6] * right[0] + left[7] * right[3] + left[8] * right[6],
        left[6] * right[1] + left[7] * right[4] + left[8] * right[7],
        left[6] * right[2] + left[7] * right[5] + left[8] * right[8],
    ]


def _position(params: dict, offset: tuple[float, float, float], config: dict) -> list[float]:
    base = _param(params, config, "pos") or config["default_position"]
    return [
        float(base[0]) + offset[0],
        float(base[1]) + offset[1],
        float(base[2]) + offset[2],
    ]


def _orientation(params: dict, config: dict) -> list[float]:
    return [float(value) for value in (_param(params, config, "ori") or config["default_orientation"])]


def _direction_from_orientation(orientation: list[float], config: dict) -> dict:
    axis_column = config["direction"]["axis_column"]
    start_index = axis_column - 1
    vector = [
        orientation[start_index],
        orientation[start_index + 3],
        orientation[start_index + 6],
    ]
    labels = config["direction"]["labels"]
    groups = config["direction"]["groups"]
    tolerance = config["direction"]["tolerance"]
    abs_values = [abs(value) for value in vector]
    max_value = max(abs_values)
    if max_value <= tolerance:
        axis = "unknown"
        sign = None
    else:
        axis_index = abs_values.index(max_value)
        axis = ("x", "y", "z")[axis_index]
        sign = "pos" if vector[axis_index] >= 0 else "neg"

    if axis == "unknown":
        direction_label = labels["unknown"]
    else:
        direction_label = labels[f"{axis}_{sign}"]

    return {
        "direction_x": vector[0],
        "direction_y": vector[1],
        "direction_z": vector[2],
        "direction_label": direction_label,
        "direction_group": groups[axis],
    }


def _connector_group(params: dict, config: dict) -> str | None:
    value = _param(params, config, "id")
    return str(value) if value is not None else None


def _connector_records_for_meta(
    meta_id: int,
    ldraw_part_num: str,
    params: dict,
    config: dict,
) -> list[dict]:
    radius, length = _radius_and_length(params, config)
    orientation = _orientation(params, config)
    direction = _direction_from_orientation(orientation, config)
    records = []
    for offset in _grid_offsets(params, config):
        position = _position(params, offset, config)
        records.append(
            {
                "ldraw_part_num": ldraw_part_num,
                "source_type": config["shadow_source_type"],
                "source_meta_id": meta_id,
                "connector_kind": config["connector_kind_cyl"],
                "normalized_connector_type": _normalize_connector_type(params, config),
                "connector_group": _connector_group(params, config),
                "connector_gender": _param(params, config, "gender"),
                "pos_x": position[0],
                "pos_y": position[1],
                "pos_z": position[2],
                "ori_11": orientation[0],
                "ori_12": orientation[1],
                "ori_13": orientation[2],
                "ori_21": orientation[3],
                "ori_22": orientation[4],
                "ori_23": orientation[5],
                "ori_31": orientation[6],
                "ori_32": orientation[7],
                "ori_33": orientation[8],
                **direction,
                "radius": radius,
                "length": length,
                "caps": _param(params, config, "caps"),
                "center_flag": _bool_param(_param(params, config, "center")),
                "slide_flag": _bool_param(_param(params, config, "slide")),
                "confidence": Decimal(config["default_confidence"]),
                "raw_params": params,
            }
        )
    return records


def _connector_record_to_local_connector(record: dict) -> dict:
    return {
        "pos": [record["pos_x"], record["pos_y"], record["pos_z"]],
        "ori": [
            record["ori_11"],
            record["ori_12"],
            record["ori_13"],
            record["ori_21"],
            record["ori_22"],
            record["ori_23"],
            record["ori_31"],
            record["ori_32"],
            record["ori_33"],
        ],
        "record": record,
    }


def _normalize_ref(ref: str) -> str:
    return ref.replace("\\", "/").lower()


def _resolve_include_ref(
    ref: str,
    file_by_ldraw_part_num: dict[str, str],
    file_by_relative_path: dict[str, str],
    config: dict,
) -> str | None:
    normalized_ref = _normalize_ref(ref)
    for candidate_format in config["include"]["reference_candidate_formats"]:
        candidate = candidate_format.format(ref=normalized_ref)
        if candidate in file_by_ldraw_part_num:
            return file_by_ldraw_part_num[candidate]
        if candidate in file_by_relative_path:
            return file_by_relative_path[candidate]
    return None


def _include_transform_records(
    include_meta_id: int,
    from_ldraw_part_num: str,
    include_params: dict,
    target_records: list[dict],
    config: dict,
) -> list[dict]:
    include_pos = include_params.get("pos") or config["default_position"]
    include_ori = include_params.get("ori") or config["default_orientation"]
    include_offsets = _grid_offsets(include_params, config)
    records = []

    for offset in include_offsets:
        offset_vector = [float(offset[0]), float(offset[1]), float(offset[2])]
        for target_connector in target_records:
            local = _connector_record_to_local_connector(target_connector)
            local_pos = [
                local["pos"][0] + offset_vector[0],
                local["pos"][1] + offset_vector[1],
                local["pos"][2] + offset_vector[2],
            ]
            rotated_pos = _matrix_vector_mul(include_ori, local_pos)
            transformed_pos = [
                float(include_pos[0]) + rotated_pos[0],
                float(include_pos[1]) + rotated_pos[1],
                float(include_pos[2]) + rotated_pos[2],
            ]
            transformed_ori = _matrix_mul(include_ori, local["ori"])
            transformed_direction = _direction_from_orientation(
                transformed_ori,
                config,
            )
            source_record = local["record"]
            records.append(
                {
                    **source_record,
                    "ldraw_part_num": from_ldraw_part_num,
                    "source_meta_id": include_meta_id,
                    "pos_x": transformed_pos[0],
                    "pos_y": transformed_pos[1],
                    "pos_z": transformed_pos[2],
                    "ori_11": transformed_ori[0],
                    "ori_12": transformed_ori[1],
                    "ori_13": transformed_ori[2],
                    "ori_21": transformed_ori[3],
                    "ori_22": transformed_ori[4],
                    "ori_23": transformed_ori[5],
                    "ori_31": transformed_ori[6],
                    "ori_32": transformed_ori[7],
                    "ori_33": transformed_ori[8],
                    **transformed_direction,
                    "raw_params": {
                        "include": include_params,
                        "target": source_record["raw_params"],
                    },
                }
            )
    return records


def _expand_connectors_for_part(
    ldraw_part_num: str,
    direct_records_by_part: dict[str, list[dict]],
    includes_by_part: dict[str, list[tuple[int, dict]]],
    file_by_ldraw_part_num: dict[str, str],
    file_by_relative_path: dict[str, str],
    config: dict,
    memo: dict[str, list[dict]],
    stack: set[str],
    depth: int,
) -> list[dict]:
    if ldraw_part_num in memo:
        return memo[ldraw_part_num]
    if depth > config["include"]["max_depth"] or ldraw_part_num in stack:
        return direct_records_by_part.get(ldraw_part_num, [])

    stack.add(ldraw_part_num)
    records = list(direct_records_by_part.get(ldraw_part_num, []))
    for include_meta_id, include_params in includes_by_part.get(ldraw_part_num, []):
        ref = include_params.get(config["include"]["ref_key"])
        if not ref:
            continue
        target_part_num = _resolve_include_ref(
            ref,
            file_by_ldraw_part_num,
            file_by_relative_path,
            config,
        )
        if target_part_num is None:
            continue
        target_records = _expand_connectors_for_part(
            target_part_num,
            direct_records_by_part,
            includes_by_part,
            file_by_ldraw_part_num,
            file_by_relative_path,
            config,
            memo,
            stack,
            depth + 1,
        )
        records.extend(
            _include_transform_records(
                include_meta_id,
                ldraw_part_num,
                include_params,
                target_records,
                config,
            )
        )
    stack.remove(ldraw_part_num)
    memo[ldraw_part_num] = records
    return records


def build_connector_instances(config_path: Path) -> dict:
    config = _load_config(config_path)
    create_ldraw_tables()

    engine = create_engine(get_db_url(), echo=False)
    Session = sessionmaker(bind=engine)
    with Session.begin() as session:
        session.execute(delete(ConnectorInstance))
        snap_cyl_rows = session.execute(
            select(
                LDrawShadowMetaRaw.id,
                LDrawShadowMetaRaw.parsed_json,
                LDrawShadowFile.ldraw_part_num,
            )
            .join(
                LDrawShadowFile,
                LDrawShadowFile.id == LDrawShadowMetaRaw.shadow_file_id,
            )
            .where(LDrawShadowMetaRaw.meta_type == config["snap_cyl_meta_type"])
        ).all()
        include_rows = session.execute(
            select(
                LDrawShadowMetaRaw.id,
                LDrawShadowMetaRaw.parsed_json,
                LDrawShadowFile.ldraw_part_num,
            )
            .join(
                LDrawShadowFile,
                LDrawShadowFile.id == LDrawShadowMetaRaw.shadow_file_id,
            )
            .where(
                LDrawShadowMetaRaw.meta_type
                == config["include"]["snap_include_meta_type"]
            )
        ).all()
        file_rows = session.execute(
            select(
                LDrawShadowFile.ldraw_part_num,
                LDrawShadowFile.relative_path,
            )
        ).all()

        direct_records_by_part = {}
        for meta_id, params, ldraw_part_num in snap_cyl_rows:
            if params:
                direct_records_by_part.setdefault(ldraw_part_num, []).extend(
                    _connector_records_for_meta(meta_id, ldraw_part_num, params, config)
                )

        includes_by_part = {}
        for meta_id, params, ldraw_part_num in include_rows:
            if params:
                includes_by_part.setdefault(ldraw_part_num, []).append((meta_id, params))

        file_by_ldraw_part_num = {
            ldraw_part_num: ldraw_part_num
            for ldraw_part_num, _ in file_rows
        }
        file_by_relative_path = {
            relative_path: ldraw_part_num
            for ldraw_part_num, relative_path in file_rows
        }

        memo = {}
        records = []
        for ldraw_part_num, _ in file_rows:
            records.extend(
                _expand_connectors_for_part(
                    ldraw_part_num,
                    direct_records_by_part,
                    includes_by_part,
                    file_by_ldraw_part_num,
                    file_by_relative_path,
                    config,
                    memo,
                    set(),
                    0,
                )
            )

        for batch in _chunks(records, config["batch_size"]):
            session.execute(insert(ConnectorInstance).values(batch))

    return {
        "snap_cyl_meta_rows": len(snap_cyl_rows),
        "snap_include_meta_rows": len(include_rows),
        "connector_instances": len(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/connector_generation.json"),
    )
    args = parser.parse_args()

    result = build_connector_instances(args.config)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
