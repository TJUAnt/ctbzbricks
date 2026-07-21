"""Supabase Auth current-user helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Request

from src.api.errors import DomainError

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
        raise DomainError("auth.authorization_header_invalid", http_status=401)
    return verify_supabase_user(token.strip())


def audit_identity(config: dict[str, Any], current_user: CurrentUser | None) -> str:
    """Return a compact value for created_by/uploaded_by style audit fields."""

    if current_user is None:
        return config["audit"]["system_user"]
    return f"auth:{current_user.user_id}"


def require_current_user(current_user: CurrentUser | None) -> CurrentUser:
    if current_user is None:
        raise DomainError("auth.authentication_required", http_status=401)
    return current_user


def require_component_repo_auth_if_configured(current_user: CurrentUser | None) -> None:
    if truthy_env_value("REQUIRE_AUTH_FOR_COMPONENT_REPO") and current_user is None:
        raise DomainError("auth.component_repo_authentication_required", http_status=401)


def verify_supabase_user(access_token: str) -> CurrentUser:
    """Verify a Supabase access token through the Supabase Auth user endpoint."""

    supabase_url = env_value("SUPABASE_URL")
    api_key = first_env_value(SUPABASE_AUTH_KEY_ENV_KEYS)
    if not supabase_url or not api_key:
        raise DomainError("auth.verification_not_configured", http_status=401)
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
        raise DomainError("auth.session_verification_unavailable", http_status=401) from error

    if response.status_code in (401, 403):
        raise DomainError("auth.session_invalid", http_status=401)
    if response.status_code >= 400:
        raise DomainError(
            "auth.session_verification_failed",
            params={"status": response.status_code},
            http_status=401,
        )

    payload = response.json()
    user_id = payload.get("id") or payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise DomainError("auth.user_payload_invalid", http_status=401)
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


def truthy_env_value(key: str) -> bool:
    return env_value(key).lower() in ("1", "true", "yes", "on")


def env_values() -> dict[str, str]:
    env_file = resolve_env_file_path(ENV_FILE_PATH)
    return {
        **read_env_file(env_file),
        **{key: value for key, value in os.environ.items()},
    }
