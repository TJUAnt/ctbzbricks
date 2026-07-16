"""Fitting candidate recall API routes."""

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas.fitting_candidate_recall import (
    FittingCandidateRecallRequest,
    FittingCandidateRecallResponse,
)
from src.services.fitting_candidate_recall_service import recall_fitting_candidates


def create_fitting_candidate_recall_router(config: dict) -> APIRouter:
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
            )
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error

    return router
