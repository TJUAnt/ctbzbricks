"""Globally select an exact cover of DEM surface patch candidates."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any

from sqlalchemy import Engine

from src.services.dem_lego_design_service import load_part_surface_profile_models
from src.services.dem_surface_patch_service import (
    SurfaceSlopeEdge,
    SurfacePatchCandidate,
    candidate_response,
    generate_surface_patch_candidates,
    validate_surface_part_ids,
)


@dataclass(frozen=True)
class SurfacePlanValidation:
    target_slope_edge_count: int
    solved_slope_edge_count: int
    unresolved_slope_edge_count: int
    covered_cell_count: int
    overlap_cell_count: int
    unsupported_placement_count: int
    base_h_collision_sample_count: int
    top_connected_placement_count: int
    top_finished_placement_count: int


@dataclass(frozen=True)
class SurfaceReplacementPhase:
    connection_class: str
    placements: tuple[SurfacePatchCandidate, ...]
    base_h: tuple[tuple[int, ...], ...]
    solved_slope_edge_count: int
    unresolved_slope_edge_count: int


@dataclass(frozen=True)
class SurfacePlan:
    strategy: str
    width_stud: int
    depth_stud: int
    samples_per_stud_axis: int
    placements: tuple[SurfacePatchCandidate, ...]
    replacement_phases: tuple[SurfaceReplacementPhase, ...]
    base_h: tuple[tuple[int, ...], ...]
    maximum_absolute_error_plate: float
    total_absolute_error_plate: float
    seam_error_plate: float
    part_count: int
    validation: SurfacePlanValidation


def candidate_sort_key(
    candidate: SurfacePatchCandidate,
    unresolved_edges: set[SurfaceSlopeEdge],
) -> tuple:
    matched_edges = set(candidate.slope_edges) & unresolved_edges
    matched_directions = {edge[4] for edge in matched_edges}
    return (
        -len(matched_directions),
        -len(matched_edges),
        candidate.uses_approximate_geometry,
        candidate.uses_nearest_color,
        -len(candidate.covered_cells),
        candidate.maximum_absolute_error_plate,
        candidate.total_absolute_error_plate,
        candidate.color_distance,
        candidate.part_id,
        candidate.z_stud,
        candidate.x_stud,
        candidate.rotation_degrees,
        candidate.base_plate,
    )


def best_compatible_candidate(
    candidates: list[SurfacePatchCandidate],
    covered: set[tuple[int, int]],
    unresolved_edges: set[SurfaceSlopeEdge],
) -> SurfacePatchCandidate | None:
    compatible = tuple(
        candidate
        for candidate in candidates
        if set(candidate.covered_cells).isdisjoint(covered)
        and bool(set(candidate.slope_edges) & unresolved_edges)
    )
    return min(
        compatible,
        key=lambda candidate: candidate_sort_key(candidate, unresolved_edges),
        default=None,
    )


def placement_sort_key(candidate: SurfacePatchCandidate) -> tuple:
    return (
        candidate.z_stud,
        candidate.x_stud,
        candidate.part_id,
        candidate.rotation_degrees,
        candidate.base_plate,
    )


def heightmap_slope_edges(
    target_height_plate: tuple[tuple[int, ...], ...],
    config: dict,
) -> set[SurfaceSlopeEdge]:
    edges = set()
    depth = len(target_height_plate)
    width = len(target_height_plate[0])
    for z_stud, row in enumerate(target_height_plate):
        for x_stud, height in enumerate(row):
            for neighbor in config["neighbors"]:
                neighbor_x = x_stud + neighbor["x"]
                neighbor_z = z_stud + neighbor["z"]
                if neighbor_x >= width or neighbor_z >= depth:
                    continue
                delta = target_height_plate[neighbor_z][neighbor_x] - height
                if abs(delta) < config["minimum_delta_plate"]:
                    continue
                edges.add(
                    (
                        x_stud,
                        z_stud,
                        neighbor_x,
                        neighbor_z,
                        neighbor["positive"] if delta > 0 else neighbor["negative"],
                    )
                )
    return edges


def map_candidates_to_heightmap_edges(
    candidates: tuple[SurfacePatchCandidate, ...],
    target_edges: set[SurfaceSlopeEdge],
) -> tuple[SurfacePatchCandidate, ...]:
    mapped = []
    for candidate in candidates:
        cells = set(candidate.covered_cells)
        directions = set(candidate.slope_directions)
        matched_edges = tuple(
            sorted(
                edge
                for edge in target_edges
                if edge[4] in directions
                and ((edge[0], edge[1]) in cells or (edge[2], edge[3]) in cells)
            )
        )
        mapped.append(replace(candidate, slope_edges=matched_edges))
    return tuple(mapped)


def surface_fill_candidates(
    candidates: tuple[SurfacePatchCandidate, ...],
    covered: set[tuple[int, int]],
    target_cells: set[tuple[int, int]],
) -> tuple[SurfacePatchCandidate, ...]:
    remaining = target_cells - covered
    selected = []
    flat_candidates = tuple(candidate for candidate in candidates if not candidate.slope_edges)
    while remaining:
        compatible = tuple(
            candidate
            for candidate in flat_candidates
            if set(candidate.covered_cells) <= remaining
        )
        if not compatible:
            break
        placement = min(
            compatible,
            key=lambda candidate: (
                -len(candidate.covered_cells),
                candidate.uses_approximate_geometry,
                candidate.uses_nearest_color,
                candidate.maximum_absolute_error_plate,
                candidate.total_absolute_error_plate,
                candidate.color_distance,
                candidate.part_id,
                candidate.z_stud,
                candidate.x_stud,
                candidate.base_plate,
            ),
        )
        selected.append(placement)
        remaining.difference_update(placement.covered_cells)
    return tuple(selected)


def predicted_sample(
    candidate: SurfacePatchCandidate,
    global_sample_x: int,
    global_sample_z: int,
    sample_rate: int,
) -> float | None:
    local_x = global_sample_x - candidate.x_stud * sample_rate
    local_z = global_sample_z - candidate.z_stud * sample_rate
    return candidate.surface_height_plate[local_z][local_x]


def surface_plan_seam_error(
    placements: tuple[SurfacePatchCandidate, ...],
    width_stud: int,
    depth_stud: int,
    target_surface: tuple[tuple[float, ...], ...],
    sample_rate: int,
    config: dict,
) -> float:
    owner = {
        cell: placement
        for placement in placements
        for cell in placement.covered_cells
    }
    seam_error = 0.0
    for z_stud in range(depth_stud):
        for x_stud in range(width_stud):
            current = owner.get((x_stud, z_stud))
            if current is None:
                continue
            for offset in config["seam_neighbor_offsets"]:
                neighbor_x = x_stud + offset["x"]
                neighbor_z = z_stud + offset["z"]
                if neighbor_x >= width_stud or neighbor_z >= depth_stud:
                    continue
                neighbor = owner.get((neighbor_x, neighbor_z))
                if neighbor is None:
                    continue
                if neighbor is current:
                    continue
                if offset["x"] == 1:
                    left_sample_x = neighbor_x * sample_rate - 1
                    right_sample_x = neighbor_x * sample_rate
                    for sample_offset in range(sample_rate):
                        sample_z = z_stud * sample_rate + sample_offset
                        left_height = predicted_sample(current, left_sample_x, sample_z, sample_rate)
                        right_height = predicted_sample(neighbor, right_sample_x, sample_z, sample_rate)
                        if left_height is None or right_height is None:
                            continue
                        left_error = left_height - target_surface[sample_z][left_sample_x]
                        right_error = right_height - target_surface[sample_z][right_sample_x]
                        seam_error += abs(left_error - right_error)
                if offset["z"] == 1:
                    upper_sample_z = neighbor_z * sample_rate - 1
                    lower_sample_z = neighbor_z * sample_rate
                    for sample_offset in range(sample_rate):
                        sample_x = x_stud * sample_rate + sample_offset
                        upper_height = predicted_sample(current, sample_x, upper_sample_z, sample_rate)
                        lower_height = predicted_sample(neighbor, sample_x, lower_sample_z, sample_rate)
                        if upper_height is None or lower_height is None:
                            continue
                        upper_error = upper_height - target_surface[upper_sample_z][sample_x]
                        lower_error = lower_height - target_surface[lower_sample_z][sample_x]
                        seam_error += abs(upper_error - lower_error)
    return round(seam_error, config["rounding_decimal_places"])


def build_base_h(
    placements: tuple[SurfacePatchCandidate, ...],
    target_height_plate: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    base_h = [list(row) for row in target_height_plate]
    for placement in placements:
        sample_rate = len(placement.collision_intervals_plate[0]) // placement.width_stud
        for local_sample_z, row in enumerate(placement.collision_intervals_plate):
            for local_sample_x, intervals in enumerate(row):
                if not intervals:
                    continue
                x_stud = placement.x_stud + local_sample_x // sample_rate
                z_stud = placement.z_stud + local_sample_z // sample_rate
                base_h[z_stud][x_stud] = min(
                    base_h[z_stud][x_stud],
                    math.floor(intervals[0][0]),
                )
        for x_stud, z_stud, base_height in placement.base_height_cells:
            base_h[z_stud][x_stud] = base_height
    return tuple(tuple(row) for row in base_h)


def base_h_collision_sample_count(
    placements: tuple[SurfacePatchCandidate, ...],
    base_h: tuple[tuple[int, ...], ...],
    sample_rate: int,
    config: dict,
) -> int:
    collision_count = 0
    for placement in placements:
        for local_sample_z, row in enumerate(placement.collision_intervals_plate):
            for local_sample_x, intervals in enumerate(row):
                cell_x = placement.x_stud + local_sample_x // sample_rate
                cell_z = placement.z_stud + local_sample_z // sample_rate
                for lower_plate, _upper_plate in intervals:
                    if base_h[cell_z][cell_x] > lower_plate + config["collision_tolerance_plate"]:
                        collision_count += 1
    return collision_count


def solve_surface_plan(
    width_stud: int,
    depth_stud: int,
    target_surface: tuple[tuple[float, ...], ...],
    target_height_plate: tuple[tuple[int, ...], ...],
    sample_rate: int,
    candidates: tuple[SurfacePatchCandidate, ...],
    rejected_base_h: set[tuple[tuple[int, ...], ...]],
    config: dict,
    slope_direction_config: dict,
) -> SurfacePlan:
    target_cells = tuple(
        (x_stud, z_stud)
        for z_stud in range(depth_stud)
        for x_stud in range(width_stud)
    )
    if (
        len(target_height_plate) != depth_stud
        or any(len(row) != width_stud for row in target_height_plate)
    ):
        raise ValueError(config["errors"]["target_height_dimensions_mismatch"])
    target_cell_set = set(target_cells)
    for candidate in candidates:
        if not candidate.covered_cells:
            raise ValueError(config["errors"]["candidate_cells_empty"])
        if any(cell not in target_cell_set for cell in candidate.covered_cells):
            raise ValueError(config["errors"]["candidate_outside_target"])
    target_edges = heightmap_slope_edges(target_height_plate, slope_direction_config)
    candidates = map_candidates_to_heightmap_edges(candidates, target_edges)
    covered: set[tuple[int, int]] = set()
    selected: list[SurfacePatchCandidate] = []
    replacement_phases = []
    unresolved_edges = set(target_edges)
    for connection_class in config["top_connection_phase_order"]:
        phase_candidates = [
            candidate
            for candidate in candidates
            if candidate.top_connection_class == connection_class
            and candidate.slope_edges
        ]
        while True:
            placement = best_compatible_candidate(
                phase_candidates,
                covered,
                unresolved_edges,
            )
            if placement is None:
                break
            selected.append(placement)
            covered.update(placement.covered_cells)
            unresolved_edges.difference_update(placement.slope_edges)
        phase_placements = tuple(sorted(selected, key=placement_sort_key))
        replacement_phases.append(
            SurfaceReplacementPhase(
                connection_class=connection_class,
                placements=phase_placements,
                base_h=build_base_h(phase_placements, target_height_plate),
                solved_slope_edge_count=len(target_edges) - len(unresolved_edges),
                unresolved_slope_edge_count=len(unresolved_edges),
            )
        )

    fill_placements = surface_fill_candidates(candidates, covered, target_cell_set)
    selected.extend(fill_placements)
    for placement in fill_placements:
        covered.update(placement.covered_cells)
    replacement_phases.append(
        SurfaceReplacementPhase(
            connection_class=config["surface_fill_connection_class"],
            placements=tuple(sorted(selected, key=placement_sort_key)),
            base_h=build_base_h(tuple(selected), target_height_plate),
            solved_slope_edge_count=len(target_edges) - len(unresolved_edges),
            unresolved_slope_edge_count=len(unresolved_edges),
        )
    )

    placements = tuple(sorted(selected, key=placement_sort_key))
    base_h = build_base_h(placements, target_height_plate)
    if base_h in rejected_base_h:
        raise ValueError(config["errors"]["surface_not_coverable"])
    maximum_absolute_error = round(
        max((placement.maximum_absolute_error_plate for placement in placements), default=0),
        config["rounding_decimal_places"],
    )
    total_absolute_error = round(
        sum(placement.total_absolute_error_plate for placement in placements),
        config["rounding_decimal_places"],
    )
    seam_error = surface_plan_seam_error(
        placements,
        width_stud,
        depth_stud,
        target_surface,
        sample_rate,
        config,
    )
    unsupported_count = sum(
        any(base_h[z_stud][x_stud] < base_height for x_stud, z_stud, base_height in placement.base_height_cells)
        for placement in placements
    )
    return SurfacePlan(
        strategy=config["strategy"],
        width_stud=width_stud,
        depth_stud=depth_stud,
        samples_per_stud_axis=sample_rate,
        placements=placements,
        replacement_phases=tuple(replacement_phases),
        base_h=base_h,
        maximum_absolute_error_plate=float(maximum_absolute_error),
        total_absolute_error_plate=float(total_absolute_error),
        seam_error_plate=float(seam_error),
        part_count=len(placements),
        validation=SurfacePlanValidation(
            target_slope_edge_count=len(target_edges),
            solved_slope_edge_count=len(target_edges) - len(unresolved_edges),
            unresolved_slope_edge_count=len(unresolved_edges),
            covered_cell_count=len(covered),
            overlap_cell_count=0,
            unsupported_placement_count=unsupported_count,
            base_h_collision_sample_count=base_h_collision_sample_count(
                placements,
                base_h,
                sample_rate,
                config,
            ),
            top_connected_placement_count=sum(
                placement.top_connection_class == config["top_connection_phase_order"][0]
                for placement in placements
            ),
            top_finished_placement_count=sum(
                placement.top_connection_class == config["top_connection_phase_order"][1]
                for placement in placements
            ),
        ),
    )


def surface_plan_response(plan: SurfacePlan, candidate_count: int) -> dict[str, Any]:
    return {
        "strategy": plan.strategy,
        "widthStud": plan.width_stud,
        "depthStud": plan.depth_stud,
        "samplesPerStudAxis": plan.samples_per_stud_axis,
        "candidateCount": candidate_count,
        "placements": [candidate_response(placement) for placement in plan.placements],
        "replacementPhases": [
            {
                "connectionClass": phase.connection_class,
                "placements": [candidate_response(placement) for placement in phase.placements],
                "baseH": phase.base_h,
                "solvedSlopeEdgeCount": phase.solved_slope_edge_count,
                "unresolvedSlopeEdgeCount": phase.unresolved_slope_edge_count,
            }
            for phase in plan.replacement_phases
        ],
        "baseH": plan.base_h,
        "maximumAbsoluteErrorPlate": plan.maximum_absolute_error_plate,
        "totalAbsoluteErrorPlate": plan.total_absolute_error_plate,
        "seamErrorPlate": plan.seam_error_plate,
        "partCount": plan.part_count,
        "validation": {
            "targetSlopeEdgeCount": plan.validation.target_slope_edge_count,
            "solvedSlopeEdgeCount": plan.validation.solved_slope_edge_count,
            "unresolvedSlopeEdgeCount": plan.validation.unresolved_slope_edge_count,
            "coveredCellCount": plan.validation.covered_cell_count,
            "overlapCellCount": plan.validation.overlap_cell_count,
            "unsupportedPlacementCount": plan.validation.unsupported_placement_count,
            "baseHCollisionSampleCount": plan.validation.base_h_collision_sample_count,
            "topConnectedPlacementCount": plan.validation.top_connected_placement_count,
            "topFinishedPlacementCount": plan.validation.top_finished_placement_count,
        },
    }


def load_surface_plan(
    target_surface: list[list[float]],
    target_height_plate: list[list[int]],
    target_colors: list[list[int]],
    part_ids: list[str],
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    plan, candidate_count = create_surface_plan(
        target_surface,
        target_height_plate,
        target_colors,
        part_ids,
        engine,
        set(),
        config,
    )
    return surface_plan_response(plan, candidate_count)


def create_surface_plan(
    target_surface: list[list[float]],
    target_height_plate: list[list[int]],
    target_colors: list[list[int]],
    part_ids: list[str],
    engine: Engine,
    rejected_base_h: set[tuple[tuple[int, ...], ...]],
    config: dict[str, Any],
) -> tuple[SurfacePlan, int]:
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
    plan = solve_surface_plan(
        len(normalized_colors[0]),
        len(normalized_colors),
        normalized_surface,
        normalized_height,
        profiles[0].samples_per_stud_axis,
        candidates,
        rejected_base_h,
        config["surface_plan"],
        config["surface_patch"]["matching"]["slope_directions"],
    )
    return plan, len(candidates)
