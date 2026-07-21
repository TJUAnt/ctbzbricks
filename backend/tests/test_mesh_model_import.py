"""Unit tests for direct GLB mesh import."""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from src.config.app_settings import load_json_config
from src.mesh.glb_color import extract_glb_material_color_summary
from src.services.mesh_model_service import save_uploaded_mesh_model
from src.services.model_asset_service import ensure_model_asset_table, paginated_model_assets


REQUIRED_CONFIG_KEYS = (
    "routes",
    "storage",
    "upload",
    "model_asset",
    "response",
    "color_summary",
    "glb",
    "json_keys",
    "metadata_keys",
    "errors",
    "http_status",
)


class MeshModelImportTest(unittest.TestCase):
    def test_legacy_model_asset_table_is_upgraded_with_content_locale(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE model_assets ("
                    "id VARCHAR(64) PRIMARY KEY, name VARCHAR(255) NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO model_assets (id, name) "
                    "VALUES ('legacy-asset', 'Legacy asset')"
                )
            )

        ensure_model_asset_table(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("model_assets")}
        with engine.connect() as connection:
            content_locale = connection.scalar(
                text(
                    "SELECT content_locale FROM model_assets "
                    "WHERE id = 'legacy-asset'"
                )
            )
        self.assertIn("content_locale", columns)
        self.assertEqual(content_locale, "zh-CN")

    def test_glb_material_colors_include_face_coverage_and_texture_flag(self) -> None:
        config = load_json_config("mesh_model_import.json", REQUIRED_CONFIG_KEYS)
        summary = extract_glb_material_color_summary(config, sample_glb())

        self.assertEqual(summary["source"], "material")
        self.assertEqual(summary["colors"][0]["hex"], "#CC0000")
        self.assertEqual(summary["colors"][0]["materialName"], "red plastic")
        self.assertEqual(summary["colors"][0]["faceCount"], 2)
        self.assertEqual(summary["colors"][0]["coverageRatio"], 0.6667)
        self.assertEqual(summary["colors"][1]["hex"], "#0000FF")
        self.assertEqual(summary["colors"][1]["hasBaseColorTexture"], True)
        self.assertEqual(summary["hasBaseColorTexture"], True)
        self.assertEqual(summary["textureSamplingStatus"], "not_processed")

    def test_uploaded_mesh_is_saved_and_indexed_as_model_asset(self) -> None:
        config = load_json_config("mesh_model_import.json", REQUIRED_CONFIG_KEYS)
        engine = create_engine("sqlite:///:memory:")
        ensure_model_asset_table(engine)
        with tempfile.TemporaryDirectory() as directory:
            config = {
                **config,
                "storage": {
                    **config["storage"],
                    "model_store_path": str(Path(directory)),
                },
            }

            saved_asset = save_uploaded_mesh_model(
                engine,
                config,
                "uploaded mesh",
                "uploaded.glb",
                "model/gltf-binary",
                sample_glb(),
                "en-US",
            )
            page = paginated_model_assets(engine, 1, 10)

            self.assertEqual(saved_asset["modelType"], "mesh")
            self.assertEqual(saved_asset["sourceType"], "direct_upload")
            self.assertEqual(saved_asset["contentLocale"], "en-US")
            self.assertTrue(Path(saved_asset["assetPath"]).exists())
            self.assertEqual(page["total"], 1)
            self.assertEqual(page["items"][0]["metadata"]["colorSummary"]["colors"][0]["hex"], "#CC0000")


def sample_glb() -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 6}, {"count": 3}],
        "materials": [
            {
                "name": "red plastic",
                "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0, 0, 1]},
            },
            {
                "name": "blue textured",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0, 0, 1, 1],
                    "baseColorTexture": {"index": 0},
                },
            },
        ],
        "meshes": [
            {
                "primitives": [
                    {"material": 0, "indices": 0},
                    {"material": 1, "indices": 1},
                ]
            }
        ],
    }
    json_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    declared_length = 12 + 8 + len(json_bytes)
    return (
        struct.pack("<4sII", b"glTF", 2, declared_length)
        + struct.pack("<II", len(json_bytes), 1313821514)
        + json_bytes
    )


if __name__ == "__main__":
    unittest.main()
