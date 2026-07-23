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

    def head(self, storage_key: str) -> "ArtifactObjectMetadata":
        """Read object metadata without downloading the object body."""

    def create_download_url(self, storage_key: str, expires_in: int) -> str | None:
        """Return a direct temporary download URL when supported."""


class ArtifactStorageError(RuntimeError):
    """Raised when an artifact storage provider rejects an operation."""


@dataclass(frozen=True)
class ArtifactObjectMetadata:
    """Storage metadata available without reading an object's body."""

    content_length: int
    content_type: str | None = None
    etag: str | None = None


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
        try:
            return self._target_path(storage_key).read_bytes()
        except OSError as error:
            raise ArtifactStorageError(
                f"Local artifact download failed for bucket={self.bucket}, key={storage_key}"
            ) from error

    def head(self, storage_key: str) -> ArtifactObjectMetadata:
        try:
            target_path = self._target_path(storage_key)
            return ArtifactObjectMetadata(content_length=target_path.stat().st_size)
        except OSError as error:
            raise ArtifactStorageError(
                f"Local artifact head failed for bucket={self.bucket}, key={storage_key}"
            ) from error

    def create_download_url(self, storage_key: str, expires_in: int) -> str | None:
        del storage_key, expires_in
        return None

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

    def head(self, storage_key: str) -> ArtifactObjectMetadata:
        # Supabase's ordinary object URL rejects HTTP HEAD. Its object-info endpoint
        # provides the same metadata-only semantics without transferring the body.
        response = httpx.get(
            self._info_url(storage_key),
            headers=self._auth_headers(),
            timeout=30,
        )
        raise_for_storage_status("head", self.bucket, storage_key, response)
        payload = response.json()
        content_length = payload.get("size")
        if content_length is None and isinstance(payload.get("metadata"), dict):
            content_length = payload["metadata"].get("size")
        if content_length is None:
            raise ArtifactStorageError(
                f"Supabase Storage head response omitted object size for "
                f"bucket={self.bucket}, key={storage_key}"
            )
        return ArtifactObjectMetadata(
            content_length=int(content_length),
            content_type=payload.get("content_type") or payload.get("contentType"),
            etag=payload.get("etag"),
        )

    def create_download_url(self, storage_key: str, expires_in: int) -> str | None:
        response = httpx.post(
            self._sign_url(storage_key),
            json={"expiresIn": expires_in},
            headers=self._auth_headers(),
            timeout=30,
        )
        raise_for_storage_status("sign", self.bucket, storage_key, response)
        payload = response.json()
        signed_url = payload.get("signedURL") or payload.get("signedUrl")
        if not isinstance(signed_url, str) or not signed_url:
            raise ArtifactStorageError(
                f"Supabase Storage sign response omitted signed URL for "
                f"bucket={self.bucket}, key={storage_key}"
            )
        if signed_url.startswith("http://") or signed_url.startswith("https://"):
            return signed_url
        base_url = self.supabase_url.rstrip("/")
        if signed_url.startswith("/storage/v1/"):
            return f"{base_url}{signed_url}"
        return f"{base_url}/storage/v1/{signed_url.lstrip('/')}"

    def _object_url(self, storage_key: str) -> str:
        base_url = self.supabase_url.rstrip("/")
        return f"{base_url}/storage/v1/object/{self.bucket}/{storage_key}"

    def _sign_url(self, storage_key: str) -> str:
        base_url = self.supabase_url.rstrip("/")
        return f"{base_url}/storage/v1/object/sign/{self.bucket}/{storage_key}"

    def _info_url(self, storage_key: str) -> str:
        base_url = self.supabase_url.rstrip("/")
        return f"{base_url}/storage/v1/object/info/{self.bucket}/{storage_key}"

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
        api_key = env_value(storage_config["supabase_storage_key_env"], env_values)
        if not api_key:
            api_key = first_env_value(
                storage_config.get("supabase_legacy_key_envs", []),
                env_values,
            )
        if not supabase_url or not api_key:
            raise RuntimeError(config["errors"]["missing_supabase_config"])
        return SupabaseArtifactStorage(
            supabase_url=supabase_url,
            api_key=api_key,
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
