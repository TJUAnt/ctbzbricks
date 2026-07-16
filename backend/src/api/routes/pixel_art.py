"""Pixel art API routes."""

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError

from src.api.schemas.pixel_art import (
    PixelArtGenerateSettings,
    PixelArtProjectListResponse,
    PixelArtPixelsUpdateRequest,
    PixelArtProjectResponse,
)
from src.pixel_art.quantization import create_pixel_art_asset
from src.services.pixel_art_service import (
    load_pixel_art_project,
    bounded_page,
    bounded_page_size,
    paginated_pixel_art_projects,
    save_pixel_art_project,
    update_pixel_art_project_pixels,
)


def create_pixel_art_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.get(config["routes"]["projects"], response_model=PixelArtProjectListResponse)
    def pixel_art_projects(
        request: Request,
        page: int | None = Query(default=None),
        page_size: int | None = Query(default=None),
    ) -> dict:
        return paginated_pixel_art_projects(
            request.app.state.db_engine,
            config,
            bounded_page(page, config["storage"]["default_page"]),
            bounded_page_size(
                page_size,
                config["storage"]["default_page_size"],
                config["storage"]["max_page_size"],
            ),
        )

    @router.post(config["routes"]["projects"], response_model=PixelArtProjectResponse)
    async def save_pixel_art_project_route(
        request: Request,
        name: str = Form(...),
        settings: str = Form(...),
        image: UploadFile = File(...),
    ) -> dict:
        try:
            generation_settings = PixelArtGenerateSettings.model_validate_json(settings)
        except ValidationError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=config["errors"]["invalid_settings"],
            ) from error
        image_bytes = await image.read()
        try:
            asset = create_pixel_art_asset(
                config,
                image_bytes,
                image.filename,
                image.content_type,
                generation_settings,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error
        return save_pixel_art_project(
            request.app.state.db_engine,
            config,
            name,
            image_bytes,
            asset,
        )

    @router.get(config["routes"]["project"], response_model=PixelArtProjectResponse)
    def pixel_art_project(project_id: str, request: Request) -> dict:
        project = load_pixel_art_project(request.app.state.db_engine, config, project_id)
        if project is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["project_not_found"],
            )
        return project

    @router.put(config["routes"]["project_pixels"], response_model=PixelArtProjectResponse)
    def update_pixel_art_pixels(
        project_id: str,
        request_body: PixelArtPixelsUpdateRequest,
        request: Request,
    ) -> dict:
        project = update_pixel_art_project_pixels(
            request.app.state.db_engine,
            config,
            project_id,
            request_body.palette,
            request_body.pixels,
        )
        if project is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["project_not_found"],
            )
        return project

    return router
