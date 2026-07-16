"""Component Repo API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from src.api.schemas.component_repo import (
    ComponentAssemblyRelationResponse,
    ComponentApproveRequest,
    ComponentApproveResponse,
    ComponentCandidateResponse,
    ComponentFreeConnectorResponse,
    ComponentInterfaceCreateRequest,
    ComponentInterfaceResponse,
    ComponentImportCreateResponse,
    ComponentImportParseResponse,
    ComponentImportResponse,
    ComponentRelationCandidateResponse,
    ComponentValidationReportResponse,
    ComponentResponse,
    ComponentVersionPublishRequest,
    ComponentVersionResponse,
)
from src.auth.current_user import CurrentUser, audit_identity, optional_current_user
from src.component_repo.component_service import (
    approve_component_candidate,
    component_version_source_artifact_id,
    create_component_interface,
    get_component,
    get_component_version,
    list_component_interfaces,
    list_component_versions,
    list_components,
    publish_component_version,
    set_component_version_lifecycle_status,
    validate_component_candidate,
)
from src.component_repo.services import (
    artifact_type_for_filename,
    create_component_artifact,
    create_component_import,
    get_component_import,
    get_component_candidate_for_import,
    parse_component_import,
    read_component_artifact,
)
from src.component_repo.storage import ArtifactStorageError, storage_from_config
from src.component_repo.relation_service import (
    confirm_relation_candidate,
    detect_relation_candidates,
    list_free_connectors,
    list_relation_candidates,
    reject_relation_candidate,
)
from src.config.app_settings import BACKEND_ROOT


def create_component_repo_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(
        config["routes"]["component_imports"],
        response_model=ComponentImportCreateResponse,
    )
    async def create_import(
        request: Request,
        source_file: UploadFile = File(...),
        exchange_file: UploadFile | None = File(None),
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        try:
            storage = component_repo_storage(request, config, current_user)
            actor = audit_identity(config, current_user)
            source_content = await source_file.read()
            source_artifact = create_component_artifact(
                request.app.state.db_engine,
                config,
                storage,
                artifact_type_for_filename(config, source_file.filename or "source.io"),
                source_file.filename or "source.io",
                source_content,
                source_file.content_type,
                uploaded_by=actor,
            )
            exchange_artifact = None
            if exchange_file is not None:
                exchange_content = await exchange_file.read()
                exchange_artifact = create_component_artifact(
                    request.app.state.db_engine,
                    config,
                    storage,
                    artifact_type_for_filename(config, exchange_file.filename or "model.ldr"),
                    exchange_file.filename or "model.ldr",
                    exchange_content,
                    exchange_file.content_type,
                    uploaded_by=actor,
                )
            if (
                exchange_artifact is None
                and source_artifact["artifactType"]
                in (config["artifacts"]["ldraw_ldr"], config["artifacts"]["ldraw_mpd"])
            ):
                exchange_artifact = source_artifact
            import_job = create_component_import(
                request.app.state.db_engine,
                config,
                source_artifact["id"],
                exchange_artifact["id"] if exchange_artifact else None,
                created_by=actor,
            )
            return {
                "importJob": import_job,
                "sourceArtifact": source_artifact,
                "exchangeArtifact": exchange_artifact,
            }
        except ArtifactStorageError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @router.get(
        config["routes"]["component_import"],
        response_model=ComponentImportResponse,
    )
    def get_import(request: Request, import_id: str) -> dict:
        import_job = get_component_import(request.app.state.db_engine, import_id)
        if import_job is None:
            raise HTTPException(status_code=404, detail="Component import not found")
        return import_job

    @router.post(
        config["routes"]["component_import_parse"],
        response_model=ComponentImportParseResponse,
    )
    def parse_import(
        request: Request,
        import_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        storage = component_repo_storage(request, config, current_user)
        try:
            return parse_component_import(
                request.app.state.db_engine,
                config,
                storage,
                import_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get(
        config["routes"]["component_import_candidate"],
        response_model=ComponentCandidateResponse,
    )
    def get_import_candidate(request: Request, import_id: str) -> dict:
        candidate = get_component_candidate_for_import(
            request.app.state.db_engine,
            import_id,
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="Component candidate not found")
        return candidate

    @router.post(
        config["routes"]["candidate_relations_detect"],
        response_model=list[ComponentRelationCandidateResponse],
    )
    def detect_relations(request: Request, candidate_id: str) -> list[dict]:
        try:
            return detect_relation_candidates(
                request.app.state.db_engine,
                config,
                candidate_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get(
        config["routes"]["candidate_relations"],
        response_model=list[ComponentRelationCandidateResponse],
    )
    def get_relations(request: Request, candidate_id: str) -> list[dict]:
        return list_relation_candidates(request.app.state.db_engine, candidate_id)

    @router.post(
        config["routes"]["candidate_relation_confirm"],
        response_model=ComponentAssemblyRelationResponse,
    )
    def confirm_relation(
        request: Request,
        candidate_id: str,
        relation_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        try:
            return confirm_relation_candidate(
                request.app.state.db_engine,
                config,
                relation_id,
                confirmed_by=audit_identity(config, current_user),
                component_candidate_id=candidate_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post(
        config["routes"]["candidate_relation_reject"],
        response_model=ComponentRelationCandidateResponse,
    )
    def reject_relation(request: Request, candidate_id: str, relation_id: str) -> dict:
        try:
            return reject_relation_candidate(
                request.app.state.db_engine,
                config,
                relation_id,
                component_candidate_id=candidate_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get(
        config["routes"]["candidate_free_connectors"],
        response_model=list[ComponentFreeConnectorResponse],
    )
    def get_free_connectors(request: Request, candidate_id: str) -> list[dict]:
        try:
            return list_free_connectors(request.app.state.db_engine, candidate_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post(
        config["routes"]["candidate_interfaces"],
        response_model=ComponentInterfaceResponse,
    )
    def create_interface(
        request: Request,
        candidate_id: str,
        payload: ComponentInterfaceCreateRequest,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        try:
            return create_component_interface(
                request.app.state.db_engine,
                config,
                candidate_id,
                payload.worldConnectorId,
                payload.name,
                exposure=payload.exposure,
                default_behavior=payload.defaultBehavior,
                mechanical_roles=payload.mechanicalRoles,
                business_roles=payload.businessRoles,
                requirements=payload.requirements,
                created_by=audit_identity(config, current_user),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get(
        config["routes"]["candidate_interfaces"],
        response_model=list[ComponentInterfaceResponse],
    )
    def get_interfaces(request: Request, candidate_id: str) -> list[dict]:
        return list_component_interfaces(request.app.state.db_engine, candidate_id)

    @router.post(
        config["routes"]["candidate_validate"],
        response_model=ComponentValidationReportResponse,
    )
    def validate_candidate(request: Request, candidate_id: str) -> dict:
        try:
            return validate_component_candidate(
                request.app.state.db_engine,
                config,
                candidate_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post(
        config["routes"]["candidate_approve"],
        response_model=ComponentApproveResponse,
    )
    def approve_candidate(
        request: Request,
        candidate_id: str,
        payload: ComponentApproveRequest,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        try:
            return approve_component_candidate(
                request.app.state.db_engine,
                config,
                candidate_id,
                payload.name,
                category=payload.category,
                component_id=payload.componentId,
                version=payload.version,
                revision=payload.revision,
                description=payload.description,
                tags=payload.tags,
                created_by=audit_identity(config, current_user),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get(
        config["routes"]["components"],
        response_model=list[ComponentResponse],
    )
    def get_components(request: Request, status: str | None = None) -> list[dict]:
        return list_components(request.app.state.db_engine, config, status=status)

    @router.get(
        config["routes"]["component_detail"],
        response_model=ComponentResponse,
    )
    def get_component_detail(request: Request, component_id: str, status: str | None = None) -> dict:
        component = get_component(
            request.app.state.db_engine,
            config,
            component_id,
            status=status,
        )
        if component is None:
            raise HTTPException(status_code=404, detail="Component not found")
        return component

    @router.get(
        config["routes"]["component_versions"],
        response_model=list[ComponentVersionResponse],
    )
    def get_versions(request: Request, component_id: str, status: str | None = None) -> list[dict]:
        return list_component_versions(
            request.app.state.db_engine,
            config,
            component_id,
            status=status,
        )

    @router.get(
        config["routes"]["component_version"],
        response_model=ComponentVersionResponse,
    )
    def get_version(request: Request, version_id: str, status: str | None = None) -> dict:
        version = get_component_version(
            request.app.state.db_engine,
            config,
            version_id,
            status=status,
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Component version not found")
        return version

    @router.post(
        config["routes"]["component_version_publish"],
        response_model=ComponentVersionResponse,
    )
    def publish_version(
        request: Request,
        version_id: str,
        payload: ComponentVersionPublishRequest | None = None,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        try:
            return publish_component_version(
                request.app.state.db_engine,
                config,
                version_id,
                release_note=payload.releaseNote if payload else None,
                published_by=audit_identity(config, current_user),
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post(
        config["routes"]["component_version_deprecate"],
        response_model=ComponentVersionResponse,
    )
    def deprecate_version(request: Request, version_id: str) -> dict:
        try:
            return set_component_version_lifecycle_status(
                request.app.state.db_engine,
                config,
                version_id,
                config["versions"]["status"]["deprecated"],
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post(
        config["routes"]["component_version_archive"],
        response_model=ComponentVersionResponse,
    )
    def archive_version(request: Request, version_id: str) -> dict:
        try:
            return set_component_version_lifecycle_status(
                request.app.state.db_engine,
                config,
                version_id,
                config["versions"]["status"]["archived"],
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get(config["routes"]["component_version_source"])
    def download_version_source(
        request: Request,
        version_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        storage = component_repo_storage(request, config, current_user)
        try:
            artifact_id = component_version_source_artifact_id(
                request.app.state.db_engine,
                config,
                version_id,
            )
            artifact, content = read_component_artifact(
                request.app.state.db_engine,
                config,
                storage,
                artifact_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(
            content=content,
            media_type=artifact["mimeType"],
            headers={
                "Content-Disposition": f"attachment; filename=\"{artifact['originalFilename']}\"",
            },
        )

    @router.get(config["routes"]["component_artifact_source"])
    def download_artifact(
        request: Request,
        artifact_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        storage = component_repo_storage(request, config, current_user)
        try:
            artifact, content = read_component_artifact(
                request.app.state.db_engine,
                config,
                storage,
                artifact_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(
            content=content,
            media_type=artifact["mimeType"],
            headers={
                "Content-Disposition": f"attachment; filename=\"{artifact['originalFilename']}\"",
            },
        )

    return router


def component_repo_storage(
    request: Request,
    config: dict,
    current_user: CurrentUser | None = None,
):
    if hasattr(request.app.state, "component_repo_storage"):
        storage = request.app.state.component_repo_storage
    else:
        storage = storage_from_config(config, BACKEND_ROOT)
    if current_user is not None and hasattr(storage, "with_authorization_token"):
        return storage.with_authorization_token(current_user.access_token)
    return storage
