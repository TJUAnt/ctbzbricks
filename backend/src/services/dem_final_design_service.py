"""Build the complete validated DEM LEGO design."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import sessionmaker

from src.model.models import Color, InventoryPart, LDrawPart, XrefPartNumber
from src.services.dem_lego_design_service import (
    apply_dem_part_xref,
    build_base_h_structure,
    load_dem_structure_parts,
    load_part_surface_profile_models,
)
from src.services.dem_colored_replacement_service import load_colored_replacement_plan
from src.services.dem_surface_patch_service import (
    SurfacePatchCandidate,
    candidate_response,
    generate_surface_patch_candidates,
    orient_ldraw_matrix_to_dem,
    rotate_matrix,
    shifted_collision,
    support_stud_cells,
    validate_surface_part_ids,
)
from src.services.dem_surface_plan_service import (
    SurfacePlan,
    SurfacePlanValidation,
    SurfaceReplacementPhase,
    base_h_collision_sample_count,
    best_compatible_candidate,
    build_base_h,
    heightmap_slope_edges,
    map_candidates_to_heightmap_edges,
    placement_sort_key,
    solve_surface_plan,
    surface_fill_candidates,
    surface_plan_seam_error,
    surface_plan_response,
)
from src.services.dem_vertical_continuity_service import (
    VerticalContinuityValidation,
    phase_vertical_continuity,
    vertical_continuity_response,
)
from src.services.lego_design_service import create_support_base_placements
from src.services.lego_pixmap_strategy import create_lego_base_steps


def surface_part_height(placement: dict[str, Any]) -> float:
    return max(
        upper_plate
        for row in placement["collisionIntervalsPlate"]
        for intervals in row
        for _lower_plate, upper_plate in intervals
    ) - placement["basePlate"]


def final_surface_placements(
    plan: SurfacePlan,
    metadata: dict[tuple[str, int], dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    placements = []
    for candidate in plan.placements:
        placement = candidate_response(candidate)
        part_metadata = metadata[(candidate.part_id, candidate.color_id)]
        placement.update(
            {
                "role": config["final_design"]["roles"]["surface"],
                **part_metadata,
                "heightPlate": surface_part_height(placement),
            }
        )
        placements.append(placement)
    return placements


def final_bom(
    structure: dict[str, Any],
    surface_placements: list[dict[str, Any]],
    support_base: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    items: dict[tuple[str, int, str], dict[str, Any]] = {}
    support_config = config["support_base"]
    support_roles = {
        support_config["placement_ref_kinds"]["white_base"]: support_config["roles"]["white_base"],
        support_config["placement_ref_kinds"]["black_support"]: support_config["roles"]["black_support"],
    }
    for support_key, placements in support_base.items():
        role = support_roles[support_key]
        for placement in placements:
            key = (placement["partId"], placement["colorId"], role)
            item = items.setdefault(
                key,
                {
                    "partId": placement["partId"],
                    "rebrickablePartNum": placement["rebrickablePartNum"],
                    "legoDesignId": placement["legoDesignId"],
                    "role": role,
                    "colorId": placement["colorId"],
                    "colorName": placement["colorName"],
                    "colorRgb": placement["colorRgb"],
                    "ldrawColorCode": placement["ldrawColorCode"],
                    "widthStud": placement["width"],
                    "depthStud": placement["height"],
                    "heightPlate": placement["logicalHeightPlate"],
                    "quantity": 0,
                },
            )
            item["quantity"] += 1
    for placement in structure["placements"]:
        key = (placement["partId"], placement["colorId"], placement["role"])
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
                "ldrawColorCode": placement["ldrawColorCode"],
                "widthStud": placement["width"],
                "depthStud": placement["depth"],
                "heightPlate": placement["heightPlate"],
                "quantity": 0,
            },
        )
        item["quantity"] += 1
    for placement in surface_placements:
        key = (placement["partId"], placement["colorId"], placement["role"])
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
                "ldrawColorCode": placement["ldrawColorCode"],
                "widthStud": placement["widthStud"],
                "depthStud": placement["depthStud"],
                "heightPlate": placement["heightPlate"],
                "quantity": 0,
            },
        )
        item["quantity"] += 1
    role_order = config["final_design"]["bom_role_order"]
    return sorted(
        items.values(),
        key=lambda item: (
            role_order.index(item["role"]),
            -(item["widthStud"] * item["depthStud"]),
            item["partId"],
            item["colorId"],
        ),
    )


def placement_chunks(references: list[dict[str, Any]], maximum_size: int) -> list[list[dict[str, Any]]]:
    return [
        references[index : index + maximum_size]
        for index in range(0, len(references), maximum_size)
    ]


def final_build_steps(
    structure: dict[str, Any],
    surface_placements: list[dict[str, Any]],
    support_base: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    step_config = config["final_design"]["steps"]
    support_steps = final_support_base_steps(
        structure,
        support_base,
        config,
    )
    structure_by_base: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, placement in enumerate(structure["placements"]):
        structure_by_base[placement["basePlate"]].append(
            {"kind": step_config["structure_stage"], "index": index}
        )
    surface_by_phase: dict[str, dict[int, list[dict[str, Any]]]] = {
        phase["connection_class"]: defaultdict(list)
        for phase in step_config["surface_phases"]
    }
    for index, placement in enumerate(surface_placements):
        surface_by_phase[placement["topConnectionClass"]][placement["basePlate"]].append(
            {"kind": step_config["surface_ref_kind"], "index": index}
        )
    step_groups = [
        (
            step_config["structure_stage"],
            step_config["structure_name_template"],
            structure_by_base,
        )
    ] + [
        (
            phase["stage"],
            phase["name_template"],
            surface_by_phase[phase["connection_class"]],
        )
        for phase in step_config["surface_phases"]
    ]
    steps = support_steps
    for stage, name_template, grouped in step_groups:
        for base_plate in sorted(grouped):
            for references in placement_chunks(
                grouped[base_plate],
                step_config["maximum_placements_per_step"],
            ):
                order = len(steps) + step_config["index_start"]
                steps.append(
                    {
                        "id": step_config["id_template"].format(index=order),
                        "name": name_template.format(base_plate=base_plate),
                        "order": order,
                        "stage": stage,
                        "basePlate": base_plate,
                        "placementRefs": references,
                    }
                )
    return steps


def final_support_base_steps(
    structure: dict[str, Any],
    support_base: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    support_config = dem_support_base_config(config)
    kind_by_layer = {
        support_config["plan_export"]["layer_ids"]["white_base"]: config["support_base"]["placement_ref_kinds"]["white_base"],
        support_config["plan_export"]["layer_ids"]["black_support"]: config["support_base"]["placement_ref_kinds"]["black_support"],
    }
    support_index_by_kind = {
        config["support_base"]["placement_ref_kinds"]["white_base"]: {
            id(placement): index
            for index, placement in enumerate(support_base[config["support_base"]["placement_ref_kinds"]["white_base"]])
        },
        config["support_base"]["placement_ref_kinds"]["black_support"]: {
            id(placement): index
            for index, placement in enumerate(support_base[config["support_base"]["placement_ref_kinds"]["black_support"]])
        },
    }
    support_design = dem_support_design(structure)
    return [
        {
            "id": step_config["id"],
            "name": step_config["name"],
            "order": step_config["order"],
            "stage": step_config["layer"],
            "basePlate": config["support_base"]["steps"]["base_plate"],
            "placementRefs": [
                {
                    "kind": kind_by_layer[item["layer"]],
                    "index": support_index_by_kind[kind_by_layer[item["layer"]]][id(item["placement"])],
                }
                for item in step_config["placements"]
            ],
        }
        for step_config in create_lego_base_steps(
            support_design,
            support_base[config["support_base"]["placement_ref_kinds"]["white_base"]],
            support_base[config["support_base"]["placement_ref_kinds"]["black_support"]],
            support_config,
        )
    ]


def dem_support_design(structure: dict[str, Any]) -> dict[str, int]:
    return {
        "width": structure["widthStud"],
        "height": structure["depthStud"],
    }


def dem_support_base_config(config: dict[str, Any]) -> dict[str, Any]:
    support_config = config["support_base"]
    return {
        "algorithm": config["algorithm"],
        "ldraw": support_config["ldraw"],
        "lego_pixmap_strategy": support_config["steps"],
        "plan_export": support_config["plan_export"],
        "errors": support_config["errors"],
    }


def dem_support_parts(
    structure_parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "ldrawPartNum": part["partId"],
            "rebrickablePartNum": part["rebrickablePartNum"],
            "legoDesignId": part["legoDesignId"],
            "width": part["width"],
            "height": part["depth"],
            "logicalHeightPlate": part["heightPlate"],
            "area": part["area"],
        }
        for part in structure_parts
        if part["role"] == config["support_base"]["part_role"]
    ]


def build_dem_support_base(
    structure: dict[str, Any],
    structure_parts: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    support_base = create_support_base_placements(
        dem_support_design(structure),
        {"parts": dem_support_parts(structure_parts, config)},
        dem_support_base_config(config),
    )
    return {
        config["support_base"]["placement_ref_kinds"]["white_base"]: [
            {
                **placement,
                "yLdu": config["support_base"]["ldraw"]["white_base_y_ldu"],
            }
            for placement in support_base[config["support_base"]["generated_keys"]["white_base"]]
        ],
        config["support_base"]["placement_ref_kinds"]["black_support"]: [
            {
                **placement,
                "yLdu": config["support_base"]["ldraw"]["black_support_y_ldu"],
            }
            for placement in support_base[config["support_base"]["generated_keys"]["black_support"]]
        ],
    }


def heightmap_with_target_heights(
    heightmap: dict[str, Any],
    target_height_plate: list[list[int]],
    config: dict[str, Any],
) -> dict[str, Any]:
    width_stud = int(heightmap["metrics"]["widthStud"])
    depth_stud = int(heightmap["metrics"]["depthStud"])
    if (
        len(target_height_plate) != depth_stud
        or any(len(row) != width_stud for row in target_height_plate)
    ):
        raise ValueError(config["colored_replacement"]["errors"]["target_dimensions_mismatch"])
    return {
        **heightmap,
        "modelId": config["colored_replacement"]["transient_heightmap_model_id_template"].format(
            source_dem_model_id=heightmap["sourceDemModelId"],
        ),
        "cells": [
            {
                **cell,
                "heightPlate": target_height_plate[int(cell["z"])][int(cell["x"])],
            }
            for cell in heightmap["cells"]
        ],
    }


def rotation_quarter_turns(rotation_degrees: int, config: dict[str, Any]) -> int:
    rotations = {
        int(rotation["degrees"]): int(rotation["quarter_turns"])
        for rotation in config["rotations"]
    }
    if rotation_degrees not in rotations:
        raise ValueError(config["errors"]["rotation_missing"])
    return rotations[rotation_degrees]


def oriented_profile_matrices(
    profile: Any,
    rotation_degrees: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    quarter_turns = rotation_quarter_turns(rotation_degrees, config)
    return {
        "surface": rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.surface_height_plate),
            quarter_turns,
        ),
        "collision": rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.collision_intervals_plate),
            quarter_turns,
        ),
        "contact": rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.bottom_contact),
            quarter_turns,
        ),
        "topConnection": rotate_matrix(
            orient_ldraw_matrix_to_dem(profile.top_connection_mask),
            quarter_turns,
        ),
    }


def colored_replacement_candidate(
    placement: dict[str, Any],
    profile: Any,
    config: dict[str, Any],
) -> SurfacePatchCandidate:
    sample_rate = profile.samples_per_stud_axis
    matrices = oriented_profile_matrices(
        profile,
        int(placement["rotationDegrees"]),
        config["colored_replacement"],
    )
    top_connect_cells = tuple(
        (placement["xStud"] + x // sample_rate, placement["zStud"] + z // sample_rate)
        for z, row in enumerate(matrices["topConnection"])
        for x, connected in enumerate(row)
        if connected
    )
    support_cells = tuple(
        (placement["xStud"] + x, placement["zStud"] + z)
        for x, z in support_stud_cells(matrices["contact"], sample_rate)
    )
    decimals = config["surface_patch"]["matching"]["rounding_decimal_places"]
    base_plate = int(placement["basePlate"])
    return SurfacePatchCandidate(
        part_id=placement["partId"],
        ldraw_origin_to_base_ldu=profile.ldraw_origin_to_base_ldu,
        ldraw_center_x_ldu=profile.ldraw_center_x_ldu,
        ldraw_center_z_ldu=profile.ldraw_center_z_ldu,
        x_stud=int(placement["xStud"]),
        z_stud=int(placement["zStud"]),
        width_stud=int(placement["widthStud"]),
        depth_stud=int(placement["depthStud"]),
        rotation_degrees=int(placement["rotationDegrees"]),
        base_plate=base_plate,
        color_id=int(placement["colorId"]),
        target_color_id=int(placement["colorId"]),
        color_distance=int(placement["colorDistance"]),
        uses_nearest_color=placement["colorMatchType"]
        == config["colored_replacement"]["color"]["nearest_match"],
        uses_approximate_geometry=True,
        is_visible=True,
        covered_cells=tuple(tuple(cell) for cell in placement["coveredCells"]),
        required_support_cells=support_cells,
        base_height_cells=tuple(tuple(cell) for cell in placement["baseHeightCells"]),
        top_connect_cells=top_connect_cells,
        top_connection_class=(
            config["surface_patch"]["matching"]["top_connection_classes"]["connected"]
            if top_connect_cells
            else config["surface_patch"]["matching"]["top_connection_classes"]["finished"]
        ),
        slope_edges=tuple(tuple(edge[:5]) for edge in placement["solvedSlopeEdges"]),
        slope_directions=tuple(placement["slopeDirections"]),
        matched_slope_direction_count=int(placement["slopeDirectionCount"]),
        surface_height_plate=tuple(
            tuple(
                None if value is None else round(value + base_plate, decimals)
                for value in row
            )
            for row in matrices["surface"]
        ),
        collision_intervals_plate=shifted_collision(
            matrices["collision"],
            base_plate,
            decimals,
        ),
        maximum_absolute_error_plate=float(placement["maximumPatternErrorPlate"]),
        total_absolute_error_plate=float(placement["maximumPatternErrorPlate"]),
        root_mean_square_error_plate=float(placement["maximumPatternErrorPlate"]),
    )


def supplement_candidates_after_replacement(
    candidates: tuple[SurfacePatchCandidate, ...],
    replacement_placements: tuple[SurfacePatchCandidate, ...],
    covered: set[tuple[int, int]],
    unresolved_edges: set[tuple[int, int, int, int, str]],
    target_height: tuple[tuple[int, ...], ...],
    sample_rate: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    selected = []
    current_placements = list(replacement_placements)
    covered_after_selection = set(covered)
    unresolved_after_selection = set(unresolved_edges)
    rejection_reasons = config["colored_replacement"]["supplement_rejection_reasons"]
    buildability_rejections: dict[SurfacePatchCandidate, str] = {}
    phase_candidates = [
        candidate
        for candidate in candidates
        if candidate.slope_edges
        and not candidate.uses_approximate_geometry
        and set(candidate.covered_cells).isdisjoint(covered_after_selection)
    ]
    eligible_candidate_count = len(phase_candidates)
    while unresolved_after_selection:
        placement = best_compatible_candidate(
            phase_candidates,
            covered_after_selection,
            unresolved_after_selection,
        )
        if placement is None:
            break
        build_rejection_reason = supplement_build_rejection_reason(
            tuple(current_placements + [placement]),
            target_height,
            sample_rate,
            config,
        )
        if build_rejection_reason is not None:
            buildability_rejections[placement] = build_rejection_reason
            phase_candidates.remove(placement)
            continue
        supplement = replace(
            placement,
            top_connection_class=config["colored_replacement"]["supplement_connection_class"],
        )
        selected.append(supplement)
        current_placements.append(supplement)
        covered_after_selection.update(supplement.covered_cells)
        unresolved_after_selection.difference_update(supplement.slope_edges)
        phase_candidates.remove(placement)
    rejections = supplement_rejection_examples(
        candidates,
        covered,
        covered_after_selection,
        unresolved_edges,
        unresolved_after_selection,
        buildability_rejections,
        {placement for placement in selected},
        rejection_reasons,
        int(config["colored_replacement"]["maximum_supplement_rejection_examples"]),
    )
    return {
        "placements": tuple(selected),
        "coveredCells": covered_after_selection,
        "unresolvedEdges": unresolved_after_selection,
        "diagnostics": {
            "sourceCandidateCount": len(candidates),
            "eligibleCandidateCount": eligible_candidate_count,
            "selectedPlacementCount": len(selected),
            "unresolvedEdgeCountBefore": len(unresolved_edges),
            "unresolvedEdgeCountAfter": len(unresolved_after_selection),
            "solvedEdgeCount": len(unresolved_edges) - len(unresolved_after_selection),
            "rejectedCandidateCount": len(rejections),
            "rejectionSummary": supplement_rejection_summary(rejections),
            "rejectionExamples": rejections[
                : int(config["colored_replacement"]["maximum_supplement_rejection_examples"])
            ],
        },
    }


def supplement_rejection_examples(
    candidates: tuple[SurfacePatchCandidate, ...],
    replacement_covered: set[tuple[int, int]],
    final_covered: set[tuple[int, int]],
    original_unresolved_edges: set[tuple[int, int, int, int, str]],
    final_unresolved_edges: set[tuple[int, int, int, int, str]],
    buildability_rejections: dict[SurfacePatchCandidate, str],
    selected: set[SurfacePatchCandidate],
    reasons: dict[str, str],
    maximum_examples: int,
) -> list[dict[str, Any]]:
    examples = []
    for candidate in candidates:
        if candidate in selected:
            continue
        reason = buildability_rejections.get(candidate)
        if reason is None:
            reason = supplement_rejection_reason(
                candidate,
                replacement_covered,
                final_covered,
                original_unresolved_edges,
                final_unresolved_edges,
                reasons,
            )
        if reason is None:
            continue
        examples.append(supplement_rejection_example(candidate, reason))
        if len(examples) >= maximum_examples:
            break
    return examples


def supplement_build_rejection_reason(
    placements: tuple[SurfacePatchCandidate, ...],
    target_height: tuple[tuple[int, ...], ...],
    sample_rate: int,
    config: dict[str, Any],
) -> str | None:
    base_h = build_base_h(placements, target_height)
    reasons = config["colored_replacement"]["supplement_rejection_reasons"]
    if any(
        base_h[z_stud][x_stud] < base_height
        for placement in placements
        for x_stud, z_stud, base_height in placement.base_height_cells
    ):
        return reasons["unsupported_base_h"]
    if (
        base_h_collision_sample_count(
            placements,
            base_h,
            sample_rate,
            config["surface_plan"],
        )
        != 0
    ):
        return reasons["base_h_collision"]
    return None


def supplement_rejection_reason(
    candidate: SurfacePatchCandidate,
    replacement_covered: set[tuple[int, int]],
    final_covered: set[tuple[int, int]],
    original_unresolved_edges: set[tuple[int, int, int, int, str]],
    final_unresolved_edges: set[tuple[int, int, int, int, str]],
    reasons: dict[str, str],
) -> str | None:
    covered_cells = set(candidate.covered_cells)
    slope_edges = set(candidate.slope_edges)
    if not slope_edges:
        return reasons["no_slope_edges"]
    if candidate.uses_approximate_geometry:
        return reasons["approximate_geometry"]
    if not covered_cells.isdisjoint(replacement_covered):
        return reasons["overlaps_replacement"]
    if not bool(slope_edges & original_unresolved_edges):
        return reasons["no_unresolved_edge_match"]
    if not covered_cells.isdisjoint(final_covered) and bool(slope_edges & final_unresolved_edges):
        return reasons["overlaps_selected_supplement"]
    return None


def supplement_rejection_example(
    candidate: SurfacePatchCandidate,
    reason: str,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "partId": candidate.part_id,
        "xStud": candidate.x_stud,
        "zStud": candidate.z_stud,
        "widthStud": candidate.width_stud,
        "depthStud": candidate.depth_stud,
        "rotationDegrees": candidate.rotation_degrees,
        "colorId": candidate.color_id,
        "targetColorId": candidate.target_color_id,
        "colorDistance": candidate.color_distance,
        "usesNearestColor": candidate.uses_nearest_color,
        "slopeDirections": list(candidate.slope_directions),
        "slopeDirectionCount": len(candidate.slope_directions),
        "slopeEdgeCount": len(candidate.slope_edges),
        "coveredCells": candidate.covered_cells,
        "slopeEdges": candidate.slope_edges,
    }


def supplement_rejection_summary(
    rejections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for rejection in rejections:
        counts[rejection["reason"]] += 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items())
    ]


def colored_replacement_surface_plan(
    replacement_plan: dict[str, Any],
    target_surface: tuple[tuple[float, ...], ...],
    target_height: tuple[tuple[int, ...], ...],
    target_colors: tuple[tuple[int, ...], ...],
    profiles: tuple[Any, ...],
    engine: Engine,
    config: dict[str, Any],
) -> tuple[SurfacePlan, int, dict[str, Any]]:
    profiles_by_part_id = {profile.part_id: profile for profile in profiles}
    replacement_placements = tuple(
        colored_replacement_candidate(
            placement,
            profiles_by_part_id[placement["partId"]],
            config,
        )
        for placement in replacement_plan["placements"]
    )
    supplement_source_candidates = generate_surface_patch_candidates(
        target_surface,
        target_colors,
        profiles,
        config["surface_patch"]["matching"],
    )
    target_color_rgb, available_color_rgb_by_part = load_surface_color_options(
        engine,
        {profile.part_id for profile in profiles},
        {color_id for row in target_colors for color_id in row},
        config,
    )
    supplement_source_candidates, _excluded_color_candidate_count = (
        prepare_surface_candidates_for_inventory(
            supplement_source_candidates,
            target_color_rgb,
            available_color_rgb_by_part,
            config["final_design"]["inventory_colors"],
        )
    )
    target_edges = heightmap_slope_edges(
        target_height,
        config["surface_patch"]["matching"]["slope_directions"],
    )
    replacement_solved_edges = {
        edge
        for placement in replacement_placements
        for edge in placement.slope_edges
    }
    covered = {
        cell
        for placement in replacement_placements
        for cell in placement.covered_cells
    }
    unresolved_edges = target_edges - replacement_solved_edges
    supplement_source_candidates = map_candidates_to_heightmap_edges(
        supplement_source_candidates,
        target_edges,
    )
    sample_rate = config["surface_profile"]["sampling"]["samples_per_stud_axis"]
    supplement_result = supplement_candidates_after_replacement(
        supplement_source_candidates,
        replacement_placements,
        covered,
        unresolved_edges,
        target_height,
        sample_rate,
        config,
    )
    supplement_placements = supplement_result["placements"]
    covered = supplement_result["coveredCells"]
    unresolved_edges = supplement_result["unresolvedEdges"]
    fill_placements = surface_fill_candidates(
        tuple(
            replace(
                candidate,
                top_connection_class=config["surface_plan"]["surface_fill_connection_class"],
            )
            for candidate in supplement_source_candidates
        ),
        covered,
        {
            (x_stud, z_stud)
            for z_stud in range(len(target_height))
            for x_stud in range(len(target_height[0]))
        },
    )
    placements = tuple(
        sorted(
            replacement_placements + supplement_placements + fill_placements,
            key=placement_sort_key,
        )
    )
    base_h = build_base_h(placements, target_height)
    replacement_phase = SurfaceReplacementPhase(
        connection_class=config["colored_replacement"]["strategy"],
        placements=tuple(sorted(replacement_placements, key=placement_sort_key)),
        base_h=build_base_h(replacement_placements, target_height),
        solved_slope_edge_count=int(replacement_plan["solvedSlopeEdgeCount"]),
        unresolved_slope_edge_count=int(replacement_plan["unresolvedSlopeEdgeCount"]),
    )
    supplement_phase = SurfaceReplacementPhase(
        connection_class=config["colored_replacement"]["supplement_connection_class"],
        placements=tuple(
            sorted(replacement_placements + supplement_placements, key=placement_sort_key)
        ),
        base_h=build_base_h(replacement_placements + supplement_placements, target_height),
        solved_slope_edge_count=len(target_edges) - len(unresolved_edges),
        unresolved_slope_edge_count=len(unresolved_edges),
    )
    fill_phase = SurfaceReplacementPhase(
        connection_class=config["surface_plan"]["surface_fill_connection_class"],
        placements=placements,
        base_h=base_h,
        solved_slope_edge_count=len(target_edges) - len(unresolved_edges),
        unresolved_slope_edge_count=len(unresolved_edges),
    )
    placed_cells = [cell for placement in placements for cell in placement.covered_cells]
    return (
        SurfacePlan(
            strategy=config["colored_replacement"]["final_strategy"],
            width_stud=len(target_height[0]),
            depth_stud=len(target_height),
            samples_per_stud_axis=sample_rate,
            placements=placements,
            replacement_phases=(replacement_phase, supplement_phase, fill_phase),
            base_h=base_h,
            maximum_absolute_error_plate=float(
                max(
                    (
                        placement.maximum_absolute_error_plate
                        for placement in placements
                    ),
                    default=0,
                )
            ),
            total_absolute_error_plate=float(
                sum(placement.total_absolute_error_plate for placement in placements)
            ),
            seam_error_plate=surface_plan_seam_error(
                placements,
                len(target_height[0]),
                len(target_height),
                target_surface,
                sample_rate,
                config["surface_plan"],
            ),
            part_count=len(placements),
            validation=SurfacePlanValidation(
                target_slope_edge_count=len(target_edges),
                solved_slope_edge_count=len(target_edges) - len(unresolved_edges),
                unresolved_slope_edge_count=len(unresolved_edges),
                covered_cell_count=len(set(placed_cells)),
                overlap_cell_count=len(placed_cells) - len(set(placed_cells)),
                unsupported_placement_count=sum(
                    any(
                        base_h[z_stud][x_stud] < base_height
                        for x_stud, z_stud, base_height in placement.base_height_cells
                    )
                    for placement in placements
                ),
                base_h_collision_sample_count=base_h_collision_sample_count(
                    placements,
                    base_h,
                    sample_rate,
                    config["surface_plan"],
                ),
                top_connected_placement_count=sum(
                    placement.top_connection_class
                    == config["surface_patch"]["matching"]["top_connection_classes"]["connected"]
                    for placement in placements
                ),
                top_finished_placement_count=sum(
                    placement.top_connection_class
                    == config["surface_patch"]["matching"]["top_connection_classes"]["finished"]
                    for placement in placements
                ),
            ),
        ),
        len(supplement_source_candidates),
        supplement_result["diagnostics"],
    )


def assemble_final_dem_design(
    plan: SurfacePlan,
    candidate_count: int,
    structure: dict[str, Any],
    support_base: dict[str, list[dict[str, Any]]],
    metadata: dict[tuple[str, int], dict[str, Any]],
    continuity_validations: tuple[VerticalContinuityValidation, ...],
    rejected_base_h_count: int,
    inventory_color_mapping_count: int,
    approximate_geometry_placement_count: int,
    excluded_color_candidate_count: int,
    strategy: str,
    replacement_diagnostics: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    surface_placements = final_surface_placements(plan, metadata, config)
    bom = final_bom(structure, surface_placements, support_base, config)
    steps = final_build_steps(structure, surface_placements, support_base, config)
    support_placement_count = sum(len(placements) for placements in support_base.values())
    total_placement_count = (
        len(structure["placements"])
        + len(surface_placements)
        + support_placement_count
    )
    step_placement_count = sum(len(step["placementRefs"]) for step in steps)
    structure_validation = structure["validation"]
    validation_failed = (
        plan.validation.covered_cell_count != plan.width_stud * plan.depth_stud
        or plan.validation.overlap_cell_count != 0
        or plan.validation.unsupported_placement_count != 0
        or plan.validation.base_h_collision_sample_count != 0
        or any(
            validation.discontinuous_column_count != 0
            for validation in continuity_validations
        )
        or structure_validation["targetVolumeStudPlate"]
        != structure_validation["placedVolumeStudPlate"]
        or structure_validation["unsupportedPlacementCount"] != 0
        or tuple(tuple(row) for row in structure["baseH"]) != plan.base_h
        or step_placement_count != total_placement_count
        or sum(item["quantity"] for item in bom) != total_placement_count
    )
    if validation_failed:
        raise ValueError(config["final_design"]["errors"]["validation_failed"])
    return {
        "strategy": strategy,
        "surfacePlan": surface_plan_response(plan, candidate_count),
        "supportBase": support_base,
        "baseStructure": structure,
        "surfacePlacements": surface_placements,
        "bom": bom,
        "steps": steps,
        "replacementDiagnostics": replacement_diagnostics,
        "validation": {
            "rejectedBaseHCount": rejected_base_h_count,
            "inventoryColorMappingCount": inventory_color_mapping_count,
            "approximateGeometryPlacementCount": approximate_geometry_placement_count,
            "excludedColorCandidateCount": excluded_color_candidate_count,
            "totalPlacementCount": total_placement_count,
            "stepPlacementCount": step_placement_count,
            "surfaceCollisionSampleCount": plan.validation.base_h_collision_sample_count,
            "surfaceUnsupportedPlacementCount": plan.validation.unsupported_placement_count,
            "structureUnsupportedPlacementCount": structure_validation["unsupportedPlacementCount"],
            "targetVolumeStudPlate": structure_validation["targetVolumeStudPlate"],
            "placedVolumeStudPlate": structure_validation["placedVolumeStudPlate"],
            "verticalContinuity": [
                vertical_continuity_response(validation)
                for validation in continuity_validations
            ],
        },
    }


def replacement_phase_diagnostics(plan: SurfacePlan) -> list[dict[str, Any]]:
    previous_placements: set[SurfacePatchCandidate] = set()
    summaries = []
    for phase in plan.replacement_phases:
        phase_placements = set(phase.placements)
        incremental_placements = phase_placements - previous_placements
        summaries.append(
            {
                "connectionClass": phase.connection_class,
                "placementCount": len(phase.placements),
                "incrementalPlacementCount": len(incremental_placements),
                "targetSlopeEdgeCount": (
                    phase.solved_slope_edge_count
                    + phase.unresolved_slope_edge_count
                ),
                "solvedSlopeEdgeCount": phase.solved_slope_edge_count,
                "unresolvedSlopeEdgeCount": phase.unresolved_slope_edge_count,
                "nearestColorPlacementCount": sum(
                    placement.uses_nearest_color
                    for placement in incremental_placements
                ),
                "approximateGeometryPlacementCount": sum(
                    placement.uses_approximate_geometry
                    for placement in incremental_placements
                ),
            }
        )
        previous_placements = phase_placements
    return summaries


def load_surface_metadata(
    engine: Engine,
    plan: SurfacePlan,
    config: dict[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    part_ids = {placement.part_id for placement in plan.placements}
    color_ids = {placement.color_id for placement in plan.placements}
    Session = sessionmaker(bind=engine)
    with Session() as session:
        colors = {
            color.id: color
            for color in session.scalars(select(Color).where(Color.id.in_(color_ids))).all()
        }
        part_rows = session.execute(
            select(LDrawPart, XrefPartNumber)
            .outerjoin(XrefPartNumber, XrefPartNumber.ldraw_part_num == LDrawPart.ldraw_part_num)
            .where(LDrawPart.ldraw_part_num.in_(part_ids))
        ).all()
    parts = {}
    for ldraw_part, xref in part_rows:
        part = parts.setdefault(
            ldraw_part.ldraw_part_num,
            {
                "rebrickablePartNum": None,
                "legoDesignId": None,
                "xrefRank": config["parts"]["xref_missing_rank"],
            },
        )
        apply_dem_part_xref(part, xref, config)
    if set(parts) != part_ids:
        raise ValueError(config["final_design"]["errors"]["part_metadata_missing"])
    if set(colors) != color_ids or any(colors[color_id].rgb is None for color_id in color_ids):
        raise ValueError(config["final_design"]["errors"]["color_metadata_missing"])
    metadata = {}
    for part_id in part_ids:
        for color_id in color_ids:
            if not any(
                placement.part_id == part_id and placement.color_id == color_id
                for placement in plan.placements
            ):
                continue
            part = parts[part_id]
            color = colors[color_id]
            rgb = color.rgb.upper()
            metadata[(part_id, color_id)] = {
                "rebrickablePartNum": part["rebrickablePartNum"],
                "legoDesignId": part["legoDesignId"],
                "colorName": color.name,
                "colorRgb": f"{config['final_design']['color']['rgb_prefix']}{rgb}",
                "ldrawColorCode": config["final_design"]["color"]["ldraw_code_template"].format(
                    color_id=color.id,
                ),
            }
    return metadata


def rgb_channels(rgb: str, config: dict[str, Any]) -> tuple[int, int, int]:
    channels = config["rgb_channels"]
    radix = config["hex_radix"]
    return (
        int(rgb[channels["red_start"] : channels["red_end"]], radix),
        int(rgb[channels["green_start"] : channels["green_end"]], radix),
        int(rgb[channels["blue_start"] : channels["blue_end"]], radix),
    )


def prepare_surface_candidates_for_inventory(
    candidates: tuple[SurfacePatchCandidate, ...],
    target_color_rgb: dict[int, str],
    available_color_rgb_by_part: dict[str, dict[int, str]],
    config: dict[str, Any],
) -> tuple[tuple[SurfacePatchCandidate, ...], int]:
    prepared = []
    excluded_candidate_count = 0
    for candidate in candidates:
        available_colors = available_color_rgb_by_part.get(candidate.part_id)
        if not available_colors:
            excluded_candidate_count += 1
            continue
        if not candidate.is_visible:
            color_id = min(available_colors)
            prepared.append(replace(candidate, color_id=color_id))
            continue
        if candidate.target_color_id in available_colors:
            prepared.append(candidate)
            continue
        source_channels = rgb_channels(target_color_rgb[candidate.target_color_id], config)
        color_id = min(
            available_colors,
            key=lambda candidate_color_id: (
                sum(
                    (source - available) ** config["distance_exponent"]
                    for source, available in zip(
                        source_channels,
                        rgb_channels(available_colors[candidate_color_id], config),
                    )
                ),
                candidate_color_id,
            ),
        )
        distance = sum(
            (source - available) ** config["distance_exponent"]
            for source, available in zip(
                source_channels,
                rgb_channels(available_colors[color_id], config),
            )
        )
        if distance > int(config["maximum_squared_distance"]):
            excluded_candidate_count += 1
            continue
        prepared.append(
            replace(
                candidate,
                color_id=color_id,
                color_distance=distance,
                uses_nearest_color=True,
            )
        )
    return tuple(prepared), excluded_candidate_count


def surface_plan_is_complete(plan: SurfacePlan) -> bool:
    return (
        plan.validation.unresolved_slope_edge_count == 0
        and plan.validation.covered_cell_count == plan.width_stud * plan.depth_stud
    )


def solve_layered_surface_plan(
    width_stud: int,
    depth_stud: int,
    target_surface: tuple[tuple[float, ...], ...],
    target_height: tuple[tuple[int, ...], ...],
    sample_rate: int,
    candidates: tuple[SurfacePatchCandidate, ...],
    rejected_base_h: set[tuple[tuple[int, ...], ...]],
    config: dict[str, Any],
) -> SurfacePlan:
    last_plan = None
    not_coverable_error = config["surface_plan"]["errors"]["surface_not_coverable"]
    for layer in config["final_design"]["surface_candidate_layers"]:
        layer_candidates = tuple(
            candidate
            for candidate in candidates
            if (layer["allow_nearest_color"] or not candidate.uses_nearest_color)
            and (
                layer["allow_approximate_geometry"]
                or not candidate.uses_approximate_geometry
            )
        )
        try:
            last_plan = solve_surface_plan(
                width_stud,
                depth_stud,
                target_surface,
                target_height,
                sample_rate,
                layer_candidates,
                rejected_base_h,
                config["surface_plan"],
                config["surface_patch"]["matching"]["slope_directions"],
            )
        except ValueError as error:
            if str(error) != not_coverable_error:
                raise
            continue
        if surface_plan_is_complete(last_plan):
            return last_plan
    if last_plan is None:
        raise ValueError(not_coverable_error)
    return last_plan


def load_surface_color_options(
    engine: Engine,
    part_ids: set[str],
    target_color_ids: set[int],
    config: dict[str, Any],
) -> tuple[dict[int, str], dict[str, dict[int, str]]]:
    color_config = config["final_design"]["inventory_colors"]
    Session = sessionmaker(bind=engine)
    with Session() as session:
        target_colors = {
            color.id: color.rgb.upper()
            for color in session.scalars(
                select(Color).where(Color.id.in_(target_color_ids), Color.rgb.is_not(None))
            ).all()
        }
        rows = session.execute(
            select(XrefPartNumber.ldraw_part_num, Color.id, Color.rgb)
            .join(
                InventoryPart,
                InventoryPart.part_num == XrefPartNumber.rebrickable_part_num,
            )
            .join(Color, Color.id == InventoryPart.color_id)
            .where(XrefPartNumber.ldraw_part_num.in_(part_ids))
            .where(XrefPartNumber.relation_type == color_config["xref_relation"])
            .where(Color.rgb.is_not(None))
            .distinct()
        ).all()
        fallback_part_numbers = {
            part_num
            for part_numbers in color_config["part_number_fallbacks"].values()
            for part_num in part_numbers
        }
        fallback_rows = session.execute(
            select(InventoryPart.part_num, Color.id, Color.rgb)
            .join(Color, Color.id == InventoryPart.color_id)
            .where(InventoryPart.part_num.in_(fallback_part_numbers))
            .where(Color.rgb.is_not(None))
            .distinct()
        ).all()
    if set(target_colors) != target_color_ids:
        raise ValueError(color_config["errors"]["target_color_missing"])
    available_colors: dict[str, dict[int, str]] = defaultdict(dict)
    for part_id, color_id, rgb in rows:
        available_colors[part_id][color_id] = rgb.upper()
    fallback_colors: dict[str, dict[int, str]] = defaultdict(dict)
    for part_num, color_id, rgb in fallback_rows:
        fallback_colors[part_num][color_id] = rgb.upper()
    for part_id, part_numbers in color_config["part_number_fallbacks"].items():
        for part_num in part_numbers:
            available_colors[part_id].update(fallback_colors[part_num])
    return target_colors, dict(available_colors)


def load_final_dem_design(
    target_surface: list[list[float]],
    target_height_plate: list[list[int]],
    target_colors: list[list[int]],
    part_ids: list[str],
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    validate_surface_part_ids(part_ids, config["surface_patch"])
    profiles = load_part_surface_profile_models(
        tuple(part_ids),
        engine,
        config,
        config["surface_profile"]["sampling"]["samples_per_stud_axis"],
    )
    normalized_surface = tuple(tuple(row) for row in target_surface)
    normalized_height = tuple(tuple(row) for row in target_height_plate)
    normalized_colors = tuple(tuple(row) for row in target_colors)
    candidates = generate_surface_patch_candidates(
        normalized_surface,
        normalized_colors,
        profiles,
        config["surface_patch"]["matching"],
    )
    target_color_rgb, available_color_rgb_by_part = load_surface_color_options(
        engine,
        {profile.part_id for profile in profiles},
        {color_id for row in normalized_colors for color_id in row},
        config,
    )
    candidates, excluded_color_candidate_count = (
        prepare_surface_candidates_for_inventory(
            candidates,
            target_color_rgb,
            available_color_rgb_by_part,
            config["final_design"]["inventory_colors"],
        )
    )
    structure_parts = load_dem_structure_parts(engine, config)
    rejected_base_h: set[tuple[tuple[int, ...], ...]] = set()
    while True:
        try:
            plan = solve_layered_surface_plan(
                len(normalized_colors[0]),
                len(normalized_colors),
                normalized_surface,
                normalized_height,
                profiles[0].samples_per_stud_axis,
                candidates,
                rejected_base_h,
                config,
            )
        except ValueError as error:
            if rejected_base_h and str(error) == config["surface_plan"]["errors"]["surface_not_coverable"]:
                raise ValueError(config["final_design"]["errors"]["structure_not_coverable"]) from error
            raise
        try:
            structure = build_base_h_structure(
                [list(row) for row in plan.base_h],
                structure_parts,
                config,
            )
        except ValueError as error:
            if str(error) != config["errors"]["base_h_uncovered"]:
                raise
            rejected_base_h.add(plan.base_h)
            continue
        metadata = load_surface_metadata(engine, plan, config)
        inventory_color_mapping_count = sum(
            placement.uses_nearest_color for placement in plan.placements
        )
        approximate_geometry_placement_count = sum(
            placement.uses_approximate_geometry for placement in plan.placements
        )
        continuity_part_ids = tuple(sorted({
            placement.part_id
            for placement in plan.placements
        }))
        continuity_profiles = load_part_surface_profile_models(
            continuity_part_ids,
            engine,
            config,
            config["vertical_continuity"]["samples_per_stud_axis"],
        )
        profiles_by_part_id = {
            profile.part_id: profile
            for profile in continuity_profiles
        }
        continuity_validations = tuple(
            phase_vertical_continuity(
                phase,
                plan.width_stud,
                plan.depth_stud,
                profiles_by_part_id,
                config["vertical_continuity"],
            )
            for phase in plan.replacement_phases
        )
        return assemble_final_dem_design(
            plan,
            len(candidates),
            structure,
            build_dem_support_base(structure, structure_parts, config),
            metadata,
            continuity_validations,
            len(rejected_base_h),
            inventory_color_mapping_count,
            approximate_geometry_placement_count,
            excluded_color_candidate_count,
            config["final_design"]["strategy"],
            None,
            config,
        )


def load_colored_replacement_final_dem_design(
    heightmap: dict[str, Any],
    target_surface: list[list[float]],
    target_height_plate: list[list[int]],
    target_colors: list[list[int]],
    part_ids: list[str],
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    normalized_surface = tuple(tuple(row) for row in target_surface)
    normalized_height = tuple(tuple(row) for row in target_height_plate)
    normalized_colors = tuple(tuple(row) for row in target_colors)
    replacement_heightmap = heightmap_with_target_heights(
        heightmap,
        target_height_plate,
        config,
    )
    replacement_plan = load_colored_replacement_plan(
        replacement_heightmap,
        engine,
        config["colored_replacement"],
    )
    replacement_part_ids = {
        placement["partId"]
        for placement in replacement_plan["placements"]
    }
    profile_part_ids = tuple(sorted(set(part_ids) | replacement_part_ids))
    profiles = load_part_surface_profile_models(
        profile_part_ids,
        engine,
        config,
        config["surface_profile"]["sampling"]["samples_per_stud_axis"],
    )
    plan, candidate_count, supplement_diagnostics = colored_replacement_surface_plan(
        replacement_plan,
        normalized_surface,
        normalized_height,
        normalized_colors,
        profiles,
        engine,
        config,
    )
    structure_parts = load_dem_structure_parts(engine, config)
    structure = build_base_h_structure(
        [list(row) for row in plan.base_h],
        structure_parts,
        config,
    )
    metadata = load_surface_metadata(engine, plan, config)
    continuity_part_ids = tuple(sorted({
        placement.part_id
        for placement in plan.placements
    }))
    continuity_profiles = load_part_surface_profile_models(
        continuity_part_ids,
        engine,
        config,
        config["vertical_continuity"]["samples_per_stud_axis"],
    )
    profiles_by_part_id = {
        profile.part_id: profile
        for profile in continuity_profiles
    }
    continuity_validations = tuple(
        phase_vertical_continuity(
            phase,
            plan.width_stud,
            plan.depth_stud,
            profiles_by_part_id,
            config["vertical_continuity"],
        )
        for phase in plan.replacement_phases
    )
    return assemble_final_dem_design(
        plan,
        candidate_count,
        structure,
        build_dem_support_base(structure, structure_parts, config),
        metadata,
        continuity_validations,
        0,
        sum(placement.uses_nearest_color for placement in plan.placements),
        sum(placement.uses_approximate_geometry for placement in plan.placements),
        replacement_plan["missingColorRequirementCount"],
        config["colored_replacement"]["final_strategy"],
        {
            "heightmapModelId": replacement_plan["heightmapModelId"],
            "connectedRegionCount": replacement_plan["connectedRegionCount"],
            "patternCount": replacement_plan["patternCount"],
            "geometricMatchCount": replacement_plan["geometricMatchCount"],
            "colorMatchedCount": replacement_plan["colorMatchedCount"],
            "colorSubstitutionCount": replacement_plan["colorSubstitutionCount"],
            "missingColorRequirementCount": replacement_plan["missingColorRequirementCount"],
            "missingColorRequirementTypeCount": replacement_plan["missingColorRequirementTypeCount"],
            "replacementPlacementCount": replacement_plan["placementCount"],
            "targetSlopeEdgeCount": replacement_plan["targetSlopeEdgeCount"],
            "solvedSlopeEdgeCount": replacement_plan["solvedSlopeEdgeCount"],
            "unresolvedSlopeEdgeCount": replacement_plan["unresolvedSlopeEdgeCount"],
            "phaseSummaries": replacement_phase_diagnostics(plan),
            "supplementDiagnostics": supplement_diagnostics,
            "missingColorSummary": replacement_plan["missingColorSummary"],
            "missingColorRequirements": replacement_plan["missingColorRequirements"],
        },
        config,
    )


def export_dem_final_design_ldraw(
    dem_design: dict[str, Any],
    config: dict[str, Any],
) -> str:
    """Convert the final DEM design to step-constrained LDraw text."""
    ldraw_config = config["dem_ldraw"]
    support_base = dem_design["supportBase"]
    structure = dem_design["baseStructure"]
    surface_placements = dem_design["surfacePlacements"]
    grid_width = structure["widthStud"]
    grid_depth = structure["depthStud"]

    lines = _dem_ldraw_header(ldraw_config)

    constrained_steps = _dem_resolve_and_constrain_steps(
        dem_design["steps"],
        support_base,
        structure["placements"],
        surface_placements,
        ldraw_config,
    )

    for step_index, step in enumerate(constrained_steps):
        if step_index:
            lines.append(_dem_ldraw_step_line(ldraw_config))
        lines.extend(_dem_ldraw_section(step["name"], ldraw_config))
        for placement in step["placements"]:
            lines.append(
                _dem_ldraw_part_line(
                    placement,
                    grid_width,
                    grid_depth,
                    ldraw_config,
                )
            )

    return ldraw_config["line_separator"].join(lines) + ldraw_config["line_separator"]


def _dem_resolve_and_constrain_steps(
    steps: list[dict[str, Any]],
    support_base: dict[str, list[dict[str, Any]]],
    structure_placements: list[dict[str, Any]],
    surface_placements: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve placementRefs and split steps by part/type limits."""
    step_config = config["steps"]
    max_placements = step_config["maximum_placements_per_step"]
    max_types = step_config["maximum_part_types_per_step"]

    resolved = []
    for step in steps:
        placements = []
        for ref in step["placementRefs"]:
            source_by_kind = {
                config["placement_ref_kinds"]["structure"]: structure_placements,
                config["placement_ref_kinds"]["surface"]: surface_placements,
                config["placement_ref_kinds"]["white_base"]: support_base[
                    config["placement_ref_kinds"]["white_base"]
                ],
                config["placement_ref_kinds"]["black_support"]: support_base[
                    config["placement_ref_kinds"]["black_support"]
                ],
            }
            source = source_by_kind[ref["kind"]]
            source_placement = source[ref["index"]]
            placements.append(
                _map_dem_placement(source_placement, ref["kind"], config)
            )

        # Split if exceeds limits
        sub_batches = _split_placements(placements, max_placements, max_types)
        for batch_index, batch in enumerate(sub_batches):
            batch_name = step["name"] if len(sub_batches) == 1 else (
                f"{step['name']} ({batch_index + 1}/{len(sub_batches)})"
            )
            resolved.append(
                {
                    "name": batch_name,
                    "basePlate": step["basePlate"],
                    "placements": batch,
                }
            )

    return resolved


def _split_placements(
    placements: list[dict[str, Any]],
    max_placements: int,
    max_types: int,
) -> list[list[dict[str, Any]]]:
    """Split placements into batches respecting part count and type limits."""
    batches = []
    batch = []
    batch_types: set[str] = set()

    for placement in placements:
        part_id = placement["partId"]
        would_exceed_count = len(batch) >= max_placements
        would_exceed_types = (
            part_id not in batch_types
            and len(batch_types) >= max_types
        )

        if batch and (would_exceed_count or would_exceed_types):
            batches.append(batch)
            batch = []
            batch_types = set()

        batch.append(placement)
        batch_types.add(part_id)

    if batch:
        batches.append(batch)

    return batches


def _map_dem_placement(
    placement: dict[str, Any],
    kind: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Map DEM placement to LDraw-compatible format."""
    if kind == config["placement_ref_kinds"]["structure"]:
        return {
            "x": placement["x"],
            "y": placement["z"],
            "width": placement["width"],
            "height": placement["depth"],
            "rotation": placement["rotation"],
            "basePlate": placement["basePlate"],
            "originToBaseLdu": placement["heightPlate"] * config["ldu_per_plate"],
            "originCenterXLdu": 0,
            "originCenterZLdu": 0,
            "matrix": config["structure_rotation_matrices"][str(placement["rotation"])],
            "ldrawColorCode": placement["ldrawColorCode"],
            "partId": placement["partId"],
        }
    if kind == config["placement_ref_kinds"]["surface"]:
        return {
            "x": placement["xStud"],
            "y": placement["zStud"],
            "width": placement["widthStud"],
            "height": placement["depthStud"],
            "rotation": placement["rotationDegrees"],
            "basePlate": placement["basePlate"],
            "originToBaseLdu": placement["ldrawOriginToBaseLdu"],
            "originCenterXLdu": placement["ldrawCenterXLdu"],
            "originCenterZLdu": placement["ldrawCenterZLdu"],
            "matrix": config["surface_rotation_matrices"][str(placement["rotationDegrees"])],
            "ldrawColorCode": placement["ldrawColorCode"],
            "partId": placement["partId"],
        }
    return {
        "x": placement["x"],
        "y": placement["y"],
        "width": placement["width"],
        "height": placement["height"],
        "rotation": placement["rotation"],
        "basePlate": -placement["yLdu"] / config["ldu_per_plate"],
        "originToBaseLdu": config["support_origin_to_base_ldu"],
        "originCenterXLdu": config["support_origin_center_x_ldu"],
        "originCenterZLdu": config["support_origin_center_z_ldu"],
        "matrix": config["structure_rotation_matrices"][str(placement["rotation"])],
        "ldrawColorCode": placement["ldrawColorCode"],
        "partId": placement["partId"],
    }


def _dem_ldraw_header(config: dict[str, Any]) -> list[str]:
    return [
        _dem_ldraw_meta_line(config["file_command"], config["model_file_name"], config),
        _dem_ldraw_meta_line(config["name_command"], config["model_file_name"], config),
        _dem_ldraw_meta_line(config["author_command"], config["author"], config),
    ]


def _dem_ldraw_section(section: str, config: dict[str, Any]) -> list[str]:
    return [_dem_ldraw_meta_line(config["comment_prefix"], section, config)]


def _dem_ldraw_meta_line(command: str, value: str, config: dict[str, Any]) -> str:
    return " ".join([str(config["metadata_line_type"]), command, value])


def _dem_ldraw_step_line(config: dict[str, Any]) -> str:
    return " ".join([str(config["metadata_line_type"]), config["step_command"]])


def _dem_ldraw_part_line(
    placement: dict[str, Any],
    grid_width: int,
    grid_depth: int,
    config: dict[str, Any],
) -> str:
    projection = _dem_ldraw_part_projection(placement, grid_width, grid_depth, config)
    return " ".join(
        [
            str(config["part_line_type"]),
            placement["ldrawColorCode"],
            str(projection["x"]),
            str(projection["y"]),
            str(projection["z"]),
            *[str(value) for value in projection["matrix"]],
            placement["partId"],
        ]
    )


def _dem_ldraw_part_projection(
    placement: dict[str, Any],
    grid_width: int,
    grid_depth: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    origin_divisor = config["part_origin_offset_divisor"]
    x_center = placement["x"] * origin_divisor + placement["width"]
    z_center = placement["y"] * origin_divisor + placement["height"]
    x_origin = grid_width * origin_divisor * config["x_origin_grid_width_multiplier"]
    z_origin = grid_depth * origin_divisor * config["z_origin_grid_height_multiplier"]
    matrix = placement["matrix"]
    (
        matrix_xx,
        _matrix_xy,
        matrix_xz,
        _matrix_yx,
        _matrix_yy,
        _matrix_yz,
        matrix_zx,
        _matrix_zy,
        matrix_zz,
    ) = matrix
    transformed_center_x = (
        matrix_xx * placement["originCenterXLdu"]
        + matrix_xz * placement["originCenterZLdu"]
    )
    transformed_center_z = (
        matrix_zx * placement["originCenterXLdu"]
        + matrix_zz * placement["originCenterZLdu"]
    )
    y_ldu = round(
        config["y_ground_ldu"]
        + config["y_direction"]
        * (
            placement["basePlate"] * config["ldu_per_plate"]
            + placement["originToBaseLdu"]
        ),
        config["coordinate_precision"],
    )
    return {
        "x": round(
            (x_origin + x_center * config["x_direction"])
            * config["ldu_per_stud"]
            / origin_divisor
            - transformed_center_x,
            config["coordinate_precision"],
        ),
        "y": y_ldu,
        "z": round(
            (z_origin + z_center * config["z_direction"])
            * config["ldu_per_stud"]
            / origin_divisor
            - transformed_center_z,
            config["coordinate_precision"],
        ),
        "matrix": matrix,
    }
