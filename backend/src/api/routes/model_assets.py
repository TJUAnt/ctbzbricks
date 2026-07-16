"""3D model asset API routes."""

from pathlib import Path

from fastapi import APIRouter, Query, Request

from src.services.model_asset_service import (
    bounded_page,
    bounded_page_size,
    delete_model_asset,
    paginated_model_assets,
)


def create_model_asset_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.get(config["routes"]["model_assets"])
    def model_assets(
        request: Request,
        page: int | None = Query(default=None),
        page_size: int | None = Query(default=None),
    ) -> dict:
        asset_config = request.app.state.model_asset_config
        return paginated_model_assets(
            request.app.state.db_engine,
            bounded_page(page, asset_config["default_page"]),
            bounded_page_size(
                page_size,
                asset_config["default_page_size"],
                asset_config["max_page_size"],
            ),
        )

    @router.delete(config["routes"]["model_asset"])
    def delete_asset(asset_id: str, request: Request) -> dict:
        asset_path = delete_model_asset(request.app.state.db_engine, asset_id)
        if asset_path is None:
            return {"deleted": False}
        path = Path(asset_path)
        if path.exists():
            path.unlink()
        return {"deleted": True, "assetPath": asset_path}

    return router
