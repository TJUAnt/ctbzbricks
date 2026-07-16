"""Tests for recursive LDraw triangle mesh loading."""

import tempfile
import unittest
from pathlib import Path

from src.ldraw.mesh import collect_ldraw_mesh, index_ldraw_files


MESH_CONFIG = {
    "file_pattern": "*.dat",
    "text_encodings": ["utf-8", "latin-1"],
    "maximum_recursion_depth": 8,
    "line_type": {
        "comment": "0",
        "reference": "1",
        "triangle": "3",
        "quadrilateral": "4",
    },
    "ignored_missing_references": [],
    "surface_excluded_path_patterns": ["(^|/)stud[0-9a-z]*\\.dat$"],
    "top_connection_path_patterns": ["(^|/)stud(?:2)?\\.dat$"],
    "syntax": {
        "reference_token_count": 15,
        "triangle_vertex_count": 3,
        "quadrilateral_vertex_count": 4,
        "face_header_token_count": 2,
        "coordinate_count": 3,
    },
    "errors": {
        "text_decode": "cannot decode {path}: {errors}",
        "maximum_recursion": "maximum recursion at {path}",
        "recursive_include": "recursive include at {path}",
        "missing_file": "missing file {path}",
        "invalid_line": "invalid line {path}:{line}",
        "missing_reference": "missing reference {reference} at {path}:{line}",
    },
}


class LDrawMeshTest(unittest.TestCase):
    def test_collect_mesh_applies_child_transform_and_splits_quad(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = root / "parts"
            parts.mkdir()
            (parts / "child.dat").write_text(
                "4 16 0 0 0 10 0 0 10 0 10 0 0 10\n",
                encoding="utf-8",
            )
            (parts / "parent.dat").write_text(
                "1 16 20 0 0 1 0 0 0 1 0 0 0 1 child.dat\n",
                encoding="utf-8",
            )

            files = index_ldraw_files(root, MESH_CONFIG)
            mesh = collect_ldraw_mesh("parts/parent.dat", files, MESH_CONFIG)

        self.assertEqual(len(mesh.triangles), 2)
        self.assertEqual(len(mesh.surface_triangles), 2)
        self.assertEqual(mesh.source_face_count, 1)
        self.assertEqual(mesh.source_vertex_count, 4)
        self.assertEqual(mesh.errors, ())
        self.assertEqual(min(vertex.x for triangle in mesh.triangles for vertex in triangle.vertices), 20)
        self.assertEqual(max(vertex.x for triangle in mesh.triangles for vertex in triangle.vertices), 30)

    def test_collect_mesh_excludes_stud_subtree_only_from_surface_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = root / "parts"
            primitives = root / "p"
            parts.mkdir()
            primitives.mkdir()
            (primitives / "stud.dat").write_text(
                "4 16 0 -4 0 20 -4 0 20 -4 20 0 -4 20\n",
                encoding="utf-8",
            )
            (parts / "body.dat").write_text(
                "4 16 0 0 0 20 0 0 20 0 20 0 0 20\n"
                "1 16 0 0 0 1 0 0 0 1 0 0 0 1 stud.dat\n",
                encoding="utf-8",
            )

            files = index_ldraw_files(root, MESH_CONFIG)
            mesh = collect_ldraw_mesh("parts/body.dat", files, MESH_CONFIG)

        self.assertEqual(len(mesh.triangles), 4)
        self.assertEqual(len(mesh.surface_triangles), 2)
        self.assertEqual(mesh.top_connection_origins, (mesh.top_connection_origins[0],))
        self.assertEqual(mesh.top_connection_origins[0].x, 0)
        self.assertEqual(mesh.top_connection_origins[0].y, 0)
        self.assertEqual(mesh.top_connection_origins[0].z, 0)

    def test_collect_mesh_does_not_treat_bottom_tube_as_top_connection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parts = root / "parts"
            primitives = root / "p"
            parts.mkdir()
            primitives.mkdir()
            (primitives / "stud4a.dat").write_text(
                "4 16 0 0 0 20 0 0 20 0 20 0 0 20\n",
                encoding="utf-8",
            )
            (parts / "body.dat").write_text(
                "4 16 0 0 0 20 0 0 20 0 20 0 0 20\n"
                "1 16 10 8 10 1 0 0 0 1 0 0 0 1 stud4a.dat\n",
                encoding="utf-8",
            )

            files = index_ldraw_files(root, MESH_CONFIG)
            mesh = collect_ldraw_mesh("parts/body.dat", files, MESH_CONFIG)

        self.assertEqual(mesh.top_connection_origins, ())


if __name__ == "__main__":
    unittest.main()
