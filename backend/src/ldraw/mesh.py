"""Recursive LDraw triangle mesh loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from src.tools.import_ldraw_references import _candidate_paths


@dataclass(frozen=True)
class Vector:
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Matrix:
    xx: float
    xy: float
    xz: float
    yx: float
    yy: float
    yz: float
    zx: float
    zy: float
    zz: float

    def multiply(self, other: Matrix) -> Matrix:
        return Matrix(
            self.xx * other.xx + self.xy * other.yx + self.xz * other.zx,
            self.xx * other.xy + self.xy * other.yy + self.xz * other.zy,
            self.xx * other.xz + self.xy * other.yz + self.xz * other.zz,
            self.yx * other.xx + self.yy * other.yx + self.yz * other.zx,
            self.yx * other.xy + self.yy * other.yy + self.yz * other.zy,
            self.yx * other.xz + self.yy * other.yz + self.yz * other.zz,
            self.zx * other.xx + self.zy * other.yx + self.zz * other.zx,
            self.zx * other.xy + self.zy * other.yy + self.zz * other.zy,
            self.zx * other.xz + self.zy * other.yz + self.zz * other.zz,
        )

    def apply(self, vector: Vector) -> Vector:
        return Vector(
            self.xx * vector.x + self.xy * vector.y + self.xz * vector.z,
            self.yx * vector.x + self.yy * vector.y + self.yz * vector.z,
            self.zx * vector.x + self.zy * vector.y + self.zz * vector.z,
        )


@dataclass(frozen=True)
class Transform:
    matrix: Matrix
    offset: Vector

    def combine(self, child: Transform) -> Transform:
        transformed_offset = self.matrix.apply(child.offset)
        return Transform(
            self.matrix.multiply(child.matrix),
            Vector(
                transformed_offset.x + self.offset.x,
                transformed_offset.y + self.offset.y,
                transformed_offset.z + self.offset.z,
            ),
        )

    def apply(self, vector: Vector) -> Vector:
        transformed = self.matrix.apply(vector)
        return Vector(
            transformed.x + self.offset.x,
            transformed.y + self.offset.y,
            transformed.z + self.offset.z,
        )


@dataclass(frozen=True)
class Triangle:
    first: Vector
    second: Vector
    third: Vector

    @property
    def vertices(self) -> tuple[Vector, Vector, Vector]:
        return self.first, self.second, self.third


@dataclass(frozen=True)
class LDrawMesh:
    triangles: tuple[Triangle, ...]
    surface_triangles: tuple[Triangle, ...]
    top_connection_origins: tuple[Vector, ...]
    source_face_count: int
    source_vertex_count: int
    errors: tuple[str, ...]


IDENTITY_TRANSFORM = Transform(
    Matrix(1, 0, 0, 0, 1, 0, 0, 0, 1),
    Vector(0, 0, 0),
)


def index_ldraw_files(root: Path, config: dict) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix().lower(): path
        for path in root.rglob(config["file_pattern"])
    }


def read_ldraw_text(path: Path, config: dict) -> str:
    decoding_errors = []
    for encoding in config["text_encodings"]:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as error:
            decoding_errors.append(str(error))
    raise ValueError(config["errors"]["text_decode"].format(path=path, errors="; ".join(decoding_errors)))


def parse_reference(line: str, config: dict) -> tuple[Transform, str] | None:
    tokens = line.split()
    if len(tokens) != config["syntax"]["reference_token_count"]:
        return None
    (
        line_type,
        _color,
        x,
        y,
        z,
        xx,
        xy,
        xz,
        yx,
        yy,
        yz,
        zx,
        zy,
        zz,
        reference_name,
    ) = tokens
    if line_type != config["line_type"]["reference"]:
        return None
    values = [float(value) for value in (x, y, z, xx, xy, xz, yx, yy, yz, zx, zy, zz)]
    (
        offset_x,
        offset_y,
        offset_z,
        matrix_xx,
        matrix_xy,
        matrix_xz,
        matrix_yx,
        matrix_yy,
        matrix_yz,
        matrix_zx,
        matrix_zy,
        matrix_zz,
    ) = values
    return (
        Transform(
            Matrix(
                matrix_xx,
                matrix_xy,
                matrix_xz,
                matrix_yx,
                matrix_yy,
                matrix_yz,
                matrix_zx,
                matrix_zy,
                matrix_zz,
            ),
            Vector(offset_x, offset_y, offset_z),
        ),
        reference_name.strip('"').replace("\\", "/").lower(),
    )


def parse_face(line: str, config: dict) -> tuple[Triangle, ...] | None:
    tokens = line.split()
    line_type = tokens[0]
    if line_type == config["line_type"]["triangle"]:
        expected_vertex_count = config["syntax"]["triangle_vertex_count"]
    elif line_type == config["line_type"]["quadrilateral"]:
        expected_vertex_count = config["syntax"]["quadrilateral_vertex_count"]
    else:
        return None
    coordinate_tokens = tokens[config["syntax"]["face_header_token_count"] :]
    if len(coordinate_tokens) != expected_vertex_count * config["syntax"]["coordinate_count"]:
        return None
    coordinates = iter(float(value) for value in coordinate_tokens)
    vertices = tuple(Vector(x, y, z) for x, y, z in zip(coordinates, coordinates, coordinates))
    if line_type == config["line_type"]["triangle"]:
        first, second, third = vertices
        return (Triangle(first, second, third),)
    first, second, third, fourth = vertices
    return Triangle(first, second, third), Triangle(first, third, fourth)


def collect_ldraw_mesh(
    relative_path: str,
    files: dict[str, Path],
    config: dict,
    transform: Transform = IDENTITY_TRANSFORM,
    stack: tuple[str, ...] = (),
    exclude_from_surface: bool = False,
) -> LDrawMesh:
    if len(stack) >= config["maximum_recursion_depth"]:
        return LDrawMesh((), (), (), 0, 0, (config["errors"]["maximum_recursion"].format(path=relative_path),))
    if relative_path in stack:
        return LDrawMesh((), (), (), 0, 0, (config["errors"]["recursive_include"].format(path=relative_path),))
    path = files.get(relative_path)
    if path is None:
        return LDrawMesh((), (), (), 0, 0, (config["errors"]["missing_file"].format(path=relative_path),))

    triangles = []
    surface_triangles = []
    top_connection_origins = []
    source_face_count = 0
    source_vertex_count = 0
    errors = []
    for line_number, raw_line in enumerate(read_ldraw_text(path, config).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(config["line_type"]["comment"]):
            continue
        line_type = line.split(maxsplit=1)[0]
        if line_type == config["line_type"]["reference"]:
            try:
                reference = parse_reference(line, config)
            except ValueError:
                reference = None
            if reference is None:
                errors.append(config["errors"]["invalid_line"].format(path=relative_path, line=line_number))
                continue
            child_transform, reference_name = reference
            child_path = next(
                (candidate for candidate in _candidate_paths(relative_path, reference_name) if candidate in files),
                None,
            )
            if child_path is None:
                if reference_name not in config["ignored_missing_references"]:
                    errors.append(
                        config["errors"]["missing_reference"].format(
                            path=relative_path,
                            line=line_number,
                            reference=reference_name,
                        )
                    )
                continue
            combined_transform = transform.combine(child_transform)
            if any(
                re.search(pattern, child_path) is not None
                for pattern in config["top_connection_path_patterns"]
            ):
                top_connection_origins.append(combined_transform.apply(Vector(0, 0, 0)))
            child_mesh = collect_ldraw_mesh(
                child_path,
                files,
                config,
                combined_transform,
                stack + (relative_path,),
                exclude_from_surface or any(
                    re.search(pattern, child_path) is not None
                    for pattern in config["surface_excluded_path_patterns"]
                ),
            )
            triangles.extend(child_mesh.triangles)
            surface_triangles.extend(child_mesh.surface_triangles)
            top_connection_origins.extend(child_mesh.top_connection_origins)
            source_face_count += child_mesh.source_face_count
            source_vertex_count += child_mesh.source_vertex_count
            errors.extend(child_mesh.errors)
            continue
        try:
            faces = parse_face(line, config)
        except (ValueError, IndexError):
            faces = None
        if line_type in (config["line_type"]["triangle"], config["line_type"]["quadrilateral"]):
            if faces is None:
                errors.append(config["errors"]["invalid_line"].format(path=relative_path, line=line_number))
                continue
            transformed_triangles = tuple(
                Triangle(*(transform.apply(vertex) for vertex in triangle.vertices))
                for triangle in faces
            )
            triangles.extend(transformed_triangles)
            source_face_count += 1
            source_vertex_count += (
                config["syntax"]["triangle_vertex_count"]
                if line_type == config["line_type"]["triangle"]
                else config["syntax"]["quadrilateral_vertex_count"]
            )
            if not exclude_from_surface:
                surface_triangles.extend(transformed_triangles)
    return LDrawMesh(
        tuple(triangles),
        tuple(surface_triangles),
        tuple(top_connection_origins),
        source_face_count,
        source_vertex_count,
        tuple(errors),
    )
