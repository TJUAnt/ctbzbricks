"""Component Repo API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response

from src.api.errors import DomainError, domain_error_from_exception
from src.api.schemas.component_repo import (
    ComponentAssemblyRelationResponse,
    ComponentCandidateResponse,
    ComponentFreeConnectorResponse,
    ComponentInterfaceCreateRequest,
    ComponentInterfaceResponse,
    ComponentImportCreateResponse,
    ComponentImportParseResponse,
    ComponentImportResponse,
    ComponentPreviewResponse,
    ComponentRelationCandidateResponse,
    ComponentUploadSessionCreateRequest,
    ComponentUploadSessionResponse,
    ComponentValidationReportResponse,
    ComponentResponse,
    ComponentVersionPublishRequest,
    ComponentVersionResponse,
)
from src.auth.current_user import (
    CurrentUser,
    audit_identity,
    optional_current_user,
    require_component_repo_auth_if_configured,
    require_current_user,
)
from src.component_repo.component_service import (
    component_candidate_preview,
    component_version_preview,
    component_version_source_artifact_id,
    create_component_interface,
    first_component_preview,
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
    complete_component_upload_session,
    create_component_artifact,
    create_component_import,
    create_component_upload_session,
    get_component_import,
    get_component_candidate,
    get_component_candidate_for_import,
    list_component_imports,
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
        target_component_id: str | None = Form(None),
        base_version_id: str | None = Form(None),
        content_locale: str = Form(...),
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        try:
            storage = component_repo_storage(request, config, current_user)
            actor = component_repo_actor(config, current_user)
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
                target_component_id=target_component_id,
                base_version_id=base_version_id,
                content_locale=content_locale,
                created_by=actor,
            )
            return {
                "importJob": import_job,
                "sourceArtifact": source_artifact,
                "exchangeArtifact": exchange_artifact,
            }
        except ArtifactStorageError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                http_status=502,
            ) from error
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.import_create_failed",
                params={"contentLocale": content_locale},
                http_status=400,
            ) from error

    @router.get(
        config["routes"]["component_imports"],
        response_model=list[ComponentImportResponse],
    )
    def get_imports(
        request: Request,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> list[dict]:
        actor = audit_identity(config, current_user) if current_user else None
        return list_component_imports(request.app.state.db_engine, created_by=actor)

    @router.post(
        config["routes"]["component_import_upload_session"],
        response_model=ComponentUploadSessionResponse,
    )
    def create_upload_session(
        request: Request,
        payload: ComponentUploadSessionCreateRequest,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        try:
            return create_component_upload_session(
                request.app.state.db_engine,
                config,
                user.user_id,
                payload.sourceFile.filename,
                payload.sourceFile.contentType,
                payload.exchangeFile.filename if payload.exchangeFile else None,
                payload.exchangeFile.contentType if payload.exchangeFile else None,
                target_component_id=payload.targetComponentId,
                base_version_id=payload.baseVersionId,
                content_locale=payload.contentLocale,
                created_by=audit_identity(config, user),
            )
        except ValueError as error:
            raise component_repo_operation_error(error, "upload_session_create") from error

    @router.post(
        config["routes"]["component_import_upload_complete"],
        response_model=ComponentImportCreateResponse,
    )
    def complete_upload_session(
        request: Request,
        upload_session_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        storage = component_repo_storage(request, config, user)
        try:
            return complete_component_upload_session(
                request.app.state.db_engine,
                config,
                storage,
                upload_session_id,
                user.user_id,
                completed_by=audit_identity(config, user),
            )
        except ArtifactStorageError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                http_status=502,
            ) from error
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "upload_session_complete",
                uploadSessionId=upload_session_id,
            ) from error

    @router.get(
        config["routes"]["component_import"],
        response_model=ComponentImportResponse,
    )
    def get_import(request: Request, import_id: str) -> dict:
        import_job = get_component_import(request.app.state.db_engine, import_id)
        if import_job is None:
            raise DomainError(
                "component_repo.import_not_found",
                params={"importId": import_id},
                http_status=404,
            )
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
        require_component_repo_auth_if_configured(current_user)
        storage = component_repo_storage(request, config, current_user)
        try:
            return parse_component_import(
                request.app.state.db_engine,
                config,
                storage,
                import_id,
            )
        except ValueError as error:
            raise component_repo_operation_error(error, "import_parse", importId=import_id) from error

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
            raise DomainError(
                "component_repo.candidate_not_found",
                params={"importId": import_id},
                http_status=404,
            )
        return candidate

    @router.get(
        config["routes"]["candidate_detail"],
        response_model=ComponentCandidateResponse,
    )
    def get_candidate(request: Request, candidate_id: str) -> dict:
        candidate = get_component_candidate(request.app.state.db_engine, candidate_id)
        if candidate is None:
            raise DomainError(
                "component_repo.candidate_id_not_found",
                params={"candidateId": candidate_id},
                http_status=404,
            )
        return candidate

    @router.get(
        config["routes"]["candidate_preview"],
        response_model=ComponentPreviewResponse,
        summary="Get one Component candidate preview",
        description=(
            "Returns the candidate scene snapshot as assembly transforms plus one indexed "
            "LDraw triangle mesh per unique Part. A ComponentVersion is not required."
        ),
        response_description="The render-ready assembly for the requested candidate.",
        responses={
            404: {"description": "The Component candidate does not exist."},
            409: {"description": "Required Part mesh geometry is unavailable."},
        },
    )
    def get_candidate_preview(
        request: Request,
        candidate_id: str,
        contentLocale: str = Query(
            ...,
            description="BCP 47 locale for Component content; geometry is locale-neutral.",
        ),
    ) -> dict:
        try:
            preview = component_candidate_preview(
                request.app.state.db_engine,
                config,
                candidate_id,
                contentLocale,
            )
        except ValueError as error:
            locale_unsupported = str(error) == "request.locale_unsupported"
            raise domain_error_from_exception(
                error,
                "component_repo.preview_unavailable",
                params={
                    "candidateId": candidate_id,
                    **({"locale": contentLocale} if locale_unsupported else {}),
                },
                http_status=400 if locale_unsupported else 409,
            ) from error
        if preview is None:
            raise DomainError(
                "component_repo.candidate_id_not_found",
                params={"candidateId": candidate_id},
                http_status=404,
            )
        return preview

    @router.post(
        config["routes"]["candidate_relations_detect"],
        response_model=list[ComponentRelationCandidateResponse],
    )
    def detect_relations(
        request: Request,
        candidate_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> list[dict]:
        require_component_repo_auth_if_configured(current_user)
        try:
            return detect_relation_candidates(
                request.app.state.db_engine,
                config,
                candidate_id,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "relation_detect",
                candidateId=candidate_id,
            ) from error

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
                confirmed_by=component_repo_actor(config, current_user),
                component_candidate_id=candidate_id,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "relation_confirm",
                http_status=(
                    409
                    if str(error) == "component_repo.connector_capacity_exceeded"
                    else 400
                ),
                candidateId=candidate_id,
                relationId=relation_id,
            ) from error

    @router.post(
        config["routes"]["candidate_relation_reject"],
        response_model=ComponentRelationCandidateResponse,
    )
    def reject_relation(
        request: Request,
        candidate_id: str,
        relation_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        try:
            return reject_relation_candidate(
                request.app.state.db_engine,
                config,
                relation_id,
                component_candidate_id=candidate_id,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "relation_reject",
                http_status=(
                    409
                    if str(error) == "component_repo.confirmed_relation_cannot_be_rejected"
                    else 400
                ),
                candidateId=candidate_id,
                relationId=relation_id,
            ) from error

    @router.get(
        config["routes"]["candidate_free_connectors"],
        response_model=list[ComponentFreeConnectorResponse],
    )
    def get_free_connectors(request: Request, candidate_id: str) -> list[dict]:
        try:
            return list_free_connectors(request.app.state.db_engine, candidate_id)
        except ValueError as error:
            if str(error) == "No active part library version exists":
                raise DomainError(
                    "component_repo.part_library_unavailable",
                    params={"candidateId": candidate_id},
                    http_status=409,
                ) from error
            raise component_repo_operation_error(
                error,
                "free_connectors_list",
                candidateId=candidate_id,
            ) from error

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
            actor = component_repo_actor(config, current_user)
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
                created_by=actor,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "interface_create",
                candidateId=candidate_id,
            ) from error

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
    def validate_candidate(
        request: Request,
        candidate_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        try:
            return validate_component_candidate(
                request.app.state.db_engine,
                config,
                candidate_id,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "candidate_validate",
                candidateId=candidate_id,
            ) from error

    @router.get(
        config["routes"]["components"],
        response_model=list[ComponentResponse],
    )
    def get_components(
        request: Request,
        contentLocale: str,
        status: str | None = None,
    ) -> list[dict]:
        try:
            return list_components(
                request.app.state.db_engine,
                config,
                status=status,
                content_locale=contentLocale,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "request.locale_unsupported",
                params={"locale": contentLocale},
                http_status=400,
            ) from error

    @router.get(
        config["routes"]["component_preview_first"],
        response_model=ComponentPreviewResponse,
        summary="Get the first previewable Component Repo item",
        description=(
            "Returns Component assembly instances and one indexed LDraw triangle mesh "
            "for each unique Part reference. The Component snapshot defines placement "
            "only; Part geometry is resolved from the configured LDraw library when the "
            "preview is requested. Coordinates and transforms use LDraw units (LDU)."
        ),
        response_description=(
            "A render-ready Component assembly with deduplicated Part meshes."
        ),
        responses={
            404: {"description": "No previewable Component Repo item exists."},
            409: {"description": "Required Part mesh geometry is unavailable."},
        },
    )
    def get_first_component_preview(
        request: Request,
        contentLocale: str = Query(
            ...,
            description=(
                "BCP 47 locale used to select Component domain content. Mesh geometry "
                "is locale-neutral."
            ),
        ),
    ) -> dict:
        try:
            preview = first_component_preview(
                request.app.state.db_engine,
                config,
                contentLocale,
            )
        except ValueError as error:
            locale_unsupported = str(error) == "request.locale_unsupported"
            raise domain_error_from_exception(
                error,
                "component_repo.preview_unavailable",
                params={"locale": contentLocale} if locale_unsupported else None,
                http_status=400 if locale_unsupported else 409,
            ) from error
        if preview is None:
            raise DomainError(
                "component_repo.preview_empty",
                http_status=404,
            )
        return preview

    @router.get(
        config["routes"]["component_version_preview"],
        response_model=ComponentPreviewResponse,
        summary="Get one Component version preview",
        description=(
            "Returns the selected ComponentVersion as assembly transforms plus one indexed "
            "LDraw triangle mesh per unique Part. Coordinates use LDraw units (LDU)."
        ),
        response_description="The render-ready assembly for the requested ComponentVersion.",
        responses={
            404: {"description": "The ComponentVersion does not exist."},
            409: {"description": "Required Part mesh geometry is unavailable."},
        },
    )
    def get_component_version_preview(
        request: Request,
        version_id: str,
        contentLocale: str = Query(
            ...,
            description="BCP 47 locale for Component content; geometry is locale-neutral.",
        ),
    ) -> dict:
        try:
            preview = component_version_preview(
                request.app.state.db_engine,
                config,
                version_id,
                contentLocale,
            )
        except ValueError as error:
            locale_unsupported = str(error) == "request.locale_unsupported"
            raise domain_error_from_exception(
                error,
                "component_repo.preview_unavailable",
                params={
                    "versionId": version_id,
                    **({"locale": contentLocale} if locale_unsupported else {}),
                },
                http_status=400 if locale_unsupported else 409,
            ) from error
        if preview is None:
            raise DomainError(
                "component_repo.version_not_found",
                params={"versionId": version_id},
                http_status=404,
            )
        return preview

    @router.get(
        config["routes"]["component_detail"],
        response_model=ComponentResponse,
    )
    def get_component_detail(
        request: Request,
        component_id: str,
        contentLocale: str,
        status: str | None = None,
    ) -> dict:
        try:
            component = get_component(
                request.app.state.db_engine,
                config,
                component_id,
                status=status,
                content_locale=contentLocale,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "request.locale_unsupported",
                params={"locale": contentLocale},
                http_status=400,
            ) from error
        if component is None:
            raise DomainError(
                "component_repo.component_not_found",
                params={"componentId": component_id},
                http_status=404,
            )
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
            raise DomainError(
                "component_repo.version_not_found",
                params={"versionId": version_id},
                http_status=404,
            )
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
            actor = component_repo_actor(config, current_user)
            return publish_component_version(
                request.app.state.db_engine,
                config,
                version_id,
                release_note=payload.releaseNote if payload else None,
                name=payload.name if payload else None,
                category=payload.category if payload else None,
                version_name=payload.version if payload else None,
                content_locale=payload.contentLocale if payload else None,
                published_by=actor,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "version_publish",
                http_status=(
                    409
                    if str(error)
                    in {
                        "component_repo.publish_validation_failed",
                        "component_repo.version_conflict",
                    }
                    else 400
                ),
                versionId=version_id,
            ) from error

    @router.post(
        config["routes"]["component_version_deprecate"],
        response_model=ComponentVersionResponse,
    )
    def deprecate_version(
        request: Request,
        version_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        try:
            return set_component_version_lifecycle_status(
                request.app.state.db_engine,
                config,
                version_id,
                config["versions"]["status"]["deprecated"],
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "version_deprecate",
                versionId=version_id,
            ) from error

    @router.post(
        config["routes"]["component_version_archive"],
        response_model=ComponentVersionResponse,
    )
    def archive_version(
        request: Request,
        version_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        try:
            return set_component_version_lifecycle_status(
                request.app.state.db_engine,
                config,
                version_id,
                config["versions"]["status"]["archived"],
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "version_archive",
                versionId=version_id,
            ) from error

    @router.get(config["routes"]["component_version_source"])
    def download_version_source(
        request: Request,
        version_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        require_component_repo_auth_if_configured(current_user)
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
            raise component_repo_operation_error(
                error,
                "version_source_not_found",
                http_status=404,
                versionId=version_id,
            ) from error
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
        require_component_repo_auth_if_configured(current_user)
        storage = component_repo_storage(request, config, current_user)
        try:
            artifact, content = read_component_artifact(
                request.app.state.db_engine,
                config,
                storage,
                artifact_id,
            )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "artifact_not_found",
                http_status=404,
                artifactId=artifact_id,
            ) from error
        return Response(
            content=content,
            media_type=artifact["mimeType"],
            headers={
                "Content-Disposition": f"attachment; filename=\"{artifact['originalFilename']}\"",
            },
        )

    return router


def component_repo_operation_error(
    error: Exception,
    operation: str,
    *,
    http_status: int = 400,
    **params: object,
) -> DomainError:
    return domain_error_from_exception(
        error,
        f"component_repo.{operation}_failed",
        params=params,
        http_status=http_status,
    )


def component_repo_actor(config: dict, current_user: CurrentUser | None) -> str:
    require_component_repo_auth_if_configured(current_user)
    return audit_identity(config, current_user)


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
