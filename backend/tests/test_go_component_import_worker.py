from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import psycopg
import pytest
from psycopg.rows import dict_row

from src.component_repo.go_import_parser import materialize_import
from src.component_repo.go_import_worker import (
    ComponentImportWorker,
    LeaseLost,
    WorkerSettings,
    storage_from_environment,
)
from src.component_repo.go_relation_worker import ComponentRelationWorker
from src.component_repo.storage import ArtifactObjectMetadata
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS


PARSER_VERSION = "component-repo-ldraw-parser-v1"
SNAPSHOT_SCHEMA = "component-repo-v1"
OWNER_ID = UUID("65000000-0000-0000-0000-000000000001")


def test_python_worker_accepts_modern_supabase_secret_key(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_STORAGE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_worker")

    storage = storage_from_environment({"storage": {"bucket": "component-artifacts"}})

    assert storage.api_key == "sb_secret_worker"
    assert storage._auth_headers() == {"apikey": "sb_secret_worker"}


def test_python_worker_rejects_publishable_server_key(monkeypatch) -> None:
    monkeypatch.delenv("SUPABASE_STORAGE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_publishable_browser")

    with pytest.raises(RuntimeError, match="must not be publishable"):
        storage_from_environment({"storage": {"bucket": "component-artifacts"}})


@dataclass
class MemoryStorage:
    objects: dict[str, bytes]
    provider: str = "test"
    bucket: str = "test"

    def read_bytes(self, storage_key: str) -> bytes:
        return self.objects[storage_key]

    def write_bytes(self, storage_key: str, content: bytes, content_type: str) -> str:
        del content_type
        self.objects.setdefault(storage_key, content)
        return f"test://test/{storage_key}"

    def head(self, storage_key: str) -> ArtifactObjectMetadata:
        return ArtifactObjectMetadata(content_length=len(self.objects[storage_key]))

    def delete(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)

    def create_download_url(self, storage_key: str, expires_in: int) -> str | None:
        del storage_key, expires_in
        return None


@pytest.fixture(scope="module")
def component_config() -> dict:
    return load_json_config("component_repo.json", REQUIRED_COMPONENT_REPO_CONFIG_KEYS)


def test_parser_materializes_stable_structured_result(component_config: dict) -> None:
    content = (
        b"0 FILE model.ldr\n"
        b"1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
        b"0 NOFILE\n"
    )
    first = materialize_import(content, "ldraw_ldr", "用户模型.ldr", component_config)
    second = materialize_import(content, "ldraw_ldr", "用户模型.ldr", component_config)

    assert first.bom == {"3001.dat": 1}
    assert first.summary["partInstanceCount"] == 1
    assert first.structure_hash == second.structure_hash
    assert first.geometry_hash == second.geometry_hash
    assert len(first.interface_signature) == 64
    assert all(set(issue) == {"code", "severity", "params", "path"} for issue in first.parse_issues)
    assert all("exception" not in str(issue).lower() for issue in first.parse_issues)


def test_studio_parser_extracts_canonical_exchange(component_config: dict) -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("model.ldr", "0 FILE studio.ldr\n0 NOFILE\n")
    result = materialize_import(buffer.getvalue(), "studio_io", "studio.io", component_config)
    assert result.exchange_filename == "studio.ldr"
    assert result.exchange_bytes == b"0 FILE studio.ldr\n0 NOFILE\n"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="isolated PostgreSQL is required")
def test_python_worker_commits_candidate_draft_and_task_atomically(component_config: dict) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    content = (
        b"0 FILE model.ldr\n"
        b"1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
        b"0 NOFILE\n"
    )
    storage = MemoryStorage({"imports/source.ldr": content})
    import_id, parse_task_id = seed_import(database_url, content, "imports/source.ldr")
    worker = ComponentImportWorker(
        WorkerSettings(database_url, "python-parser-test", heartbeat_interval=1.0),
        storage,
        component_config,
    )

    assert worker.run_once() is True
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        result = connection.execute(
            """
            SELECT import_job.status AS import_status, import_job.locale,
                   task.status AS task_status, task.locale AS task_locale,
                   task.result, candidate.id AS candidate_id,
                   snapshot.id AS snapshot_id, snapshot.parse_issues,
                   version.id AS version_id, version.status AS version_status,
                   component.content_locale, component.name
            FROM component_repo.imports import_job
            JOIN component_repo.tasks task ON task.id = import_job.parse_task_id
            JOIN component_repo.candidates candidate ON candidate.import_id = import_job.id
            JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
            JOIN component_repo.component_versions version ON version.component_candidate_id = candidate.id
            JOIN component_repo.components component ON component.id = version.component_id
            WHERE import_job.id = %s
            """,
            (import_id,),
        ).fetchone()
        assert result["import_status"] == "succeeded"
        assert result["task_status"] == "succeeded"
        assert result["version_status"] == "draft"
        assert result["locale"] == result["task_locale"] == result["content_locale"] == "zh-CN"
        assert result["name"] == "用户模型"
        assert result["result"]["candidateId"] == str(result["candidate_id"])
        assert all("exception" not in str(issue).lower() for issue in result["parse_issues"])
        assert connection.execute(
            "SELECT count(*) FROM component_repo.scene_snapshots WHERE import_id = %s",
            (import_id,),
        ).fetchone()["count"] == 1
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "UPDATE component_repo.scene_snapshots SET document = '{}' WHERE id = %s",
                (result["snapshot_id"],),
            )
        connection.rollback()

    assert worker.run_once() is False
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        assert connection.execute(
            "SELECT count(*) FROM component_repo.scene_snapshots WHERE import_id = %s",
            (import_id,),
        ).fetchone()["count"] == 1
        assert connection.execute(
            "SELECT status FROM component_repo.tasks WHERE id = %s",
            (parse_task_id,),
        ).fetchone()["status"] == "succeeded"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="isolated PostgreSQL is required")
def test_python_worker_failure_is_structured_without_exception_text(component_config: dict) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    content = b"\xff\xfe"
    storage = MemoryStorage({"imports/invalid.ldr": content})
    import_id, parse_task_id = seed_import(database_url, content, "imports/invalid.ldr", filename="invalid.ldr")
    worker = ComponentImportWorker(
        WorkerSettings(database_url, "python-parser-failure", heartbeat_interval=1.0),
        storage,
        component_config,
    )

    assert worker.run_once() is True
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT import_job.status AS import_status, import_job.failure_code,
                   import_job.failure_params, task.status AS task_status,
                   task.error_code, task.error_params
            FROM component_repo.imports import_job
            JOIN component_repo.tasks task ON task.id = import_job.parse_task_id
            WHERE import_job.id = %s AND task.id = %s
            """,
            (import_id, parse_task_id),
        ).fetchone()
        assert row["import_status"] == row["task_status"] == "failed"
        assert row["failure_code"] == row["error_code"] == "component_repo.import_parse_failed"
        assert row["failure_params"] == row["error_params"] == {"importId": str(import_id)}
        assert "exception" not in json_text(row).lower()
        assert connection.execute(
            "SELECT count(*) FROM component_repo.scene_snapshots WHERE import_id = %s",
            (import_id,),
        ).fetchone()["count"] == 0


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="isolated PostgreSQL is required")
def test_python_worker_lease_is_fenced_by_claimed_attempt(component_config: dict) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    content = b"0 FILE model.ldr\n0 NOFILE\n"
    _, task_id = seed_import(database_url, content, "imports/fenced.ldr")
    worker = ComponentImportWorker(
        WorkerSettings(database_url, "reused-python-worker", heartbeat_interval=1.0),
        MemoryStorage({"imports/fenced.ldr": content}),
        component_config,
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute(
            """
            UPDATE component_repo.tasks
            SET status = 'running', attempts = 1, lease_owner = %s,
                lease_expires_at = now() + interval '1 minute'
            WHERE id = %s
            """,
            (worker.settings.worker_id, task_id),
        )
        connection.execute(
            """
            UPDATE component_repo.tasks
            SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL
            WHERE id = %s
            """,
            (task_id,),
        )
        connection.execute(
            """
            UPDATE component_repo.tasks
            SET status = 'running', attempts = 2, lease_owner = %s,
                lease_expires_at = now() + interval '1 minute'
            WHERE id = %s
            """,
            (worker.settings.worker_id, task_id),
        )
        with connection.cursor() as cursor:
            with pytest.raises(LeaseLost):
                worker._lock_owned_lease(
                    cursor,
                    {"id": task_id, "attempts": 1},
                    datetime.now(timezone.utc),
                )
            current = worker._lock_owned_lease(
                cursor,
                {"id": task_id, "attempts": 2},
                datetime.now(timezone.utc),
            )
            assert current["attempts"] == 2


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="isolated PostgreSQL is required")
def test_python_worker_materializes_studio_exchange_with_explicit_lineage(component_config: dict) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("model.ldr", "0 FILE studio.ldr\n0 NOFILE\n")
    content = buffer.getvalue()
    storage = MemoryStorage({"imports/studio.io": content})
    import_id, _ = seed_import(
        database_url,
        content,
        "imports/studio.io",
        filename="studio.io",
        artifact_type="studio_io",
    )
    worker = ComponentImportWorker(
        WorkerSettings(database_url, "python-parser-studio", heartbeat_interval=1.0),
        storage,
        component_config,
    )

    assert worker.run_once() is True
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT import_job.status, import_job.source_artifact_id,
                   import_job.exchange_artifact_id, exchange.source_kind,
                   exchange.derived_from_artifact_id, exchange.verification_status,
                   version.exchange_artifact_id AS version_exchange_artifact_id
            FROM component_repo.imports import_job
            JOIN component_repo.artifacts exchange ON exchange.id = import_job.exchange_artifact_id
            JOIN component_repo.candidates candidate ON candidate.import_id = import_job.id
            JOIN component_repo.component_versions version ON version.component_candidate_id = candidate.id
            WHERE import_job.id = %s
            """,
            (import_id,),
        ).fetchone()
        assert row["status"] == "succeeded"
        assert row["source_kind"] == "derived"
        assert row["verification_status"] == "verified"
        assert row["derived_from_artifact_id"] == row["source_artifact_id"]
        assert row["version_exchange_artifact_id"] == row["exchange_artifact_id"]


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="isolated PostgreSQL is required")
def test_python_relation_worker_materializes_candidates_without_changing_transforms(component_config: dict) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    content = (
        b"0 FILE model.ldr\n"
        b"1 16 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n"
        b"1 16 0 0 0 1 0 0 0 1 0 0 0 1 3002.dat\n"
        b"0 NOFILE\n"
    )
    storage = MemoryStorage({"imports/relations.ldr": content})
    import_id, _ = seed_import(database_url, content, "imports/relations.ldr", filename="relations.ldr")
    part_library_id = UUID("65000000-0000-0000-0000-000000000020")
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO component_repo.part_library_versions (
                id, source_name, source_hash, connector_count, status, created_by
            ) VALUES (%s, 'fixture', repeat('a', 64), 2, 'active', %s)
            """,
            (part_library_id, OWNER_ID),
        )
        connection.execute(
            """
            INSERT INTO component_repo.part_connector_definitions (
                part_library_version_id, source_connector_id, ldraw_part_num,
                connector_kind, normalized_connector_type, connector_gender,
                position, orientation, direction
            ) VALUES
                (%s, 1, '3001.dat', 'stud', 'stud', 'M',
                 ARRAY[0,0,0]::float8[], ARRAY[1,0,0,0,1,0,0,0,1]::float8[], ARRAY[0,1,0]::float8[]),
                (%s, 2, '3002.dat', 'tube', 'anti_stud', 'F',
                 ARRAY[0,0,0]::float8[], ARRAY[1,0,0,0,1,0,0,0,1]::float8[], ARRAY[0,-1,0]::float8[])
            """,
            (part_library_id, part_library_id),
        )
        connection.execute(
            "UPDATE component_repo.imports SET part_library_version_id = %s WHERE id = %s",
            (part_library_id, import_id),
        )
    parser = ComponentImportWorker(
        WorkerSettings(database_url, "python-parser-relations", heartbeat_interval=1.0),
        storage,
        component_config,
    )
    assert parser.run_once() is True
    detection_task_id = UUID("65000000-0000-0000-0000-000000000021")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        candidate = connection.execute(
            """
            SELECT candidate.id, candidate.scene_snapshot_id, snapshot.document
            FROM component_repo.candidates candidate
            JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
            WHERE candidate.import_id = %s
            """,
            (import_id,),
        ).fetchone()
        original_document = candidate["document"]
        connection.execute(
            """
            INSERT INTO component_repo.tasks (
                id, owner_id, task_type, payload, locale, timezone, created_by, max_attempts
            ) VALUES (%s, %s, 'component.relations.detect', %s, 'zh-CN', 'Asia/Shanghai', %s, 3)
            """,
            (detection_task_id, OWNER_ID, psycopg.types.json.Jsonb({
                "candidateId": str(candidate["id"]),
                "detectionVersion": "component-relation-detector-v1",
                "partLibraryVersionId": str(part_library_id),
                "inputHash": _relation_input_hash(connection, candidate["id"]),
            }), OWNER_ID),
        )
        connection.execute(
            """
            UPDATE component_repo.candidates
            SET relation_detection_task_id = %s,
                relation_detection_version = 'component-relation-detector-v1'
            WHERE id = %s
            """,
            (detection_task_id, candidate["id"]),
        )

    worker = ComponentRelationWorker(
        WorkerSettings(database_url, "python-relation-test", heartbeat_interval=1.0),
        component_config,
    )
    assert worker.run_once() is True
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        result = connection.execute(
            """
            SELECT task.status, task.locale, task.timezone, task.result,
                   candidate.interface_signature AS candidate_signature,
                   version.interface_signature AS version_signature,
                   snapshot.document,
                   (SELECT count(*) FROM component_repo.relation_candidates relation
                    WHERE relation.component_candidate_id = candidate.id) AS relation_count,
                   (SELECT count(*) FROM component_repo.connector_analysis_items item
                    WHERE item.component_candidate_id = candidate.id) AS connector_count,
                   (SELECT count(*) FROM component_repo.interfaces interface_row
                    WHERE interface_row.component_candidate_id = candidate.id) AS interface_count
            FROM component_repo.tasks task
            JOIN component_repo.candidates candidate ON candidate.relation_detection_task_id = task.id
            JOIN component_repo.component_versions version ON version.component_candidate_id = candidate.id
            JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
            WHERE task.id = %s
            """,
            (detection_task_id,),
        ).fetchone()
        assert result["status"] == "succeeded"
        assert result["locale"] == "zh-CN"
        assert result["timezone"] == "Asia/Shanghai"
        assert result["relation_count"] == 1
        assert result["connector_count"] == result["interface_count"] == 2
        assert result["candidate_signature"] == result["version_signature"]
        assert result["document"] == original_document
        assert set(result["result"]) == {
            "candidateId", "relationCandidateCount", "connectorCount",
            "interfaceCount", "detectionVersion",
        }
    assert worker.run_once() is False


def seed_import(
    database_url: str,
    content: bytes,
    storage_key: str,
    filename: str = "用户模型.ldr",
    artifact_type: str = "ldraw_ldr",
) -> tuple[UUID, UUID]:
    import_id = UUID("65000000-0000-0000-0000-000000000010")
    artifact_id = UUID("65000000-0000-0000-0000-000000000011")
    upload_session_id = UUID("65000000-0000-0000-0000-000000000012")
    prerequisite_id = UUID("65000000-0000-0000-0000-000000000013")
    parse_task_id = UUID("65000000-0000-0000-0000-000000000014")
    payload = {
        "importId": str(import_id),
        "parserVersion": PARSER_VERSION,
        "snapshotSchema": SNAPSHOT_SCHEMA,
    }
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "TRUNCATE component_repo.upload_sessions, component_repo.imports, "
            "component_repo.artifacts, component_repo.tasks, component_repo.outbox_events "
            "RESTART IDENTITY CASCADE"
        )
        connection.execute(
            """
            INSERT INTO component_repo.upload_sessions (
                id, owner_id, status, locale, timezone, created_by,
                expires_at, completed_at
            ) VALUES (%s, %s, 'completed', 'zh-CN', 'Asia/Shanghai', %s,
                      now() + interval '1 hour', now())
            """,
            (upload_session_id, OWNER_ID, OWNER_ID),
        )
        connection.execute(
            """
            INSERT INTO component_repo.artifacts (
                id, owner_id, artifact_type, source_kind, original_filename,
                storage_provider, storage_bucket, storage_key, sha256, file_size,
                mime_type, immutable, verification_status, verified_at, uploaded_by
            ) VALUES (%s, %s, %s, 'source', %s, 'test', 'test', %s,
                      %s, %s, 'text/plain', true, 'verified', now(), %s)
            """,
            (artifact_id, OWNER_ID, artifact_type, filename, storage_key,
             hashlib.sha256(content).hexdigest(), len(content), OWNER_ID),
        )
        connection.execute(
            """
            INSERT INTO component_repo.tasks (
                id, owner_id, task_type, payload, locale, timezone, created_by, max_attempts
            ) VALUES (%s, %s, 'component.artifact.verify', %s, 'zh-CN', 'Asia/Shanghai', %s, 1)
            """,
            (prerequisite_id, OWNER_ID, psycopg.types.json.Jsonb({"artifactId": str(artifact_id)}), OWNER_ID),
        )
        connection.execute(
            """
            UPDATE component_repo.tasks
            SET status = 'running', attempts = 1, lease_owner = 'fixture',
                lease_expires_at = now() + interval '1 minute', started_at = now()
            WHERE id = %s
            """,
            (prerequisite_id,),
        )
        connection.execute(
            """
            UPDATE component_repo.tasks
            SET status = 'succeeded', result = '{}', lease_owner = NULL,
                lease_expires_at = NULL, finished_at = now()
            WHERE id = %s
            """,
            (prerequisite_id,),
        )
        connection.execute(
            """
            INSERT INTO component_repo.tasks (
                id, owner_id, task_type, payload, locale, timezone, created_by, max_attempts
            ) VALUES (%s, %s, 'component.import.parse', %s, 'zh-CN', 'Asia/Shanghai', %s, 3)
            """,
            (parse_task_id, OWNER_ID, psycopg.types.json.Jsonb(payload), OWNER_ID),
        )
        connection.execute(
            """
            INSERT INTO component_repo.task_dependencies (task_id, prerequisite_task_id, owner_id)
            VALUES (%s, %s, %s)
            """,
            (parse_task_id, prerequisite_id, OWNER_ID),
        )
        connection.execute(
            """
            INSERT INTO component_repo.imports (
                id, owner_id, source_artifact_id, status, parser_version,
                locale, timezone, metadata, created_by, upload_session_id, parse_task_id
            ) VALUES (%s, %s, %s, 'queued', %s, 'zh-CN', 'Asia/Shanghai', '{}', %s, %s, %s)
            """,
            (import_id, OWNER_ID, artifact_id, PARSER_VERSION, OWNER_ID, upload_session_id, parse_task_id),
        )
    return import_id, parse_task_id


def _relation_input_hash(connection: psycopg.Connection, candidate_id: UUID) -> str:
    row = connection.execute(
        """
        SELECT candidate.structure_hash, candidate.geometry_hash,
               snapshot.schema_version, snapshot.parser_version,
               part_library.source_hash
        FROM component_repo.candidates candidate
        JOIN component_repo.scene_snapshots snapshot ON snapshot.id = candidate.scene_snapshot_id
        JOIN component_repo.imports import_job ON import_job.id = candidate.import_id
        JOIN component_repo.part_library_versions part_library
          ON part_library.id = import_job.part_library_version_id
        WHERE candidate.id = %s
        """,
        (candidate_id,),
    ).fetchone()
    digest = hashlib.sha256()
    values = (
        row["structure_hash"],
        row["geometry_hash"],
        row["schema_version"],
        row["parser_version"],
        row["source_hash"],
        "component-relation-detector-v1",
    )
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(f"{len(encoded)}:".encode("ascii"))
        digest.update(encoded)
    return digest.hexdigest()


def json_text(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
