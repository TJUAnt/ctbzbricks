"""LEGO heightmap model API routes."""

from fastapi import APIRouter, Request

from src.api.errors import domain_error_from_exception
from src.api.schemas.lego_heightmap import LegoHeightmapFromDemRequest, LegoHeightmapSaveRequest
from src.lego.heightmap_asset_helper import load_heightmap_asset, save_heightmap_asset
from src.services.lego_heightmap_generation_service import create_colored_heightmap_asset
from src.services.model_asset_service import save_lego_heightmap_model_asset
from src.terrain.dem_asset_helper import load_model_asset


def create_lego_heightmap_router(
    api_config: dict,
    terrain_config: dict,
    heightmap_config: dict,
) -> APIRouter:
    router = APIRouter()

    @router.post(api_config["routes"]["lego_heightmap_models"])
    def save_lego_heightmap_model(request_body: LegoHeightmapSaveRequest, request: Request) -> dict:
        model = save_heightmap_asset(heightmap_config, request_body.asset, request_body.name)
        save_lego_heightmap_model_asset(
            request.app.state.db_engine,
            request.app.state.model_asset_config,
            heightmap_config,
            request_body.asset,
            model,
            request_body.contentLocale,
        )
        return model

    @router.post(api_config["routes"]["lego_heightmap_from_dem"])
    def create_lego_heightmap_from_dem(
        request_body: LegoHeightmapFromDemRequest,
        request: Request,
    ) -> dict:
        try:
            dem_asset = load_model_asset(terrain_config, request_body.modelId)
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "terrain.model_not_found",
                params={"modelId": request_body.modelId},
                http_status=terrain_config["http_status"]["not_found"],
            ) from error
        try:
            heightmap_asset = create_colored_heightmap_asset(
                dem_asset,
                request_body.modelId,
                request_body.scale.model_dump(),
                terrain_config,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "lego_heightmap.generation_failed",
                params={"modelId": request_body.modelId},
                http_status=terrain_config["http_status"]["bad_request"],
            ) from error
        model = save_heightmap_asset(heightmap_config, heightmap_asset, request_body.name)
        save_lego_heightmap_model_asset(
            request.app.state.db_engine,
            request.app.state.model_asset_config,
            heightmap_config,
            heightmap_asset,
            model,
            request_body.contentLocale,
        )
        return model

    @router.get(api_config["routes"]["lego_heightmap_model"])
    def lego_heightmap_model(model_id: str) -> dict:
        try:
            return load_heightmap_asset(heightmap_config, model_id)
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "lego_heightmap.model_not_found",
                params={"modelId": model_id},
                http_status=terrain_config["http_status"]["not_found"],
            ) from error

    return router
