"""Supabase Auth current-user helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request

from src.config.db_config import ENV_FILE_PATH, read_env_file, resolve_env_file_path


SUPABASE_AUTH_KEY_ENV_KEYS = (
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_ANON_KEY",
)


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated Supabase user identity."""

    user_id: str
    email: str | None
    role: str | None
    access_token: str
    raw: dict[str, Any]


def optional_current_user(request: Request) -> CurrentUser | None:
    """Return the Supabase user when a Bearer token is supplied.

    Existing local/dev flows remain usable without an Authorization header; mutating
    services then fall back to the configured system audit actor.
    """

    authorization = request.headers.get("Authorization", "").strip()
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return verify_supabase_user(token.strip())


def audit_identity(config: dict[str, Any], current_user: CurrentUser | None) -> str:
    """Return a compact value for created_by/uploaded_by style audit fields."""

    if current_user is None:
        return config["audit"]["system_user"]
    return f"auth:{current_user.user_id}"


def verify_supabase_user(access_token: str) -> CurrentUser:
    """Verify a Supabase access token through the Supabase Auth user endpoint."""

    supabase_url = env_value("SUPABASE_URL")
    api_key = first_env_value(SUPABASE_AUTH_KEY_ENV_KEYS)
    if not supabase_url or not api_key:
        raise HTTPException(
            status_code=401,
            detail="Supabase auth verification is not configured on the backend",
        )
    try:
        response = httpx.get(
            f"{supabase_url.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=10,
        )
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=401,
            detail="Unable to verify Supabase session",
        ) from error

    if response.status_code in (401, 403):
        raise HTTPException(status_code=401, detail="Invalid Supabase session")
    if response.status_code >= 400:
        raise HTTPException(
            status_code=401,
            detail=f"Supabase auth verification failed with HTTP {response.status_code}",
        )

    payload = response.json()
    user_id = payload.get("id") or payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid Supabase user payload")
    email = payload.get("email")
    role = payload.get("role")
    return CurrentUser(
        user_id=user_id,
        email=email if isinstance(email, str) else None,
        role=role if isinstance(role, str) else None,
        access_token=access_token,
        raw=payload,
    )


def env_value(key: str) -> str:
    return env_values().get(key, "").strip()


def first_env_value(keys: tuple[str, ...]) -> str:
    values = env_values()
    for key in keys:
        value = values.get(key, "").strip()
        if value:
            return value
    return ""


def env_values() -> dict[str, str]:
    env_file = resolve_env_file_path(ENV_FILE_PATH)
    return {
        **read_env_file(env_file),
        **{key: value for key, value in os.environ.items()},
    }
