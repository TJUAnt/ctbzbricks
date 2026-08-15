"""Python Worker adapter for Go-owned ``component.import.parse`` tasks."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.component_repo.go_import_parser import ImportParseError, MaterializedImport, materialize_import
from src.component_repo.storage import ArtifactStorage, ArtifactStorageError, SupabaseArtifactStorage
from src.config.app_settings import load_json_config
from src.config.component_repo_config import REQUIRED_COMPONENT_REPO_CONFIG_KEYS
from src.config.db_config import ENV_FILE_PATH, read_env_file, resolve_env_file_path


LOGGER = logging.getLogger(__name__)
TASK_TYPE = "component.import.parse"
OUTBOX_TOPIC = "component.task.events"
DERIVED_NAMESPACE = UUID("f45f8cb9-337a-4d70-89e4-5020bdd0d9e5")
TASK_COLUMNS = """
id, owner_id, task_type, status, payload, result, result_artifact_id,
locale, timezone, created_by, attempts, max_attempts,
available_at, lease_owner, lease_expires_at, progress_code, progress_params,
progress_percent, error_code, error_params, created_at, started_at, finished_at,
cancel_requested_at, cancel_requested_by, updated_at, task_job_id,
execution_number, retry_of_task_id
""".strip()
TASK_COLUMNS_QUALIFIED = ", ".join(
    f"task.{column.strip()}" for column in TASK_COLUMNS.replace("\n", " ").split(",")
)
IMPORT_COLUMNS = """
id, owner_id, source_artifact_id, exchange_artifact_id, target_component_id,
base_version_id, status, parser_version, part_library_version_id, locale,
timezone, created_by, parse_task_id
""".strip()


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str
    worker_id: str
    poll_interval: float = 0.5
    lease_duration: float = 30.0
    heartbeat_interval: float = 10.0
    retry_delay: float = 5.0


class LeaseLost(RuntimeError):
    pass


class ComponentImportWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        storage: ArtifactStorage,
        component_config: dict[str, Any],
        connect: Callable[..., psycopg.Connection] = psycopg.connect,
        task_type: str = TASK_TYPE,
    ) -> None:
        if settings.heartbeat_interval * 2 >= settings.lease_duration:
            raise ValueError("heartbeat interval must be less than half the lease duration")
        self.settings = settings
        self.storage = storage
        self.config = component_config
        self.connect = connect
        self.task_type = task_type

    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                worked = self.run_once()
            except (psycopg.Error, ArtifactStorageError):
                LOGGER.exception("component import worker cycle failed", extra={"errorCode": "common.internal_error"})
                worked = False
            if not worked:
                stop.wait(self.settings.poll_interval)

    def run_once(self) -> bool:
        self._recover_expired()
        task = self._claim()
        if task is None:
            return False
        stopped = threading.Event()
        lease_lost = threading.Event()
        cancel_requested = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(task["id"], task["attempts"], stopped, lease_lost, cancel_requested),
            daemon=True,
        )
        heartbeat.start()
        try:
            import_row, source_artifact, parse_artifact = self._load_input(task)
            content = self.storage.read_bytes(parse_artifact["storage_key"])
            if hashlib.sha256(content).hexdigest() != parse_artifact["sha256"]:
                self._finish_failure(task, "component_repo.hash_mismatch", {"artifactId": str(parse_artifact["id"])}, False)
                return True
            result = materialize_import(
                content,
                parse_artifact["artifact_type"],
                parse_artifact["original_filename"],
                self.config,
            )
            derived = self._store_exchange(import_row, source_artifact, result)
            if lease_lost.is_set():
                raise LeaseLost()
            if cancel_requested.is_set():
                self._finish_cancelled(task)
                return True
            self._commit_success(task, import_row, source_artifact, result, derived)
        except LeaseLost:
            return True
        except ArtifactStorageError:
            self._finish_failure(
                task,
                "component_repo.storage_unavailable",
                {"importId": str(task["payload"]["importId"])},
                True,
            )
        except ImportParseError:
            self._finish_failure(
                task,
                "component_repo.import_parse_failed",
                {"importId": str(task["payload"]["importId"])},
                False,
            )
        except (KeyError, TypeError, ValueError, UnicodeError):
            self._finish_failure(
                task,
                "component_repo.import_parse_failed",
                {"importId": str(task["payload"].get("importId", ""))},
                False,
            )
        except psycopg.Error:
            self._finish_failure(task, "common.internal_error", {}, True)
        finally:
            stopped.set()
            heartbeat.join(timeout=self.settings.heartbeat_interval)
        return True

    def _connection(self) -> psycopg.Connection:
        return self.connect(self.settings.database_url, row_factory=dict_row)

    def _claim(self) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        lease_expires = now + timedelta(seconds=self.settings.lease_duration)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH candidate AS (
                    SELECT task.id
                    FROM component_repo.tasks task
                    WHERE task.status = 'queued'
                      AND task.task_type = %s
                      AND task.available_at <= %s
                      AND task.attempts < task.max_attempts
                      AND NOT EXISTS (
                          SELECT 1
                          FROM component_repo.task_dependencies dependency
                          JOIN component_repo.tasks prerequisite
                            ON prerequisite.id = dependency.prerequisite_task_id
                          WHERE dependency.task_id = task.id
                            AND prerequisite.status <> 'succeeded'
                      )
                    ORDER BY task.available_at, task.created_at, task.id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE component_repo.tasks task
                SET status = 'running', attempts = task.attempts + 1,
                    lease_owner = %s, lease_expires_at = %s,
                    started_at = COALESCE(task.started_at, %s),
                    error_code = NULL, error_params = NULL, updated_at = %s
                FROM candidate
                WHERE task.id = candidate.id
                RETURNING {TASK_COLUMNS_QUALIFIED}
                """,
                (self.task_type, now, self.settings.worker_id, lease_expires, now, now),
            )
            task = cursor.fetchone()
            if task is None:
                return None
            task["payload"] = dict(task["payload"])
            self._record_event(cursor, task, "running")
            return task

    def _load_input(self, task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        payload = task["payload"]
        if set(payload) != {"importId", "parserVersion", "snapshotSchema"}:
            raise ValueError("invalid parse payload")
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT import_job.id, import_job.owner_id, import_job.source_artifact_id,
                       import_job.exchange_artifact_id, import_job.target_component_id,
                       import_job.base_version_id, import_job.status, import_job.parser_version,
                       import_job.part_library_version_id, import_job.locale,
                       import_job.timezone, import_job.created_by, import_job.parse_task_id,
                       source_artifact.original_filename AS source_filename,
                       source_artifact.storage_provider AS source_storage_provider,
                       source_artifact.storage_bucket AS source_storage_bucket,
                       source_artifact.storage_key AS source_storage_key,
                       source_artifact.sha256 AS source_sha256,
                       source_artifact.artifact_type AS source_artifact_type,
                       source_artifact.verification_status AS source_verification_status,
                       source_artifact.immutable AS source_immutable,
                       parse_artifact.id AS parse_artifact_id,
                       parse_artifact.artifact_type AS parse_artifact_type,
                       parse_artifact.original_filename AS parse_filename,
                       parse_artifact.storage_key AS parse_storage_key,
                       parse_artifact.sha256 AS parse_sha256,
                       parse_artifact.verification_status AS parse_verification_status
                FROM component_repo.imports import_job
                JOIN component_repo.artifacts source_artifact
                  ON source_artifact.id = import_job.source_artifact_id
                 AND source_artifact.owner_id = import_job.owner_id
                JOIN component_repo.artifacts parse_artifact
                  ON parse_artifact.id = COALESCE(import_job.exchange_artifact_id, import_job.source_artifact_id)
                 AND parse_artifact.owner_id = import_job.owner_id
                WHERE import_job.id = %s AND import_job.owner_id = %s
                  AND import_job.parse_task_id = %s
                """,
                (payload["importId"], task["owner_id"], task["id"]),
            )
            row = cursor.fetchone()
        if (
            row is None
            or row["source_verification_status"] != "verified"
            or not row["source_immutable"]
            or row["parse_verification_status"] != "verified"
        ):
            raise ValueError("invalid import source")
        if row["parser_version"] != payload["parserVersion"]:
            raise ValueError("parser version mismatch")
        if payload["parserVersion"] != self.config["ldraw"]["parser_version"]:
            raise ValueError("worker parser version mismatch")
        source = {
            "id": row["source_artifact_id"],
            "original_filename": row["source_filename"],
            "storage_provider": row["source_storage_provider"],
            "storage_bucket": row["source_storage_bucket"],
            "storage_key": row["source_storage_key"],
            "sha256": row["source_sha256"],
            "artifact_type": row["source_artifact_type"],
        }
        parse = {
            "id": row["parse_artifact_id"],
            "artifact_type": row["parse_artifact_type"],
            "original_filename": row["parse_filename"],
            "storage_key": row["parse_storage_key"],
            "sha256": row["parse_sha256"],
        }
        return row, source, parse

    def _store_exchange(
        self,
        import_row: dict[str, Any],
        source: dict[str, Any],
        result: MaterializedImport,
    ) -> dict[str, Any] | None:
        if result.exchange_bytes is None or result.exchange_filename is None:
            return None
        artifact_id = uuid5(DERIVED_NAMESPACE, f"{import_row['id']}:studio-exchange")
        source_directory = source["storage_key"].rsplit("/", 1)[0]
        storage_key = f"{source_directory}/derived/{artifact_id}.ldr"
        try:
            self.storage.write_bytes(storage_key, result.exchange_bytes, "text/plain")
        except ArtifactStorageError:
            metadata = self.storage.head(storage_key)
            if metadata.content_length != len(result.exchange_bytes):
                raise
        return {
            "id": artifact_id,
            "original_filename": result.exchange_filename,
            "storage_key": storage_key,
            "sha256": hashlib.sha256(result.exchange_bytes).hexdigest(),
            "file_size": len(result.exchange_bytes),
        }

    def _commit_success(
        self,
        task: dict[str, Any],
        import_row: dict[str, Any],
        source: dict[str, Any],
        result: MaterializedImport,
        derived: dict[str, Any] | None,
    ) -> None:
        import_id = UUID(str(import_row["id"]))
        snapshot_id = uuid5(DERIVED_NAMESPACE, f"{import_id}:snapshot")
        candidate_id = uuid5(DERIVED_NAMESPACE, f"{import_id}:candidate")
        component_id = import_row["target_component_id"] or uuid5(DERIVED_NAMESPACE, f"{import_id}:component")
        version_id = uuid5(DERIVED_NAMESPACE, f"{import_id}:draft-version")
        now = datetime.now(timezone.utc)
        with self._connection() as connection, connection.cursor() as cursor:
            current_task = self._lock_owned_lease(cursor, task, now)
            cursor.execute(
                f"SELECT {IMPORT_COLUMNS} FROM component_repo.imports WHERE id = %s FOR UPDATE",
                (import_id,),
            )
            current_import = cursor.fetchone()
            if current_import is None:
                raise LeaseLost()
            cursor.execute("SELECT id FROM component_repo.candidates WHERE import_id = %s", (import_id,))
            existing = cursor.fetchone()
            if existing is not None:
                cursor.execute(
                    "SELECT id, component_id, scene_snapshot_id FROM component_repo.component_versions "
                    "WHERE component_candidate_id = %s AND deleted_at IS NULL",
                    (existing["id"],),
                )
                version = cursor.fetchone()
                if current_import["status"] != "succeeded" or version is None:
                    raise ValueError("partial import result")
                self._complete_task(cursor, current_task, current_import, existing["id"], version)
                return

            exchange_artifact_id = current_import["exchange_artifact_id"]
            if derived is not None:
                cursor.execute(
                    """
                    INSERT INTO component_repo.artifacts (
                        id, owner_id, artifact_type, source_kind, original_filename,
                        storage_provider, storage_bucket, storage_key, sha256, file_size,
                        mime_type, immutable, verification_status, verified_at, uploaded_by,
                        metadata, derived_from_artifact_id
                    ) VALUES (
                        %s, %s, 'ldraw_ldr', 'derived', %s, %s, %s, %s, %s, %s,
                        'text/plain', true, 'verified', %s, %s, %s, %s
                    ) ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        derived["id"], current_import["owner_id"], derived["original_filename"],
                        source["storage_provider"], source["storage_bucket"], derived["storage_key"],
                        derived["sha256"], derived["file_size"], now, current_import["created_by"],
                        Jsonb({"derivedBy": self.task_type, "parserVersion": current_import["parser_version"]}),
                        source["id"],
                    ),
                )
                exchange_artifact_id = derived["id"]

            if current_import["target_component_id"] is None:
                component_name = Path(source["original_filename"]).stem.strip() or source["original_filename"]
                cursor.execute(
                    """
                    INSERT INTO component_repo.components (
                        id, owner_id, content_kind, content_locale, name, status,
                        metadata, created_by, created_at, updated_at
                    ) VALUES (%s, %s, 'user', %s, %s, 'draft', '{}', %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (component_id, current_import["owner_id"], current_import["locale"], component_name,
                     current_import["created_by"], now, now),
                )

            cursor.execute(
                """
                UPDATE component_repo.imports
                SET target_component_id = %s, exchange_artifact_id = %s,
                    status = 'succeeded', failure_code = NULL, failure_params = NULL,
                    completed_at = %s
                WHERE id = %s AND status = 'running'
                """,
                (component_id, exchange_artifact_id, now, import_id),
            )
            if cursor.rowcount != 1:
                raise LeaseLost()
            cursor.execute(
                """
                INSERT INTO component_repo.scene_snapshots (
                    id, import_id, schema_version, parser_version, root_model_id,
                    document, bom, parse_issues, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (snapshot_id, import_id, task["payload"]["snapshotSchema"], current_import["parser_version"],
                 result.root_model_id, Jsonb(result.document), Jsonb(result.bom), Jsonb(result.parse_issues), now),
            )
            decisions = {"componentId": str(component_id), "draftVersionId": str(version_id)}
            cursor.execute(
                """
                INSERT INTO component_repo.candidates (
                    id, owner_id, import_id, scene_snapshot_id, status, summary,
                    review_decisions, interface_signature, structure_hash, geometry_hash,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, %s, 'pending_review', %s, %s, %s, %s, %s, %s, %s)
                """,
                (candidate_id, current_import["owner_id"], import_id, snapshot_id,
                 Jsonb(result.summary), Jsonb(decisions), result.interface_signature,
                 result.structure_hash, result.geometry_hash, now, now),
            )
            version_label, revision = self._draft_identity(cursor, current_import, component_id)
            cursor.execute(
                """
                INSERT INTO component_repo.component_versions (
                    id, component_id, component_candidate_id, version_label, revision, status,
                    source_artifact_id, exchange_artifact_id, scene_snapshot_id, parser_version,
                    part_library_version_id, interface_signature, structure_hash, geometry_hash,
                    metadata, created_by, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (version_id, component_id, candidate_id, version_label, revision,
                 current_import["source_artifact_id"], exchange_artifact_id, snapshot_id,
                 current_import["parser_version"], current_import["part_library_version_id"],
                 result.interface_signature, result.structure_hash, result.geometry_hash,
                 Jsonb({"summary": result.summary, "baseVersionId": _uuid_text(current_import["base_version_id"])}),
                 current_import["created_by"], now),
            )
            version = {"id": version_id, "component_id": component_id, "scene_snapshot_id": snapshot_id}
            self._complete_task(cursor, current_task, current_import, candidate_id, version)

    def _draft_identity(self, cursor: psycopg.Cursor, import_row: dict[str, Any], component_id: UUID) -> tuple[str, int]:
        base_id = import_row["base_version_id"]
        if base_id is not None:
            cursor.execute(
                "SELECT version_label FROM component_repo.component_versions "
                "WHERE id = %s AND component_id = %s AND deleted_at IS NULL",
                (base_id, component_id),
            )
            base = cursor.fetchone()
            if base is None:
                raise ValueError("invalid base version")
            label = base["version_label"]
        else:
            label = "0.1.0"
        cursor.execute(
            "SELECT COALESCE(max(revision), 0) + 1 AS revision "
            "FROM component_repo.component_versions WHERE component_id = %s AND version_label = %s",
            (component_id, label),
        )
        return label, int(cursor.fetchone()["revision"])

    def _complete_task(
        self,
        cursor: psycopg.Cursor,
        task: dict[str, Any],
        import_row: dict[str, Any],
        candidate_id: UUID,
        version: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc)
        result = {
            "importId": str(import_row["id"]),
            "candidateId": str(candidate_id),
            "componentId": str(version["component_id"]),
            "draftVersionId": str(version["id"]),
            "sceneSnapshotId": str(version["scene_snapshot_id"]),
        }
        cursor.execute(
            f"""
            UPDATE component_repo.tasks
            SET status = 'succeeded', result = %s, lease_owner = NULL,
                lease_expires_at = NULL, progress_percent = 100,
                error_code = NULL, error_params = NULL,
                finished_at = %s, updated_at = %s
            WHERE id = %s AND status = 'running' AND lease_owner = %s
              AND attempts = %s AND lease_expires_at > %s AND cancel_requested_at IS NULL
            RETURNING {TASK_COLUMNS}
            """,
            (Jsonb(result), now, now, task["id"], self.settings.worker_id, task["attempts"], now),
        )
        completed = cursor.fetchone()
        if completed is None:
            raise LeaseLost()
        self._record_event(cursor, completed, "succeeded", percent=100.0)

    def _finish_failure(
        self,
        task: dict[str, Any],
        code: str,
        params: dict[str, Any],
        retryable: bool,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._connection() as connection, connection.cursor() as cursor:
            current = self._lock_owned_lease(cursor, task, now)
            if retryable and current["attempts"] < current["max_attempts"]:
                status = "queued"
                event_status = "retrying"
                available_at = now + timedelta(seconds=self.settings.retry_delay)
                finished_at = None
            else:
                status = "failed"
                event_status = "failed"
                available_at = current["available_at"]
                finished_at = now
            cursor.execute(
                f"""
                UPDATE component_repo.tasks
                SET status = %s, available_at = %s, lease_owner = NULL,
                    lease_expires_at = NULL, progress_code = NULL,
                    progress_params = NULL, progress_percent = NULL,
                    error_code = %s, error_params = %s, finished_at = %s, updated_at = %s
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                  AND attempts = %s AND lease_expires_at > %s AND cancel_requested_at IS NULL
                RETURNING {TASK_COLUMNS}
                """,
                (status, available_at, code, Jsonb(params), finished_at, now,
                 task["id"], self.settings.worker_id, task["attempts"], now),
            )
            updated = cursor.fetchone()
            if updated is None:
                raise LeaseLost()
            self._record_event(cursor, updated, event_status, code, params)

    def _finish_cancelled(self, task: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE component_repo.tasks
                SET status = 'cancelled', lease_owner = NULL, lease_expires_at = NULL,
                    finished_at = %s, updated_at = %s
                WHERE id = %s AND status = 'running' AND lease_owner = %s
                  AND attempts = %s AND lease_expires_at > %s
                  AND cancel_requested_at IS NOT NULL
                RETURNING {TASK_COLUMNS}
                """,
                (now, now, task["id"], self.settings.worker_id, task["attempts"], now),
            )
            updated = cursor.fetchone()
            if updated is not None:
                self._record_event(cursor, updated, "cancelled")

    def _lock_owned_lease(self, cursor: psycopg.Cursor, task: dict[str, Any], now: datetime) -> dict[str, Any]:
        cursor.execute(
            f"SELECT {TASK_COLUMNS} FROM component_repo.tasks WHERE id = %s AND status = 'running' "
            "AND lease_owner = %s AND attempts = %s AND lease_expires_at > %s FOR UPDATE",
            (task["id"], self.settings.worker_id, task["attempts"], now),
        )
        current = cursor.fetchone()
        if current is None:
            raise LeaseLost()
        return current

    def _heartbeat_loop(
        self,
        task_id: UUID,
        claimed_attempt: int,
        stopped: threading.Event,
        lease_lost: threading.Event,
        cancel_requested: threading.Event,
    ) -> None:
        while not stopped.wait(self.settings.heartbeat_interval):
            now = datetime.now(timezone.utc)
            try:
                with self._connection() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE component_repo.tasks
                        SET lease_expires_at = %s, updated_at = %s
                        WHERE id = %s AND status = 'running' AND lease_owner = %s
                          AND attempts = %s AND lease_expires_at > %s
                        RETURNING cancel_requested_at
                        """,
                        (now + timedelta(seconds=self.settings.lease_duration), now,
                         task_id, self.settings.worker_id, claimed_attempt, now),
                    )
                    row = cursor.fetchone()
                if row is None:
                    lease_lost.set()
                    return
                if row["cancel_requested_at"] is not None:
                    cancel_requested.set()
                    return
            except psycopg.Error:
                lease_lost.set()
                return

    def _recover_expired(self) -> None:
        now = datetime.now(timezone.utc)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH candidate AS (
                    SELECT id FROM component_repo.tasks
                    WHERE task_type = %s AND status = 'running' AND lease_expires_at <= %s
                    ORDER BY lease_expires_at, id FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE component_repo.tasks task
                SET status = CASE
                        WHEN task.cancel_requested_at IS NOT NULL THEN 'cancelled'
                        WHEN task.attempts < task.max_attempts THEN 'queued'
                        ELSE 'failed' END,
                    available_at = CASE WHEN task.cancel_requested_at IS NULL
                        AND task.attempts < task.max_attempts THEN %s ELSE task.available_at END,
                    lease_owner = NULL, lease_expires_at = NULL,
                    error_code = CASE WHEN task.cancel_requested_at IS NULL
                        AND task.attempts >= task.max_attempts THEN 'common.internal_error'
                        ELSE task.error_code END,
                    error_params = CASE WHEN task.cancel_requested_at IS NULL
                        AND task.attempts >= task.max_attempts THEN '{{}}'::jsonb
                        ELSE task.error_params END,
                    finished_at = CASE WHEN task.cancel_requested_at IS NOT NULL
                        OR task.attempts >= task.max_attempts THEN %s ELSE NULL END,
                    updated_at = %s
                FROM candidate WHERE task.id = candidate.id RETURNING {TASK_COLUMNS_QUALIFIED}
                """,
                (self.task_type, now, now, now, now),
            )
            recovered = cursor.fetchone()
            if recovered is not None:
                event_status = "retrying" if recovered["status"] == "queued" else recovered["status"]
                self._record_event(
                    cursor,
                    recovered,
                    event_status,
                    recovered["error_code"],
                    recovered["error_params"],
                )

    def _record_event(
        self,
        cursor: psycopg.Cursor,
        task: dict[str, Any],
        event_status: str,
        code: str | None = None,
        params: dict[str, Any] | None = None,
        percent: float | None = None,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO component_repo.task_events (task_id, status, code, params, progress_percent)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (task["id"], event_status, code, Jsonb(params) if code is not None else None, percent),
        )
        event = cursor.fetchone()
        payload = {
            "eventId": event["id"],
            "taskId": str(task["id"]),
            "ownerId": str(task["owner_id"]),
            "taskType": task["task_type"],
            "taskStatus": task["status"],
            "eventStatus": event_status,
            "taskJobId": str(task["task_job_id"]),
            "executionNumber": task["execution_number"],
            "attempt": task["attempts"],
            "code": code,
            "params": params or {},
        }
        cursor.execute(
            """
            INSERT INTO component_repo.outbox_events (
                id, aggregate_type, aggregate_id, topic, event_key, payload,
                max_attempts, available_at
            ) VALUES (%s, 'task', %s, %s, %s, %s, 10, %s)
            ON CONFLICT (topic, event_key) DO NOTHING
            """,
            (uuid4(), task["id"], OUTBOX_TOPIC, f"{task['id']}:{event['id']}", Jsonb(payload), event["created_at"]),
        )


def settings_from_environment() -> WorkerSettings:
    env_file = read_env_file(resolve_env_file_path(ENV_FILE_PATH))
    database_url = os.environ.get("DATABASE_URL", env_file.get("DATABASE_URL", "")).strip()
    if database_url.startswith("postgresql+psycopg://"):
        database_url = "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must be PostgreSQL for the component import worker")
    worker_id = os.environ.get("PYTHON_COMPONENT_WORKER_ID", "").strip()
    if not worker_id:
        worker_id = f"{socket.gethostname()}-{os.getpid()}-component-parser"
    return WorkerSettings(
        database_url=database_url,
        worker_id=worker_id,
        poll_interval=_positive_float("WORKER_POLL_INTERVAL_SECONDS", 0.5),
        lease_duration=_positive_float("WORKER_LEASE_DURATION_SECONDS", 30.0),
        heartbeat_interval=_positive_float("WORKER_HEARTBEAT_INTERVAL_SECONDS", 10.0),
        retry_delay=_positive_float("WORKER_RETRY_DELAY_SECONDS", 5.0),
    )


def storage_from_environment(config: dict[str, Any]) -> ArtifactStorage:
    env_file = read_env_file(resolve_env_file_path(ENV_FILE_PATH))
    supabase_url = os.environ.get("SUPABASE_URL", env_file.get("SUPABASE_URL", "")).strip()
    service_key = os.environ.get(
        "SUPABASE_STORAGE_SERVICE_ROLE_KEY",
        env_file.get("SUPABASE_STORAGE_SERVICE_ROLE_KEY", ""),
    ).strip()
    if not service_key:
        service_key = os.environ.get(
            "SUPABASE_SECRET_KEY",
            env_file.get("SUPABASE_SECRET_KEY", ""),
        ).strip()
    bucket = os.environ.get("STORAGE_BUCKET", config["storage"]["bucket"]).strip()
    if not supabase_url or not service_key:
        raise RuntimeError("Supabase server-side storage configuration is required")
    if service_key.startswith("sb_publishable_"):
        raise RuntimeError("Supabase server-side storage key must not be publishable")
    return SupabaseArtifactStorage(
        supabase_url=supabase_url,
        api_key=service_key,
        bucket=bucket,
        authorization_token=service_key,
    )


def build_worker() -> ComponentImportWorker:
    config = load_json_config("component_repo.json", REQUIRED_COMPONENT_REPO_CONFIG_KEYS)
    return ComponentImportWorker(settings_from_environment(), storage_from_environment(config), config)


def _positive_float(key: str, default: float) -> float:
    value = float(os.environ.get(key, default))
    if value <= 0:
        raise RuntimeError(f"{key} must be positive")
    return value


def _uuid_text(value: UUID | None) -> str | None:
    return str(value) if value is not None else None
