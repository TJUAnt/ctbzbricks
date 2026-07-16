"""Artifact storage providers for Component Repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from src.config.db_config import ENV_FILE_PATH, read_env_file, resolve_env_file_path


class ArtifactStorage(Protocol):
    """Storage interface used by Component Repo services."""

    provider: str
    bucket: str

    def write_bytes(self, storage_key: str, content: bytes, content_type: str) -> str:
        """Persist bytes and return a stable storage URI."""

    def read_bytes(self, storage_key: str) -> bytes:
        """Read bytes from storage."""


class ArtifactStorageError(RuntimeError):
    """Raised when an artifact storage provider rejects an operation."""


@dataclass
class LocalArtifactStorage:
    """Filesystem storage used by tests and offline development."""

    root_path: Path
    bucket: str
    provider: str = "local"

    def write_bytes(self, storage_key: str, content: bytes, content_type: str) -> str:
        target_path = self._target_path(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        return f"local://{self.bucket}/{storage_key}"

    def read_bytes(self, storage_key: str) -> bytes:
        return self._target_path(storage_key).read_bytes()

    def _target_path(self, storage_key: str) -> Path:
        clean_parts = [part for part in storage_key.split("/") if part not in ("", ".", "..")]
        return self.root_path.joinpath(*clean_parts)


@dataclass
class SupabaseArtifactStorage:
    """Supabase Storage provider backed by the Storage REST API."""

    supabase_url: str
    api_key: str
    bucket: str
    provider: str = "supabase"
    authorization_token: str | None = None

    def write_bytes(self, storage_key: str, content: bytes, content_type: str) -> str:
        response = httpx.post(
            self._object_url(storage_key),
            content=content,
            headers={
                **self._auth_headers(),
                "Content-Type": content_type,
                "x-upsert": "false",
            },
            timeout=30,
        )
        raise_for_storage_status("upload", self.bucket, storage_key, response)
        return f"supabase://{self.bucket}/{storage_key}"

    def read_bytes(self, storage_key: str) -> bytes:
        response = httpx.get(
            self._object_url(storage_key),
            headers=self._auth_headers(),
            timeout=30,
        )
        raise_for_storage_status("download", self.bucket, storage_key, response)
        return response.content

    def _object_url(self, storage_key: str) -> str:
        base_url = self.supabase_url.rstrip("/")
        return f"{base_url}/storage/v1/object/{self.bucket}/{storage_key}"

    def with_authorization_token(self, authorization_token: str | None) -> "SupabaseArtifactStorage":
        return SupabaseArtifactStorage(
            supabase_url=self.supabase_url,
            api_key=self.api_key,
            bucket=self.bucket,
            provider=self.provider,
            authorization_token=authorization_token,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.authorization_token or self.api_key}",
        }


def storage_from_config(config: dict, backend_root: Path) -> ArtifactStorage:
    """Build the configured storage provider."""
    storage_config = config["storage"]
    env_values = read_env_file(resolve_env_file_path(ENV_FILE_PATH))
    provider = env_value(
        "COMPONENT_REPO_STORAGE_PROVIDER",
        env_values,
        storage_config["default_provider"],
    )
    if provider == storage_config["local_provider"]:
        return LocalArtifactStorage(
            root_path=backend_root.parent / storage_config["local_root_path"],
            bucket=storage_config["bucket"],
            provider=storage_config["local_provider"],
        )
    if provider == storage_config["supabase_provider"]:
        supabase_url = env_value(storage_config["supabase_url_env"], env_values)
        service_key = env_value(storage_config["supabase_storage_key_env"], env_values)
        if not service_key:
            service_key = first_env_value(
                storage_config.get("supabase_legacy_key_envs", []),
                env_values,
            )
        if not supabase_url or not service_key:
            raise RuntimeError(config["errors"]["missing_supabase_config"])
        return SupabaseArtifactStorage(
            supabase_url=supabase_url,
            api_key=service_key,
            bucket=storage_config["bucket"],
            provider=storage_config["supabase_provider"],
        )
    raise RuntimeError(f"Unknown Component Repo storage provider: {provider}")


def env_value(key: str, env_values: dict[str, str], default: str = "") -> str:
    return os.environ.get(key, env_values.get(key, default)).strip()


def first_env_value(keys: list[str], env_values: dict[str, str]) -> str:
    for key in keys:
        value = env_value(key, env_values)
        if value:
            return value
    return ""


def raise_for_storage_status(
    operation: str,
    bucket: str,
    storage_key: str,
    response: httpx.Response,
) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        body = response.text.strip()
        detail = (
            f"Supabase Storage {operation} failed "
            f"with HTTP {response.status_code} for bucket={bucket}, key={storage_key}"
        )
        if body:
            detail = f"{detail}: {body}"
        raise ArtifactStorageError(detail) from error
