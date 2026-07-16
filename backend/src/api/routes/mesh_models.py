"""Direct mesh model import API routes."""

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from src.services.mesh_model_service import mesh_model_file_path, save_uploaded_mesh_model


def create_mesh_model_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(config["routes"]["mesh_models"])
    async def upload_mesh_model(
        request: Request,
        name: str = Form(...),
        model: UploadFile = File(...),
    ) -> dict:
        if model.filename is None:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=config["errors"]["missing_filename"],
            )
        if model.content_type is None:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=config["errors"]["unsupported_content_type"],
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
            )
        except ValueError as error:
            raise HTTPException(
                status_code=config["http_status"]["bad_request"],
                detail=str(error),
            ) from error

    @router.get(config["routes"]["mesh_model_file"])
    def mesh_model_file(model_id: str, request: Request) -> FileResponse:
        path = mesh_model_file_path(request.app.state.db_engine, config, model_id)
        if path is None or not path.exists():
            raise HTTPException(
                status_code=config["http_status"]["not_found"],
                detail=config["errors"]["model_not_found"],
            )
        return FileResponse(path, media_type=config["response"]["media_type"])

    return router
