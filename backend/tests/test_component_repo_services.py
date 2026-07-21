"""Tests for Component Repo artifact and import foundations."""

from pathlib import Path
import json
import tempfile
import unittest

from sqlalchemy import create_engine, inspect, text

from src.component_repo.services import (
    create_component_artifact,
    create_component_import,
    complete_component_upload_session,
    create_component_upload_session,
    ensure_component_repo_tables,
    get_component_candidate_for_import,
    parse_component_import,
    read_component_artifact,
)
from src.component_repo.storage import LocalArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class ComponentRepoServicesTest(unittest.TestCase):
    def test_legacy_component_repo_tables_are_upgraded(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE component_imports ("
                    "id VARCHAR(36) PRIMARY KEY, failure_reason TEXT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO component_imports (id, failure_reason) "
                    "VALUES ('legacy-import', 'legacy parser failure')"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE components ("
                    "id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL)"
                )
            )

        ensure_component_repo_tables(engine)

        import_columns = {
            column["name"]
            for column in inspect(engine).get_columns("component_imports")
        }
        component_columns = {
            column["name"]
            for column in inspect(engine).get_columns("components")
        }
        with engine.connect() as connection:
            failure_code, failure_params = connection.execute(
                text(
                    "SELECT failure_code, failure_params_json "
                    "FROM component_imports WHERE id = 'legacy-import'"
                )
            ).one()
        self.assertIn("failure_code", import_columns)
        self.assertIn("failure_params_json", import_columns)
        self.assertIn("content_kind", component_columns)
        self.assertIn("content_locale", component_columns)
        self.assertEqual(failure_code, "component_repo.legacy_failure")
        self.assertEqual(
            json.loads(failure_params),
            {"legacyMessage": "legacy parser failure"},
        )

    def test_create_and_read_component_artifact_roundtrips_bytes(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            content = b"studio source bytes"

            artifact = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "../wheel_shell_component.io",
                content,
            )
            saved_artifact, saved_content = read_component_artifact(
                engine,
                config,
                storage,
                artifact["id"],
            )

        self.assertEqual(saved_content, content)
        self.assertEqual(saved_artifact["id"], artifact["id"])
        self.assertEqual(saved_artifact["originalFilename"], "wheel_shell_component.io")
        self.assertEqual(saved_artifact["storageProvider"], config["storage"]["local_provider"])
        self.assertEqual(saved_artifact["uploadedBy"], config["audit"]["system_user"])
        self.assertEqual(saved_artifact["fileSize"], len(content))
        self.assertEqual(len(saved_artifact["sha256"]), 64)

    def test_create_component_artifact_rejects_unknown_artifact_type(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)

            with self.assertRaises(ValueError) as error:
                create_component_artifact(
                    engine,
                    config,
                    storage,
                    "unknown",
                    "sample.bin",
                    b"content",
                )

        self.assertEqual(
            str(error.exception),
            config["errors"]["invalid_artifact_type"].format(artifact_type="unknown"),
        )

    def test_create_component_import_links_source_and_exchange_artifacts(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "wheel_shell_component.io",
                b"io",
            )
            exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "wheel_shell_component2.ldr",
                b"0 FILE wheel_shell_component\n",
            )

            import_row = create_component_import(
                engine,
                config,
                source["id"],
                exchange["id"],
            )

        self.assertEqual(import_row["sourceArtifactId"], source["id"])
        self.assertEqual(import_row["exchangeArtifactId"], exchange["id"])
        self.assertEqual(import_row["status"], config["imports"]["status"]["uploaded"])
        self.assertEqual(import_row["createdBy"], config["audit"]["system_user"])

    def test_complete_upload_session_creates_artifacts_and_import(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        owner_id = "user-123"
        actor = f"auth:{owner_id}"
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            upload_session = create_component_upload_session(
                engine,
                config,
                owner_id,
                "wheel_shell_component.io",
                "application/octet-stream",
                "wheel_shell_component2.ldr",
                "text/plain",
                created_by=actor,
            )
            for upload in upload_session["uploads"]:
                content = b"io" if upload["role"] == "source" else b"0 FILE model\n"
                storage.write_bytes(upload["objectPath"], content, upload["contentType"])

            result = complete_component_upload_session(
                engine,
                config,
                storage,
                upload_session["id"],
                owner_id,
                completed_by=actor,
            )

        self.assertEqual(result["importJob"]["createdBy"], actor)
        self.assertEqual(result["sourceArtifact"]["uploadedBy"], actor)
        self.assertEqual(result["exchangeArtifact"]["uploadedBy"], actor)
        self.assertTrue(result["sourceArtifact"]["storageKey"].startswith(f"{owner_id}/component-repo/imports/"))
        self.assertEqual(
            result["sourceArtifact"]["metadata"]["uploadMethod"],
            "direct_storage",
        )

    def test_parse_component_import_persists_scene_snapshot_and_candidate(self) -> None:
        config = component_repo_config()
        engine = test_engine()
        ldraw_content = fixture_path("repo/8cars/wheel_shell_component2.ldr").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            storage = local_storage(config, directory)
            source = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["studio_io"],
                "wheel_shell_component.io",
                b"io",
            )
            exchange = create_component_artifact(
                engine,
                config,
                storage,
                config["artifacts"]["ldraw_ldr"],
                "wheel_shell_component2.ldr",
                ldraw_content,
            )
            import_row = create_component_import(
                engine,
                config,
                source["id"],
                exchange["id"],
            )

            result = parse_component_import(
                engine,
                config,
                storage,
                import_row["id"],
            )
            repeated = parse_component_import(
                engine,
                config,
                storage,
                import_row["id"],
            )
            candidate = get_component_candidate_for_import(engine, import_row["id"])

        self.assertEqual(result["importJob"]["status"], config["imports"]["status"]["parsed"])
        self.assertEqual(result["sceneSnapshot"]["rootModelId"], "model_0001")
        self.assertEqual(result["candidate"]["status"], config["candidates"]["status"]["in_review"])
        self.assertEqual(result["component"]["status"], config["components"]["status"]["draft"])
        self.assertEqual(result["version"]["status"], config["versions"]["status"]["draft"])
        self.assertEqual(repeated["candidate"]["id"], result["candidate"]["id"])
        self.assertEqual(repeated["version"]["id"], result["version"]["id"])
        self.assertEqual(result["candidate"]["summary"]["modelCount"], 4)
        self.assertEqual(result["candidate"]["summary"]["partInstanceCount"], 3)
        self.assertEqual(result["candidate"]["summary"]["submodelInstanceCount"], 3)
        self.assertEqual(result["candidate"]["summary"]["parseIssueCount"], 1)
        self.assertEqual(candidate["id"], result["candidate"]["id"])

    def test_parse_repo_components_persists_candidates(self) -> None:
        config = component_repo_config()
        fixtures = repo_ldraw_fixture_paths()

        self.assertGreaterEqual(len(fixtures), 1)
        for path in fixtures:
            with self.subTest(path=str(path.relative_to(WORKSPACE_ROOT))):
                engine = test_engine()
                ldraw_content = path.read_bytes()
                with tempfile.TemporaryDirectory() as directory:
                    storage = local_storage(config, directory)
                    source = create_component_artifact(
                        engine,
                        config,
                        storage,
                        config["artifacts"]["studio_io"],
                        f"{path.stem}.io",
                        b"io",
                    )
                    exchange = create_component_artifact(
                        engine,
                        config,
                        storage,
                        config["artifacts"]["ldraw_ldr"],
                        path.name,
                        ldraw_content,
                    )
                    import_row = create_component_import(
                        engine,
                        config,
                        source["id"],
                        exchange["id"],
                    )

                    result = parse_component_import(
                        engine,
                        config,
                        storage,
                        import_row["id"],
                    )
                    candidate = get_component_candidate_for_import(engine, import_row["id"])

                self.assertEqual(result["importJob"]["status"], config["imports"]["status"]["parsed"])
                self.assertEqual(result["candidate"]["status"], config["candidates"]["status"]["in_review"])
                self.assertGreaterEqual(result["candidate"]["summary"]["modelCount"], 1)
                self.assertGreaterEqual(result["candidate"]["summary"]["partInstanceCount"], 1)
                self.assertEqual(
                    result["candidate"]["summary"]["bom"],
                    result["sceneSnapshot"]["bom"],
                )
                self.assertEqual(candidate["id"], result["candidate"]["id"])


def component_repo_config() -> dict:
    return load_json_config(
        "component_repo.json",
        REQUIRED_COMPONENT_REPO_CONFIG_KEYS,
    )


def test_engine():
    engine = create_engine("sqlite:///:memory:")
    ensure_component_repo_tables(engine)
    return engine


def local_storage(config: dict, directory: str) -> LocalArtifactStorage:
    return LocalArtifactStorage(
        root_path=Path(directory),
        bucket=config["storage"]["bucket"],
        provider=config["storage"]["local_provider"],
    )


def fixture_path(relative_path: str) -> Path:
    return WORKSPACE_ROOT / relative_path


def repo_ldraw_fixture_paths() -> list[Path]:
    repo_root = WORKSPACE_ROOT / "repo"
    return sorted([*repo_root.rglob("*.ldr"), *repo_root.rglob("*.mpd")])
