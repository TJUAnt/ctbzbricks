"""Fitting candidate recall API routes."""

from fastapi import APIRouter, Request

from src.api.errors import domain_error_from_exception
from src.api.schemas.fitting_candidate_recall import (
    FittingCandidateRecallRequest,
    FittingCandidateRecallResponse,
)
from src.services.fitting_candidate_recall_service import recall_fitting_candidates


def create_fitting_candidate_recall_router(
    config: dict,
    component_config: dict | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        config["routes"]["recall"],
        response_model=FittingCandidateRecallResponse,
    )
    def recall(
        request_body: FittingCandidateRecallRequest,
        request: Request,
    ) -> FittingCandidateRecallResponse:
        try:
            return recall_fitting_candidates(
                request.app.state.db_engine,
                config,
                request_body,
                component_config,
                include_images=True,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "fitting_candidate_recall.failed",
                http_status=config["http_status"]["bad_request"],
            ) from error

    return router
