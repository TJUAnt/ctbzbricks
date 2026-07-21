"""LEGO design API routes."""

import json
from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, Query, Request, Response

from src.api.errors import DomainError, domain_error_from_exception
from src.api.schemas.lego_design import (
    LegoDesignCandidatePartsResponse,
    LegoDesignJobRequest,
    LegoDesignJobResponse,
    LegoDesignMetadataResponse,
)
from src.i18n.messages import error_from_exception, progress
from src.i18n.export_catalog import (
    content_disposition,
    create_export_context,
    localized_filename,
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
            raise domain_error_from_exception(
                error,
                "lego_design.candidates_failed",
                params={"footprint": footprint},
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.post(config["routes"]["jobs"], response_model=LegoDesignJobResponse)
    def create_job(request_body: LegoDesignJobRequest, request: Request) -> dict:
        job_id = uuid4().hex[: int(config["jobs"]["job_id_hex_length"])]
        export_context = create_export_context(request_body.locale, request_body.timezone)
        job = {
            "jobId": job_id,
            "status": config["job_status"]["queued"],
            "progress": progress(config["progress"]["queued"], "lego_design.progress.queued"),
            "projectId": request_body.projectId,
            "result": None,
            "error": None,
            "locale": request_body.locale,
            "timezone": request_body.timezone,
            "catalogVersion": export_context["catalogVersion"],
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
            raise DomainError(
                config["errors"]["job_not_found"],
                params={"jobId": job_id},
                http_status=config["http_status"]["not_found"],
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
            raise DomainError(
                config["errors"]["job_not_found"],
                params={"jobId": job_id},
                http_status=config["http_status"]["not_found"],
            )
        if active_job["status"] != config["job_status"]["complete"] or active_job["result"] is None:
            raise DomainError(
                config["errors"]["design_not_ready"],
                params={"jobId": job_id},
                http_status=config["http_status"]["bad_request"],
            )
        metadata = lego_design_metadata(request.app.state.db_engine, config)
        try:
            content = export_lego_design_ldraw(
                active_job["result"], metadata, include_base, config, job_export_context(active_job),
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "lego_design.export_ldraw_failed",
                params={"jobId": job_id},
                http_status=config["http_status"]["bad_request"],
            ) from error
        filename = localized_filename(job_export_context(active_job), "legoLdraw", jobId=job_id)
        return Response(
            content=content,
            media_type=config["ldraw"]["content_type"],
            headers={
                config["ldraw"]["content_disposition_header"]: content_disposition(filename),
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
            plan = export_lego_design_plan(
                active_job["result"], metadata, include_base, config, job_export_context(active_job),
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "lego_design.export_plan_failed",
                params={"jobId": job_id},
                http_status=config["http_status"]["bad_request"],
            ) from error
        filename = localized_filename(job_export_context(active_job), "legoPlan", jobId=job_id)
        return Response(
            content=json.dumps(plan, ensure_ascii=False, indent=config["plan_export"]["json_indent"]),
            media_type=config["plan_export"]["content_type"],
            headers={
                config["plan_export"]["content_disposition_header"]: content_disposition(filename),
            },
        )

    return router


def completed_job(job_id: str, request: Request, config: dict) -> dict:
    with request.app.state.lego_design_jobs_lock:
        active_job = request.app.state.lego_design_jobs.get(job_id)
    if active_job is None:
        raise DomainError(
            config["errors"]["job_not_found"],
            params={"jobId": job_id},
            http_status=config["http_status"]["not_found"],
        )
    if active_job["status"] != config["job_status"]["complete"] or active_job["result"] is None:
        raise DomainError(
            config["errors"]["design_not_ready"],
            params={"jobId": job_id},
            http_status=config["http_status"]["bad_request"],
        )
    return active_job


def run_lego_design_job(app: object, config: dict, job_id: str, project_id: str) -> None:
    update_job(
        app,
        job_id,
        {
            "status": config["job_status"]["running"],
            "progress": progress(
                config["progress"]["metadata_loaded"],
                "lego_design.progress.processing",
            ),
        },
    )
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
            lambda percent: update_job(
                app,
                job_id,
                {"progress": progress(percent, "lego_design.progress.processing")},
            ),
        )
        update_job(
            app,
            job_id,
            {
                "status": config["job_status"]["complete"],
                "progress": progress(
                    config["progress"]["complete"],
                    "lego_design.progress.completed",
                ),
                "result": result,
            },
        )
    except Exception as error:
        update_job(
            app,
            job_id,
            {
                "status": config["job_status"]["failed"],
                "progress": progress(100, "lego_design.progress.failed"),
                "error": error_from_exception(error, "lego_design.generation_failed"),
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
        "locale": job["locale"],
        "timezone": job["timezone"],
        "catalogVersion": job["catalogVersion"],
    }


def job_export_context(job: dict) -> dict[str, str]:
    return {
        "locale": job["locale"],
        "timezone": job["timezone"],
        "catalogVersion": job["catalogVersion"],
    }
