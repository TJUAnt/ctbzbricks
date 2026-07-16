"""API tests for Component Repo artifact upload and download."""

from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.api.routes.component_repo import create_component_repo_router
from src.component_repo.services import ensure_component_repo_tables
from src.component_repo.storage import LocalArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.model.models import ConnectorInstance


class ComponentRepoApiTest(unittest.TestCase):
    def test_create_import_accepts_single_ldraw_source_as_exchange(self) -> None:
        config = component_repo_config()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ConnectorInstance.__table__.create(bind=engine)
        ensure_component_repo_tables(engine)
        with tempfile.TemporaryDirectory() as directory:
            app = FastAPI()
            app.state.db_engine = engine
            app.state.component_repo_storage = LocalArtifactStorage(
                root_path=Path(directory),
                bucket=config["storage"]["bucket"],
                provider=config["storage"]["local_provider"],
            )
            app.include_router(create_component_repo_router(config))
            client = TestClient(app)

            response = client.post(
                config["routes"]["component_imports"],
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
                config["routes"]["component_import_parse"].format(
                    import_id=payload["importJob"]["id"],
                )
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
        seed_connector_pair(engine)
        with tempfile.TemporaryDirectory() as directory:
            app = FastAPI()
            app.state.db_engine = engine
            app.state.component_repo_storage = LocalArtifactStorage(
                root_path=Path(directory),
                bucket=config["storage"]["bucket"],
                provider=config["storage"]["local_provider"],
            )
            app.include_router(create_component_repo_router(config))
            client = TestClient(app)

            response = client.post(
                config["routes"]["component_imports"],
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

            parse_response = client.post(
                config["routes"]["component_import_parse"].format(
                    import_id=payload["importJob"]["id"],
                )
            )

            self.assertEqual(parse_response.status_code, 200)
            parse_payload = parse_response.json()
            self.assertEqual(
                parse_payload["importJob"]["status"],
                config["imports"]["status"]["parsed"],
            )
            self.assertEqual(parse_payload["candidate"]["summary"]["modelCount"], 1)
            self.assertEqual(parse_payload["candidate"]["summary"]["partInstanceCount"], 2)

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

            approve_response = client.post(
                config["routes"]["candidate_approve"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                ),
                json={
                    "name": "Wheel Shell Component",
                    "category": "technic",
                    "version": "0.1.0",
                    "tags": ["api-test"],
                },
            )

            self.assertEqual(approve_response.status_code, 200)
            self.assertEqual(
                approve_response.json()["version"]["status"],
                config["versions"]["status"]["draft"],
            )
            draft_version_id = approve_response.json()["version"]["id"]

            hidden_draft_response = client.get(
                config["routes"]["component_version"].format(
                    version_id=draft_version_id,
                )
            )

            self.assertEqual(hidden_draft_response.status_code, 404)

            publish_response = client.post(
                config["routes"]["component_version_publish"].format(
                    version_id=draft_version_id,
                ),
                json={"releaseNote": "first publish"},
            )

            self.assertEqual(publish_response.status_code, 200)
            self.assertEqual(
                publish_response.json()["status"],
                config["versions"]["status"]["published"],
            )

            components_response = client.get(config["routes"]["components"])
            versions_response = client.get(
                config["routes"]["component_versions"].format(
                    component_id=approve_response.json()["component"]["id"],
                )
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
            self.assertEqual(versions_response.status_code, 200)
            self.assertEqual(len(versions_response.json()), 1)
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


def seed_connector_pair(engine) -> None:
    from sqlalchemy.orm import sessionmaker

    Session = sessionmaker(bind=engine)
    with Session() as session:
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
