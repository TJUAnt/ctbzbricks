"""API tests for Component Repo artifact upload and download."""

from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.errors import install_error_handlers
from src.api.routes.component_repo import create_component_repo_router
from src.component_repo.services import ensure_component_repo_tables
from src.component_repo.storage import ArtifactStorageError, LocalArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.model.models import (
    ConnectorInstance,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    PartTranslation,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
)


class ComponentRepoApiTest(unittest.TestCase):
    def test_parse_import_maps_missing_storage_object_to_stable_error(self) -> None:
        config = component_repo_config()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ConnectorInstance.__table__.create(bind=engine)
        ensure_component_repo_tables(engine)
        ensure_fitting_candidate_profile_table(engine)
        with tempfile.TemporaryDirectory() as directory:
            app = FastAPI()
            install_error_handlers(app)
            app.state.db_engine = engine
            storage = LocalArtifactStorage(
                root_path=Path(directory),
                bucket=config["storage"]["bucket"],
                provider=config["storage"]["local_provider"],
            )
            app.state.component_repo_storage = storage
            app.include_router(create_component_repo_router(config))
            client = TestClient(app)

            create_response = client.post(
                config["routes"]["component_imports"],
                data={"content_locale": "en-US"},
                files={
                    "source_file": (
                        "car_seat.ldr",
                        fixture_path("repo/8cars/car_seat.ldr").read_bytes(),
                        "text/plain",
                    ),
                },
            )
            self.assertEqual(create_response.status_code, 200)
            payload = create_response.json()

            def missing_read(_storage_key: str) -> bytes:
                raise ArtifactStorageError("Object not found")

            storage.read_bytes = missing_read

            parse_response = client.post(
                config["routes"]["component_import_parse"],
                json={"importId": payload["importJob"]["id"]},
            )

            self.assertEqual(parse_response.status_code, 502)
            self.assertEqual(
                parse_response.json()["error"]["code"],
                "component_repo.storage_unavailable",
            )
            self.assertEqual(
                parse_response.json()["error"]["params"],
                {"importId": payload["importJob"]["id"]},
            )

    def test_create_import_accepts_single_ldraw_source_as_exchange(self) -> None:
        config = component_repo_config()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ConnectorInstance.__table__.create(bind=engine)
        ensure_component_repo_tables(engine)
        ensure_fitting_candidate_profile_table(engine)
        with tempfile.TemporaryDirectory() as directory:
            app = FastAPI()
            install_error_handlers(app)
            app.state.db_engine = engine
            app.state.component_repo_storage = LocalArtifactStorage(
                root_path=Path(directory),
                bucket=config["storage"]["bucket"],
                provider=config["storage"]["local_provider"],
            )
            app.include_router(create_component_repo_router(config))
            openapi = app.openapi()
            preview_operation = openapi["paths"][
                config["routes"]["component_preview_first"]
            ]["get"]
            self.assertEqual(
                preview_operation["summary"],
                "Get the first previewable Component Repo item",
            )
            self.assertIn("Component snapshot defines placement", preview_operation["description"])
            locale_parameter = next(
                parameter
                for parameter in preview_operation["parameters"]
                if parameter["name"] == "contentLocale"
            )
            self.assertIn("locale-neutral", locale_parameter["description"])
            model_schema = openapi["components"]["schemas"]["ComponentPreviewModelResponse"]
            self.assertIn("Binary model format", model_schema["properties"]["format"]["description"])
            version_preview_operation = openapi["paths"][
                config["routes"]["component_version_preview"]
            ]["get"]
            self.assertEqual(version_preview_operation["summary"], "Get one Component version preview")
            item_preview_operation = openapi["paths"][
                config["routes"]["library_item_preview"]
            ]["get"]
            self.assertEqual(
                item_preview_operation["summary"],
                "Get a Component or Part preview by type and ID",
            )
            self.assertEqual(
                {parameter["name"] for parameter in item_preview_operation["parameters"]},
                {"item_type", "item_id", "contentLocale"},
            )
            client = TestClient(app)

            empty_preview_response = client.get(
                config["routes"]["component_preview_first"],
                params={"contentLocale": "zh-CN"},
            )

            self.assertEqual(empty_preview_response.status_code, 404)
            self.assertEqual(
                empty_preview_response.json()["error"]["code"],
                "component_repo.preview_empty",
            )

            response = client.post(
                config["routes"]["component_imports"],
                data={"content_locale": "zh-CN"},
                files={
                    "source_file": (
                        "wheel_shell_component2.ldr",
                        fixture_path("repo/8cars/wheel_shell_component2.ldr").read_bytes(),
                        "text/plain",
                    ),
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(
                payload["sourceArtifact"]["artifactType"],
                config["artifacts"]["ldraw_ldr"],
            )
            self.assertEqual(payload["exchangeArtifact"]["id"], payload["sourceArtifact"]["id"])
            self.assertEqual(
                payload["importJob"]["exchangeArtifactId"],
                payload["sourceArtifact"]["id"],
            )

            parse_response = client.post(
                config["routes"]["component_import_parse"],
                json={"importId": payload["importJob"]["id"]},
            )

            self.assertEqual(parse_response.status_code, 200)
            self.assertEqual(parse_response.json()["candidate"]["summary"]["partInstanceCount"], 3)

    def test_create_import_uploads_artifacts_and_downloads_source(self) -> None:
        config = component_repo_config()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ConnectorInstance.__table__.create(bind=engine)
        ensure_component_repo_tables(engine)
        ensure_fitting_candidate_profile_table(engine)
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            preview_root = Path(directory) / "ldraw"
            seed_preview_ldraw_library(preview_root)
            config["preview"]["ldraw_root_env"] = "COMPONENT_REPO_TEST_LDRAW_ROOT"
            config["preview"]["ldraw_root_candidates"] = [str(preview_root)]
            app = FastAPI()
            install_error_handlers(app)
            app.state.db_engine = engine
            app.state.component_repo_storage = LocalArtifactStorage(
                root_path=Path(directory),
                bucket=config["storage"]["bucket"],
                provider=config["storage"]["local_provider"],
            )
            app.include_router(create_component_repo_router(config))
            client = TestClient(app)

            part_preview_response = client.get(
                config["routes"]["library_item_preview"].format(
                    item_type="part",
                    item_id="male.dat",
                ),
                params={"contentLocale": "en-US"},
            )
            self.assertEqual(part_preview_response.status_code, 200)
            self.assertEqual(part_preview_response.json()["source"]["kind"], "part")
            self.assertEqual(part_preview_response.json()["source"]["id"], "male.dat")
            self.assertEqual(part_preview_response.json()["partCount"], 1)
            self.assertEqual(part_preview_response.json()["parts"][0]["partRef"], "male.dat")
            self.assertEqual(part_preview_response.json()["model"]["format"], "glb")
            self.assertEqual(part_preview_response.json()["model"]["compression"], "meshopt")
            self.assertNotIn("meshes", part_preview_response.json())
            part_model_response = client.get(part_preview_response.json()["model"]["url"])
            self.assertEqual(part_model_response.status_code, 200)
            self.assertEqual(part_model_response.content[:4], b"glTF")
            self.assertIn(b"EXT_meshopt_compression", part_model_response.content)

            missing_item_response = client.get(
                config["routes"]["library_item_preview"].format(
                    item_type="part",
                    item_id="missing.dat",
                ),
                params={"contentLocale": "en-US"},
            )
            self.assertEqual(missing_item_response.status_code, 404)
            self.assertEqual(
                missing_item_response.json()["error"]["code"],
                "component_repo.library_item_not_found",
            )

            unsupported_item_response = client.get(
                config["routes"]["library_item_preview"].format(
                    item_type="submodel",
                    item_id="demo",
                ),
                params={"contentLocale": "en-US"},
            )
            self.assertEqual(unsupported_item_response.status_code, 400)
            self.assertEqual(
                unsupported_item_response.json()["error"]["code"],
                "component_repo.preview_type_unsupported",
            )

            response = client.post(
                config["routes"]["component_imports"],
                data={"content_locale": "en-US"},
                files={
                    "source_file": (
                        "wheel_shell_component.io",
                        b"io-bytes",
                        "application/octet-stream",
                    ),
                    "exchange_file": (
                        "wheel_shell_component2.ldr",
                        pin_pair_ldraw().encode("utf-8"),
                        "text/plain",
                    ),
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            source_artifact_id = payload["sourceArtifact"]["id"]
            self.assertEqual(payload["importJob"]["sourceArtifactId"], source_artifact_id)
            self.assertEqual(
                payload["sourceArtifact"]["artifactType"],
                config["artifacts"]["studio_io"],
            )
            self.assertEqual(
                payload["exchangeArtifact"]["artifactType"],
                config["artifacts"]["ldraw_ldr"],
            )

            imports_response = client.get(config["routes"]["component_imports"])

            self.assertEqual(imports_response.status_code, 200)
            self.assertEqual(len(imports_response.json()), 1)
            self.assertEqual(
                imports_response.json()[0]["sourceFilename"],
                "wheel_shell_component.io",
            )
            self.assertEqual(imports_response.json()[0]["sourceFileSize"], len(b"io-bytes"))

            parse_response = client.post(
                config["routes"]["component_import_parse"],
                json={"importId": payload["importJob"]["id"]},
            )

            self.assertEqual(parse_response.status_code, 200)
            parse_payload = parse_response.json()
            self.assertEqual(
                parse_payload["importJob"]["status"],
                config["imports"]["status"]["parsed"],
            )
            self.assertEqual(parse_payload["candidate"]["summary"]["modelCount"], 1)
            self.assertEqual(parse_payload["candidate"]["summary"]["partInstanceCount"], 2)
            self.assertEqual(
                parse_payload["version"]["status"],
                config["versions"]["status"]["draft"],
            )

            candidate_response = client.get(
                config["routes"]["component_import_candidate"].format(
                    import_id=payload["importJob"]["id"],
                )
            )

            self.assertEqual(candidate_response.status_code, 200)
            self.assertEqual(
                candidate_response.json()["id"],
                parse_payload["candidate"]["id"],
            )

            explicit_candidate_preview_response = client.get(
                config["routes"]["candidate_preview"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                ),
                params={"contentLocale": "zh-CN"},
            )

            self.assertEqual(explicit_candidate_preview_response.status_code, 200)
            self.assertEqual(
                explicit_candidate_preview_response.json()["versionId"],
                parse_payload["version"]["id"],
            )
            self.assertEqual(
                explicit_candidate_preview_response.json()["partCount"],
                2,
            )

            component_item_preview_response = client.get(
                config["routes"]["library_item_preview"].format(
                    item_type="component",
                    item_id=parse_payload["component"]["id"],
                ),
                params={"contentLocale": "zh-CN"},
            )
            self.assertEqual(component_item_preview_response.status_code, 200)
            self.assertEqual(
                component_item_preview_response.json()["source"]["id"],
                parse_payload["component"]["id"],
            )
            self.assertEqual(
                component_item_preview_response.json()["versionId"],
                parse_payload["version"]["id"],
            )

            candidate_preview_response = client.get(
                config["routes"]["component_preview_first"],
                params={"contentLocale": "zh-CN"},
            )

            self.assertEqual(candidate_preview_response.status_code, 200)
            self.assertEqual(candidate_preview_response.json()["source"]["kind"], "component")
            self.assertEqual(
                candidate_preview_response.json()["source"]["id"],
                parse_payload["component"]["id"],
            )
            self.assertEqual(
                candidate_preview_response.json()["source"]["name"],
                "wheel_shell_component",
            )
            self.assertEqual(
                candidate_preview_response.json()["source"]["status"],
                config["components"]["status"]["draft"],
            )
            self.assertEqual(
                candidate_preview_response.json()["component"]["id"],
                parse_payload["component"]["id"],
            )
            self.assertEqual(
                candidate_preview_response.json()["versionId"],
                parse_payload["version"]["id"],
            )
            self.assertEqual(candidate_preview_response.json()["partCount"], 2)
            self.assertEqual(candidate_preview_response.json()["model"]["format"], "glb")
            self.assertEqual(candidate_preview_response.json()["model"]["compression"], "meshopt")
            self.assertNotIn("meshes", candidate_preview_response.json())

            unavailable_free_response = client.get(
                config["routes"]["candidate_free_connectors"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )
            self.assertEqual(unavailable_free_response.status_code, 409)
            self.assertEqual(
                unavailable_free_response.json()["error"]["code"],
                "component_repo.part_library_unavailable",
            )

            relation_response = client.post(
                config["routes"]["candidate_relations_detect"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )

            self.assertEqual(relation_response.status_code, 200)
            self.assertEqual(len(relation_response.json()), 1)

            free_response = client.get(
                config["routes"]["candidate_free_connectors"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )

            self.assertEqual(free_response.status_code, 200)
            self.assertEqual(len(free_response.json()), 2)

            interface_response = client.post(
                config["routes"]["candidate_interfaces"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                ),
                json={
                    "worldConnectorId": free_response.json()[0]["worldConnectorId"],
                    "name": "mount_pin",
                    "mechanicalRoles": ["mount"],
                    "businessRoles": ["external_mount"],
                },
            )

            self.assertEqual(interface_response.status_code, 200)
            self.assertEqual(interface_response.json()["name"], "mount_pin")

            validation_response = client.post(
                config["routes"]["candidate_validate"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )

            self.assertEqual(validation_response.status_code, 200)
            self.assertTrue(validation_response.json()["passed"])

            draft_version_id = parse_payload["version"]["id"]

            draft_preview_response = client.get(
                config["routes"]["component_preview_first"],
                params={"contentLocale": "zh-CN"},
            )

            self.assertEqual(draft_preview_response.status_code, 200)
            self.assertEqual(draft_preview_response.json()["versionId"], draft_version_id)
            self.assertEqual(draft_preview_response.json()["component"]["status"], "draft")

            draft_response = client.get(
                config["routes"]["component_version"].format(
                    version_id=draft_version_id,
                )
            )

            self.assertEqual(draft_response.status_code, 200)

            publish_response = client.post(
                config["routes"]["component_version_publish"].format(
                    version_id=draft_version_id,
                ),
                json={
                    "releaseNote": "first publish",
                    "name": "Wheel Shell Component",
                    "category": "technic",
                    "version": "0.1.0",
                    "contentLocale": "en-US",
                },
            )

            self.assertEqual(publish_response.status_code, 200)
            self.assertEqual(
                publish_response.json()["status"],
                config["versions"]["status"]["published"],
            )

            components_response = client.get(
                config["routes"]["components"],
                params={"contentLocale": "zh-CN"},
            )
            preview_response = client.get(
                config["routes"]["component_preview_first"],
                params={"contentLocale": "zh-CN"},
            )
            versions_response = client.get(
                config["routes"]["component_versions"].format(
                    component_id=parse_payload["component"]["id"],
                )
            )
            version_preview_response = client.get(
                config["routes"]["component_version_preview"].format(
                    version_id=draft_version_id,
                ),
                params={"contentLocale": "zh-CN"},
            )
            version_source_response = client.get(
                config["routes"]["component_version_source"].format(
                    version_id=draft_version_id,
                )
            )
            immutable_interface_response = client.post(
                config["routes"]["candidate_interfaces"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                ),
                json={
                    "worldConnectorId": free_response.json()[1]["worldConnectorId"],
                    "name": "second_mount",
                },
            )
            immutable_relation_response = client.post(
                config["routes"]["candidate_relation_reject"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                    relation_id=relation_response.json()[0]["id"],
                )
            )

            self.assertEqual(components_response.status_code, 200)
            self.assertEqual(len(components_response.json()), 1)
            self.assertEqual(components_response.json()[0]["contentLocale"], "en-US")
            self.assertEqual(components_response.json()[0]["contentKind"], "user")
            self.assertEqual(preview_response.status_code, 200)
            self.assertEqual(
                preview_response.json()["component"]["id"],
                parse_payload["component"]["id"],
            )
            self.assertEqual(preview_response.json()["component"]["name"], "Wheel Shell Component")
            self.assertEqual(preview_response.json()["partCount"], 2)
            self.assertEqual(
                [part["partRef"] for part in preview_response.json()["parts"]],
                ["male.dat", "female.dat"],
            )
            self.assertEqual(
                preview_response.json()["logicalSize"],
                {"widthStud": 1.0, "depthStud": 1.0, "heightPlate": 1.0},
            )
            self.assertEqual(versions_response.status_code, 200)
            self.assertEqual(len(versions_response.json()), 1)
            self.assertEqual(version_preview_response.status_code, 200)
            self.assertEqual(version_preview_response.json()["versionId"], draft_version_id)
            self.assertEqual(version_source_response.status_code, 200)
            self.assertEqual(version_source_response.content, b"io-bytes")
            self.assertEqual(immutable_interface_response.status_code, 400)
            self.assertEqual(immutable_relation_response.status_code, 400)

            download = client.get(
                config["routes"]["component_artifact_source"].format(
                    artifact_id=source_artifact_id,
                )
            )

        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"io-bytes")


def component_repo_config() -> dict:
    return load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )


def fixture_path(relative_path: str) -> Path:
    return Path(__file__).resolve().parents[2] / relative_path


def seed_preview_ldraw_library(root: Path) -> None:
    parts = root / "parts"
    high_resolution_primitives = root / "p" / "48"
    parts.mkdir(parents=True)
    high_resolution_primitives.mkdir(parents=True)
    (parts / "male.dat").write_text(
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 curve.dat\n",
        encoding="utf-8",
    )
    (parts / "female.dat").write_text(
        "3 16 0 0 0 20 0 0 0 8 20\n",
        encoding="utf-8",
    )
    (high_resolution_primitives / "curve.dat").write_text(
        "4 16 0 0 0 20 0 0 20 8 20 0 8 20\n",
        encoding="utf-8",
    )


def seed_connector_pair(engine) -> None:
    from sqlalchemy.orm import sessionmaker

    LDrawFile.__table__.create(bind=engine, checkfirst=True)
    LDrawPart.__table__.create(bind=engine, checkfirst=True)
    LDrawPartGeometry.__table__.create(bind=engine, checkfirst=True)
    PartTranslation.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        for row_id, part_num in ((1, "male.dat"), (2, "female.dat")):
            session.add(
                LDrawFile(
                    id=row_id,
                    relative_path=f"parts/{part_num}",
                    file_name=part_num,
                    library_section="parts",
                )
            )
            session.add(
                LDrawPart(
                    id=row_id,
                    ldraw_part_num=part_num,
                    file_id=row_id,
                    name=part_num,
                    category="Technic",
                    relative_path=f"parts/{part_num}",
                )
            )
            session.add(
                LDrawPartGeometry(
                    id=row_id,
                    ldraw_part_id=row_id,
                    bbox_min_x=0,
                    bbox_min_y=0,
                    bbox_min_z=0,
                    bbox_max_x=20,
                    bbox_max_y=8,
                    bbox_max_z=20,
                    width_ldu=20,
                    height_ldu=8,
                    depth_ldu=20,
                    logical_width_stud=1,
                    logical_depth_stud=1,
                    logical_height_plate=1,
                )
            )
        session.add(
            ConnectorInstance(
                id=1,
                ldraw_part_num="male.dat",
                source_type="test",
                connector_kind="cyl",
                normalized_connector_type="technic_pin",
                connector_group="pin",
                connector_gender="M",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
                direction_x=0,
                direction_y=1,
                direction_z=0,
                direction_label="top",
                direction_group="vertical",
                confidence=1,
                raw_params={},
            )
        )
        session.add(
            ConnectorInstance(
                id=2,
                ldraw_part_num="female.dat",
                source_type="test",
                connector_kind="cyl",
                normalized_connector_type="technic_pin_hole",
                connector_group="hole",
                connector_gender="F",
                pos_x=0,
                pos_y=0,
                pos_z=0,
                ori_11=1,
                ori_12=0,
                ori_13=0,
                ori_21=0,
                ori_22=1,
                ori_23=0,
                ori_31=0,
                ori_32=0,
                ori_33=1,
                direction_x=0,
                direction_y=-1,
                direction_z=0,
                direction_label="bottom",
                direction_group="vertical",
                confidence=1,
                raw_params={},
            )
        )
        session.commit()


def pin_pair_ldraw() -> str:
    return (
        "0 FILE pin_pair\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 male.dat\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 female.dat\n"
        "0 NOFILE\n"
    )
