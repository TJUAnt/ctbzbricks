"""Terrain DEM API routes."""

from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, Request

from src.api.errors import DomainError, domain_error_from_exception
from src.api.schemas.terrain import TerrainJobRequest, TerrainJobResponse, TerrainSaveRequest
from src.i18n.messages import error_from_exception, progress
from src.terrain.dem_asset_helper import (
    build_asset_from_geojson,
    dem_dataset_config,
    list_model_metadata,
    load_model_asset,
    save_model_asset,
)
from src.services.model_asset_service import save_dem_model_asset


def create_terrain_router(api_config: dict, terrain_config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(api_config["routes"]["terrain_jobs"], response_model=TerrainJobResponse)
    def create_terrain_job(request_body: TerrainJobRequest, request: Request) -> dict:
        validate_dem_dataset_key(request_body.dem_dataset_key, terrain_config)
        job_id = uuid4().hex[: int(terrain_config["model_id_hex_length"])]
        job = {
            "jobId": job_id,
            "status": terrain_config["job_status"]["queued"],
            "progress": progress(
                terrain_config["progress"]["queued"],
                "terrain.progress.queued",
            ),
            "sourceName": request_body.source_name,
            "asset": None,
            "model": None,
            "error": None,
            "locale": request_body.locale,
            "timezone": request_body.timezone,
        }
        with request.app.state.terrain_jobs_lock:
            request.app.state.terrain_jobs[job_id] = job
        thread = Thread(
            target=run_terrain_job,
            args=(request.app, terrain_config, job_id, request_body),
            daemon=True,
        )
        thread.start()
        return public_job(job)

    @router.get(api_config["routes"]["terrain_job"], response_model=TerrainJobResponse)
    def terrain_job(job_id: str, request: Request) -> dict:
        with request.app.state.terrain_jobs_lock:
            job = request.app.state.terrain_jobs.get(job_id)
        if not job:
            raise DomainError(
                "terrain.job_not_found",
                params={"jobId": job_id},
                http_status=terrain_config["http_status"]["not_found"],
            )
        return public_job(job)

    @router.get(api_config["routes"]["terrain_models"])
    def terrain_models() -> dict:
        return {"models": list_model_metadata(terrain_config)}

    @router.post(api_config["routes"]["terrain_models"])
    def save_terrain_model(request_body: TerrainSaveRequest, request: Request) -> dict:
        model = save_model_asset(terrain_config, request_body.asset, request_body.name)
        save_dem_model_asset(
            request.app.state.db_engine,
            request.app.state.model_asset_config,
            terrain_config,
            request_body.asset,
            model,
            request_body.contentLocale,
        )
        return model

    @router.get(api_config["routes"]["terrain_model"])
    def terrain_model(model_id: str) -> dict:
        try:
            return load_model_asset(terrain_config, model_id)
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "terrain.model_not_found",
                params={"modelId": model_id},
                http_status=terrain_config["http_status"]["not_found"],
            ) from error

    return router


def run_terrain_job(
    app: object, terrain_config: dict, job_id: str, request_body: TerrainJobRequest
) -> None:
    update_job(
        app,
        job_id,
        {
            "status": terrain_config["job_status"]["running"],
            "progress": progress(
                terrain_config["progress"]["polygons"],
                "terrain.progress.processing",
            ),
        },
    )
    try:
        asset = build_asset_from_geojson(
            terrain_config,
            request_body.geojson,
            request_body.dem_dataset_key,
            request_body.source_name,
            lambda percent: update_job(
                app,
                job_id,
                {"progress": progress(percent, "terrain.progress.processing")},
            ),
        )
        update_job(
            app,
            job_id,
            {
                "status": terrain_config["job_status"]["complete"],
                "progress": progress(
                    terrain_config["progress"]["saved"],
                    "terrain.progress.completed",
                ),
                "asset": asset,
                "model": None,
            },
        )
    except Exception as error:
        update_job(
            app,
            job_id,
            {
                "status": terrain_config["job_status"]["failed"],
                "progress": progress(100, "terrain.progress.failed"),
                "error": error_from_exception(error, "terrain.generation_failed"),
            },
        )


def update_job(app: object, job_id: str, updates: dict) -> None:
    with app.state.terrain_jobs_lock:
        app.state.terrain_jobs[job_id] = {
            **app.state.terrain_jobs[job_id],
            **updates,
        }


def validate_dem_dataset_key(dem_dataset_key: str, terrain_config: dict) -> None:
    try:
        dem_dataset_config(terrain_config, dem_dataset_key)
    except ValueError as error:
        raise domain_error_from_exception(
            error,
            "terrain.invalid_dem_dataset",
            params={"datasetKey": dem_dataset_key},
            http_status=terrain_config["http_status"]["bad_request"],
        ) from error


def public_job(job: dict) -> dict:
    return {
        "jobId": job["jobId"],
        "status": job["status"],
        "progress": job["progress"],
        "sourceName": job["sourceName"],
        "asset": job["asset"],
        "model": job["model"],
        "error": job["error"],
        "locale": job["locale"],
        "timezone": job["timezone"],
    }
