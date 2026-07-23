"""Component geometry derived from assembly snapshots, Part bounds, and LDraw meshes."""

from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import sessionmaker

from src.ldraw.mesh import collect_ldraw_mesh
from src.component_repo.relation_service import (
    expanded_world_parts,
    transform_point,
)
from src.model.models import (
    Component,
    ComponentSceneSnapshot,
    ComponentVersion,
    LDrawPart,
    LDrawPartGeometry,
)


def component_geometry(session: object, document: dict[str, Any]) -> dict[str, Any] | None:
    """Calculate overall logical size by transforming every Part's local bounding box.

    Bounding boxes are sufficient for assembly dimensions, but are deliberately kept
    separate from the triangle meshes used to render curved Part surfaces.
    """
    world_parts = expanded_world_parts(document)
    if not world_parts:
        return None
    part_numbers = sorted({part["referenceName"].casefold() for part in world_parts})
    rows = session.execute(
        select(LDrawPart, LDrawPartGeometry)
        .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
        .where(LDrawPart.ldraw_part_num.in_(part_numbers))
    ).all()
    geometries = {
        part.ldraw_part_num.casefold(): (part, geometry)
        for part, geometry in rows
    }
    points: list[tuple[float, float, float]] = []
    category_counts: dict[str, int] = {}
    for world_part in world_parts:
        part_row = geometries.get(world_part["referenceName"].casefold())
        if part_row is None:
            return None
        part, geometry = part_row
        bounds = (
            geometry.bbox_min_x,
            geometry.bbox_min_y,
            geometry.bbox_min_z,
            geometry.bbox_max_x,
            geometry.bbox_max_y,
            geometry.bbox_max_z,
        )
        if any(value is None for value in bounds):
            return None
        min_x, min_y, min_z, max_x, max_y, max_z = bounds
        points.extend(
            transform_point(world_part["worldTransform"], (x, y, z))
            for x in (min_x, max_x)
            for y in (min_y, max_y)
            for z in (min_z, max_z)
        )
        if part.category:
            category_counts[part.category] = category_counts.get(part.category, 0) + 1
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return {
        "widthLdu": max(xs) - min(xs),
        "heightLdu": max(ys) - min(ys),
        "depthLdu": max(zs) - min(zs),
        "widthStud": (max(xs) - min(xs)) / 20.0,
        "depthStud": (max(zs) - min(zs)) / 20.0,
        "heightPlate": (max(ys) - min(ys)) / 8.0,
        "partCount": len(world_parts),
        "categoryCounts": category_counts,
    }


def component_preview_parts(
    session: object,
    document: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Return assembly instances with transforms and diagnostic local Part bounds.

    The returned bounds describe size only. Renderers must pair ``partRef`` with the
    meshes returned by :func:`component_preview_meshes` instead of drawing boxes.
    """
    world_parts = expanded_world_parts(document)
    if not world_parts:
        return None
    part_numbers = sorted({part["referenceName"].casefold() for part in world_parts})
    rows = session.execute(
        select(LDrawPart, LDrawPartGeometry)
        .join(LDrawPartGeometry, LDrawPartGeometry.ldraw_part_id == LDrawPart.id)
        .where(LDrawPart.ldraw_part_num.in_(part_numbers))
    ).all()
    geometries = {
        part.ldraw_part_num.casefold(): geometry
        for part, geometry in rows
    }
    preview_parts: list[dict[str, Any]] = []
    for world_part in world_parts:
        part_ref = world_part["referenceName"].casefold()
        geometry = geometries.get(part_ref)
        if geometry is None:
            return None
        bounds = (
            geometry.bbox_min_x,
            geometry.bbox_min_y,
            geometry.bbox_min_z,
            geometry.bbox_max_x,
            geometry.bbox_max_y,
            geometry.bbox_max_z,
        )
        if any(value is None for value in bounds):
            return None
        min_x, min_y, min_z, max_x, max_y, max_z = bounds
        preview_parts.append(
            {
                "instanceId": world_part["instanceId"],
                "partRef": part_ref,
                "colorCode": world_part["colorCode"],
                "transform": world_part["worldTransform"],
                "bbox": {
                    "minX": min_x,
                    "minY": min_y,
                    "minZ": min_z,
                    "maxX": max_x,
                    "maxY": max_y,
                    "maxZ": max_z,
                },
            }
        )
    return preview_parts


def component_preview_meshes(
    session: object,
    document: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Build one reusable LDraw triangle mesh for every unique assembly Part.

    Component snapshots own instance placement while Part files own surface geometry.
    Consequently, repeated instances share the same local-space mesh. The operation is
    all-or-nothing so a viewer never presents a plausible but incomplete assembly.
    """
    world_parts = expanded_world_parts(document)
    if not world_parts:
        return None
    part_refs = sorted({part["referenceName"].casefold() for part in world_parts})
    rows = session.execute(
        select(LDrawPart.ldraw_part_num, LDrawPart.relative_path)
        .where(LDrawPart.ldraw_part_num.in_(part_refs))
    ).all()
    # Part references in snapshots and library records are matched case-insensitively.
    relative_paths = {
        part_num.casefold(): relative_path.casefold()
        for part_num, relative_path in rows
    }
    if set(relative_paths) != set(part_refs):
        return None
    meshes: list[dict[str, Any]] = []
    for part_ref in part_refs:
        mesh = part_preview_mesh(
            part_ref,
            relative_paths[part_ref],
            config,
        )
        if mesh is None:
            return None
        meshes.append(mesh)
    return meshes


def part_preview_mesh(
    part_ref: str,
    relative_path: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Build the indexed local-space surface mesh for one LDraw Part."""
    root = component_preview_ldraw_root(config["preview"])
    if root is None:
        return None
    return cached_part_preview_mesh(
        part_ref.casefold(),
        relative_path.casefold(),
        str(root),
        int(config["preview"]["coordinate_precision"]),
        json.dumps(config["preview"]["mesh"], sort_keys=True, separators=(",", ":")),
    )


@lru_cache(maxsize=4096)
def cached_part_preview_mesh(
    part_ref: str,
    relative_path: str,
    root_value: str,
    precision: int,
    mesh_config_json: str,
) -> dict[str, Any] | None:
    """Cache immutable per-Part mesh payloads across Component preview requests."""
    files = indexed_component_preview_files(root_value)
    mesh = collect_ldraw_mesh(
        relative_path,
        files,
        json.loads(mesh_config_json),
    )
    if not mesh.triangles or mesh.errors:
        return None
    return indexed_mesh_payload(
        part_ref,
        mesh.triangles,
        precision,
    )


def component_preview_ldraw_root(config: dict[str, Any]) -> Path | None:
    """Resolve the LDraw library root from the configured environment variable first."""
    env_value = os.getenv(config["ldraw_root_env"])
    candidates = [env_value, *config["ldraw_root_candidates"]]
    for value in candidates:
        if not value:
            continue
        root = Path(value).expanduser()
        if root.is_dir():
            return root
    return None


@lru_cache(maxsize=4)
def indexed_component_preview_files(root_value: str) -> dict[str, Path]:
    """Index official and Studio UnOfficial files, including high-resolution aliases.

    LDraw references ``p/<name>.dat`` for primitives. Studio may additionally provide
    a smoother ``p/48/<name>.dat`` variant, which is used only when no standard primitive
    has already claimed that reference.
    """
    root = Path(root_value)
    files: dict[str, Path] = {}
    high_resolution_aliases: list[tuple[str, Path]] = []
    for base in (root, root / "UnOfficial", root / "Unofficial"):
        if not base.is_dir():
            continue
        for section in ("parts", "p"):
            section_root = base / section
            if not section_root.is_dir():
                continue
            for path in section_root.rglob("*.dat"):
                relative_path = path.relative_to(base).as_posix().casefold()
                files.setdefault(relative_path, path)
                prefix = "p/48/"
                if relative_path.startswith(prefix):
                    high_resolution_aliases.append((f"p/{relative_path[len(prefix):]}", path))
    # Apply aliases in a second pass so a real p/<name>.dat always takes precedence.
    for alias, path in high_resolution_aliases:
        files.setdefault(alias, path)
    return files


def indexed_mesh_payload(
    part_ref: str,
    triangles: tuple[Any, ...],
    precision: int,
) -> dict[str, Any]:
    """Serialize triangles as a compact indexed mesh using rounded vertex deduplication.

    Positions stay in local Part space and LDraw units. ``precision`` makes identical
    vertices stable after nested floating-point transforms, reducing response size.
    """
    positions: list[float] = []
    indices: list[int] = []
    vertex_indices: dict[tuple[float, float, float], int] = {}
    for triangle in triangles:
        for vertex in triangle.vertices:
            key = (
                round(float(vertex.x), precision),
                round(float(vertex.y), precision),
                round(float(vertex.z), precision),
            )
            vertex_index = vertex_indices.get(key)
            if vertex_index is None:
                vertex_index = len(vertex_indices)
                vertex_indices[key] = vertex_index
                positions.extend(key)
            indices.append(vertex_index)
    return {
        "partRef": part_ref,
        "positions": positions,
        "indices": indices,
        "triangleCount": len(indices) // 3,
    }


def persist_component_logical_size(
    component: Component,
    geometry: dict[str, Any],
) -> None:
    component.logical_width_stud = geometry["widthStud"]
    component.logical_depth_stud = geometry["depthStud"]
    component.logical_height_plate = geometry["heightPlate"]


def clear_component_logical_size(component: Component) -> None:
    component.logical_width_stud = None
    component.logical_depth_stud = None
    component.logical_height_plate = None


def backfill_component_logical_sizes(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        components = session.scalars(
            select(Component).where(
                Component.current_version_id.is_not(None),
                or_(
                    Component.logical_width_stud.is_(None),
                    Component.logical_depth_stud.is_(None),
                    Component.logical_height_plate.is_(None),
                ),
            )
        ).all()
        for component in components:
            version = session.get(ComponentVersion, component.current_version_id)
            if version is None:
                continue
            snapshot = session.get(ComponentSceneSnapshot, version.scene_snapshot_id)
            if snapshot is None:
                continue
            geometry = component_geometry(session, snapshot.document_json)
            if geometry is not None:
                persist_component_logical_size(component, geometry)
        session.commit()
