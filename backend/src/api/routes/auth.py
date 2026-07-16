"""Auth API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.auth.current_user import CurrentUser, optional_current_user


def create_auth_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/me")
    def me(current_user: CurrentUser | None = Depends(optional_current_user)) -> dict:
        if current_user is None:
            return {"authenticated": False, "user": None}
        return {
            "authenticated": True,
            "user": {
                "id": current_user.user_id,
                "email": current_user.email,
                "role": current_user.role,
            },
        }

    return router
