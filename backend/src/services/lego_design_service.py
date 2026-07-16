"""Database-backed metadata and generation for LEGO pixel design."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.model.models import (
    Color,
    LDrawPart,
    LDrawPartGeometry,
    XrefPartNumber,
)
from src.services.lego_pixmap_strategy import create_lego_base_steps, create_lego_pixmap_steps


def lego_design_metadata(engine: Engine, config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        colors = lego_design_colors(session, config)
        parts = lego_design_candidate_parts(
            session,
            config,
            config["candidate_features"]["default_footprint"],
        )
        terrain_parts = lego_design_terrain_parts(session, config)

    return {
        "colors": colors,
        "parts": parts,
        "terrainParts": terrain_parts,
    }


def lego_design_candidates(
    engine: Engine,
    config: dict[str, Any],
    footprint: str,
) -> dict[str, list[dict[str, Any]]]:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        return {
            "parts": lego_design_candidate_parts(session, config, footprint),
        }


def lego_design_candidate_parts(
    session,
    config: dict[str, Any],
    footprint: str,
) -> list[dict[str, Any]]:
    footprint_config = candidate_footprint_config(config, footprint)
    name_pattern = re.compile(footprint_config["name_pattern"])
    moved_exact_xrefs = moved_exact_xrefs_by_target(session, config)
    parts_by_num: dict[str, dict[str, Any]] = {}
    for ldraw_part, geometry, xref in session.execute(part_metadata_statement(config)):
        if not is_candidate_part_name(ldraw_part.name, name_pattern, config):
            continue
        width_stud = float(geometry.logical_width_stud)
        height_stud = float(geometry.logical_depth_stud)
        if not width_stud.is_integer() or not height_stud.is_integer():
            continue
        width = int(width_stud)
        height = int(height_stud)
        part = parts_by_num.setdefault(
            ldraw_part.ldraw_part_num,
            {
                "ldrawPartNum": ldraw_part.ldraw_part_num,
                "rebrickablePartNum": None,
                "legoDesignId": None,
                "name": ldraw_part.name,
                "partRole": config["heightmap_design"]["part_roles"]["plate"],
                "width": width,
                "height": height,
                "logicalHeightPlate": int(float(geometry.logical_height_plate)),
                "area": width * height,
                "xrefRelations": [],
                "movedExact": False,
            },
        )
        apply_candidate_xref(part, xref, config)
        apply_moved_exact_xref(part, moved_exact_xrefs.get(ldraw_part.ldraw_part_num))
    selected_parts = select_candidate_parts_by_size(
        list(parts_by_num.values()),
        config,
    )
    return sorted(selected_parts, key=lambda part: (-part["area"], part["ldrawPartNum"]))


def lego_design_terrain_parts(session, config: dict[str, Any]) -> list[dict[str, Any]]:
    moved_exact_xrefs = moved_exact_xrefs_by_target(session, config)
    parts_by_geometry: dict[tuple[str, str, int, int, int], dict[str, Any]] = {}
    for part_spec in config["heightmap_design"]["part_specs"].values():
        name_pattern = re.compile(part_spec["name_pattern"])
        for ldraw_part, geometry, xref in session.execute(part_metadata_statement(config, part_spec)):
            if not is_candidate_part_name(ldraw_part.name, name_pattern, config):
                continue
            width_stud = float(geometry.logical_width_stud)
            height_stud = float(geometry.logical_depth_stud)
            if not width_stud.is_integer() or not height_stud.is_integer():
                continue
            width = int(width_stud)
            height = int(height_stud)
            logical_height_plate = part_spec["logical_height_plate"]
            geometry_key = (part_spec["role"], ldraw_part.ldraw_part_num, width, height, logical_height_plate)
            part = parts_by_geometry.setdefault(
                geometry_key,
                {
                    "ldrawPartNum": ldraw_part.ldraw_part_num,
                    "rebrickablePartNum": None,
                    "legoDesignId": None,
                    "name": ldraw_part.name,
                    "partRole": part_spec["role"],
                    "width": width,
                    "height": height,
                    "logicalHeightPlate": logical_height_plate,
                    "area": width * height,
                    "xrefRelations": [],
                    "movedExact": False,
                },
            )
            apply_candidate_xref(part, xref, config)
            apply_moved_exact_xref(part, moved_exact_xrefs.get(ldraw_part.ldraw_part_num))
    return sorted(
        select_candidate_parts_by_geometry(list(parts_by_geometry.values()), config),
        key=lambda part: (-part["logicalHeightPlate"], -part["area"], part["ldrawPartNum"]),
    )


def select_candidate_parts_by_geometry(
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    parts_by_size: dict[tuple[str, int, int, int], list[dict[str, Any]]] = {}
    for part in parts:
        size_key = (part["partRole"], part["width"], part["height"], part["logicalHeightPlate"])
        parts_by_size.setdefault(size_key, []).append(part)
    selected = []
    for candidates in parts_by_size.values():
        part = min(candidates, key=lambda candidate: candidate_part_rank(candidate, config))
        selected.append(public_candidate_part(part))
    return selected


def apply_candidate_xref(
    part: dict[str, Any],
    xref: XrefPartNumber | None,
    config: dict[str, Any],
) -> None:
    if xref is None:
        return
    part["xrefRelations"].append(xref.relation_type)
    exact_relation_type = config["candidate_features"]["ranking"]["exact_relation_type"]
    if part["rebrickablePartNum"] is None or xref.relation_type == exact_relation_type:
        part["rebrickablePartNum"] = xref.rebrickable_part_num
        part["legoDesignId"] = xref.lego_design_id


def apply_moved_exact_xref(
    part: dict[str, Any],
    xref: XrefPartNumber | None,
) -> None:
    if xref is None:
        return
    part["movedExact"] = True
    if part["rebrickablePartNum"] is None:
        part["rebrickablePartNum"] = xref.rebrickable_part_num
        part["legoDesignId"] = xref.lego_design_id


def select_candidate_parts_by_size(
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    parts_by_size: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for part in parts:
        size_key = (part["width"], part["height"])
        parts_by_size.setdefault(size_key, []).append(part)
    selected = []
    for candidates in parts_by_size.values():
        part = min(candidates, key=lambda candidate: candidate_part_rank(candidate, config))
        selected.append(public_candidate_part(part))
    return selected


def candidate_part_rank(
    part: dict[str, Any],
    config: dict[str, Any],
) -> tuple[int, int, str]:
    ranking_config = config["candidate_features"]["ranking"]
    relations = set(part["xrefRelations"])
    if ranking_config["exact_relation_type"] in relations:
        relation_rank = ranking_config["direct_exact_rank"]
    elif part["movedExact"]:
        relation_rank = ranking_config["moved_exact_rank"]
    elif relations:
        relation_rank = ranking_config["mapped_rank"]
    else:
        relation_rank = ranking_config["unmapped_rank"]
    return (relation_rank, len(part["ldrawPartNum"]), part["ldrawPartNum"])


def public_candidate_part(part: dict[str, Any]) -> dict[str, Any]:
    return {
        "ldrawPartNum": part["ldrawPartNum"],
        "rebrickablePartNum": part["rebrickablePartNum"],
        "legoDesignId": part["legoDesignId"],
        "name": part["name"],
        "partRole": part["partRole"],
        "width": part["width"],
        "height": part["height"],
        "logicalHeightPlate": part["logicalHeightPlate"],
        "area": part["area"],
    }


def moved_exact_xrefs_by_target(session, config: dict[str, Any]) -> dict[str, XrefPartNumber]:
    candidate_config = config["candidate_features"]
    ranking_config = candidate_config["ranking"]
    name_pattern = re.compile(candidate_config["moved_to_pattern"])
    statement = (
        select(LDrawPart, XrefPartNumber)
        .join(XrefPartNumber, XrefPartNumber.ldraw_part_num == LDrawPart.ldraw_part_num)
        .where(XrefPartNumber.relation_type == ranking_config["exact_relation_type"])
    )
    xrefs_by_target = {}
    for ldraw_part, _xref in session.execute(statement):
        target = moved_target_part_num(ldraw_part.name, name_pattern, config)
        if target is not None:
            xrefs_by_target.setdefault(target, _xref)
    return xrefs_by_target


def moved_target_part_num(
    name: str | None,
    name_pattern: re.Pattern,
    config: dict[str, Any],
) -> str | None:
    if name is None:
        return None
    normalized_name = config["candidate_features"]["name_space_separator"].join(name.split())
    match = name_pattern.fullmatch(normalized_name)
    if match is None:
        return None
    target = match.group(config["candidate_features"]["moved_target_group"])
    if target.endswith(config["candidate_features"]["ldraw_part_suffix"]):
        return target
    return f"{target}{config['candidate_features']['ldraw_part_suffix']}"


def candidate_footprint_config(config: dict[str, Any], footprint: str) -> dict[str, Any]:
    footprint_config = config["candidate_features"]["footprints"].get(footprint)
    if footprint_config is None:
        raise ValueError(config["errors"]["candidate_feature_not_found"])
    return footprint_config


def is_candidate_part_name(name: str | None, name_pattern: re.Pattern, config: dict[str, Any]) -> bool:
    if name is None:
        return False
    normalized_name = config["candidate_features"]["name_space_separator"].join(name.split())
    return name_pattern.fullmatch(normalized_name) is not None


def create_lego_design_result(
    project: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    update_progress,
) -> dict[str, Any]:
    if not metadata["colors"] or not metadata["parts"]:
        return empty_design_result(project, config)

    update_progress(config["progress"]["metadata_loaded"])
    algorithm_config = config["algorithm"]
    colors = [
        design_color(color, algorithm_config, config["ldraw"])
        for color in metadata["colors"]
    ]
    parts = normalized_parts(metadata["parts"])
    color_mappings = map_project_colors(project, colors, algorithm_config)
    color_mapping_by_rgb = {
        mapping["sourceRgb"]: mapping
        for mapping in color_mappings
    }
    pixel_color_ids = {}
    for pixel in project["pixels"]:
        mapping = color_mapping_by_rgb.get(pixel["rgb"])
        if mapping is not None:
            pixel_color_ids[cell_key(pixel["x"], pixel["y"], algorithm_config)] = mapping["colorId"]

    components = connected_components(project, pixel_color_ids, algorithm_config)
    update_progress(config["progress"]["components_ready"])
    placements = []
    component_count = max(len(components), algorithm_config["minimum_area"])
    for index, component in enumerate(components):
        color = next(candidate for candidate in colors if candidate["id"] == component["colorId"])
        placements.extend(solve_component(component, parts, color, algorithm_config))
        progress_span = config["progress"]["complete"] - config["progress"]["components_ready"]
        update_progress(
            config["progress"]["components_ready"]
            + int(progress_span * (index + algorithm_config["minimum_area"]) / component_count)
        )
    merged_placements = merge_same_color_rectangles(placements, parts, algorithm_config)
    validate_design_coverage(pixel_color_ids, merged_placements, algorithm_config, config)

    return {
        "width": project["gridWidth"],
        "height": project["gridHeight"],
        "placements": merged_placements,
        "bom": create_bom(merged_placements, algorithm_config),
        "colorMappings": color_mappings,
        "modelDimensions": model_dimensions(merged_placements, config),
    }


def create_lego_design_result_from_heightmap(
    heightmap: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    update_progress,
) -> dict[str, Any]:
    if not metadata["terrainParts"]:
        return empty_heightmap_design_result(heightmap, config)

    update_progress(config["progress"]["metadata_loaded"])
    terrain_color = heightmap_design_color(config)
    land_cover_colors = heightmap_land_cover_colors(heightmap, metadata, config)
    terrain_parts = normalized_terrain_parts(metadata["terrainParts"])
    slope_surface = heightmap_slope_surface(
        heightmap,
        terrain_parts,
        land_cover_colors["colorsByCell"],
        terrain_color,
        config,
    )
    structure_heightmap = heightmap_structure_heightmap(heightmap, slope_surface["depthByCell"], config)
    modules = decompose_heightmap_modules(structure_heightmap, config)
    placements = []
    module_count = max(len(modules), config["algorithm"]["minimum_area"])
    for index, module in enumerate(modules):
        placements.extend(heightmap_module_placements(module, terrain_parts, terrain_color, config))
        progress_span = config["progress"]["complete"] - config["progress"]["metadata_loaded"]
        update_progress(
            config["progress"]["metadata_loaded"]
            + int(progress_span * (index + config["algorithm"]["minimum_area"]) / module_count)
        )

    surface_module = heightmap_surface_module(heightmap, config)
    surface_placements = heightmap_surface_plate_placements(
        heightmap,
        slope_surface["cellKeys"],
        terrain_parts,
        land_cover_colors["colorsByCell"],
        terrain_color,
        config,
    ) + slope_surface["placements"]
    if surface_placements:
        modules.append(surface_module)
        placements.extend(surface_placements)

    return {
        "width": heightmap["metrics"]["widthStud"],
        "height": heightmap["metrics"]["depthStud"],
        "placements": placements,
        "bom": create_bom(placements, config["algorithm"]),
        "colorMappings": land_cover_colors["colorMappings"],
        "modules": modules,
        "modelDimensions": model_dimensions(placements, config),
    }


def normalized_terrain_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(parts, key=lambda part: (-part["logicalHeightPlate"], -part["area"], part["ldrawPartNum"]))


def heightmap_structure_heightmap(
    heightmap: dict[str, Any],
    slope_depth_by_cell: dict[str, int],
    config: dict[str, Any],
) -> dict[str, Any]:
    heightmap_config = config["heightmap_design"]
    plate_depth = heightmap_config["part_specs"]["plate"]["logical_height_plate"]
    return {
        **heightmap,
        "cells": [
            {
                **cell,
                "heightPlate": max(
                    0,
                    cell["heightPlate"] - slope_depth_by_cell.get(
                        cell_key(cell["x"], cell["z"], config["algorithm"]),
                        plate_depth,
                    ),
                ),
            }
            for cell in heightmap["cells"]
        ],
    }


def heightmap_surface_module(heightmap: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    heightmap_config = config["heightmap_design"]
    return {
        "id": heightmap_config["surface_module_id"],
        "moduleType": heightmap_config["module_types"]["surface"],
        "originX": 0,
        "originZ": 0,
        "originYPlate": 0,
        "width": heightmap["metrics"]["widthStud"],
        "depth": heightmap["metrics"]["depthStud"],
        "heightPlate": max(cell["heightPlate"] for cell in heightmap["cells"]),
        "wallThickness": 0,
    }


def heightmap_surface_plate_placements(
    heightmap: dict[str, Any],
    slope_cell_keys: set[str],
    terrain_parts: list[dict[str, Any]],
    colors_by_cell: dict[str, dict[str, Any]],
    terrain_color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    heightmap_config = config["heightmap_design"]
    plate_role = heightmap_config["part_roles"]["plate"]
    plate_height = heightmap_config["part_specs"]["plate"]["logical_height_plate"]
    plate_parts = [
        part for part in terrain_parts
        if part["partRole"] == plate_role and part["logicalHeightPlate"] == plate_height
    ]
    if not plate_parts:
        raise ValueError(config["errors"]["heightmap_cover_part_not_found"])
    groups: dict[tuple[int, str], dict[str, Any]] = {}
    for cell in heightmap["cells"]:
        cell_key_value = cell_key(cell["x"], cell["z"], config["algorithm"])
        if cell["heightPlate"] <= 0 or cell_key_value in slope_cell_keys:
            continue
        color = colors_by_cell.get(cell_key_value, terrain_color)
        level = cell["heightPlate"] - plate_height
        group = groups.setdefault(
            (level, color_key(color, config["algorithm"])),
            {"level": level, "color": color, "cellKeys": set()},
        )
        group["cellKeys"].add(cell_key_value)
    placements = []
    for group in groups.values():
        group_placements = solve_support_keys(
            group["cellKeys"],
            group["color"],
            plate_parts,
            config["algorithm"],
        )
        placements.extend(
            {
                **placement,
                "yLdu": heightmap_level_y_ldu(group["level"], config),
                "moduleId": heightmap_config["surface_module_id"],
                "moduleStage": heightmap_config["module_stages"]["surface"],
            }
            for placement in group_placements
        )
    return placements


def heightmap_slope_surface(
    heightmap: dict[str, Any],
    terrain_parts: list[dict[str, Any]],
    colors_by_cell: dict[str, dict[str, Any]],
    terrain_color: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    heightmap_config = config["heightmap_design"]
    slope_config = heightmap_config["slope"]
    slope_role = heightmap_config["part_roles"]["slope"]
    slope_parts = [part for part in terrain_parts if part["partRole"] == slope_role]
    cells_by_key = {
        cell_key(cell["x"], cell["z"], config["algorithm"]): cell
        for cell in heightmap["cells"]
    }
    has_height_drop = any(
        cell["elevationMeters"] is not None
        and neighbor is not None
        and neighbor["elevationMeters"] is not None
        and neighbor["heightPlate"] < cell["heightPlate"]
        for cell in heightmap["cells"]
        for direction in slope_config["directions"]
        if (
            neighbor := cells_by_key.get(cell_key(
                cell["x"] + direction["neighbor_x"],
                cell["z"] + direction["neighbor_z"],
                config["algorithm"],
            ))
        ) is not None
    )
    if not has_height_drop:
        return {"cellKeys": set(), "depthByCell": {}, "placements": []}
    if not slope_parts:
        raise ValueError(config["errors"]["heightmap_slope_part_not_found"])
    used_cell_keys = set()
    depth_by_cell = {}
    placements = []

    corner_dimensions = slope_config["part_dimensions"]["corner"]
    corner_part = heightmap_slope_part(
        slope_parts,
        corner_dimensions["width"],
        corner_dimensions["depth"],
        config,
    )
    width = heightmap["metrics"]["widthStud"]
    depth = heightmap["metrics"]["depthStud"]
    for origin_z in range(depth - corner_dimensions["depth"] + 1):
        for origin_x in range(width - corner_dimensions["width"] + 1):
            corner_cells = [
                cells_by_key[cell_key(x, z, config["algorithm"])]
                for z in range(origin_z, origin_z + corner_dimensions["depth"])
                for x in range(origin_x, origin_x + corner_dimensions["width"])
            ]
            corner_keys = {
                cell_key(cell["x"], cell["z"], config["algorithm"])
                for cell in corner_cells
            }
            if corner_keys & used_cell_keys:
                continue
            if any(cell["elevationMeters"] is None for cell in corner_cells):
                continue
            high_height = max(cell["heightPlate"] for cell in corner_cells)
            high_cells = [cell for cell in corner_cells if cell["heightPlate"] == high_height]
            low_cells = [cell for cell in corner_cells if cell["heightPlate"] != high_height]
            if len(high_cells) != 1 or len({cell["heightPlate"] for cell in low_cells}) != 1:
                continue
            low_height = low_cells[0]["heightPlate"]
            if high_height - low_height != slope_config["corner_height_difference_plate"]:
                continue
            colors = [
                colors_by_cell.get(key, terrain_color)
                for key in corner_keys
            ]
            if len({color_key(color, config["algorithm"]) for color in colors}) != 1:
                continue
            high_cell = high_cells[0]
            rotation = next(
                item["rotation"]
                for item in slope_config["corner_rotations"]
                if item["high_x"] == high_cell["x"] - origin_x
                and item["high_z"] == high_cell["z"] - origin_z
            )
            color = colors_by_cell.get(
                cell_key(high_cell["x"], high_cell["z"], config["algorithm"]),
                terrain_color,
            )
            placements.append(heightmap_slope_placement(
                corner_part,
                color,
                origin_x,
                origin_z,
                rotation,
                high_height - corner_part["logicalHeightPlate"],
                config,
            ))
            used_cell_keys.update(corner_keys)
            depth_by_cell.update({key: 0 for key in corner_keys})
            depth_by_cell[cell_key(high_cell["x"], high_cell["z"], config["algorithm"])] = corner_part["logicalHeightPlate"]

    straight_dimensions = slope_config["part_dimensions"]["straight"]
    straight_part = heightmap_slope_part(
        slope_parts,
        straight_dimensions["width"],
        straight_dimensions["depth"],
        config,
    )
    for cell in heightmap["cells"]:
        first_key = cell_key(cell["x"], cell["z"], config["algorithm"])
        if first_key in used_cell_keys or cell["heightPlate"] < straight_part["logicalHeightPlate"]:
            continue
        first_color = colors_by_cell.get(first_key, terrain_color)
        for direction in slope_config["directions"]:
            second_x = cell["x"] + direction["pair_x"]
            second_z = cell["z"] + direction["pair_z"]
            second_key = cell_key(second_x, second_z, config["algorithm"])
            second_cell = cells_by_key.get(second_key)
            if second_key in used_cell_keys or second_cell is None or second_cell["heightPlate"] != cell["heightPlate"]:
                continue
            second_color = colors_by_cell.get(second_key, terrain_color)
            if color_key(first_color, config["algorithm"]) != color_key(second_color, config["algorithm"]):
                continue
            neighbor_keys = [
                cell_key(
                    slope_x + direction["neighbor_x"],
                    slope_z + direction["neighbor_z"],
                    config["algorithm"],
                )
                for slope_x, slope_z in [(cell["x"], cell["z"]), (second_x, second_z)]
            ]
            if any(neighbor_key not in cells_by_key for neighbor_key in neighbor_keys):
                continue
            neighbor_heights = [cells_by_key[neighbor_key]["heightPlate"] for neighbor_key in neighbor_keys]
            if any(cells_by_key[neighbor_key]["elevationMeters"] is None for neighbor_key in neighbor_keys):
                continue
            if any(
                cell["heightPlate"] - neighbor_height < slope_config["minimum_height_difference_plate"]
                for neighbor_height in neighbor_heights
            ):
                continue
            x = min(cell["x"], second_x)
            z = min(cell["z"], second_z)
            placements.append(heightmap_slope_placement(
                straight_part,
                first_color,
                x,
                z,
                direction["rotation"],
                cell["heightPlate"] - straight_part["logicalHeightPlate"],
                config,
            ))
            used_cell_keys.update([first_key, second_key])
            depth_by_cell[first_key] = straight_part["logicalHeightPlate"]
            depth_by_cell[second_key] = straight_part["logicalHeightPlate"]
            break

    single_dimensions = slope_config["part_dimensions"]["single"]
    single_part = heightmap_slope_part(
        slope_parts,
        single_dimensions["width"],
        single_dimensions["depth"],
        config,
    )
    for cell in heightmap["cells"]:
        cell_key_value = cell_key(cell["x"], cell["z"], config["algorithm"])
        if cell_key_value in used_cell_keys:
            continue
        lower_directions = [
            direction
            for direction in slope_config["directions"]
            if (
                neighbor := cells_by_key.get(cell_key(
                    cell["x"] + direction["neighbor_x"],
                    cell["z"] + direction["neighbor_z"],
                    config["algorithm"],
                ))
            ) is not None
            and neighbor["elevationMeters"] is not None
            and cell["heightPlate"] - neighbor["heightPlate"] >= slope_config["minimum_height_difference_plate"]
        ]
        if not lower_directions:
            continue
        direction = max(
            lower_directions,
            key=lambda item: cell["heightPlate"] - cells_by_key[cell_key(
                cell["x"] + item["neighbor_x"],
                cell["z"] + item["neighbor_z"],
                config["algorithm"],
            )]["heightPlate"],
        )
        surface_depth = min(cell["heightPlate"], single_part["logicalHeightPlate"])
        color = colors_by_cell.get(cell_key_value, terrain_color)
        placements.append(heightmap_slope_placement(
            single_part,
            color,
            cell["x"],
            cell["z"],
            direction["rotation"],
            cell["heightPlate"] - surface_depth,
            config,
        ))
        used_cell_keys.add(cell_key_value)
        depth_by_cell[cell_key_value] = surface_depth
    return {"cellKeys": used_cell_keys, "depthByCell": depth_by_cell, "placements": placements}


def heightmap_slope_part(
    slope_parts: list[dict[str, Any]],
    footprint_width: int,
    footprint_depth: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    candidates = [
        part for part in slope_parts
        if any(
            orientation["width"] == footprint_width and orientation["height"] == footprint_depth
            for orientation in orientations(part, config["algorithm"])
        )
    ]
    if not candidates:
        raise ValueError(config["errors"]["heightmap_slope_part_not_found"])
    return max(candidates, key=lambda part: part["area"])


def heightmap_slope_placement(
    part: dict[str, Any],
    color: dict[str, Any],
    x: int,
    z: int,
    rotation: int,
    level: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    swap_dimensions = rotation in config["heightmap_design"]["slope"]["dimension_swap_rotations"]
    placement_width = part["height"] if swap_dimensions else part["width"]
    placement_height = part["width"] if swap_dimensions else part["height"]
    return public_placement(
        {
            "partId": part["ldrawPartNum"],
            "rebrickablePartNum": part["rebrickablePartNum"],
            "legoDesignId": part["legoDesignId"],
            "colorId": color["id"],
            "colorName": color["name"],
            "colorRgb": color["hex"],
            "ldrawColorCode": color["ldrawCode"],
            "x": x,
            "y": z,
            "width": placement_width,
            "height": placement_height,
            "logicalHeightPlate": part["logicalHeightPlate"],
            "rotation": rotation,
            "yLdu": heightmap_level_y_ldu(level, config),
            "moduleId": config["heightmap_design"]["surface_module_id"],
            "moduleStage": config["heightmap_design"]["module_stages"]["slope"],
        }
    )


def heightmap_module_placements(
    module: dict[str, Any],
    terrain_parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    heightmap_config = config["heightmap_design"]
    if module["moduleType"] == heightmap_config["module_types"]["cavity"]:
        return heightmap_cavity_module_placements(module, terrain_parts, color, config)
    return heightmap_solid_module_placements(module, terrain_parts, color, config)


def heightmap_solid_module_placements(
    module: dict[str, Any],
    terrain_parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    stage = config["heightmap_design"]["module_stages"]["solid"]
    placements = []
    remaining_height = module["heightPlate"]
    level = module["originYPlate"]
    rectangle = {
        "x": module["originX"],
        "y": module["originZ"],
        "width": module["width"],
        "height": module["depth"],
        "area": module["width"] * module["depth"],
    }
    structural_parts = [
        part for part in terrain_parts
        if part["partRole"] != config["heightmap_design"]["part_roles"]["slope"]
    ]
    while remaining_height > 0:
        layer_height = max(
            part["logicalHeightPlate"]
            for part in structural_parts
            if part["logicalHeightPlate"] <= remaining_height
        )
        layer_parts = [part for part in structural_parts if part["logicalHeightPlate"] == layer_height]
        layer_placements = fill_rectangle_greedy(rectangle, layer_parts, color, config["algorithm"])
        if not layer_placements:
            raise ValueError(config["errors"]["heightmap_column_part_not_found"])
        placements.extend(
            {
                **placement,
                "yLdu": heightmap_level_y_ldu(level, config),
                "moduleId": module["id"],
                "moduleStage": stage,
            }
            for placement in layer_placements
        )
        remaining_height -= layer_height
        level += layer_height
    return placements


def heightmap_cavity_module_placements(
    module: dict[str, Any],
    terrain_parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    cover_height = config["heightmap_design"]["part_specs"]["plate"]["logical_height_plate"]
    column_height = module["heightPlate"] - cover_height
    top_cover = heightmap_top_cover_placements(module, terrain_parts, color, config)
    support_spacing = heightmap_support_spacing(top_cover, config)
    placements = []
    for cell in heightmap_cavity_column_cells(module, support_spacing):
        stage = config["heightmap_design"]["module_stages"]["wall"] if cell["isWall"] else config["heightmap_design"]["module_stages"]["support"]
        placements.extend(
            heightmap_column_placements(
                cell["x"],
                cell["z"],
                module["originYPlate"],
                column_height,
                terrain_parts,
                color,
                config,
                module["id"],
                stage,
            )
        )
    placements.extend(top_cover)
    return placements


def heightmap_column_placements(
    x: int,
    z: int,
    origin_y_plate: int,
    height_plate: int,
    terrain_parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
    module_id: str,
    module_stage: str,
) -> list[dict[str, Any]]:
    column_parts = heightmap_column_parts(terrain_parts, config)
    placements = []
    remaining_height = height_plate
    level = origin_y_plate
    for part in column_parts:
        while remaining_height >= part["logicalHeightPlate"]:
            placements.append(heightmap_part_placement(part, color, x, z, level, config, module_id, module_stage))
            remaining_height -= part["logicalHeightPlate"]
            level += part["logicalHeightPlate"]
    if remaining_height != 0:
        raise ValueError(config["errors"]["heightmap_column_part_not_found"])
    return placements


def heightmap_column_parts(parts: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    wall_thickness = config["heightmap_design"]["cavity"]["wall_thickness"]
    selected_parts = [
        part
        for part in parts
        if part["width"] == wall_thickness and part["height"] == wall_thickness
    ]
    if not selected_parts:
        raise ValueError(config["errors"]["heightmap_column_part_not_found"])
    return selected_parts


def heightmap_top_cover_placements(
    module: dict[str, Any],
    terrain_parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    plate_height = config["heightmap_design"]["part_specs"]["plate"]["logical_height_plate"]
    plate_parts = [
        part
        for part in terrain_parts
        if part["logicalHeightPlate"] == plate_height
    ]
    if not plate_parts:
        raise ValueError(config["errors"]["heightmap_cover_part_not_found"])
    rectangle = {
        "x": module["originX"],
        "y": module["originZ"],
        "width": module["width"],
        "height": module["depth"],
        "area": module["width"] * module["depth"],
    }
    placements = fill_rectangle_greedy(rectangle, plate_parts, color, config["algorithm"])
    if not placements:
        raise ValueError(config["errors"]["heightmap_cover_part_not_found"])
    y_ldu = heightmap_level_y_ldu(
        module["originYPlate"] + module["heightPlate"] - plate_height,
        config,
    )
    return [
        {
            **placement,
            "yLdu": y_ldu,
            "moduleId": module["id"],
            "moduleStage": config["heightmap_design"]["module_stages"]["cover"],
        }
        for placement in placements
    ]


def heightmap_support_spacing(top_cover: list[dict[str, Any]], config: dict[str, Any]) -> int:
    shortest_side = min(
        min(placement["width"], placement["height"])
        for placement in top_cover
    )
    return max(config["algorithm"]["minimum_area"], shortest_side - config["algorithm"]["minimum_area"])


def heightmap_cavity_column_cells(module: dict[str, Any], support_spacing: int) -> list[dict[str, int]]:
    cells = []
    max_x = module["originX"] + module["width"]
    max_z = module["originZ"] + module["depth"]
    wall_thickness = module["wallThickness"]
    inner_min_x = module["originX"] + wall_thickness
    inner_max_x = max_x - wall_thickness
    inner_min_z = module["originZ"] + wall_thickness
    inner_max_z = max_z - wall_thickness
    for z in range(module["originZ"], max_z):
        for x in range(module["originX"], max_x):
            if x < inner_min_x or x >= inner_max_x or z < inner_min_z or z >= inner_max_z:
                cells.append({"x": x, "z": z, "isWall": True})
            elif (x - inner_min_x) % support_spacing == 0 and (z - inner_min_z) % support_spacing == 0:
                cells.append({"x": x, "z": z, "isWall": False})
    return cells


def heightmap_part_placement(
    part: dict[str, Any],
    color: dict[str, Any],
    x: int,
    z: int,
    level: int,
    config: dict[str, Any],
    module_id: str,
    module_stage: str,
) -> dict[str, Any]:
    return public_placement(
        {
            "partId": part["ldrawPartNum"],
            "rebrickablePartNum": part["rebrickablePartNum"],
            "legoDesignId": part["legoDesignId"],
            "colorId": color["id"],
            "colorName": color["name"],
            "colorRgb": color["hex"],
            "ldrawColorCode": color["ldrawCode"],
            "x": x,
            "y": z,
            "width": part["width"],
            "height": part["height"],
            "logicalHeightPlate": part["logicalHeightPlate"],
            "rotation": config["heightmap_design"]["part_rotation"],
            "yLdu": heightmap_level_y_ldu(level, config),
            "moduleId": module_id,
            "moduleStage": module_stage,
        }
    )


def decompose_heightmap_modules(heightmap: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    remaining_heights = heightmap_plate_matrix(heightmap)
    origin_heights = [
        [0 for _column in row]
        for row in remaining_heights
    ]
    modules = []
    while True:
        cuboid = largest_heightmap_cuboid(origin_heights, remaining_heights)
        if cuboid is None:
            return modules
        modules.append(public_heightmap_module(cuboid, len(modules), config))
        apply_heightmap_cuboid(cuboid, origin_heights, remaining_heights)


def heightmap_plate_matrix(heightmap: dict[str, Any]) -> list[list[int]]:
    width = heightmap["metrics"]["widthStud"]
    depth = heightmap["metrics"]["depthStud"]
    matrix = [
        [0 for _x in range(width)]
        for _z in range(depth)
    ]
    for cell in heightmap["cells"]:
        if cell["elevationMeters"] is not None:
            matrix[cell["z"]][cell["x"]] = cell["heightPlate"]
    return matrix


def largest_heightmap_cuboid(
    origin_heights: list[list[int]],
    remaining_heights: list[list[int]],
) -> dict[str, int] | None:
    best_cuboid = None
    best_volume = 0
    best_area = 0
    for origin_z, row in enumerate(remaining_heights):
        for origin_x, remaining_height in enumerate(row):
            if remaining_height > 0:
                cuboid = largest_heightmap_cuboid_from_cell(origin_x, origin_z, origin_heights, remaining_heights)
                volume = cuboid["width"] * cuboid["depth"] * cuboid["heightPlate"]
                area = cuboid["width"] * cuboid["depth"]
                if volume > best_volume or volume == best_volume and area > best_area:
                    best_cuboid = cuboid
                    best_volume = volume
                    best_area = area
    return best_cuboid


def largest_heightmap_cuboid_from_cell(
    origin_x: int,
    origin_z: int,
    origin_heights: list[list[int]],
    remaining_heights: list[list[int]],
) -> dict[str, int]:
    base_height = origin_heights[origin_z][origin_x]
    best_width = 1
    best_depth = 1
    best_height = remaining_heights[origin_z][origin_x]
    best_volume = best_height
    best_area = 1
    column_heights = [None for _x in range(len(remaining_heights[origin_z]) - origin_x)]
    max_width = len(column_heights)
    for end_z in range(origin_z, len(remaining_heights)):
        row_width = heightmap_row_width_at_base(origin_x, end_z, base_height, origin_heights, remaining_heights)
        max_width = min(max_width, row_width)
        if max_width == 0:
            return {
                "originX": origin_x,
                "originZ": origin_z,
                "originYPlate": base_height,
                "width": best_width,
                "depth": best_depth,
                "heightPlate": best_height,
            }
        for offset in range(max_width):
            height = remaining_heights[end_z][origin_x + offset]
            column_heights[offset] = height if column_heights[offset] is None else min(column_heights[offset], height)
        depth = end_z - origin_z + 1
        min_height = None
        for offset in range(max_width):
            min_height = column_heights[offset] if min_height is None else min(min_height, column_heights[offset])
            width = offset + 1
            area = width * depth
            volume = area * min_height
            if volume > best_volume or volume == best_volume and area > best_area:
                best_width = width
                best_depth = depth
                best_height = min_height
                best_volume = volume
                best_area = area
    return {
        "originX": origin_x,
        "originZ": origin_z,
        "originYPlate": base_height,
        "width": best_width,
        "depth": best_depth,
        "heightPlate": best_height,
    }


def heightmap_row_width_at_base(
    origin_x: int,
    z: int,
    base_height: int,
    origin_heights: list[list[int]],
    remaining_heights: list[list[int]],
) -> int:
    width = 0
    for x in range(origin_x, len(remaining_heights[z])):
        if origin_heights[z][x] != base_height or remaining_heights[z][x] == 0:
            return width
        width += 1
    return width


def public_heightmap_module(cuboid: dict[str, int], module_index: int, config: dict[str, Any]) -> dict[str, Any]:
    heightmap_config = config["heightmap_design"]
    cavity_config = heightmap_config["cavity"]
    is_cavity = (
        cuboid["width"] >= cavity_config["min_width"]
        and cuboid["depth"] >= cavity_config["min_depth"]
        and cuboid["heightPlate"] >= cavity_config["min_height_plate"]
    )
    return {
        "id": heightmap_module_id(module_index, heightmap_config),
        "moduleType": heightmap_config["module_types"]["cavity"] if is_cavity else heightmap_config["module_types"]["solid"],
        "originX": cuboid["originX"],
        "originZ": cuboid["originZ"],
        "originYPlate": cuboid["originYPlate"],
        "width": cuboid["width"],
        "depth": cuboid["depth"],
        "heightPlate": cuboid["heightPlate"],
        "wallThickness": cavity_config["wall_thickness"] if is_cavity else 0,
    }


def heightmap_module_id(module_index: int, heightmap_config: dict[str, Any]) -> str:
    module_number = module_index + heightmap_config["module_id_start"]
    return f"{heightmap_config['module_id_prefix']}{heightmap_config['module_id_separator']}{module_number}"


def apply_heightmap_cuboid(
    cuboid: dict[str, int],
    origin_heights: list[list[int]],
    remaining_heights: list[list[int]],
) -> None:
    for z in range(cuboid["originZ"], cuboid["originZ"] + cuboid["depth"]):
        for x in range(cuboid["originX"], cuboid["originX"] + cuboid["width"]):
            remaining_heights[z][x] -= cuboid["heightPlate"]
            origin_heights[z][x] += cuboid["heightPlate"]


def heightmap_design_color(config: dict[str, Any]) -> dict[str, Any]:
    color = config["heightmap_design"]["terrain_color"]
    return {
        "id": color["id"],
        "name": color["name"],
        "hex": color["rgb"],
        "ldrawCode": color["ldraw_code"],
    }


def heightmap_land_cover_colors(
    heightmap: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    algorithm_config = config["algorithm"]
    assignment_config = config["heightmap_design"]["color_assignment"]
    colors = [
        design_color(color, algorithm_config, config["ldraw"])
        for color in metadata["colors"]
    ]
    cells_by_source: dict[str, list[dict[str, Any]]] = {}
    for cell in heightmap["cells"]:
        if cell["heightPlate"] <= 0 or cell["elevationMeters"] is None or cell.get("landCoverColor") is None:
            continue
        source_rgb = normalize_hex(cell["landCoverColor"], algorithm_config)
        cells_by_source.setdefault(source_rgb, []).append(cell)
    source_colors = sorted(
        cells_by_source,
        key=lambda source_rgb: (-len(cells_by_source[source_rgb]), source_rgb),
    )
    assignments = {}
    assigned_color_ids = set()
    for source_rgb in source_colors:
        if not colors:
            color = heightmap_design_color(config)
        else:
            candidates = sorted(
                colors,
                key=lambda candidate: color_distance(parse_rgb(source_rgb, algorithm_config), candidate),
            )[:assignment_config["candidate_color_count"]]
            color = candidates[0]
            if len(cells_by_source[source_rgb]) >= assignment_config["minimum_preserved_cell_count"]:
                color = next(
                    (candidate for candidate in candidates if candidate["id"] not in assigned_color_ids),
                    color,
                )
        assignments[source_rgb] = color
        assigned_color_ids.add(color["id"])
    colors_by_cell = {
        cell_key(cell["x"], cell["z"], algorithm_config): assignments[source_rgb]
        for source_rgb, cells in cells_by_source.items()
        for cell in cells
    }
    color_mappings = [
        {
            "sourceRgb": source_rgb,
            "colorId": assignments[source_rgb]["id"],
            "colorName": assignments[source_rgb]["name"],
            "colorRgb": assignments[source_rgb]["hex"],
            "ldrawColorCode": assignments[source_rgb]["ldrawCode"],
        }
        for source_rgb in source_colors
    ]
    return {"colorsByCell": colors_by_cell, "colorMappings": color_mappings}


def color_key(color: dict[str, Any], config: dict[str, Any]) -> str:
    return config["cell_key_separator"].join([str(color["id"]), color["ldrawCode"]])


def empty_heightmap_design_result(heightmap: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "width": heightmap["metrics"]["widthStud"],
        "height": heightmap["metrics"]["depthStud"],
        "placements": [],
        "bom": [],
        "colorMappings": [],
        "modules": [],
        "modelDimensions": empty_model_dimensions(config),
    }


def export_lego_design_ldraw(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    include_base: bool,
    config: dict[str, Any],
) -> str:
    ldraw_config = config["ldraw"]
    validate_design_parts_available(design, metadata, config)
    if design.get("modules"):
        return export_lego_terrain_ldraw(design, metadata, include_base, config)
    lines = ldraw_header(ldraw_config)
    support = create_support_base_placements(design, metadata, config) if include_base else None
    steps = create_lego_pixmap_steps(design, support, include_base, config)
    lines.extend(ldraw_step_lines(steps, design["width"], design["height"], config))
    return ldraw_config["line_separator"].join(lines) + ldraw_config["line_separator"]


def export_lego_design_plan(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    include_base: bool,
    config: dict[str, Any],
) -> dict[str, Any]:
    validate_design_parts_available(design, metadata, config)
    if design.get("modules"):
        return export_lego_terrain_plan(design, metadata, include_base, config)
    ldraw_config = config["ldraw"]
    plan_config = config["plan_export"]
    layers = []
    support = create_support_base_placements(design, metadata, config) if include_base else None
    if include_base:
        layers.append(
            plan_layer(
                plan_config["layer_ids"]["black_support"],
                plan_config["layer_names"]["black_support"],
                plan_config["layer_order"]["black_support"],
                ldraw_config["black_support_y_ldu"],
                support["blackSupport"],
                design["width"],
                design["height"],
                config,
            )
        )
        layers.append(
            plan_layer(
                plan_config["layer_ids"]["white_base"],
                plan_config["layer_names"]["white_base"],
                plan_config["layer_order"]["white_base"],
                ldraw_config["white_base_y_ldu"],
                support["whiteBase"],
                design["width"],
                design["height"],
                config,
            )
        )
    layers.append(
        plan_layer(
            plan_config["layer_ids"]["top_design"],
            plan_config["layer_names"]["top_design"],
            plan_config["layer_order"]["top_design"],
            ldraw_config["top_design_y_ldu"],
            design["placements"],
            design["width"],
            design["height"],
            config,
        )
    )
    steps = create_lego_pixmap_steps(design, support, include_base, config)
    return {
        "format": plan_config["format"],
        "includeSupportBase": include_base,
        "grid": {
            "width": design["width"],
            "height": design["height"],
        },
        "ldrawProjection": {
            "lduPerStud": ldraw_config["ldu_per_stud"],
            "gridRotationMatrices": ldraw_config["grid_rotation_matrices"],
            "xOriginGridWidthMultiplier": ldraw_config["x_origin_grid_width_multiplier"],
            "xDirection": ldraw_config["x_direction"],
            "zOriginGridHeightMultiplier": ldraw_config["z_origin_grid_height_multiplier"],
            "zDirection": ldraw_config["z_direction"],
        },
        "layers": layers,
        "steps": [
            plan_step(step, design["width"], design["height"], config)
            for step in steps
        ],
        "modelDimensions": design["modelDimensions"],
        "bom": design["bom"],
        "colorMappings": design["colorMappings"],
    }


def export_lego_terrain_ldraw(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    include_base: bool,
    config: dict[str, Any],
) -> str:
    ldraw_config = config["ldraw"]
    submodel_config = ldraw_config["submodels"]
    lines = ldraw_header(ldraw_config)
    lines.extend(ldraw_section(submodel_config["main_assembly_name"], ldraw_config))
    if include_base:
        support = create_support_base_placements(design, metadata, config)
        base_steps = terrain_base_steps(support, design, config)
        lines.extend(ldraw_step_lines(base_steps, design["width"], design["height"], config))
        if base_steps:
            lines.append(ldraw_step_line(ldraw_config))
    for module in design["modules"]:
        lines.append(ldraw_submodel_reference_line(module, config))
    for module in design["modules"]:
        lines.append(ldraw_meta_line(ldraw_config["file_command"], terrain_module_file_name(module, config), ldraw_config))
        lines.extend(ldraw_section(module["id"], ldraw_config))
        module_steps = terrain_module_steps(module, design, config)
        lines.extend(ldraw_step_lines(module_steps, design["width"], design["height"], config))
    return ldraw_config["line_separator"].join(lines) + ldraw_config["line_separator"]


def ldraw_submodel_reference_line(module: dict[str, Any], config: dict[str, Any]) -> str:
    submodel_config = config["ldraw"]["submodels"]
    return " ".join(
        [
            str(config["ldraw"]["part_line_type"]),
            submodel_config["reference_color_code"],
            str(submodel_config["reference_x_ldu"]),
            str(submodel_config["reference_y_ldu"]),
            str(submodel_config["reference_z_ldu"]),
            *[str(value) for value in submodel_config["reference_matrix"]],
            terrain_module_file_name(module, config),
        ]
    )


def terrain_module_file_name(module: dict[str, Any], config: dict[str, Any]) -> str:
    return config["ldraw"]["submodels"]["file_name_template"].format(module_id=module["id"])


def export_lego_terrain_plan(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    include_base: bool,
    config: dict[str, Any],
) -> dict[str, Any]:
    ldraw_config = config["ldraw"]
    plan_config = config["plan_export"]
    support = create_support_base_placements(design, metadata, config) if include_base else None
    layers = []
    if include_base:
        layers.append(
            plan_layer(
                plan_config["layer_ids"]["black_support"],
                plan_config["layer_names"]["black_support"],
                plan_config["layer_order"]["black_support"],
                ldraw_config["black_support_y_ldu"],
                support["blackSupport"],
                design["width"],
                design["height"],
                config,
            )
        )
        layers.append(
            plan_layer(
                plan_config["layer_ids"]["white_base"],
                plan_config["layer_names"]["white_base"],
                plan_config["layer_order"]["white_base"],
                ldraw_config["white_base_y_ldu"],
                support["whiteBase"],
                design["width"],
                design["height"],
                config,
            )
        )
    layers.extend([
        plan_layer(
            module["id"],
            module["id"],
            index + config["heightmap_design"]["module_id_start"],
            ldraw_config["top_design_y_ldu"],
            terrain_module_placements(module, design),
            design["width"],
            design["height"],
            config,
        )
        for index, module in enumerate(design["modules"])
    ])
    steps = []
    if include_base:
        steps.extend(
            plan_step(step, design["width"], design["height"], config)
            for step in terrain_base_steps(support, design, config)
        )
    steps.extend([
        step
        for module in design["modules"]
        for step in [
            plan_step(module_step, design["width"], design["height"], config)
            for module_step in terrain_module_steps(module, design, config)
        ]
    ])
    return {
        "format": plan_config["format"],
        "includeSupportBase": include_base,
        "grid": {
            "width": design["width"],
            "height": design["height"],
        },
        "ldrawProjection": {
            "lduPerStud": ldraw_config["ldu_per_stud"],
            "gridRotationMatrices": ldraw_config["grid_rotation_matrices"],
            "xOriginGridWidthMultiplier": ldraw_config["x_origin_grid_width_multiplier"],
            "xDirection": ldraw_config["x_direction"],
            "zOriginGridHeightMultiplier": ldraw_config["z_origin_grid_height_multiplier"],
            "zDirection": ldraw_config["z_direction"],
        },
        "layers": layers,
        "submodels": [
            terrain_plan_submodel(module, design, config, index)
            for index, module in enumerate(design["modules"])
        ],
        "steps": steps,
        "modelDimensions": design["modelDimensions"],
        "bom": design["bom"],
        "colorMappings": design["colorMappings"],
    }


def terrain_plan_submodel(
    module: dict[str, Any],
    design: dict[str, Any],
    config: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    return {
        "id": module["id"],
        "fileName": terrain_module_file_name(module, config),
        "order": index + config["heightmap_design"]["module_id_start"],
        "module": module,
        "steps": [
            plan_step(step, design["width"], design["height"], config)
            for step in terrain_module_steps(module, design, config)
        ],
    }


def terrain_base_steps(
    support: dict[str, list[dict[str, Any]]],
    design: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    return create_lego_base_steps(
        design,
        support["whiteBase"],
        support["blackSupport"],
        config,
    )


def terrain_module_steps(
    module: dict[str, Any],
    design: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    heightmap_config = config["heightmap_design"]
    stage_names = heightmap_config["module_step_names"]
    stages = terrain_module_stage_order(module, config)
    steps = []
    for stage in stages:
        placements = [
            placement
            for placement in terrain_module_placements(module, design)
            if placement["moduleStage"] == stage
        ]
        if placements:
            order = len(steps) + config["heightmap_design"]["module_id_start"]
            steps.append(
                {
                    "id": config["heightmap_design"]["module_id_separator"].join([module["id"], stage]),
                    "name": heightmap_config["module_step_name_template"].format(
                        module_id=module["id"],
                        stage_name=stage_names[stage],
                    ),
                    "order": order,
                    "layer": module["id"],
                    "placements": [
                        {
                            "layer": module["id"],
                            "ldrawY": placement.get("yLdu", config["ldraw"]["top_design_y_ldu"]),
                            "placement": placement,
                        }
                        for placement in sorted(placements, key=terrain_placement_sort_key)
                    ],
                }
            )
    return steps


def terrain_module_stage_order(module: dict[str, Any], config: dict[str, Any]) -> list[str]:
    stages = config["heightmap_design"]["module_stages"]
    if module["moduleType"] == config["heightmap_design"]["module_types"]["surface"]:
        return [stages["slope"], stages["surface"]]
    if module["moduleType"] == config["heightmap_design"]["module_types"]["cavity"]:
        return [stages["wall"], stages["support"], stages["cover"]]
    return [stages["solid"]]


def terrain_module_placements(module: dict[str, Any], design: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        placement
        for placement in design["placements"]
        if placement.get("moduleId") == module["id"]
    ]


def terrain_placement_sort_key(placement: dict[str, Any]) -> tuple[int, int, int, str]:
    return (
        -placement.get("yLdu", 0),
        placement["y"],
        placement["x"],
        placement["partId"],
    )


def plan_layer(
    layer_id: str,
    name: str,
    order: int,
    y_ldu: int,
    placements: list[dict[str, Any]],
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": layer_id,
        "name": name,
        "order": order,
        "ldrawY": y_ldu,
        "placements": [
            plan_placement(placement, y_ldu, grid_width, grid_height, config)
            for placement in placements
        ],
    }


def plan_placement(
    placement: dict[str, Any],
    y_ldu: int,
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "partId": placement["partId"],
        "rebrickablePartNum": placement["rebrickablePartNum"],
        "legoDesignId": placement["legoDesignId"],
        "colorId": placement["colorId"],
        "colorName": placement["colorName"],
        "colorRgb": placement["colorRgb"],
        "ldrawColorCode": placement["ldrawColorCode"],
        "grid": {
            "x": placement["x"],
            "y": placement["y"],
            "level": placement.get("yLdu", y_ldu),
            "width": placement["width"],
            "height": placement["height"],
            "logicalHeightPlate": placement["logicalHeightPlate"],
            "rotation": placement["rotation"],
        },
        "ldraw": ldraw_part_projection(placement, y_ldu, grid_width, grid_height, config),
    }


def plan_step(
    step: dict[str, Any],
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": step["id"],
        "name": step["name"],
        "order": step["order"],
        "layer": step["layer"],
        "placements": [
            plan_step_placement(item, grid_width, grid_height, config)
            for item in step["placements"]
        ],
    }


def plan_step_placement(
    item: dict[str, Any],
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    placement = plan_placement(
        item["placement"],
        item["ldrawY"],
        grid_width,
        grid_height,
        config,
    )
    return {
        "layer": item["layer"],
        "ldrawY": item["ldrawY"],
        **placement,
    }


def validate_design_coverage(
    pixel_color_ids: dict[str, int],
    placements: list[dict[str, Any]],
    algorithm_config: dict[str, Any],
    config: dict[str, Any],
) -> None:
    expected_keys = set(pixel_color_ids)
    actual_keys = placement_cell_keys(placements, algorithm_config)
    if expected_keys != actual_keys:
        raise ValueError(config["errors"]["design_coverage_failed"])


def validate_design_parts_available(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> None:
    candidate_part_ids = {
        part["ldrawPartNum"]
        for part in metadata["parts"] + metadata["terrainParts"]
    }
    design_part_ids = {placement["partId"] for placement in design["placements"]}
    if not design_part_ids.issubset(candidate_part_ids):
        raise ValueError(config["errors"]["design_part_not_available"])


def create_support_base_placements(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    white_base = create_white_base_placements(design, metadata, config)
    parts = normalized_parts(metadata["parts"])
    algorithm_config = config["algorithm"]
    black_color = support_color(config["ldraw"]["support_colors"]["black"], algorithm_config)
    black_keys = support_connector_cell_keys(white_base, config)
    black_keys |= support_border_cell_keys(design["width"], design["height"], config)
    black_keys = expand_support_cell_keys(
        black_keys,
        design["width"],
        design["height"],
        parts,
        config,
    )
    black_support = solve_support_keys(black_keys, black_color, parts, algorithm_config)
    if not black_support:
        raise ValueError(config["errors"]["support_base_failed"])
    return {
        "whiteBase": white_base,
        "blackSupport": black_support,
    }


def create_white_base_placements(
    design: dict[str, Any],
    metadata: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    parts = normalized_parts(metadata["parts"])
    algorithm_config = config["algorithm"]
    white_color = support_color(config["ldraw"]["support_colors"]["white"], algorithm_config)
    base_rectangle = {
        "x": 0,
        "y": 0,
        "width": design["width"],
        "height": design["height"],
        "area": design["width"] * design["height"],
    }
    white_base = fill_rectangle_greedy(base_rectangle, parts, white_color, algorithm_config)
    if not white_base:
        raise ValueError(config["errors"]["support_base_failed"])
    return white_base


def support_connector_cell_keys(
    white_base: list[dict[str, Any]],
    config: dict[str, Any],
) -> set[str]:
    ldraw_config = config["ldraw"]
    algorithm_config = config["algorithm"]
    before = max(ldraw_config["seam_connector_before_stud"], ldraw_config["minimum_support_width_stud"] // 2)
    after = max(ldraw_config["seam_connector_after_stud"], ldraw_config["minimum_support_width_stud"] - before)
    seam_keys = set()
    left_edges: dict[int, list[dict[str, Any]]] = {}
    right_edges: dict[int, list[dict[str, Any]]] = {}
    top_edges: dict[int, list[dict[str, Any]]] = {}
    bottom_edges: dict[int, list[dict[str, Any]]] = {}
    for placement in white_base:
        left_edges.setdefault(placement["x"], []).append(placement)
        right_edges.setdefault(placement["x"] + placement["width"], []).append(placement)
        top_edges.setdefault(placement["y"], []).append(placement)
        bottom_edges.setdefault(placement["y"] + placement["height"], []).append(placement)
    for seam_x in set(right_edges) & set(left_edges):
        for left in right_edges[seam_x]:
            for right in left_edges[seam_x]:
                overlap_start = max(left["y"], right["y"])
                overlap_end = min(left["y"] + left["height"], right["y"] + right["height"])
                if overlap_start < overlap_end:
                    seam_keys |= rectangle_cell_keys(
                        {
                            "x": seam_x - before,
                            "y": overlap_start,
                            "width": before + after,
                            "height": overlap_end - overlap_start,
                            "area": (before + after) * (overlap_end - overlap_start),
                        },
                        algorithm_config,
                    )
    for seam_y in set(bottom_edges) & set(top_edges):
        for top in bottom_edges[seam_y]:
            for bottom in top_edges[seam_y]:
                overlap_start = max(top["x"], bottom["x"])
                overlap_end = min(top["x"] + top["width"], bottom["x"] + bottom["width"])
                if overlap_start < overlap_end:
                    seam_keys |= rectangle_cell_keys(
                        {
                            "x": overlap_start,
                            "y": seam_y - before,
                            "width": overlap_end - overlap_start,
                            "height": before + after,
                            "area": (overlap_end - overlap_start) * (before + after),
                        },
                        algorithm_config,
                    )
    return seam_keys


def support_border_cell_keys(width: int, height: int, config: dict[str, Any]) -> set[str]:
    ldraw_config = config["ldraw"]
    algorithm_config = config["algorithm"]
    border_width = max(ldraw_config["border_width_stud"], ldraw_config["minimum_support_width_stud"])
    rectangles = [
        {
            "x": 0,
            "y": 0,
            "width": width,
            "height": border_width,
        },
        {
            "x": 0,
            "y": height - border_width,
            "width": width,
            "height": border_width,
        },
        {
            "x": 0,
            "y": 0,
            "width": border_width,
            "height": height,
        },
        {
            "x": width - border_width,
            "y": 0,
            "width": border_width,
            "height": height,
        },
    ]
    keys = set()
    for rectangle in rectangles:
        keys |= rectangle_cell_keys(
            {
                **rectangle,
                "area": rectangle["width"] * rectangle["height"],
            },
            algorithm_config,
        )
    return keys


def expand_support_cell_keys(
    keys: set[str],
    width: int,
    height: int,
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> set[str]:
    ldraw_config = config["ldraw"]
    algorithm_config = config["algorithm"]
    candidates = []
    for part in parts:
        for orientation in orientations(part, algorithm_config):
            for y in range(height - orientation["height"] + 1):
                for x in range(width - orientation["width"] + 1):
                    placement_keys = {
                        cell_key(cell_x, cell_y, algorithm_config)
                        for cell_y in range(y, y + orientation["height"])
                        for cell_x in range(x, x + orientation["width"])
                    }
                    covered_count = len(placement_keys & keys)
                    extra_keys = placement_keys - keys
                    if (
                        covered_count >= ldraw_config["support_minimum_covered_cells_per_part"]
                        and len(extra_keys) <= ldraw_config["support_maximum_extra_cells_per_part"]
                        and extra_keys
                    ):
                        candidates.append(
                            {
                                "coveredCount": covered_count,
                                "area": orientation["width"] * orientation["height"],
                                "extraKeys": extra_keys,
                            }
                        )
    expanded_keys = set(keys)
    for candidate in sorted(
        candidates,
        key=lambda item: (-item["coveredCount"], -item["area"]),
    ):
        expanded_keys.update(candidate["extraKeys"])
    return expanded_keys


def solve_support_keys(
    keys: set[str],
    color: dict[str, Any],
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    placements = []
    for component in remaining_components_from_keys(keys, color["id"], config):
        placements.extend(solve_component(component, parts, color, config))
    return merge_same_color_rectangles(placements, parts, config)


def support_color(color_config: dict[str, Any], algorithm_config: dict[str, Any]) -> dict[str, Any]:
    color = parsed_color(
        {
            "id": color_config["id"],
            "name": color_config["name"],
            "rgb": color_config["rgb"],
        },
        algorithm_config,
    )
    return {
        **color,
        "ldrawCode": color_config["ldraw_code"],
    }


def ldraw_header(config: dict[str, Any]) -> list[str]:
    return [
        ldraw_meta_line(config["file_command"], config["model_file_name"], config),
        ldraw_meta_line(config["name_command"], config["model_file_name"], config),
        ldraw_meta_line(config["author_command"], config["author"], config),
    ]


def ldraw_section(section: str, config: dict[str, Any]) -> list[str]:
    return [ldraw_meta_line(config["comment_prefix"], section, config)]


def ldraw_meta_line(command: str, value: str, config: dict[str, Any]) -> str:
    return " ".join([str(config["metadata_line_type"]), command, value])


def ldraw_step_lines(
    steps: list[dict[str, Any]],
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> list[str]:
    lines = []
    for step_index, step in enumerate(steps):
        if step_index:
            lines.append(ldraw_step_line(config["ldraw"]))
        lines.extend(ldraw_section(step["name"], config["ldraw"]))
        for item in step["placements"]:
            lines.append(ldraw_part_line(
                item["placement"],
                item["ldrawY"],
                grid_width,
                grid_height,
                config,
            ))
    return lines


def ldraw_step_line(config: dict[str, Any]) -> str:
    return " ".join([str(config["metadata_line_type"]), config["step_command"]])


def ldraw_part_line(
    placement: dict[str, Any],
    y_ldu: int,
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> str:
    projection = ldraw_part_projection(placement, y_ldu, grid_width, grid_height, config)
    return " ".join(
        [
            str(config["ldraw"]["part_line_type"]),
            placement["ldrawColorCode"],
            str(projection["x"]),
            str(projection["y"]),
            str(projection["z"]),
            *[str(value) for value in projection["matrix"]],
            placement["partId"],
        ]
    )


def ldraw_part_projection(
    placement: dict[str, Any],
    y_ldu: int,
    grid_width: int,
    grid_height: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    ldraw_config = config["ldraw"]
    origin_divisor = ldraw_config["part_origin_offset_divisor"]
    x_center_numerator = placement["x"] * origin_divisor + placement["width"]
    z_center_numerator = placement["y"] * origin_divisor + placement["height"]
    x_origin_numerator = grid_width * origin_divisor * ldraw_config["x_origin_grid_width_multiplier"]
    z_origin_numerator = grid_height * origin_divisor * ldraw_config["z_origin_grid_height_multiplier"]
    return {
        "x": (x_origin_numerator + x_center_numerator * ldraw_config["x_direction"])
        * ldraw_config["ldu_per_stud"]
        // origin_divisor,
        "y": placement.get("yLdu", y_ldu),
        "z": (z_origin_numerator + z_center_numerator * ldraw_config["z_direction"])
        * ldraw_config["ldu_per_stud"]
        // origin_divisor,
        "matrix": ldraw_config["grid_rotation_matrices"][str(placement["rotation"])],
    }


def empty_design_result(project: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    return {
        "width": project["gridWidth"],
        "height": project["gridHeight"],
        "placements": [],
        "bom": [],
        "colorMappings": [],
        "modelDimensions": empty_model_dimensions(config),
    }


def model_dimensions(placements: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    if not placements:
        return empty_model_dimensions(config)
    dimensions_config = config["model_dimensions"]
    plate_height_ldu = config["heightmap_design"]["plate_height_ldu"]
    height_direction = config["heightmap_design"]["height_direction"]
    min_x = min(placement["x"] for placement in placements)
    max_x = max(placement["x"] + placement["width"] for placement in placements)
    min_y = min(placement["y"] for placement in placements)
    max_y = max(placement["y"] + placement["height"] for placement in placements)
    max_top_plate = max(
        (
            placement.get("yLdu", config["ldraw"]["top_design_y_ldu"]) // (plate_height_ldu * height_direction)
            + placement["logicalHeightPlate"]
        )
        for placement in placements
    )
    length_stud = max_x - min_x
    width_stud = max_y - min_y
    height_plate = max_top_plate
    return {
        "lengthStud": length_stud,
        "widthStud": width_stud,
        "heightPlate": height_plate,
        "lengthCm": dimension_cm(length_stud, dimensions_config["stud_width_mm"], dimensions_config),
        "widthCm": dimension_cm(width_stud, dimensions_config["stud_width_mm"], dimensions_config),
        "heightCm": dimension_cm(height_plate, dimensions_config["plate_height_mm"], dimensions_config),
    }


def heightmap_level_y_ldu(level: int, config: dict[str, Any]) -> int:
    heightmap_config = config["heightmap_design"]
    return level * heightmap_config["plate_height_ldu"] * heightmap_config["height_direction"]


def empty_model_dimensions(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "lengthStud": config["algorithm"]["minimum_empty_dimension"],
        "widthStud": config["algorithm"]["minimum_empty_dimension"],
        "heightPlate": config["algorithm"]["minimum_empty_dimension"],
        "lengthCm": config["algorithm"]["minimum_empty_dimension"],
        "widthCm": config["algorithm"]["minimum_empty_dimension"],
        "heightCm": config["algorithm"]["minimum_empty_dimension"],
    }


def dimension_cm(value: int, millimeters_per_unit: float, config: dict[str, Any]) -> float:
    return round(
        value * millimeters_per_unit / config["millimeters_per_centimeter"],
        config["round_digits"],
    )


def normalized_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts_by_size: dict[tuple[int, int], dict[str, Any]] = {}
    for part in parts:
        size_key = (part["width"], part["height"])
        rotated_size_key = (part["height"], part["width"])
        if rotated_size_key in parts_by_size:
            continue
        parts_by_size.setdefault(size_key, part)
    return sorted(parts_by_size.values(), key=lambda part: (-part["area"], part["ldrawPartNum"]))


def merge_same_color_rectangles(
    placements: list[dict[str, Any]],
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    cells_by_color: dict[int, set[str]] = {}
    color_by_id: dict[int, dict[str, Any]] = {}
    for placement in placements:
        color_id = placement["colorId"]
        color_by_id[color_id] = {
            "id": color_id,
            "name": placement["colorName"],
            "hex": placement["colorRgb"],
            "ldrawCode": placement["ldrawColorCode"],
        }
        cells = cells_by_color.setdefault(color_id, set())
        for y in range(placement["y"], placement["y"] + placement["height"]):
            for x in range(placement["x"], placement["x"] + placement["width"]):
                cells.add(cell_key(x, y, config))

    merged = []
    for color_id, cells in cells_by_color.items():
        remaining_cells = set(cells)
        color = color_by_id[color_id]
        while remaining_cells:
            cell = top_left_cell(remaining_cells, config)
            placement = best_rectangle_covering_cell(cell, remaining_cells, parts, color, config)
            if placement is None:
                return placements
            merged.append(public_placement(placement))
            for y in range(placement["y"], placement["y"] + placement["height"]):
                for x in range(placement["x"], placement["x"] + placement["width"]):
                    remaining_cells.remove(cell_key(x, y, config))

    if len(merged) <= len(placements):
        return merged
    return placements


def top_left_cell(cells: set[str], config: dict[str, Any]) -> dict[str, int]:
    return min(
        (parse_cell_key(key, config) for key in cells),
        key=lambda cell: (cell["y"], cell["x"]),
    )


def best_rectangle_covering_cell(
    cell: dict[str, int],
    cells: set[str],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    candidates = []
    for part in parts:
        for orientation in orientations(part, config):
            for dx in range(orientation["width"]):
                for dy in range(orientation["height"]):
                    placement = {
                        "partId": part["ldrawPartNum"],
                        "rebrickablePartNum": part["rebrickablePartNum"],
                        "legoDesignId": part["legoDesignId"],
                        "colorId": color["id"],
                        "colorName": color["name"],
                        "colorRgb": color["hex"],
                        "ldrawColorCode": color["ldrawCode"],
                        "x": cell["x"] - dx,
                        "y": cell["y"] - dy,
                        "width": orientation["width"],
                        "height": orientation["height"],
                        "logicalHeightPlate": part["logicalHeightPlate"],
                        "rotation": orientation["rotation"],
                        "area": orientation["width"] * orientation["height"],
                    }
                    if is_rectangle_merge_valid(placement, cells, config):
                        candidates.append(placement)
    if not candidates:
        return None
    return max(candidates, key=lambda placement: (placement["area"], -placement["y"], -placement["x"]))


def is_rectangle_merge_valid(
    placement: dict[str, Any],
    cells: set[str],
    config: dict[str, Any],
) -> bool:
    for y in range(placement["y"], placement["y"] + placement["height"]):
        for x in range(placement["x"], placement["x"] + placement["width"]):
            if cell_key(x, y, config) not in cells:
                return False
    return True


def map_project_colors(
    project: dict[str, Any],
    colors: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    source_rgbs = list(dict.fromkeys(
        [palette_color["rgb"] for palette_color in project["palette"]]
        + [pixel["rgb"] for pixel in project["pixels"]]
    ))
    mappings = []
    for source_rgb in source_rgbs:
        source_color = parse_rgb(source_rgb, config)
        color = nearest_color(source_color, colors)
        mappings.append(
            {
                "sourceRgb": source_rgb,
                "colorId": color["id"],
                "colorName": color["name"],
                "colorRgb": color["hex"],
                "ldrawColorCode": color["ldrawCode"],
            }
        )
    return mappings


def nearest_color(source_color: dict[str, int], colors: list[dict[str, Any]]) -> dict[str, Any]:
    return min(colors, key=lambda color: color_distance(source_color, color))


def color_distance(source_color: dict[str, int], color: dict[str, Any]) -> int:
    return (
        (source_color["red"] - color["red"]) ** 2
        + (source_color["green"] - color["green"]) ** 2
        + (source_color["blue"] - color["blue"]) ** 2
    )


def connected_components(
    project: dict[str, Any],
    pixel_color_ids: dict[str, int],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    visited = set()
    components = []
    for pixel in project["pixels"]:
        start_key = cell_key(pixel["x"], pixel["y"], config)
        color_id = pixel_color_ids.get(start_key)
        if color_id is None or start_key in visited:
            continue
        queue = [{"x": pixel["x"], "y": pixel["y"]}]
        cells = []
        cell_keys = set()
        visited.add(start_key)
        index = 0
        while index < len(queue):
            cell = queue[index]
            cells.append(cell)
            cell_keys.add(cell_key(cell["x"], cell["y"], config))
            for neighbor in neighbors(cell):
                neighbor_key = cell_key(neighbor["x"], neighbor["y"], config)
                if (
                    neighbor["x"] < 0
                    or neighbor["y"] < 0
                    or neighbor["x"] >= project["gridWidth"]
                    or neighbor["y"] >= project["gridHeight"]
                    or neighbor_key in visited
                    or pixel_color_ids.get(neighbor_key) != color_id
                ):
                    continue
                visited.add(neighbor_key)
                queue.append(neighbor)
            index += 1
        components.append({"colorId": color_id, "cells": cells, "cellKeys": cell_keys})
    return components


def solve_component(
    component: dict[str, Any],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    return solve_component_by_largest_rectangles(component, parts, color, config)


def solve_component_by_largest_rectangles(
    component: dict[str, Any],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    placements = []
    remaining_components = [component]
    while remaining_components:
        active_component = remaining_components.pop(0)
        if not active_component["cellKeys"]:
            continue
        rectangle = largest_remaining_rectangle(active_component, config)
        if rectangle is None:
            placements.extend(solve_component_beam(active_component, parts, color, config))
            continue
        rectangle_placements = fill_rectangle_greedy(rectangle, parts, color, config)
        if not rectangle_placements:
            placements.extend(solve_component_beam(active_component, parts, color, config))
            continue
        placements.extend(rectangle_placements)
        covered_keys = placement_cell_keys(rectangle_placements, config)
        remaining_keys = active_component["cellKeys"] - covered_keys
        remaining_components.extend(
            remaining_components_from_keys(remaining_keys, active_component["colorId"], config)
        )
    return placements


def largest_remaining_rectangle(
    component: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, int] | None:
    cells = [parse_cell_key(key, config) for key in component["cellKeys"]]
    if not cells:
        return None
    min_x = min(cell["x"] for cell in cells)
    max_x = max(cell["x"] for cell in cells)
    min_y = min(cell["y"] for cell in cells)
    max_y = max(cell["y"] for cell in cells)
    column_count = max_x - min_x + 1
    heights = [0 for _ in range(column_count)]
    best_rectangle = None
    best_area = 0
    for y in range(min_y, max_y + 1):
        for column_index in range(column_count):
            x = min_x + column_index
            if cell_key(x, y, config) in component["cellKeys"]:
                heights[column_index] += 1
            else:
                heights[column_index] = 0
        stack = []
        for column_index in range(column_count + 1):
            current_height = heights[column_index] if column_index < column_count else 0
            while stack and heights[stack[-1]] > current_height:
                height = heights[stack.pop()]
                left_index = stack[-1] + 1 if stack else 0
                width = column_index - left_index
                area = width * height
                if area > best_area:
                    best_area = area
                    best_rectangle = {
                        "x": min_x + left_index,
                        "y": y - height + 1,
                        "width": width,
                        "height": height,
                        "area": area,
                    }
            stack.append(column_index)
    return best_rectangle


def fill_rectangle_greedy(
    rectangle: dict[str, int],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    remaining_keys = rectangle_cell_keys(rectangle, config)
    placements = []
    candidate_parts = rectangle_candidate_parts(rectangle, parts, config)
    while remaining_keys:
        cell = top_left_cell(remaining_keys, config)
        placement = best_rectangle_fill_at_cell(
            cell,
            rectangle,
            remaining_keys,
            candidate_parts,
            color,
            config,
        )
        if placement is None:
            return []
        placements.append(public_placement(placement))
        remaining_keys -= placement_cell_keys([placement], config)
    return placements


def rectangle_candidate_parts(
    rectangle: dict[str, int],
    parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        part for part in parts
        if part["area"] <= rectangle["area"]
        and any(
            orientation["width"] <= rectangle["width"]
            and orientation["height"] <= rectangle["height"]
            for orientation in orientations(part, config)
        )
    ]


def best_rectangle_fill_at_cell(
    cell: dict[str, int],
    rectangle: dict[str, int],
    remaining_keys: set[str],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    candidates = []
    for part in parts:
        for orientation in orientations(part, config):
            placement = {
                "partId": part["ldrawPartNum"],
                "rebrickablePartNum": part["rebrickablePartNum"],
                "legoDesignId": part["legoDesignId"],
                "colorId": color["id"],
                "colorName": color["name"],
                "colorRgb": color["hex"],
                "ldrawColorCode": color["ldrawCode"],
                "x": cell["x"],
                "y": cell["y"],
                "width": orientation["width"],
                "height": orientation["height"],
                "logicalHeightPlate": part["logicalHeightPlate"],
                "rotation": orientation["rotation"],
                "area": orientation["width"] * orientation["height"],
            }
            if is_rectangle_fill_valid(placement, rectangle, remaining_keys, config):
                candidates.append(placement)
    if not candidates:
        return None
    return max(candidates, key=lambda placement: placement["area"])


def is_rectangle_fill_valid(
    placement: dict[str, Any],
    rectangle: dict[str, int],
    remaining_keys: set[str],
    config: dict[str, Any],
) -> bool:
    if (
        placement["x"] + placement["width"] > rectangle["x"] + rectangle["width"]
        or placement["y"] + placement["height"] > rectangle["y"] + rectangle["height"]
    ):
        return False
    return placement_cell_keys([placement], config).issubset(remaining_keys)


def rectangle_cell_keys(
    rectangle: dict[str, int],
    config: dict[str, Any],
) -> set[str]:
    return {
        cell_key(x, y, config)
        for y in range(rectangle["y"], rectangle["y"] + rectangle["height"])
        for x in range(rectangle["x"], rectangle["x"] + rectangle["width"])
    }


def placement_cell_keys(
    placements: list[dict[str, Any]],
    config: dict[str, Any],
) -> set[str]:
    keys = set()
    for placement in placements:
        for y in range(placement["y"], placement["y"] + placement["height"]):
            for x in range(placement["x"], placement["x"] + placement["width"]):
                keys.add(cell_key(x, y, config))
    return keys


def remaining_components_from_keys(
    cell_keys: set[str],
    color_id: int,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    remaining_keys = set(cell_keys)
    components = []
    while remaining_keys:
        first_key = remaining_keys.pop()
        queue = [parse_cell_key(first_key, config)]
        component_cells = []
        component_keys = {first_key}
        index = 0
        while index < len(queue):
            cell = queue[index]
            component_cells.append(cell)
            for neighbor in neighbors(cell):
                neighbor_key = cell_key(neighbor["x"], neighbor["y"], config)
                if neighbor_key in remaining_keys:
                    remaining_keys.remove(neighbor_key)
                    component_keys.add(neighbor_key)
                    queue.append(neighbor)
            index += 1
        components.append(
            {
                "colorId": color_id,
                "cells": component_cells,
                "cellKeys": component_keys,
            }
        )
    return components


def solve_component_beam(
    component: dict[str, Any],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    beam = [{"coveredKeys": set(), "placements": [], "score": 0}]
    max_area = max_part_area(parts, config)
    while beam:
        completed = [
            state for state in beam
            if len(state["coveredKeys"]) == len(component["cells"])
        ]
        if completed:
            return min(completed, key=lambda state: len(state["placements"]))["placements"]
        next_states = []
        for state in beam:
            cell = select_most_constrained_cell(component, state, parts, color, config)
            candidates = sorted(
                generate_placements_covering_cell(cell, component, state, parts, color, config),
                key=lambda placement: -placement["area"],
            )[:config["max_candidates_per_cell"]]
            for placement in candidates:
                next_state = apply_placement(state, placement, component, config)
                next_state["score"] = evaluate_state(next_state, component, max_area, config)
                next_states.append(next_state)
        beam = sorted(next_states, key=lambda state: state["score"])[:config["beam_size"]]
    return solve_component_greedy(component, parts, color, config)


def solve_component_greedy(
    component: dict[str, Any],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    state = {"coveredKeys": set(), "placements": [], "score": 0}
    while len(state["coveredKeys"]) < len(component["cells"]):
        cell = first_uncovered_cell(component, state, config)
        candidates = sorted(
            generate_placements_covering_cell(cell, component, state, parts, color, config),
            key=lambda placement: -placement["area"],
        )
        if not candidates:
            break
        state = apply_placement(state, candidates[0], component, config)
    return state["placements"]


def first_uncovered_cell(
    component: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, int]:
    return next(
        cell for cell in component["cells"]
        if cell_key(cell["x"], cell["y"], config) not in state["coveredKeys"]
    )


def select_most_constrained_cell(
    component: dict[str, Any],
    state: dict[str, Any],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, int]:
    uncovered_cells = [
        cell for cell in component["cells"]
        if cell_key(cell["x"], cell["y"], config) not in state["coveredKeys"]
    ]
    return min(
        uncovered_cells,
        key=lambda cell: len(generate_placements_covering_cell(
            cell,
            component,
            state,
            parts,
            color,
            config,
        )),
    )


def generate_placements_covering_cell(
    cell: dict[str, int],
    component: dict[str, Any],
    state: dict[str, Any],
    parts: list[dict[str, Any]],
    color: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    for part in parts:
        for orientation in orientations(part, config):
            for dx in range(orientation["width"]):
                for dy in range(orientation["height"]):
                    placement = {
                        "partId": part["ldrawPartNum"],
                        "rebrickablePartNum": part["rebrickablePartNum"],
                        "legoDesignId": part["legoDesignId"],
                        "colorId": color["id"],
                        "colorName": color["name"],
                        "colorRgb": color["hex"],
                        "ldrawColorCode": color["ldrawCode"],
                        "x": cell["x"] - dx,
                        "y": cell["y"] - dy,
                        "width": orientation["width"],
                        "height": orientation["height"],
                        "logicalHeightPlate": part["logicalHeightPlate"],
                        "rotation": orientation["rotation"],
                        "area": orientation["width"] * orientation["height"],
                    }
                    if is_placement_valid(placement, component, state, config):
                        candidates.append(placement)
    return candidates


def orientations(part: dict[str, Any], config: dict[str, Any]) -> list[dict[str, int]]:
    if part["width"] == part["height"]:
        return [
            {
                "width": part["width"],
                "height": part["height"],
                "rotation": config["no_rotation_degrees"],
            }
        ]
    return [
        {
            "width": part["width"],
            "height": part["height"],
            "rotation": config["no_rotation_degrees"],
        },
        {
            "width": part["height"],
            "height": part["width"],
            "rotation": config["rotation_degrees"],
        },
    ]


def is_placement_valid(
    placement: dict[str, Any],
    component: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
) -> bool:
    for y in range(placement["y"], placement["y"] + placement["height"]):
        for x in range(placement["x"], placement["x"] + placement["width"]):
            key = cell_key(x, y, config)
            if key not in component["cellKeys"] or key in state["coveredKeys"]:
                return False
    return True


def apply_placement(
    state: dict[str, Any],
    placement: dict[str, Any],
    component: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    covered_keys = set(state["coveredKeys"])
    for y in range(placement["y"], placement["y"] + placement["height"]):
        for x in range(placement["x"], placement["x"] + placement["width"]):
            key = cell_key(x, y, config)
            if key in component["cellKeys"]:
                covered_keys.add(key)
    return {
        "coveredKeys": covered_keys,
        "placements": state["placements"] + [public_placement(placement)],
        "score": state["score"],
    }


def public_placement(placement: dict[str, Any]) -> dict[str, Any]:
    return {
        "partId": placement["partId"],
        "rebrickablePartNum": placement["rebrickablePartNum"],
        "legoDesignId": placement["legoDesignId"],
        "colorId": placement["colorId"],
        "colorName": placement["colorName"],
        "colorRgb": placement["colorRgb"],
        "ldrawColorCode": placement["ldrawColorCode"],
        "x": placement["x"],
        "y": placement["y"],
        "width": placement["width"],
        "height": placement["height"],
        "logicalHeightPlate": placement["logicalHeightPlate"],
        "rotation": placement["rotation"],
        **({"yLdu": placement["yLdu"]} if "yLdu" in placement else {}),
        **({"moduleId": placement["moduleId"]} if "moduleId" in placement else {}),
        **({"moduleStage": placement["moduleStage"]} if "moduleStage" in placement else {}),
    }


def evaluate_state(
    state: dict[str, Any],
    component: dict[str, Any],
    max_area: int,
    config: dict[str, Any],
) -> float:
    remaining_area = len(component["cells"]) - len(state["coveredKeys"])
    optimistic_remaining = -(-remaining_area // max_area)
    fragments = count_remaining_components(component, state, config)
    isolated = count_isolated_cells(component, state, config)
    return (
        len(state["placements"])
        + optimistic_remaining
        + fragments * config["fragment_penalty"]
        + isolated * config["isolated_penalty"]
    )


def count_remaining_components(
    component: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
) -> int:
    remaining_keys = {
        cell_key(cell["x"], cell["y"], config)
        for cell in component["cells"]
        if cell_key(cell["x"], cell["y"], config) not in state["coveredKeys"]
    }
    count = 0
    while remaining_keys:
        count += 1
        queue = [remaining_keys.pop()]
        index = 0
        while index < len(queue):
            cell = parse_cell_key(queue[index], config)
            for neighbor in neighbors(cell):
                neighbor_key = cell_key(neighbor["x"], neighbor["y"], config)
                if neighbor_key in remaining_keys:
                    remaining_keys.remove(neighbor_key)
                    queue.append(neighbor_key)
            index += 1
    return count


def count_isolated_cells(
    component: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
) -> int:
    isolated_count = 0
    for cell in component["cells"]:
        key = cell_key(cell["x"], cell["y"], config)
        if key in state["coveredKeys"]:
            continue
        if all(
            cell_key(neighbor["x"], neighbor["y"], config) not in component["cellKeys"]
            or cell_key(neighbor["x"], neighbor["y"], config) in state["coveredKeys"]
            for neighbor in neighbors(cell)
        ):
            isolated_count += 1
    return isolated_count


def max_part_area(parts: list[dict[str, Any]], config: dict[str, Any]) -> int:
    return max([config["minimum_area"]] + [part["area"] for part in parts])


def create_bom(
    placements: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    items = {}
    for placement in placements:
        key = config["cell_key_separator"].join(
            [
                placement["partId"],
                str(placement["colorId"]),
                placement["ldrawColorCode"],
                str(placement["width"]),
                str(placement["height"]),
            ]
        )
        if key in items:
            items[key]["quantity"] += 1
            continue
        items[key] = {
            "key": key,
            "partId": placement["partId"],
            "rebrickablePartNum": placement["rebrickablePartNum"],
            "legoDesignId": placement["legoDesignId"],
            "colorId": placement["colorId"],
            "colorName": placement["colorName"],
            "colorRgb": placement["colorRgb"],
            "ldrawColorCode": placement["ldrawColorCode"],
            "width": placement["width"],
            "height": placement["height"],
            "quantity": 1,
        }
    return sorted(items.values(), key=lambda item: -item["quantity"])


def parsed_color(color: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_rgb(color["rgb"], config)
    return {
        **color,
        "hex": normalize_hex(color["rgb"], config),
        **parsed,
    }


def design_color(
    color: dict[str, Any],
    algorithm_config: dict[str, Any],
    ldraw_config: dict[str, Any],
) -> dict[str, Any]:
    parsed = parsed_color(color, algorithm_config)
    return {
        **parsed,
        "ldrawCode": direct_ldraw_color_code(parsed["hex"], algorithm_config, ldraw_config),
    }


def direct_ldraw_color_code(
    rgb: str,
    algorithm_config: dict[str, Any],
    ldraw_config: dict[str, Any],
) -> str:
    hex_value = normalize_hex(rgb, algorithm_config)[len(algorithm_config["hex_color_prefix"]):]
    return f"{ldraw_config['direct_color_prefix']}{hex_value}"


def parse_rgb(rgb: str, config: dict[str, Any]) -> dict[str, int]:
    hex_value = normalize_hex(rgb, config)[len(config["hex_color_prefix"]):]
    channels = config["rgb_channels"]
    return {
        "red": int(hex_value[channels["red_start"]:channels["red_end"]], config["hex_radix"]),
        "green": int(hex_value[channels["green_start"]:channels["green_end"]], config["hex_radix"]),
        "blue": int(hex_value[channels["blue_start"]:channels["blue_end"]], config["hex_radix"]),
    }


def normalize_hex(rgb: str, config: dict[str, Any]) -> str:
    raw = rgb[len(config["hex_color_prefix"]):] if rgb.startswith(config["hex_color_prefix"]) else rgb
    return f"{config['hex_color_prefix']}{raw.rjust(config['hex_color_length'], config['hex_pad_value']).upper()}"


def neighbors(cell: dict[str, int]) -> list[dict[str, int]]:
    return [
        {"x": cell["x"] + 1, "y": cell["y"]},
        {"x": cell["x"] - 1, "y": cell["y"]},
        {"x": cell["x"], "y": cell["y"] + 1},
        {"x": cell["x"], "y": cell["y"] - 1},
    ]


def cell_key(x: int, y: int, config: dict[str, Any]) -> str:
    return f"{x}{config['cell_key_separator']}{y}"


def parse_cell_key(key: str, config: dict[str, Any]) -> dict[str, int]:
    x, y = key.split(config["cell_key_separator"])
    return {"x": int(x), "y": int(y)}


def lego_design_colors(session, config: dict[str, Any]) -> list[dict[str, Any]]:
    statement = select(Color).where(Color.rgb.is_not(None)).order_by(Color.name)
    if not config["colors"]["include_transparent"]:
        statement = statement.where(Color.is_trans.is_(False))
    if config["colors"]["excluded_ids"]:
        statement = statement.where(Color.id.not_in(config["colors"]["excluded_ids"]))
    if config["colors"]["excluded_names"]:
        statement = statement.where(Color.name.not_in(config["colors"]["excluded_names"]))
    return [
        {
            "id": color.id,
            "name": color.name,
            "rgb": color.rgb,
            "isTrans": bool(color.is_trans),
        }
        for color in session.scalars(statement)
    ]


def part_metadata_statement(config: dict[str, Any], part_config: dict[str, Any] | None = None):
    active_part_config = config["parts"] if part_config is None else part_config
    geometry = LDrawPartGeometry
    minimum_height = (
        active_part_config["geometry_height_plate"]
        - active_part_config["geometry_height_tolerance_plate"]
    )
    maximum_height = (
        active_part_config["geometry_height_plate"]
        + active_part_config["geometry_height_tolerance_plate"]
    )
    statement = (
        select(LDrawPart, geometry, XrefPartNumber)
        .join(geometry, geometry.ldraw_part_id == LDrawPart.id)
        .outerjoin(XrefPartNumber, XrefPartNumber.ldraw_part_num == LDrawPart.ldraw_part_num)
        .where(LDrawPart.category == active_part_config["category"])
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
        .order_by(
            geometry.logical_width_stud * geometry.logical_depth_stud,
            LDrawPart.ldraw_part_num,
        )
    )
    return statement
