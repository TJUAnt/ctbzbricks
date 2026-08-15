"""API tests for Component Repo artifact upload and download."""

import hashlib
from pathlib import Path
import tempfile
import unittest
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.errors import install_error_handlers
from src.api.routes.component_repo import create_component_repo_router
from src.auth.current_user import CurrentUser, optional_current_user
from src.component_repo.services import ensure_component_repo_tables
from src.component_repo.storage import LocalArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.model.models import (
    ConnectorInstance,
    Component,
    ComponentArtifact,
    ComponentCandidate,
    ComponentImport,
    ComponentUploadSession,
    LDrawFile,
    LDrawPart,
    LDrawPartGeometry,
    Part,
    PartImage,
    PartTranslation,
    XrefPartNumber,
)
from src.services.fitting_candidate_profile_service import (
    ensure_fitting_candidate_profile_table,
)


class DeferredFuture:
    def __init__(self) -> None:
        self._done = False
        self._callbacks: list[Callable[["DeferredFuture"], None]] = []

    def done(self) -> bool:
        return self._done

    def add_done_callback(
        self,
        callback: Callable[["DeferredFuture"], None],
    ) -> None:
        self._callbacks.append(callback)

    def finish(self) -> None:
        self._done = True
        for callback in self._callbacks:
            callback(self)


class DeferredExecutor:
    def __init__(self) -> None:
        self._pending: list[
            tuple[Callable[..., None], tuple[Any, ...], dict[str, Any], DeferredFuture]
        ] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def submit(
        self,
        function: Callable[..., None],
        *args: Any,
        **kwargs: Any,
    ) -> DeferredFuture:
        future = DeferredFuture()
        self._pending.append((function, args, kwargs, future))
        return future

    def run_next(self) -> None:
        function, args, kwargs, future = self._pending.pop(0)
        try:
            function(*args, **kwargs)
        finally:
            future.finish()


class ComponentRepoApiTest(unittest.TestCase):
    def test_direct_upload_completion_queues_reviewable_candidate_processing(self) -> None:
        config = component_repo_config()
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ConnectorInstance.__table__.create(bind=engine)
        ensure_component_repo_tables(engine)
        ensure_fitting_candidate_profile_table(engine)
        content = fixture_path("repo/8cars/car_seat.ldr").read_bytes()
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
            executor = DeferredExecutor()
            app.state.component_import_executor = executor
            app.dependency_overrides[optional_current_user] = lambda: CurrentUser(
                user_id="owner-1",
                email="owner@example.com",
                role="authenticated",
                access_token="test-token",
                raw={},
            )
            app.include_router(create_component_repo_router(config))
            client = TestClient(app)

            session_response = client.post(
                config["routes"]["component_import_upload_session"],
                json={
                    "sourceFile": {
                        "filename": "car_seat.ldr",
                        "contentType": "text/plain",
                        "fileSize": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    },
                    "contentLocale": "en-US",
                    "timezone": "Asia/Shanghai",
                },
            )
            self.assertEqual(session_response.status_code, 200)
            upload_session = session_response.json()
            target = upload_session["uploads"][0]
            storage.write_bytes(target["objectPath"], content, target["contentType"])

            response = client.post(
                config["routes"]["component_import_upload_complete"].format(
                    upload_session_id=upload_session["id"],
                )
            )
            self.assertEqual(response.status_code, 202)
            payload = response.json()
            self.assertEqual(payload["importJob"]["status"], "uploaded")
            self.assertEqual(
                payload["importJob"]["metadata"]["processing"]["status"],
                "queued",
            )
            self.assertEqual(executor.pending_count, 1)

            executor.run_next()
            import_response = client.get(
                config["routes"]["component_import"].format(
                    import_id=payload["importJob"]["id"],
                )
            )
            candidate_response = client.get(
                config["routes"]["component_import_candidate"].format(
                    import_id=payload["importJob"]["id"],
                )
            )

        self.assertEqual(import_response.status_code, 200)
        self.assertEqual(import_response.json()["status"], "parsed")
        processing = import_response.json()["metadata"]["processing"]
        self.assertEqual(processing["status"], "completed")
        self.assertEqual(processing["contentLocale"], "en-US")
        self.assertEqual(processing["timezone"], "Asia/Shanghai")
        self.assertEqual(candidate_response.status_code, 200)
        self.assertEqual(candidate_response.json()["status"], "in_review")
        self.assertEqual(candidate_response.json()["summary"]["partInstanceCount"], 4)
        self.assertEqual(payload["sourceArtifact"]["originalFilename"], "car_seat.ldr")

    def test_owner_can_delete_non_current_draft_version(self) -> None:
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
            app = FastAPI()
            install_error_handlers(app)
            app.state.db_engine = engine
            app.state.component_repo_storage = LocalArtifactStorage(
                root_path=Path(directory),
                bucket=config["storage"]["bucket"],
                provider=config["storage"]["local_provider"],
            )
            app.dependency_overrides[optional_current_user] = lambda: CurrentUser(
                user_id="owner-1",
                email="owner@example.com",
                role="authenticated",
                access_token="test-token",
                raw={},
            )
            app.include_router(create_component_repo_router(config))
            client = TestClient(app)

            create_response = client.post(
                config["routes"]["component_imports"],
                data={"content_locale": "en-US"},
                files={
                    "source_file": (
                        "delete_version.io",
                        b"io-bytes",
                        "application/octet-stream",
                    ),
                    "exchange_file": (
                        "delete_version.ldr",
                        separated_pair_ldraw().encode("utf-8"),
                        "text/plain",
                    ),
                },
            )
            payload = create_response.json()
            versions_before = client.get(
                config["routes"]["component_versions"].format(
                    component_id=payload["component"]["id"],
                )
            )
            delete_response = client.delete(
                config["routes"]["component_version_delete"].format(
                    version_id=payload["version"]["id"],
                )
            )
            versions_after = client.get(
                config["routes"]["component_versions"].format(
                    component_id=payload["component"]["id"],
                )
            )
            components_after = client.get(
                config["routes"]["components"],
                params={"contentLocale": "en-US"},
            )

        self.assertEqual(create_response.status_code, 200)
        self.assertEqual(
            versions_before.json()[0]["deletion"],
            {"allowed": True, "reason": None},
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.json()["componentDeleted"])
        self.assertEqual(versions_after.json(), [])
        self.assertEqual(components_after.json(), [])

    def test_failed_automatic_processing_discards_temporary_aggregate(self) -> None:
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

            response = client.post(
                config["routes"]["component_imports"],
                data={"content_locale": "en-US"},
                files={
                    "source_file": (
                        "invalid.io",
                        b"not-a-studio-archive",
                        "application/octet-stream",
                    ),
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json()["error"]["code"],
                "component_repo.component_processing_failed",
            )
            with Session(engine) as session:
                for model in (
                    ComponentUploadSession,
                    ComponentImport,
                    ComponentArtifact,
                    ComponentCandidate,
                    Component,
                ):
                    self.assertEqual(
                        session.scalar(select(func.count()).select_from(model)),
                        0,
                    )
            self.assertEqual(
                [path for path in Path(directory).rglob("*") if path.is_file()],
                [],
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
            self.assertEqual(version_preview_operation["summary"], "Get one Component version GLB")
            self.assertNotIn("/api/library-items/{item_type}/{item_id}/preview", openapi["paths"])
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

            self.assertEqual(payload["candidate"]["summary"]["partInstanceCount"], 3)

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

            removed_part_preview_response = client.get(
                "/api/library-items/part/male.dat/preview",
                params={"contentLocale": "en-US"},
            )
            self.assertEqual(removed_part_preview_response.status_code, 404)

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
                        separated_pair_ldraw().encode("utf-8"),
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

            parse_payload = payload
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

            explicit_candidate_preview_response = client.post(
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

            free_response = client.get(
                config["routes"]["candidate_free_connectors"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )
            self.assertEqual(free_response.status_code, 200)
            self.assertEqual(len(free_response.json()), 2)

            relation_response = client.post(
                config["routes"]["candidate_relations_detect"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )

            self.assertEqual(relation_response.status_code, 200)
            self.assertEqual(len(relation_response.json()), 0)

            connector_response = client.get(
                config["routes"]["candidate_connectors"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )
            self.assertEqual(connector_response.status_code, 200)
            self.assertEqual(len(connector_response.json()["connectors"]), 2)
            self.assertEqual(len(connector_response.json()["externalInterfaces"]), 2)

            connector_summary_response = client.get(
                config["routes"]["candidate_connector_summary"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                )
            )
            self.assertEqual(connector_summary_response.status_code, 200)
            connector_summary = connector_summary_response.json()
            self.assertEqual(len(connector_summary["connectors"]), 2)
            self.assertEqual(len(connector_summary["externalInterfaces"]), 2)
            self.assertEqual(
                set(connector_summary["connectors"][0]),
                {
                    "worldConnectorId",
                    "partInstanceId",
                    "partRef",
                    "connectorId",
                    "connectorType",
                    "connectorKind",
                    "state",
                    "position",
                    "accessAxis",
                    "externalInterfaceId",
                },
            )

            interface_response = client.post(
                config["routes"]["candidate_interfaces"].format(
                    candidate_id=parse_payload["candidate"]["id"],
                ),
                json={
                    "worldConnectorId": free_response.json()[0]["worldConnectorId"],
                    "name": "manual_interface_is_not_supported",
                },
            )

            self.assertEqual(interface_response.status_code, 405)

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
            version_preview_expensive_queries: list[str] = []

            def record_part_preview_query(
                _connection,
                _cursor,
                statement,
                _parameters,
                _context,
                _executemany,
            ) -> None:
                normalized = " ".join(statement.casefold().split())
                if (
                    "from ldraw_parts" in normalized
                    or "component_scene_snapshots" in normalized
                ):
                    version_preview_expensive_queries.append(statement)

            event.listen(engine, "before_cursor_execute", record_part_preview_query)
            try:
                version_preview_response = client.get(
                    config["routes"]["component_version_preview"].format(
                        version_id=draft_version_id,
                    ),
                    params={"contentLocale": "zh-CN"},
                )
            finally:
                event.remove(engine, "before_cursor_execute", record_part_preview_query)
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
                preview_response.json()["partCatalog"],
                [
                    {
                        "partRef": "female.dat",
                        "name": "Female connector",
                        "contentLocale": "en-US",
                        "translationStatus": "fallback",
                        "imageUrl": "https://example.test/female.png",
                        "availability": "ready",
                    },
                    {
                        "partRef": "male.dat",
                        "name": "Male connector",
                        "contentLocale": "en-US",
                        "translationStatus": "fallback",
                        "imageUrl": "https://example.test/male.png",
                        "availability": "ready",
                    },
                ],
            )
            self.assertEqual(preview_response.json()["renderablePartCount"], 2)
            self.assertEqual(
                [part["availability"] for part in preview_response.json()["partInventory"]],
                ["ready", "ready"],
            )
            self.assertEqual(
                preview_response.json()["logicalSize"],
                {"widthStud": 3.0, "depthStud": 1.0, "heightPlate": 1.0},
            )
            self.assertEqual(versions_response.status_code, 200)
            self.assertEqual(len(versions_response.json()), 1)
            self.assertEqual(version_preview_response.status_code, 200)
            self.assertEqual(version_preview_response.json()["versionId"], draft_version_id)
            self.assertEqual(version_preview_response.json()["status"], "ready")
            self.assertIsNotNone(version_preview_response.json()["model"])
            self.assertEqual(version_preview_expensive_queries, [])
            self.assertEqual(version_source_response.status_code, 200)
            self.assertEqual(version_source_response.content, b"io-bytes")
            self.assertEqual(immutable_interface_response.status_code, 405)

            download = client.get(
                config["routes"]["component_artifact_source"].format(
                    artifact_id=source_artifact_id,
                )
            )

        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"io-bytes")

    def test_preview_excludes_missing_parts_but_keeps_inventory_status(self) -> None:
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

            create_response = client.post(
                config["routes"]["component_imports"],
                data={"content_locale": "en-US"},
                files={
                    "source_file": (
                        "partial_preview.ldr",
                        partial_preview_ldraw().encode("utf-8"),
                        "text/plain",
                    ),
                },
            )
            self.assertEqual(create_response.status_code, 200)
            version_id = create_response.json()["version"]["id"]

            model_response = client.post(
                config["routes"]["component_version_preview"].format(
                    version_id=version_id,
                ),
                params={"contentLocale": "en-US"},
            )
            preview_response = client.get(
                config["routes"]["component_version_parts"].format(
                    version_id=version_id,
                ),
                params={"contentLocale": "en-US"},
            )

        self.assertEqual(model_response.status_code, 200)
        self.assertEqual(model_response.json()["status"], "ready")
        self.assertIsNotNone(model_response.json()["model"])
        self.assertEqual(preview_response.status_code, 200)
        preview = preview_response.json()
        self.assertEqual(preview["partCount"], 2)
        self.assertEqual(preview["renderablePartCount"], 1)
        self.assertEqual(
            [
                (part["partRef"], part["quantity"], part["availability"])
                for part in preview["parts"]
            ],
            [
                ("male.dat", 1, "ready"),
                ("missing.dat", 1, "missing_geometry"),
            ],
        )
        self.assertEqual(
            preview["parts"],
            [
                {
                    "partRef": "male.dat",
                    "name": "Male connector",
                    "contentLocale": "en-US",
                    "translationStatus": "source",
                    "imageUrl": "https://example.test/male.png",
                    "quantity": 1,
                    "availability": "ready",
                },
                {
                    "partRef": "missing.dat",
                    "name": "missing.dat",
                    "contentLocale": None,
                    "translationStatus": None,
                    "imageUrl": None,
                    "quantity": 1,
                    "availability": "missing_geometry",
                },
            ],
        )
        self.assertEqual(
            preview["logicalSize"],
            {"widthStud": 1.0, "depthStud": 1.0, "heightPlate": 1.0},
        )


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
    Part.__table__.create(bind=engine, checkfirst=True)
    PartImage.__table__.create(bind=engine, checkfirst=True)
    XrefPartNumber.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        for row_id, part_num, name in (
            (1, "male.dat", "Male connector"),
            (2, "female.dat", "Female connector"),
        ):
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
                    name=name,
                    category="Technic",
                    relative_path=f"parts/{part_num}",
                )
            )
            part_stem = part_num.removesuffix(".dat")
            session.add(Part(part_num=part_stem, name=name))
            session.add(
                PartImage(
                    part_num=part_stem,
                    img_url=f"https://example.test/{part_stem}.png",
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


def separated_pair_ldraw() -> str:
    return (
        "0 FILE separated_pair\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 male.dat\n"
        "1 16 40 0 0 1 0 0 0 1 0 0 0 1 female.dat\n"
        "0 NOFILE\n"
    )


def partial_preview_ldraw() -> str:
    return (
        "0 FILE partial_preview\n"
        "1 16 0 0 0 1 0 0 0 1 0 0 0 1 male.dat\n"
        "1 4 40 0 0 1 0 0 0 1 0 0 0 1 missing.dat\n"
        "0 NOFILE\n"
    )
