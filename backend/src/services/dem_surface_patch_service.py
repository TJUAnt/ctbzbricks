"""Generate real-part surface patch candidates for DEM optimization."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from sqlalchemy import Engine

from src.ldraw.surface_profile import PartSurfaceProfile
from src.services.dem_lego_design_service import load_part_surface_profile_models


SurfaceMatrix = tuple[tuple[float | None, ...], ...]
CollisionMatrix = tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
ContactMatrix = tuple[tuple[bool, ...], ...]
SurfaceSlopeEdge = tuple[int, int, int, int, str]


@dataclass(frozen=True)
class SurfacePatchCandidate:
    part_id: str
    ldraw_origin_to_base_ldu: float
    ldraw_center_x_ldu: float
    ldraw_center_z_ldu: float
    x_stud: int
    z_stud: int
    width_stud: int
    depth_stud: int
    rotation_degrees: int
    base_plate: int
    color_id: int
    target_color_id: int
    color_distance: int
    uses_nearest_color: bool
    uses_approximate_geometry: bool
    is_visible: bool
    covered_cells: tuple[tuple[int, int], ...]
    required_support_cells: tuple[tuple[int, int], ...]
    base_height_cells: tuple[tuple[int, int, int], ...]
    top_connect_cells: tuple[tuple[int, int], ...]
    top_connection_class: str
    slope_edges: tuple[SurfaceSlopeEdge, ...]
    slope_directions: tuple[str, ...]
    matched_slope_direction_count: int
    surface_height_plate: SurfaceMatrix
    collision_intervals_plate: CollisionMatrix
    maximum_absolute_error_plate: float
    total_absolute_error_plate: float
    root_mean_square_error_plate: float


def rotate_clockwise(matrix: tuple[tuple[object, ...], ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row[column] for row in reversed(matrix))
        for column in range(len(matrix[0]))
    )


def rotate_matrix(
    matrix: tuple[tuple[object, ...], ...],
    quarter_turns: int,
) -> tuple[tuple[object, ...], ...]:
    rotated = matrix
    for _turn in range(quarter_turns):
        rotated = rotate_clockwise(rotated)
    return rotated


def orient_ldraw_matrix_to_dem(
    matrix: tuple[tuple[object, ...], ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(reversed(matrix))


def validate_targets(
    target_surface: tuple[tuple[float, ...], ...],
    target_colors: tuple[tuple[int, ...], ...],
    sample_rate: int,
    config: dict,
) -> tuple[int, int]:
    if not target_surface or not target_surface[0]:
        raise ValueError(config["errors"]["target_surface_empty"])
    sample_width = len(target_surface[0])
    if any(len(row) != sample_width for row in target_surface):
        raise ValueError(config["errors"]["target_surface_not_rectangular"])
    if not target_colors or not target_colors[0]:
        raise ValueError(config["errors"]["target_dimensions_mismatch"])
    color_width = len(target_colors[0])
    if any(len(row) != color_width for row in target_colors):
        raise ValueError(config["errors"]["target_color_not_rectangular"])
    if (
        sample_width != color_width * sample_rate
        or len(target_surface) != len(target_colors) * sample_rate
    ):
        raise ValueError(config["errors"]["target_dimensions_mismatch"])
    return color_width, len(target_colors)


def occupied_stud_cells(
    collision: CollisionMatrix,
    sample_rate: int,
) -> tuple[tuple[int, int], ...]:
    sample_depth = len(collision)
    sample_width = len(collision[0])
    cells = []
    for z_stud in range(sample_depth // sample_rate):
        for x_stud in range(sample_width // sample_rate):
            if any(
                collision[z_sample][x_sample]
                for z_sample in range(z_stud * sample_rate, (z_stud + 1) * sample_rate)
                for x_sample in range(x_stud * sample_rate, (x_stud + 1) * sample_rate)
            ):
                cells.append((x_stud, z_stud))
    return tuple(cells)


def support_stud_cells(
    contact: ContactMatrix,
    sample_rate: int,
) -> tuple[tuple[int, int], ...]:
    sample_depth = len(contact)
    sample_width = len(contact[0])
    cells = []
    for z_stud in range(sample_depth // sample_rate):
        for x_stud in range(sample_width // sample_rate):
            if any(
                contact[z_sample][x_sample]
                for z_sample in range(z_stud * sample_rate, (z_stud + 1) * sample_rate)
                for x_sample in range(x_stud * sample_rate, (x_stud + 1) * sample_rate)
            ):
                cells.append((x_stud, z_stud))
    return tuple(cells)


def local_base_height_cells(
    collision: CollisionMatrix,
    contact: ContactMatrix,
    sample_rate: int,
    base_plate: int,
) -> tuple[tuple[int, int, int], ...]:
    sample_depth = len(collision)
    sample_width = len(collision[0])
    use_contact = any(connected for row in contact for connected in row)
    cells = []
    for z_stud in range(sample_depth // sample_rate):
        for x_stud in range(sample_width // sample_rate):
            lower_values = []
            for z_sample in range(z_stud * sample_rate, (z_stud + 1) * sample_rate):
                for x_sample in range(x_stud * sample_rate, (x_stud + 1) * sample_rate):
                    intervals = collision[z_sample][x_sample]
                    if intervals and (not use_contact or contact[z_sample][x_sample]):
                        lower_values.append(intervals[0][0])
            if lower_values:
                cells.append((x_stud, z_stud, base_plate + math.floor(min(lower_values))))
    return tuple(cells)


def base_height_candidates(
    residuals: tuple[float, ...],
    config: dict,
) -> tuple[int, ...]:
    ideal_base = sum(residuals) / len(residuals)
    anchors = (math.floor(ideal_base), math.ceil(ideal_base))
    return tuple(sorted({anchor + offset for anchor in anchors for offset in config["base_height_offsets"]}))


def shifted_collision(
    collision: CollisionMatrix,
    base_plate: int,
    decimals: int,
) -> CollisionMatrix:
    return tuple(
        tuple(
            tuple(
                (
                    round(lower + base_plate, decimals),
                    round(upper + base_plate, decimals),
                )
                for lower, upper in intervals
            )
            for intervals in row
        )
        for row in collision
    )


def surface_slope_directions(
    surface: SurfaceMatrix,
    config: dict,
) -> tuple[str, ...]:
    directions = {
        edge[4]
        for edge in surface_slope_edges(surface, config)
    }
    return tuple(
        direction
        for direction in config["order"]
        if direction in directions
    )


def surface_slope_edges(
    surface: SurfaceMatrix,
    config: dict,
) -> tuple[SurfaceSlopeEdge, ...]:
    edges = []
    depth = len(surface)
    width = len(surface[0])
    for z_sample, row in enumerate(surface):
        for x_sample, height in enumerate(row):
            if height is None:
                continue
            for neighbor in config["neighbors"]:
                neighbor_x = x_sample + neighbor["x"]
                neighbor_z = z_sample + neighbor["z"]
                if neighbor_x >= width or neighbor_z >= depth:
                    continue
                neighbor_height = surface[neighbor_z][neighbor_x]
                if neighbor_height is None:
                    continue
                delta = neighbor_height - height
                if abs(delta) < config["minimum_delta_plate"]:
                    continue
                edges.append(
                    (
                        x_sample,
                        z_sample,
                        neighbor_x,
                        neighbor_z,
                        neighbor["positive"] if delta > 0 else neighbor["negative"],
                    )
                )
    return tuple(edges)


def target_patch_surface(
    target_surface: tuple[tuple[float, ...], ...],
    x_stud: int,
    z_stud: int,
    sample_width: int,
    sample_depth: int,
    sample_rate: int,
) -> SurfaceMatrix:
    start_x = x_stud * sample_rate
    start_z = z_stud * sample_rate
    return tuple(
        tuple(row[start_x : start_x + sample_width])
        for row in target_surface[start_z : start_z + sample_depth]
    )


def generate_surface_patch_candidates(
    target_surface: tuple[tuple[float, ...], ...],
    target_colors: tuple[tuple[int, ...], ...],
    profiles: tuple[PartSurfaceProfile, ...],
    config: dict,
) -> tuple[SurfacePatchCandidate, ...]:
    if not profiles:
        return ()
    sample_rate = profiles[0].samples_per_stud_axis
    width_stud, depth_stud = validate_targets(
        target_surface,
        target_colors,
        sample_rate,
        config,
    )
    if any(profile.samples_per_stud_axis != sample_rate for profile in profiles):
        raise ValueError(config["errors"]["profile_sample_rate_mismatch"])

    candidates = []
    unbounded_error_part_ids = set(config["unbounded_error_part_ids"])
    for profile in profiles:
        orientation_signatures = set()
        for rotation in config["rotations"]:
            surface = rotate_matrix(
                orient_ldraw_matrix_to_dem(profile.surface_height_plate),
                rotation["quarter_turns"],
            )
            collision = rotate_matrix(
                orient_ldraw_matrix_to_dem(profile.collision_intervals_plate),
                rotation["quarter_turns"],
            )
            contact = rotate_matrix(
                orient_ldraw_matrix_to_dem(profile.bottom_contact),
                rotation["quarter_turns"],
            )
            top_connection = rotate_matrix(
                orient_ldraw_matrix_to_dem(profile.top_connection_mask),
                rotation["quarter_turns"],
            )
            signature = (surface, collision, contact, top_connection)
            if signature in orientation_signatures:
                continue
            orientation_signatures.add(signature)
            oriented_width = len(surface[0]) // sample_rate
            oriented_depth = len(surface) // sample_rate
            occupied_cells = occupied_stud_cells(collision, sample_rate)
            support_cells = support_stud_cells(contact, sample_rate)
            top_connect_cells = tuple(
                (x, z)
                for z, row in enumerate(top_connection)
                for x, connected in enumerate(row)
                if connected
            )
            slope_directions = surface_slope_directions(
                surface,
                config["slope_directions"],
            )
            slope_edges = surface_slope_edges(surface, config["slope_directions"])
            for z_stud in range(depth_stud - oriented_depth + 1):
                for x_stud in range(width_stud - oriented_width + 1):
                    local_target_surface = target_patch_surface(
                            target_surface,
                            x_stud,
                            z_stud,
                            len(surface[0]),
                            len(surface),
                            sample_rate,
                        )
                    target_directions = set(
                        surface_slope_directions(
                            local_target_surface,
                            config["slope_directions"],
                        )
                    )
                    if not set(slope_directions) <= target_directions:
                        continue
                    colors = {
                        target_colors[z_stud + local_z][x_stud + local_x]
                        for local_x, local_z in occupied_cells
                    }
                    if len(colors) != 1:
                        continue
                    color_id = next(iter(colors))
                    residuals = tuple(
                        target_surface[z_stud * sample_rate + sample_z][x_stud * sample_rate + sample_x]
                        - profile_height
                        for sample_z, row in enumerate(surface)
                        for sample_x, profile_height in enumerate(row)
                        if profile_height is not None
                    )
                    if not residuals:
                        continue
                    base_plates = tuple(
                        base_plate
                        for base_plate in base_height_candidates(residuals, config)
                        if base_plate >= config["minimum_base_height_plate"]
                    )
                    if profile.part_id in unbounded_error_part_ids:
                        base_plates = tuple(
                            sorted(
                                base_plates,
                                key=lambda base_plate: (
                                    max(abs(residual - base_plate) for residual in residuals),
                                    sum(abs(residual - base_plate) for residual in residuals),
                                    base_plate,
                                ),
                            )[: config["unbounded_error_maximum_base_candidates"]]
                        )
                    for base_plate in base_plates:
                        errors = tuple(
                            abs(residual - base_plate)
                            for residual in residuals
                        )
                        maximum_error = max(errors)
                        uses_approximate_geometry = (
                            profile.part_id not in unbounded_error_part_ids
                            and maximum_error > config["maximum_absolute_error_plate"]
                        )
                        if (
                            profile.part_id not in unbounded_error_part_ids
                            and maximum_error > config["approximate_maximum_absolute_error_plate"]
                        ):
                            continue
                        decimals = config["rounding_decimal_places"]
                        absolute_surface = tuple(
                            tuple(
                                None if value is None else round(value + base_plate, decimals)
                                for value in row
                            )
                            for row in surface
                        )
                        candidates.append(
                            SurfacePatchCandidate(
                                part_id=profile.part_id,
                                ldraw_origin_to_base_ldu=profile.ldraw_origin_to_base_ldu,
                                ldraw_center_x_ldu=profile.ldraw_center_x_ldu,
                                ldraw_center_z_ldu=profile.ldraw_center_z_ldu,
                                x_stud=x_stud,
                                z_stud=z_stud,
                                width_stud=oriented_width,
                                depth_stud=oriented_depth,
                                rotation_degrees=rotation["degrees"],
                                base_plate=base_plate,
                                color_id=color_id,
                                target_color_id=color_id,
                                color_distance=0,
                                uses_nearest_color=False,
                                uses_approximate_geometry=uses_approximate_geometry,
                                is_visible=True,
                                covered_cells=tuple(
                                    (x_stud + local_x, z_stud + local_z)
                                    for local_x, local_z in occupied_cells
                                ),
                                required_support_cells=tuple(
                                    (x_stud + local_x, z_stud + local_z)
                                    for local_x, local_z in support_cells
                                ),
                                base_height_cells=tuple(
                                    (x_stud + local_x, z_stud + local_z, base_height)
                                    for local_x, local_z, base_height in local_base_height_cells(
                                        collision,
                                        contact,
                                        sample_rate,
                                        base_plate,
                                    )
                                ),
                                top_connect_cells=tuple(
                                    (x_stud + local_x, z_stud + local_z)
                                    for local_x, local_z in top_connect_cells
                                ),
                                top_connection_class=(
                                    config["top_connection_classes"]["connected"]
                                    if top_connect_cells
                                    else config["top_connection_classes"]["finished"]
                                ),
                                slope_edges=tuple(
                                    (
                                        start_x + x_stud * sample_rate,
                                        start_z + z_stud * sample_rate,
                                        end_x + x_stud * sample_rate,
                                        end_z + z_stud * sample_rate,
                                        direction,
                                    )
                                    for start_x, start_z, end_x, end_z, direction in slope_edges
                                ),
                                slope_directions=slope_directions,
                                matched_slope_direction_count=len(slope_directions),
                                surface_height_plate=absolute_surface,
                                collision_intervals_plate=shifted_collision(
                                    collision,
                                    base_plate,
                                    decimals,
                                ),
                                maximum_absolute_error_plate=round(maximum_error, decimals),
                                total_absolute_error_plate=round(sum(errors), decimals),
                                root_mean_square_error_plate=round(
                                    math.sqrt(sum(error * error for error in errors) / len(errors)),
                                    decimals,
                                ),
                            )
                        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.matched_slope_direction_count,
                candidate.uses_approximate_geometry,
                candidate.maximum_absolute_error_plate,
                candidate.total_absolute_error_plate,
                candidate.part_id,
                candidate.z_stud,
                candidate.x_stud,
                candidate.rotation_degrees,
                candidate.base_plate,
            ),
        )
    )


def candidate_response(candidate: SurfacePatchCandidate) -> dict[str, Any]:
    return {
        "partId": candidate.part_id,
        "ldrawOriginToBaseLdu": candidate.ldraw_origin_to_base_ldu,
        "ldrawCenterXLdu": candidate.ldraw_center_x_ldu,
        "ldrawCenterZLdu": candidate.ldraw_center_z_ldu,
        "xStud": candidate.x_stud,
        "zStud": candidate.z_stud,
        "widthStud": candidate.width_stud,
        "depthStud": candidate.depth_stud,
        "rotationDegrees": candidate.rotation_degrees,
        "basePlate": candidate.base_plate,
        "colorId": candidate.color_id,
        "targetColorId": candidate.target_color_id,
        "colorDistance": candidate.color_distance,
        "usesNearestColor": candidate.uses_nearest_color,
        "usesApproximateGeometry": candidate.uses_approximate_geometry,
        "coveredCells": candidate.covered_cells,
        "requiredSupportCells": candidate.required_support_cells,
        "baseHeightCells": candidate.base_height_cells,
        "topConnectCells": candidate.top_connect_cells,
        "topConnectionClass": candidate.top_connection_class,
        "slopeEdges": candidate.slope_edges,
        "slopeDirections": candidate.slope_directions,
        "matchedSlopeDirectionCount": candidate.matched_slope_direction_count,
        "surfaceHeightPlate": candidate.surface_height_plate,
        "collisionIntervalsPlate": candidate.collision_intervals_plate,
        "maximumAbsoluteErrorPlate": candidate.maximum_absolute_error_plate,
        "totalAbsoluteErrorPlate": candidate.total_absolute_error_plate,
        "rootMeanSquareErrorPlate": candidate.root_mean_square_error_plate,
    }


def load_surface_patch_candidates(
    target_surface: list[list[float]],
    target_colors: list[list[int]],
    part_ids: list[str],
    engine: Engine,
    config: dict[str, Any],
) -> dict[str, Any]:
    patch_config = config["surface_patch"]
    validate_surface_part_ids(part_ids, patch_config)
    profiles = load_part_surface_profile_models(
        tuple(part_ids),
        engine,
        config,
        config["surface_profile"]["sampling"]["samples_per_stud_axis"],
    )
    candidates = generate_surface_patch_candidates(
        tuple(tuple(row) for row in target_surface),
        tuple(tuple(row) for row in target_colors),
        profiles,
        patch_config["matching"],
    )
    return {
        "widthStud": len(target_colors[0]),
        "depthStud": len(target_colors),
        "samplesPerStudAxis": profiles[0].samples_per_stud_axis,
        "candidates": [candidate_response(candidate) for candidate in candidates],
    }


def validate_surface_part_ids(part_ids: list[str], patch_config: dict[str, Any]) -> None:
    if not part_ids:
        raise ValueError(patch_config["errors"]["part_ids_empty"])
    if len(set(part_ids)) != len(part_ids):
        raise ValueError(patch_config["errors"]["part_ids_duplicate"])
