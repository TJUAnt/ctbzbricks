"""Reusable LDraw submodel API routes."""

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas.submodel import (
    SubmodelCreateRequest,
    SubmodelListResponse,
    SubmodelResponse,
)
from src.services.model_asset_service import bounded_page, bounded_page_size
from src.services.submodel_service import (
    create_submodel,
    get_submodel,
    paginated_submodels,
)


def create_submodel_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(config["routes"]["submodels"], response_model=SubmodelResponse)
    def save_submodel(
        request_body: SubmodelCreateRequest,
        request: Request,
    ) -> dict:
        try:
            return create_submodel(
                request.app.state.db_engine,
                config,
                request_body.model_dump(),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error

    @router.get(config["routes"]["submodel"], response_model=SubmodelResponse)
    def submodel(submodel_id: str, request: Request) -> dict:
        saved_submodel = get_submodel(request.app.state.db_engine, submodel_id)
        if saved_submodel is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["submodel_not_found"],
            )
        return saved_submodel

    @router.get(config["routes"]["submodels"], response_model=SubmodelListResponse)
    def submodels(
        request: Request,
        page: int | None = Query(default=None),
        page_size: int | None = Query(default=None),
    ) -> dict:
        return paginated_submodels(
            request.app.state.db_engine,
            config,
            bounded_page(page, config["pagination"]["default_page"]),
            bounded_page_size(
                page_size,
                config["pagination"]["default_page_size"],
                config["pagination"]["max_page_size"],
            ),
        )

    return router
