"""Direct mesh model import API routes."""

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from src.api.errors import DomainError, domain_error_from_exception
from src.services.mesh_model_service import mesh_model_file_path, save_uploaded_mesh_model
from src.i18n.domain_content import normalize_content_locale


def create_mesh_model_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(config["routes"]["mesh_models"])
    async def upload_mesh_model(
        request: Request,
        name: str = Form(...),
        contentLocale: str = Form(...),
        model: UploadFile = File(...),
    ) -> dict:
        if model.filename is None:
            raise DomainError(
                config["errors"]["missing_filename"],
                http_status=config["http_status"]["bad_request"],
            )
        if model.content_type is None:
            raise DomainError(
                config["errors"]["unsupported_content_type"],
                http_status=config["http_status"]["bad_request"],
            )
        file_bytes = await model.read()
        try:
            return save_uploaded_mesh_model(
                request.app.state.db_engine,
                config,
                name,
                model.filename,
                model.content_type,
                file_bytes,
                normalize_content_locale(contentLocale),
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "mesh_model.upload_failed",
                params={"filename": model.filename},
                http_status=config["http_status"]["bad_request"],
            ) from error

    @router.get(config["routes"]["mesh_model_file"])
    def mesh_model_file(model_id: str, request: Request) -> FileResponse:
        path = mesh_model_file_path(request.app.state.db_engine, config, model_id)
        if path is None or not path.exists():
            raise DomainError(
                config["errors"]["model_not_found"],
                params={"modelId": model_id},
                http_status=config["http_status"]["not_found"],
            )
        return FileResponse(path, media_type=config["response"]["media_type"])

    return router
