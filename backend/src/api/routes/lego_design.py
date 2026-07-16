"""LEGO design API routes."""

import json
from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response

from src.api.schemas.lego_design import (
    LegoDesignCandidatePartsResponse,
    LegoDesignJobRequest,
    LegoDesignJobResponse,
    LegoDesignMetadataResponse,
)
from src.services.lego_design_service import (
    create_lego_design_result,
    export_lego_design_ldraw,
    export_lego_design_plan,
    lego_design_candidates,
    lego_design_metadata,
)
from src.services.pixel_art_service import load_pixel_art_project


def create_lego_design_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.get(config["routes"]["metadata"], response_model=LegoDesignMetadataResponse)
    def metadata(request: Request) -> dict:
        return lego_design_metadata(request.app.state.db_engine, config)

    @router.get(config["routes"]["candidates"], response_model=LegoDesignCandidatePartsResponse)
    def candidates(
        request: Request,
        footprint: str = Query(
            default=config["candidate_features"]["default_footprint"],
            alias=config["candidate_features"]["query_param"],
        ),
    ) -> dict:
        try:
            return lego_design_candidates(request.app.state.db_engine, config, footprint)
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error

    @router.post(config["routes"]["jobs"], response_model=LegoDesignJobResponse)
    def create_job(request_body: LegoDesignJobRequest, request: Request) -> dict:
        job_id = uuid4().hex[: int(config["jobs"]["job_id_hex_length"])]
        job = {
            "jobId": job_id,
            "status": config["job_status"]["queued"],
            "progress": config["progress"]["queued"],
            "projectId": request_body.projectId,
            "result": None,
            "error": None,
        }
        with request.app.state.lego_design_jobs_lock:
            request.app.state.lego_design_jobs[job_id] = job
        thread = Thread(
            target=run_lego_design_job,
            args=(request.app, config, job_id, request_body.projectId),
            daemon=True,
        )
        thread.start()
        return public_job(job)

    @router.get(config["routes"]["job"], response_model=LegoDesignJobResponse)
    def job(job_id: str, request: Request) -> dict:
        with request.app.state.lego_design_jobs_lock:
            active_job = request.app.state.lego_design_jobs.get(job_id)
        if active_job is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["job_not_found"],
            )
        return public_job(active_job)

    @router.get(config["routes"]["job_ldraw"])
    def export_job_ldraw(
        job_id: str,
        request: Request,
        include_base: bool = Query(alias=config["ldraw"]["include_base_query_param"]),
    ) -> Response:
        with request.app.state.lego_design_jobs_lock:
            active_job = request.app.state.lego_design_jobs.get(job_id)
        if active_job is None:
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["job_not_found"],
            )
        if active_job["status"] != config["job_status"]["complete"] or active_job["result"] is None:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=config["errors"]["design_not_ready"],
            )
        metadata = lego_design_metadata(request.app.state.db_engine, config)
        try:
            content = export_lego_design_ldraw(active_job["result"], metadata, include_base, config)
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error
        filename = config["ldraw"]["filename_template"].format(job_id=job_id)
        return Response(
            content=content,
            media_type=config["ldraw"]["content_type"],
            headers={
                config["ldraw"]["content_disposition_header"]: config["ldraw"]["content_disposition_template"].format(
                    filename=filename,
                ),
            },
        )

    @router.get(config["routes"]["job_plan"])
    def export_job_plan(
        job_id: str,
        request: Request,
        include_base: bool = Query(alias=config["ldraw"]["include_base_query_param"]),
    ) -> Response:
        active_job = completed_job(job_id, request, config)
        metadata = lego_design_metadata(request.app.state.db_engine, config)
        try:
            plan = export_lego_design_plan(active_job["result"], metadata, include_base, config)
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error
        filename = config["plan_export"]["filename_template"].format(job_id=job_id)
        return Response(
            content=json.dumps(plan, ensure_ascii=False, indent=config["plan_export"]["json_indent"]),
            media_type=config["plan_export"]["content_type"],
            headers={
                config["plan_export"]["content_disposition_header"]: config["plan_export"]["content_disposition_template"].format(
                    filename=filename,
                ),
            },
        )

    return router


def completed_job(job_id: str, request: Request, config: dict) -> dict:
    with request.app.state.lego_design_jobs_lock:
        active_job = request.app.state.lego_design_jobs.get(job_id)
    if active_job is None:
        raise HTTPException(
            status_code=config["http_status"]["not_found"],
            detail=config["errors"]["job_not_found"],
        )
    if active_job["status"] != config["job_status"]["complete"] or active_job["result"] is None:
        raise HTTPException(
            status_code=config["http_status"]["bad_request"],
            detail=config["errors"]["design_not_ready"],
        )
    return active_job


def run_lego_design_job(app: object, config: dict, job_id: str, project_id: str) -> None:
    update_job(app, job_id, {"status": config["job_status"]["running"]})
    try:
        project = load_pixel_art_project(
            app.state.db_engine,
            app.state.pixel_art_config,
            project_id,
        )
        if project is None:
            raise ValueError(config["errors"]["project_not_found"])
        metadata = lego_design_metadata(app.state.db_engine, config)
        result = create_lego_design_result(
            project,
            metadata,
            config,
            lambda progress: update_job(app, job_id, {"progress": progress}),
        )
        update_job(
            app,
            job_id,
            {
                "status": config["job_status"]["complete"],
                "progress": config["progress"]["complete"],
                "result": result,
            },
        )
    except ValueError as error:
        update_job(
            app,
            job_id,
            {
                "status": config["job_status"]["failed"],
                "error": str(error),
            },
        )


def update_job(app: object, job_id: str, updates: dict) -> None:
    with app.state.lego_design_jobs_lock:
        app.state.lego_design_jobs[job_id] = {
            **app.state.lego_design_jobs[job_id],
            **updates,
        }


def public_job(job: dict) -> dict:
    return {
        "jobId": job["jobId"],
        "status": job["status"],
        "progress": job["progress"],
        "projectId": job["projectId"],
        "result": job["result"],
        "error": job["error"],
    }
