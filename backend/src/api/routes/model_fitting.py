"""Model fitting job API routes."""

from fastapi import APIRouter, HTTPException, Request

from src.api.schemas.model_fitting import (
    ModelFittingBlocksResponse,
    ModelFittingCreateJobRequest,
    ModelFittingJobResponse,
    ModelFittingSolutionResponse,
)
from src.services.model_fitting_service import (
    create_model_fitting_job,
    get_model_fitting_blocks,
    get_model_fitting_job,
    get_model_fitting_solution,
)


def create_model_fitting_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(config["routes"]["jobs"], response_model=ModelFittingJobResponse)
    def create_job(
        request_body: ModelFittingCreateJobRequest,
        request: Request,
    ) -> dict:
        try:
            return create_model_fitting_job(
                request.app.state.db_engine,
                config,
                request.app.state.fitting_candidate_recall_config,
                request_body.model_dump(),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error

    @router.get(config["routes"]["job"], response_model=ModelFittingJobResponse)
    def job(job_id: str, request: Request) -> dict:
        saved_job = get_model_fitting_job(
            request.app.state.db_engine,
            config,
            job_id,
        )
        if saved_job is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["job_not_found"].format(job_id=job_id),
            )
        return saved_job

    @router.get(config["routes"]["job_blocks"], response_model=ModelFittingBlocksResponse)
    def blocks(job_id: str, request: Request) -> dict:
        saved_blocks = get_model_fitting_blocks(
            request.app.state.db_engine,
            config,
            job_id,
        )
        if saved_blocks is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["job_not_found"].format(job_id=job_id),
            )
        return saved_blocks

    @router.get(config["routes"]["solution"], response_model=ModelFittingSolutionResponse)
    def solution(solution_id: str, request: Request) -> dict:
        saved_solution = get_model_fitting_solution(
            request.app.state.db_engine,
            solution_id,
        )
        if saved_solution is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["solution_not_found"].format(
                    solution_id=solution_id,
                ),
            )
        return saved_solution

    return router
