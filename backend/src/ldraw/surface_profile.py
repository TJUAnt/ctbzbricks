"""Sample DEM planning profiles from real LDraw triangle geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math

from src.ldraw.mesh import Triangle, Vector


@dataclass(frozen=True)
class PartSurfaceProfile:
    part_id: str
    ldraw_origin_to_base_ldu: float
    ldraw_center_x_ldu: float
    ldraw_center_z_ldu: float
    width_stud: int
    depth_stud: int
    samples_per_stud_axis: int
    surface_height_plate: tuple[tuple[float | None, ...], ...]
    collision_intervals_plate: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
    bottom_contact: tuple[tuple[bool, ...], ...]
    top_connection_mask: tuple[tuple[bool, ...], ...]


def triangle_height_at(triangle: Triangle, x: float, z: float, tolerance: float) -> float | None:
    first, second, third = triangle.vertices
    denominator = (
        (second.z - third.z) * (first.x - third.x)
        + (third.x - second.x) * (first.z - third.z)
    )
    if math.isclose(denominator, 0, abs_tol=tolerance):
        return None
    first_weight = (
        (second.z - third.z) * (x - third.x)
        + (third.x - second.x) * (z - third.z)
    ) / denominator
    second_weight = (
        (third.z - first.z) * (x - third.x)
        + (first.x - third.x) * (z - third.z)
    ) / denominator
    third_weight = 1 - first_weight - second_weight
    if min(first_weight, second_weight, third_weight) < -tolerance:
        return None
    return first_weight * first.y + second_weight * second.y + third_weight * third.y


def unique_sorted(values: list[float], tolerance: float) -> tuple[float, ...]:
    result = []
    for value in sorted(values):
        if not result or not math.isclose(result[-1], value, abs_tol=tolerance):
            result.append(value)
    return tuple(result)


def build_part_surface_profile(
    part_id: str,
    surface_triangles: tuple[Triangle, ...],
    collision_triangles: tuple[Triangle, ...],
    top_connection_origins: tuple[Vector, ...],
    config: dict,
) -> PartSurfaceProfile:
    if not surface_triangles or not collision_triangles:
        raise ValueError(config["errors"]["empty_mesh"])
    vertices = tuple(vertex for triangle in collision_triangles for vertex in triangle.vertices)
    min_x = min(vertex.x for vertex in vertices)
    max_x = max(vertex.x for vertex in vertices)
    min_z = min(vertex.z for vertex in vertices)
    max_z = max(vertex.z for vertex in vertices)
    base_y = max(vertex.y for vertex in vertices)
    width_stud_value = (max_x - min_x) / config["ldu_per_stud"]
    depth_stud_value = (max_z - min_z) / config["ldu_per_stud"]
    width_stud = round(width_stud_value)
    depth_stud = round(depth_stud_value)
    if not math.isclose(width_stud_value, width_stud, abs_tol=config["dimension_tolerance_stud"]):
        raise ValueError(config["errors"]["non_stud_width"].format(part_id=part_id))
    if not math.isclose(depth_stud_value, depth_stud, abs_tol=config["dimension_tolerance_stud"]):
        raise ValueError(config["errors"]["non_stud_depth"].format(part_id=part_id))

    top_connection_mask = [
        [False for _x in range(width_stud)]
        for _z in range(depth_stud)
    ]
    position_tolerance = config["connection_position_tolerance_ldu"]
    for origin in top_connection_origins:
        if not (
            min_x - position_tolerance <= origin.x <= max_x + position_tolerance
            and min_z - position_tolerance <= origin.z <= max_z + position_tolerance
        ):
            continue
        x_stud = min(
            math.floor((origin.x - min_x + position_tolerance) / config["ldu_per_stud"]),
            width_stud - 1,
        )
        z_stud = min(
            math.floor((origin.z - min_z + position_tolerance) / config["ldu_per_stud"]),
            depth_stud - 1,
        )
        top_connection_mask[z_stud][x_stud] = True

    samples_per_stud = config["samples_per_stud_axis"]
    sample_step = config["ldu_per_stud"] / samples_per_stud
    sample_offset = sample_step * config["sample_center_fraction"]
    surface_rows = []
    collision_rows = []
    contact_rows = []
    for sample_z in range(depth_stud * samples_per_stud):
        z = min_z + sample_z * sample_step + sample_offset
        surface_row = []
        collision_row = []
        contact_row = []
        for sample_x in range(width_stud * samples_per_stud):
            x = min_x + sample_x * sample_step + sample_offset
            surface_intersections = unique_sorted(
                [
                    height
                    for triangle in surface_triangles
                    if (height := triangle_height_at(
                        triangle,
                        x,
                        z,
                        config["ray_tolerance_ldu"],
                    ))
                    is not None
                ],
                config["ray_tolerance_ldu"],
            )
            collision_intersections = unique_sorted(
                [
                    height
                    for triangle in collision_triangles
                    if (height := triangle_height_at(
                        triangle,
                        x,
                        z,
                        config["ray_tolerance_ldu"],
                    ))
                    is not None
                ],
                config["ray_tolerance_ldu"],
            )
            if not surface_intersections or not collision_intersections:
                surface_row.append(None)
                collision_row.append(())
                contact_row.append(False)
                continue
            surface_height = (base_y - surface_intersections[0]) / config["ldu_per_plate"]
            collision_bottom = (base_y - collision_intersections[-1]) / config["ldu_per_plate"]
            collision_top = (base_y - collision_intersections[0]) / config["ldu_per_plate"]
            surface_row.append(round(surface_height, config["rounding_decimal_places"]))
            collision_row.append(
                ((
                    round(collision_bottom, config["rounding_decimal_places"]),
                    round(collision_top, config["rounding_decimal_places"]),
                ),)
            )
            contact_row.append(
                math.isclose(
                    collision_intersections[-1],
                    base_y,
                    abs_tol=config["bottom_contact_tolerance_ldu"],
                )
            )
        surface_rows.append(tuple(surface_row))
        collision_rows.append(tuple(collision_row))
        contact_rows.append(tuple(contact_row))
    return PartSurfaceProfile(
        part_id=part_id,
        ldraw_origin_to_base_ldu=round(base_y, config["rounding_decimal_places"]),
        ldraw_center_x_ldu=round(
            (min_x + max_x) / config["center_divisor"],
            config["rounding_decimal_places"],
        ),
        ldraw_center_z_ldu=round(
            (min_z + max_z) / config["center_divisor"],
            config["rounding_decimal_places"],
        ),
        width_stud=width_stud,
        depth_stud=depth_stud,
        samples_per_stud_axis=samples_per_stud,
        surface_height_plate=tuple(surface_rows),
        collision_intervals_plate=tuple(collision_rows),
        bottom_contact=tuple(contact_rows),
        top_connection_mask=tuple(tuple(row) for row in top_connection_mask),
    )
