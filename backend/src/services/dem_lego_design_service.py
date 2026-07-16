"""Independent DEM BaseH LEGO structure strategy."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.ldraw.mesh import collect_ldraw_mesh
from src.ldraw.surface_profile import PartSurfaceProfile, build_part_surface_profile
from src.model.models import LDrawFile, LDrawPart, LDrawPartGeometry, XrefPartNumber


def load_part_surface_profile(
    part_id: str,
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    profile = load_part_surface_profile_models(
        (part_id,),
        engine,
        config,
        config["surface_profile"]["sampling"]["samples_per_stud_axis"],
    )[0]
    return {
        "partId": profile.part_id,
        "ldrawOriginToBaseLdu": profile.ldraw_origin_to_base_ldu,
        "ldrawCenterXLdu": profile.ldraw_center_x_ldu,
        "ldrawCenterZLdu": profile.ldraw_center_z_ldu,
        "widthStud": profile.width_stud,
        "depthStud": profile.depth_stud,
        "samplesPerStudAxis": profile.samples_per_stud_axis,
        "surfaceHeightPlate": profile.surface_height_plate,
        "collisionIntervalsPlate": profile.collision_intervals_plate,
        "bottomContact": profile.bottom_contact,
        "topConnectMask": profile.top_connection_mask,
    }


def load_part_surface_profile_models(
    part_ids: tuple[str, ...],
    engine: Engine,
    config: dict[str, Any],
    samples_per_stud_axis: int,
) -> tuple[PartSurfaceProfile, ...]:
    profile_config = config["surface_profile"]
    for part_id in part_ids:
        if re.fullmatch(profile_config["part_id_pattern"], part_id) is None:
            raise ValueError(config["errors"]["surface_profile_part_id"])
    root = Path(profile_config["ldraw_root"])
    Session = sessionmaker(bind=engine)
    with Session() as session:
        relative_paths = session.scalars(select(LDrawFile.relative_path)).all()
    files = {
        relative_path: root / Path(relative_path)
        for relative_path in relative_paths
    }
    profiles = []
    sampling_config = {
        **profile_config["sampling"],
        "samples_per_stud_axis": samples_per_stud_axis,
    }
    for part_id in part_ids:
        relative_path = profile_config["part_path_template"].format(part_id=part_id.lower())
        mesh = collect_ldraw_mesh(relative_path, files, profile_config["mesh"])
        if mesh.errors:
            raise ValueError(profile_config["mesh_error_separator"].join(mesh.errors))
        profiles.append(
            build_part_surface_profile(
                part_id,
                mesh.surface_triangles,
                mesh.triangles,
                mesh.top_connection_origins,
                sampling_config,
            )
        )
    return tuple(profiles)


def load_dem_structure_parts(engine: Engine, config: dict[str, Any]) -> list[dict[str, Any]]:
    Session = sessionmaker(bind=engine)
    candidates = []
    with Session() as session:
        for part_spec in config["parts"]["specs"].values():
            name_pattern = re.compile(part_spec["name_pattern"])
            parts_by_id: dict[str, dict[str, Any]] = {}
            for ldraw_part, geometry, xref in session.execute(dem_part_statement(part_spec, config)):
                normalized_name = config["parts"]["name_space_separator"].join(ldraw_part.name.split())
                if name_pattern.fullmatch(normalized_name) is None:
                    continue
                width_value = float(geometry.logical_width_stud)
                depth_value = float(geometry.logical_depth_stud)
                if not width_value.is_integer() or not depth_value.is_integer():
                    continue
                part = parts_by_id.setdefault(
                    ldraw_part.ldraw_part_num,
                    {
                        "partId": ldraw_part.ldraw_part_num,
                        "rebrickablePartNum": None,
                        "legoDesignId": None,
                        "role": part_spec["role"],
                        "width": int(width_value),
                        "depth": int(depth_value),
                        "heightPlate": part_spec["height_plate"],
                        "area": int(width_value) * int(depth_value),
                        "xrefRank": config["parts"]["xref_missing_rank"],
                    },
                )
                apply_dem_part_xref(part, xref, config)
            candidates.extend(parts_by_id.values())

    selected_by_geometry: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    for candidate in candidates:
        geometry_key = (
            candidate["role"],
            candidate["width"],
            candidate["depth"],
            candidate["heightPlate"],
        )
        current = selected_by_geometry.get(geometry_key)
        if current is None or dem_part_rank(candidate) < dem_part_rank(current):
            selected_by_geometry[geometry_key] = candidate
    return [
        {key: value for key, value in part.items() if key != "xrefRank"}
        for part in sorted(
            selected_by_geometry.values(),
            key=lambda item: (-item["heightPlate"], -item["area"], item["partId"]),
        )
    ]


def dem_part_statement(part_spec: dict[str, Any], config: dict[str, Any]):
    geometry = LDrawPartGeometry
    minimum_height = (
        part_spec["geometry_height_plate"]
        - part_spec["geometry_height_tolerance_plate"]
    )
    maximum_height = (
        part_spec["geometry_height_plate"]
        + part_spec["geometry_height_tolerance_plate"]
    )
    return (
        select(LDrawPart, geometry, XrefPartNumber)
        .join(geometry, geometry.ldraw_part_id == LDrawPart.id)
        .outerjoin(XrefPartNumber, XrefPartNumber.ldraw_part_num == LDrawPart.ldraw_part_num)
        .where(LDrawPart.category == part_spec["category"])
        .where(LDrawPart.name.is_not(None))
        .where(geometry.geometry_status == config["parts"]["geometry_status"])
        .where(geometry.logical_height_plate >= minimum_height)
        .where(geometry.logical_height_plate <= maximum_height)
        .where(geometry.logical_width_stud.is_not(None))
        .where(geometry.logical_depth_stud.is_not(None))
        .where(geometry.logical_width_stud >= config["parts"]["minimum_dimension_stud"])
        .where(geometry.logical_depth_stud >= config["parts"]["minimum_dimension_stud"])
        .where(
            geometry.logical_width_stud * geometry.logical_depth_stud
            <= config["parts"]["maximum_area_stud"]
        )
        .order_by(LDrawPart.ldraw_part_num)
    )


def apply_dem_part_xref(
    part: dict[str, Any],
    xref: XrefPartNumber | None,
    config: dict[str, Any],
) -> None:
    if xref is None:
        return
    rank = (
        config["parts"]["xref_exact_rank"]
        if xref.relation_type == config["parts"]["xref_exact_relation"]
        else config["parts"]["xref_mapped_rank"]
    )
    if rank >= part["xrefRank"]:
        return
    part["xrefRank"] = rank
    part["rebrickablePartNum"] = xref.rebrickable_part_num
    part["legoDesignId"] = xref.lego_design_id


def dem_part_rank(part: dict[str, Any]) -> tuple[int, int, str]:
    return (part["xrefRank"], len(part["partId"]), part["partId"])


def build_base_h_structure(
    base_h: list[list[int]],
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    width, depth = validate_base_h(base_h, config)
    parts_by_height = dem_parts_by_height(parts, config)
    built_heights = [[config["algorithm"]["minimum_height_plate"] for _x in range(width)] for _z in range(depth)]
    occupancy_owner: dict[tuple[int, int, int], int] = {}
    placements = []

    while True:
        incomplete_cells = [
            (x, z)
            for z, row in enumerate(base_h)
            for x, target_height in enumerate(row)
            if built_heights[z][x] < target_height
        ]
        if not incomplete_cells:
            break
        base_plate = min(built_heights[z][x] for x, z in incomplete_cells)
        available_cells = {
            (x, z)
            for x, z in incomplete_cells
            if built_heights[z][x] == base_plate
        }
        placement_count_before_layer = len(placements)
        for part_height in sorted(parts_by_height, reverse=True):
            height_cells = {
                (x, z)
                for x, z in available_cells
                if base_h[z][x] - base_plate >= part_height
            }
            if not height_cells:
                continue
            layer_placements = tile_base_h_cells(
                height_cells,
                base_plate,
                parts_by_height[part_height],
                occupancy_owner,
                config,
            )
            for placement in layer_placements:
                placement_index = len(placements)
                placements.append(placement)
                for level in range(base_plate, base_plate + part_height):
                    for z in range(placement["z"], placement["z"] + placement["depth"]):
                        for x in range(placement["x"], placement["x"] + placement["width"]):
                            occupancy_owner[(x, z, level)] = placement_index
                            built_heights[z][x] = base_plate + part_height
            available_cells -= height_cells
        if len(placements) == placement_count_before_layer:
            raise ValueError(config["errors"]["base_h_uncovered"])

    validation = validate_base_h_result(base_h, placements, config)
    return {
        "strategy": config["structure"]["strategy"],
        "widthStud": width,
        "depthStud": depth,
        "baseH": base_h,
        "placements": placements,
        "bom": dem_structure_bom(placements),
        "validation": validation,
    }


def validate_base_h(base_h: list[list[int]], config: dict[str, Any]) -> tuple[int, int]:
    if not base_h or not base_h[0]:
        raise ValueError(config["errors"]["base_h_empty"])
    width = len(base_h[0])
    if any(len(row) != width for row in base_h):
        raise ValueError(config["errors"]["base_h_not_rectangular"])
    minimum_height = config["algorithm"]["minimum_height_plate"]
    if any(type(height) is not int or height < minimum_height for row in base_h for height in row):
        raise ValueError(config["errors"]["base_h_negative"])
    return width, len(base_h)


def dem_parts_by_height(
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    parts_by_height: dict[int, list[dict[str, Any]]] = {}
    for part in parts:
        parts_by_height.setdefault(part["heightPlate"], []).append(part)
    if (
        config["algorithm"]["minimum_part_height_plate"] not in parts_by_height
        or any(
            not any(
                part["area"] == config["algorithm"]["minimum_part_area"]
                for part in height_parts
            )
            for height_parts in parts_by_height.values()
        )
    ):
        raise ValueError(config["errors"]["part_metadata_missing"])
    return {
        height: sorted(height_parts, key=lambda part: (-part["area"], part["partId"]))
        for height, height_parts in parts_by_height.items()
    }


def tile_base_h_cells(
    cells: set[tuple[int, int]],
    base_plate: int,
    parts: list[dict[str, Any]],
    occupancy_owner: dict[tuple[int, int, int], int],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    remaining = set(cells)
    placements = []
    scan_orders = config["algorithm"]["scan_orders"]
    scan_order = scan_orders[base_plate % len(scan_orders)]
    while remaining:
        anchor_x, anchor_z = min(
            remaining,
            key=lambda cell: (
                cell[1] * scan_order["z_direction"],
                cell[0] * scan_order["x_direction"],
            ),
        )
        candidates = []
        for part in parts:
            for orientation in dem_part_orientations(part, config):
                for offset_z in range(orientation["depth"]):
                    for offset_x in range(orientation["width"]):
                        x = anchor_x - offset_x
                        z = anchor_z - offset_z
                        footprint = {
                            (cell_x, cell_z)
                            for cell_z in range(z, z + orientation["depth"])
                            for cell_x in range(x, x + orientation["width"])
                        }
                        if not footprint <= remaining:
                            continue
                        support_cells = {
                            (cell_x, cell_z, base_plate - 1)
                            for cell_x, cell_z in footprint
                        }
                        fully_supported = (
                            base_plate == config["algorithm"]["minimum_height_plate"]
                            or support_cells <= occupancy_owner.keys()
                        )
                        if not fully_supported:
                            continue
                        support_ids = {
                            occupancy_owner[cell]
                            for cell in support_cells
                            if cell in occupancy_owner
                        }
                        candidates.append(
                            {
                                "part": part,
                                "x": x,
                                "z": z,
                                "width": orientation["width"],
                                "depth": orientation["depth"],
                                "rotation": orientation["rotation"],
                                "footprint": footprint,
                                "supportSpan": len(support_ids),
                            }
                        )
        if not candidates:
            raise ValueError(config["errors"]["base_h_uncovered"])
        selected = max(
            candidates,
            key=lambda candidate: (
                candidate["part"]["area"],
                candidate["supportSpan"],
                -candidate["z"] * scan_order["z_direction"],
                -candidate["x"] * scan_order["x_direction"],
            ),
        )
        part = selected["part"]
        color = config["structure"]["color"]
        placements.append(
            {
                "partId": part["partId"],
                "rebrickablePartNum": part["rebrickablePartNum"],
                "legoDesignId": part["legoDesignId"],
                "role": part["role"],
                "colorId": color["id"],
                "colorName": color["name"],
                "colorRgb": color["rgb"],
                "ldrawColorCode": color["ldraw_code"],
                "x": selected["x"],
                "z": selected["z"],
                "basePlate": base_plate,
                "width": selected["width"],
                "depth": selected["depth"],
                "heightPlate": part["heightPlate"],
                "rotation": selected["rotation"],
            }
        )
        remaining -= selected["footprint"]
    return placements


def dem_part_orientations(part: dict[str, Any], config: dict[str, Any]) -> list[dict[str, int]]:
    orientations = [
        {
            "width": part["width"],
            "depth": part["depth"],
            "rotation": config["algorithm"]["no_rotation_degrees"],
        }
    ]
    if part["width"] != part["depth"]:
        orientations.append(
            {
                "width": part["depth"],
                "depth": part["width"],
                "rotation": config["algorithm"]["rotation_degrees"],
            }
        )
    return orientations


def validate_base_h_result(
    base_h: list[list[int]],
    placements: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, int]:
    occupied = set()
    unsupported_count = config["algorithm"]["minimum_height_plate"]
    for placement in placements:
        footprint = {
            (x, z)
            for z in range(placement["z"], placement["z"] + placement["depth"])
            for x in range(placement["x"], placement["x"] + placement["width"])
        }
        if (
            placement["basePlate"] > config["algorithm"]["minimum_height_plate"]
            and any(
                (x, z, placement["basePlate"] - 1) not in occupied
                for x, z in footprint
            )
        ):
            unsupported_count += 1
        occupied.update(
            (x, z, level)
            for x, z in footprint
            for level in range(
                placement["basePlate"],
                placement["basePlate"] + placement["heightPlate"],
            )
        )
    target_occupied = {
        (x, z, level)
        for z, row in enumerate(base_h)
        for x, height in enumerate(row)
        for level in range(height)
    }
    target_volume = len(target_occupied)
    placed_volume = len(occupied)
    if occupied != target_occupied:
        raise ValueError(config["errors"]["base_h_uncovered"])
    return {
        "targetVolumeStudPlate": target_volume,
        "placedVolumeStudPlate": placed_volume,
        "unsupportedPlacementCount": unsupported_count,
    }


def dem_structure_bom(placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: dict[tuple[str, int], dict[str, Any]] = {}
    for placement in placements:
        key = (placement["partId"], placement["colorId"])
        item = items.setdefault(
            key,
            {
                "partId": placement["partId"],
                "rebrickablePartNum": placement["rebrickablePartNum"],
                "legoDesignId": placement["legoDesignId"],
                "role": placement["role"],
                "colorId": placement["colorId"],
                "colorName": placement["colorName"],
                "colorRgb": placement["colorRgb"],
                "width": placement["width"],
                "depth": placement["depth"],
                "heightPlate": placement["heightPlate"],
                "quantity": 0,
            },
        )
        item["quantity"] += 1
    return sorted(items.values(), key=lambda item: (-item["heightPlate"], -item["width"] * item["depth"], item["partId"]))
