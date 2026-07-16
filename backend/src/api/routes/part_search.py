"""Part search API routes."""
from fastapi import APIRouter, Request

from src.api.schemas.part_search import PartSearchRequest, PartSearchResponse
from src.services.part_search_service import search_parts


def create_part_search_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(config["routes"]["search"], response_model=PartSearchResponse)
    def search(request_body: PartSearchRequest, request: Request) -> PartSearchResponse:
        return search_parts(
            request_body,
            request.app.state.db_engine,
            request.app.state.search_api_config,
        )

    return router
