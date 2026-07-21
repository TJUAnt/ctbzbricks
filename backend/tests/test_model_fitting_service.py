"""Unit tests for model fitting jobs."""

import json
import struct
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.app_settings import load_json_config
from src.config.fitting_candidate_recall_config import (
    REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
)
from src.config.model_fitting_config import REQUIRED_MODEL_FITTING_CONFIG_KEYS
from src.mesh.glb_geometry import analyze_glb_geometry
from src.model.models import (
    FittingCandidateProfile,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    LDrawPartShapeProfile,
    ModelAsset,
)
from src.services.model_fitting_service import (
    create_model_fitting_job,
    ensure_model_fitting_tables,
    get_model_fitting_solution,
)
from src.services.model_asset_service import ensure_model_asset_table
from src.services.part_shape_profile_service import ensure_part_shape_profile_table


class ModelFittingServiceTest(unittest.TestCase):
    def test_glb_geometry_analysis_uses_accessor_bounds_and_counts_triangles(self) -> None:
        config = model_fitting_config()

        analysis = analyze_glb_geometry(config, sample_glb_bytes(config))

        self.assertEqual(analysis["targetBBox"]["width"], 2)
        self.assertEqual(analysis["targetBBox"]["height"], 1)
        self.assertEqual(analysis["targetBBox"]["depth"], 3)
        self.assertEqual(analysis["meshStats"]["meshCount"], 1)
        self.assertEqual(analysis["meshStats"]["primitiveCount"], 1)
        self.assertEqual(analysis["meshStats"]["vertexCount"], 3)
        self.assertEqual(analysis["meshStats"]["triangleCount"], 1)

    def test_create_model_fitting_job_persists_block_recall_and_draft_solution(self) -> None:
        config = model_fitting_config()
        recall_config = fitting_candidate_recall_config()
        engine = test_engine()
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "sample.glb"
            model_path.write_bytes(sample_glb_bytes(config))
            seed_mesh_model_asset(engine, config, model_path)

            job = create_model_fitting_job(
                engine,
                config,
                recall_config,
                {
                    "modelId": "mesh-model",
                    "name": None,
                    "scaleToLdu": 20,
                    "modelTypeHint": None,
                    "semanticPreset": None,
                    "targetWidthStud": None,
                    "locale": "zh-CN",
                    "timezone": "Asia/Shanghai",
                },
            )

        self.assertEqual(job["sourceModelId"], "mesh-model")
        self.assertEqual(job["status"], config["job_status"]["complete"])
        self.assertEqual(job["targetAnalysis"]["normalizedBBox"]["width"], 40)
        self.assertEqual(job["blocks"][0]["blockType"], config["target_block"]["whole_model_type"])
        self.assertEqual(job["blocks"][0]["candidateSummary"]["total"], 0)
        self.assertEqual(job["solutions"][0]["status"], config["solution_status"]["draft"])
        self.assertEqual(job["solutions"][0]["placements"], [])

        solution = get_model_fitting_solution(engine, job["solutions"][0]["id"])

        self.assertEqual(solution["id"], job["solutions"][0]["id"])
        self.assertEqual(solution["placements"], [])

    def test_create_vehicle_8_wide_job_generates_vehicle_semantic_blocks(self) -> None:
        config = model_fitting_config()
        recall_config = fitting_candidate_recall_config()
        engine = test_engine()
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "sample.glb"
            model_path.write_bytes(sample_glb_bytes(config))
            seed_mesh_model_asset(engine, config, model_path)

            job = create_model_fitting_job(
                engine,
                config,
                recall_config,
                {
                    "modelId": "mesh-model",
                    "name": "8 wide car",
                    "scaleToLdu": None,
                    "modelTypeHint": config["semantic"]["vehicle_model_type"],
                    "semanticPreset": config["semantic"]["vehicle_8_wide_preset"],
                    "targetWidthStud": 8,
                    "locale": "en-US",
                    "timezone": "UTC",
                },
            )

        self.assertEqual(
            job["settings"]["semanticPreset"],
            config["semantic"]["vehicle_8_wide_preset"],
        )
        self.assertEqual(job["settings"]["scaleToLdu"], 80)
        self.assertEqual(job["locale"], "en-US")
        self.assertEqual(job["timezone"], "UTC")
        self.assertEqual(job["targetAnalysis"]["normalizedBBox"]["width"], 160)
        self.assertEqual(len(job["blocks"]), len(config["semantic"]["block_templates"]))
        self.assertEqual(job["blocks"][0]["blockType"], config["target_block"]["vehicle_region_type"])
        self.assertEqual(
            job["blocks"][0]["profile"]["semanticType"],
            config["semantic"]["block_templates"][0]["semantic_type"],
        )
        self.assertEqual(
            job["blocks"][0]["profile"]["semanticSource"],
            config["semantic"]["source_vehicle_preset"],
        )
        wheel_blocks = [
            block
            for block in job["blocks"]
            if block["profile"]["reuseGroup"] == "wheel-assembly"
        ]
        self.assertEqual(len(wheel_blocks), 4)

    def test_create_model_fitting_job_rejects_non_mesh_asset(self) -> None:
        config = model_fitting_config()
        recall_config = fitting_candidate_recall_config()
        engine = test_engine()
        seed_non_mesh_model_asset(engine)

        with self.assertRaises(ValueError) as error:
            create_model_fitting_job(
                engine,
                config,
                recall_config,
                {
                    "modelId": "dem-model",
                    "name": None,
                    "scaleToLdu": None,
                    "modelTypeHint": None,
                    "semanticPreset": None,
                    "targetWidthStud": None,
                },
            )

        self.assertEqual(
            str(error.exception),
            config["errors"]["unsupported_model_type"].format(model_id="dem-model"),
        )


def model_fitting_config() -> dict:
    return load_json_config("model_fitting.json", REQUIRED_MODEL_FITTING_CONFIG_KEYS)


def fitting_candidate_recall_config() -> dict:
    return load_json_config(
        "fitting_candidate_recall.json",
        REQUIRED_FITTING_CANDIDATE_RECALL_CONFIG_KEYS,
    )


def test_engine():
    engine = create_engine("sqlite:///:memory:")
    LDrawFile.__table__.create(bind=engine)
    LDrawPart.__table__.create(bind=engine)
    LDrawPartGeometry.__table__.create(bind=engine)
    ensure_part_shape_profile_table(engine)
    FittingCandidateProfile.__table__.create(bind=engine)
    ensure_model_asset_table(engine)
    ensure_model_fitting_tables(engine)
    return engine


def sample_glb_bytes(config: dict) -> bytes:
    glb = config["glb"]
    keys = config["json_keys"]
    document = {
        keys["meshes"]: [
            {
                keys["primitives"]: [
                    {
                        keys["attributes"]: {
                            glb["position_attribute"]: 0,
                        },
                        keys["mode"]: glb["triangles_mode"],
                    }
                ]
            }
        ],
        keys["accessors"]: [
            {
                keys["count"]: 3,
                keys["type"]: glb["vec3_type"],
                keys["component_type"]: glb["float_component_type"],
                keys["min"]: [0, 0, 0],
                keys["max"]: [2, 1, 3],
            }
        ],
    }
    json_bytes = json.dumps(document).encode(glb["json_encoding"])
    padded_json_bytes = json_bytes + b" " * ((4 - len(json_bytes) % 4) % 4)
    declared_length = (
        glb["header_length"]
        + glb["chunk_header_length"]
        + len(padded_json_bytes)
    )
    return (
        struct.pack(
            glb["header_struct"],
            glb["magic"].encode(glb["binary_encoding"]),
            glb["version"],
            declared_length,
        )
        + struct.pack(
            glb["chunk_header_struct"],
            len(padded_json_bytes),
            glb["json_chunk_type"],
        )
        + padded_json_bytes
    )


def seed_mesh_model_asset(engine, config: dict, model_path: Path) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            ModelAsset(
                id="mesh-model",
                name="mesh model",
                content_locale="en-US",
                model_type=config["model_asset"]["required_model_type"],
                source_type="direct_upload",
                source_name="sample.glb",
                asset_path=str(model_path),
                preview_path=None,
                status="complete",
                metadata_json={
                    "colorSummary": {
                        "colors": [],
                    }
                },
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def seed_non_mesh_model_asset(engine) -> None:
    Session = sessionmaker(bind=engine)
    with Session() as session:
        session.add(
            ModelAsset(
                id="dem-model",
                name="dem model",
                content_locale="en-US",
                model_type="dem",
                source_type="test",
                source_name="dem.json",
                asset_path="dem.json",
                preview_path=None,
                status="complete",
                metadata_json={},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


if __name__ == "__main__":
    unittest.main()
