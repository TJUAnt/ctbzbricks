"""Component Repo API routes."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from time import perf_counter

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Path,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from src.api.errors import DomainError, domain_error_from_exception
from src.api.schemas.component_repo import (
    ComponentAssemblyRelationResponse,
    ComponentCandidateResponse,
    ComponentConnectorAnalysisResponse,
    ComponentConnectorSummaryAnalysisResponse,
    ComponentFreeConnectorResponse,
    ComponentInterfaceResponse,
    ComponentImportParseRequest,
    ComponentImportParseResponse,
    ComponentImportResponse,
    ComponentImportUploadCompleteResponse,
    ComponentPreviewResponse,
    ComponentRelationCandidateResponse,
    ComponentUploadSessionCreateRequest,
    ComponentUploadSessionResponse,
    ComponentValidationReportResponse,
    ComponentResponse,
    ComponentGroupCreateRequest,
    ComponentGroupSearchRequest,
    ComponentGroupSearchResponse,
    ComponentGroupMembershipsResponse,
    ComponentGroupMoveRequest,
    ComponentGroupResponse,
    ComponentGroupTreeResponse,
    ComponentGroupUpdateRequest,
    ComponentVersionPublishRequest,
    ComponentVersionDeleteResponse,
    ComponentVersionPartsResponse,
    ComponentVersionPreviewModelResponse,
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
    component_version_parts,
    component_version_preview,
    component_version_source_artifact_id,
    delete_component_version,
    first_component_preview,
    get_component,
    get_component_version,
    list_component_versions,
    list_components,
    publish_component_version,
    set_component_version_lifecycle_status,
    validate_component_candidate,
)
from src.component_repo.interface_recognition_service import (
    read_component_connector_analysis,
    read_component_connector_summary,
)
from src.component_repo.group_service import (
    add_component_to_group,
    create_group,
    delete_group,
    list_component_group_ids,
    list_group_components,
    search_group_components,
    list_group_tree,
    move_group,
    remove_component_from_group,
    subscribe_component,
    unsubscribe_component,
    update_group,
)
from src.component_repo.services import (
    artifact_type_for_filename,
    complete_component_upload_session,
    create_component_artifact,
    create_component_import,
    create_component_upload_session,
    discard_component_ingestion,
    get_component_artifact,
    get_component_artifacts,
    get_component_import,
    get_component_candidate,
    get_component_candidate_for_import,
    list_component_imports,
    parse_component_import,
    read_component_artifact,
    update_component_import_processing_metadata,
)
from src.component_repo.preview_model_service import (
    cached_preview_model,
    component_version_preview_model,
    mark_component_version_preview_failed,
    materialize_component_version_preview_model,
    materialize_preview_model,
)
from src.component_repo.storage import (
    ArtifactStorage,
    ArtifactStorageError,
    storage_from_config,
)
from src.component_repo.relation_service import (
    confirm_relation_candidate,
    detect_relation_candidates,
    list_free_connectors,
    list_relation_candidates,
    reject_relation_candidate,
)
from src.config.app_settings import BACKEND_ROOT


logger = logging.getLogger(__name__)


def create_component_repo_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.post(
        config["routes"]["component_imports"],
        response_model=ComponentImportParseResponse,
    )
    async def create_import(
        request: Request,
        background_tasks: BackgroundTasks,
        source_file: UploadFile = File(...),
        exchange_file: UploadFile | None = File(None),
        target_component_id: str | None = Form(None),
        base_version_id: str | None = Form(None),
        content_locale: str = Form(...),
        timezone_name: str = Form("UTC", alias="timezone"),
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        artifact_ids: set[str] = set()
        import_id: str | None = None
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
            artifact_ids.add(source_artifact["id"])
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
                artifact_ids.add(exchange_artifact["id"])
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
                timezone_name=timezone_name,
                created_by=actor,
            )
            import_id = import_job["id"]
            result = process_component_import_for_review(
                request.app.state.db_engine,
                config,
                storage,
                import_id,
            )
            schedule_component_preview_prewarm(
                background_tasks,
                request.app.state.db_engine,
                config,
                storage,
                result,
                current_user,
            )
            return result
        except ArtifactStorageError as error:
            discard_failed_component_ingestion(
                request,
                storage if "storage" in locals() else None,
                import_id=import_id,
                artifact_ids=artifact_ids,
            )
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                http_status=502,
            ) from error
        except ValueError as error:
            discard_failed_component_ingestion(
                request,
                storage if "storage" in locals() else None,
                import_id=import_id,
                artifact_ids=artifact_ids,
            )
            if import_id is not None:
                raise DomainError(
                    "component_repo.component_processing_failed",
                    params={"contentLocale": content_locale},
                    http_status=400,
                ) from error
            raise domain_error_from_exception(
                error,
                "component_repo.import_create_failed",
                params={"contentLocale": content_locale},
                http_status=400,
            ) from error
        except SQLAlchemyError as error:
            discard_failed_component_ingestion(
                request,
                storage if "storage" in locals() else None,
                import_id=import_id,
                artifact_ids=artifact_ids,
            )
            raise domain_error_from_exception(
                error,
                "component_repo.component_processing_failed",
                http_status=500,
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
                source_file_size=payload.sourceFile.fileSize,
                source_sha256=payload.sourceFile.sha256,
                exchange_file_size=(
                    payload.exchangeFile.fileSize if payload.exchangeFile else None
                ),
                exchange_sha256=(
                    payload.exchangeFile.sha256 if payload.exchangeFile else None
                ),
                target_component_id=payload.targetComponentId,
                base_version_id=payload.baseVersionId,
                content_locale=payload.contentLocale,
                timezone_name=payload.timezone,
                created_by=audit_identity(config, user),
            )
        except ValueError as error:
            raise component_repo_operation_error(error, "upload_session_create") from error

    @router.post(
        config["routes"]["component_import_upload_complete"],
        response_model=ComponentImportUploadCompleteResponse,
        status_code=202,
    )
    def complete_upload_session(
        request: Request,
        upload_session_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        storage = component_repo_storage(request, config, user)
        upload_completion_started = perf_counter()
        try:
            completed = complete_component_upload_session(
                request.app.state.db_engine,
                config,
                storage,
                upload_session_id,
                user.user_id,
                completed_by=audit_identity(config, user),
            )
            log_component_ingestion_stage(
                "upload_verification",
                upload_completion_started,
                uploadSessionId=upload_session_id,
            )
        except ArtifactStorageError as error:
            discard_failed_component_ingestion(
                request,
                storage,
                upload_session_id=upload_session_id,
            )
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                http_status=502,
            ) from error
        except ValueError as error:
            discard_failed_component_ingestion(
                request,
                storage,
                upload_session_id=upload_session_id,
            )
            raise component_repo_operation_error(
                error,
                "upload_session_complete",
                uploadSessionId=upload_session_id,
            ) from error

        schedule_component_import_processing(
            request,
            config,
            storage,
            completed,
            user,
        )
        return completed

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
        background_tasks: BackgroundTasks,
        payload: ComponentImportParseRequest,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        storage = component_repo_storage(request, config, current_user)
        import_id = payload.importId
        try:
            result = process_component_import_for_review(
                request.app.state.db_engine,
                config,
                storage,
                import_id,
            )
            schedule_component_preview_prewarm(
                background_tasks,
                request.app.state.db_engine,
                config,
                storage,
                result,
                current_user,
            )
            return result
        except ArtifactStorageError as error:
            discard_failed_component_ingestion(
                request,
                storage,
                import_id=import_id,
            )
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                params={"importId": import_id},
                http_status=502,
            ) from error
        except ValueError as error:
            discard_failed_component_ingestion(
                request,
                storage,
                import_id=import_id,
            )
            raise DomainError(
                "component_repo.component_processing_failed",
                params={"importId": import_id},
                http_status=400,
            ) from error
        except SQLAlchemyError as error:
            discard_failed_component_ingestion(
                request,
                storage,
                import_id=import_id,
            )
            raise domain_error_from_exception(
                error,
                "component_repo.component_processing_failed",
                params={"importId": import_id},
                http_status=500,
            ) from error

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
    @router.post(
        config["routes"]["candidate_preview"],
        response_model=ComponentPreviewResponse,
        summary="Materialize one Component candidate preview",
        description=(
            "Idempotently creates the current user's GLB cache when missing, then "
            "returns the same preview contract as GET."
        ),
    )
    def get_candidate_preview(
        request: Request,
        candidate_id: str,
        contentLocale: str = Query(
            ...,
            description="BCP 47 locale for Component content; geometry is locale-neutral.",
        ),
        current_user: CurrentUser | None = Depends(optional_current_user),
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
        return preview_with_model(
            request,
            config,
            preview,
            current_user,
            materialize=request.method == "POST",
        )

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
        config["routes"]["candidate_connectors"],
        response_model=ComponentConnectorAnalysisResponse,
    )
    def get_connectors(request: Request, candidate_id: str) -> dict:
        try:
            Session = sessionmaker(bind=request.app.state.db_engine)
            with Session() as session:
                return read_component_connector_analysis(
                    session,
                    config,
                    candidate_id,
                )
        except ValueError as error:
            if str(error) == "No active part library version exists":
                raise DomainError(
                    "component_repo.part_library_unavailable",
                    params={"candidateId": candidate_id},
                    http_status=409,
                ) from error
            raise component_repo_operation_error(
                error,
                "connectors_list",
                candidateId=candidate_id,
            ) from error

    @router.get(
        config["routes"]["candidate_connector_summary"],
        response_model=ComponentConnectorSummaryAnalysisResponse,
    )
    def get_connector_summary(request: Request, candidate_id: str) -> dict:
        try:
            Session = sessionmaker(bind=request.app.state.db_engine)
            with Session() as session:
                return read_component_connector_summary(
                    session,
                    candidate_id,
                )
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "connectors_list",
                candidateId=candidate_id,
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

    @router.get(
        config["routes"]["candidate_interfaces"],
        response_model=list[ComponentInterfaceResponse],
    )
    def get_interfaces(request: Request, candidate_id: str) -> list[dict]:
        try:
            Session = sessionmaker(bind=request.app.state.db_engine)
            with Session() as session:
                return read_component_connector_analysis(
                    session,
                    config,
                    candidate_id,
                )["externalInterfaces"]
        except ValueError as error:
            raise component_repo_operation_error(
                error,
                "interfaces_list",
                candidateId=candidate_id,
            ) from error

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
        config["routes"]["component_groups"],
        response_model=ComponentGroupTreeResponse,
    )
    def get_component_groups(
        request: Request,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return list_group_tree(request.app.state.db_engine, user.user_id)

    @router.post(
        config["routes"]["component_groups"],
        response_model=ComponentGroupResponse,
        status_code=201,
    )
    def post_component_group(
        payload: ComponentGroupCreateRequest,
        request: Request,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return create_group(
            request.app.state.db_engine,
            user.user_id,
            payload.parentGroupId,
            payload.name,
            payload.contentLocale,
        )

    @router.patch(
        config["routes"]["component_group"],
        response_model=ComponentGroupResponse,
    )
    def patch_component_group(
        payload: ComponentGroupUpdateRequest,
        request: Request,
        group_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return update_group(
            request.app.state.db_engine,
            user.user_id,
            group_id,
            name=payload.name,
            content_locale=payload.contentLocale,
            parent_group_id=payload.parentGroupId,
            sort_order=payload.sortOrder,
        )

    @router.delete(
        config["routes"]["component_group"],
        status_code=204,
    )
    def remove_component_group(
        request: Request,
        group_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        user = require_current_user(current_user)
        delete_group(request.app.state.db_engine, user.user_id, group_id)
        return Response(status_code=204)

    @router.post(
        config["routes"]["component_group_move"],
        response_model=ComponentGroupResponse,
    )
    def move_component_group(
        payload: ComponentGroupMoveRequest,
        request: Request,
        group_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return move_group(
            request.app.state.db_engine,
            user.user_id,
            group_id,
            payload.parentGroupId,
            payload.position,
        )

    @router.get(
        config["routes"]["component_group_components"],
        response_model=list[ComponentResponse],
    )
    def get_component_group_components(
        request: Request,
        group_id: str,
        contentLocale: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> list[dict]:
        user = require_current_user(current_user)
        return list_group_components(
            request.app.state.db_engine,
            user.user_id,
            group_id,
            contentLocale,
        )

    @router.post(
        config["routes"]["component_group_component_search"],
        response_model=ComponentGroupSearchResponse,
    )
    def post_component_group_search(
        payload: ComponentGroupSearchRequest,
        request: Request,
        group_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return search_group_components(
            request.app.state.db_engine,
            user.user_id,
            group_id,
            payload.contentLocale,
            payload.query,
            payload.statuses,
            payload.allowPlanarRotation,
            payload.sizeTolerance,
            payload.page,
            payload.pageSize,
        )

    @router.put(
        config["routes"]["component_group_component"],
        status_code=204,
    )
    def put_component_group_membership(
        request: Request,
        group_id: str,
        component_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        user = require_current_user(current_user)
        add_component_to_group(
            request.app.state.db_engine,
            user.user_id,
            group_id,
            component_id,
        )
        return Response(status_code=204)

    @router.delete(
        config["routes"]["component_group_component"],
        status_code=204,
    )
    def delete_component_group_membership(
        request: Request,
        group_id: str,
        component_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        user = require_current_user(current_user)
        remove_component_from_group(
            request.app.state.db_engine,
            user.user_id,
            group_id,
            component_id,
        )
        return Response(status_code=204)

    @router.get(
        config["routes"]["component_groups_for_component"],
        response_model=ComponentGroupMembershipsResponse,
    )
    def get_groups_for_component(
        request: Request,
        component_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return {
            "componentId": component_id,
            "groupIds": list_component_group_ids(
                request.app.state.db_engine,
                user.user_id,
                component_id,
            ),
        }

    @router.put(
        config["routes"]["component_subscription"],
        status_code=204,
    )
    def put_component_subscription(
        request: Request,
        component_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        user = require_current_user(current_user)
        subscribe_component(request.app.state.db_engine, user.user_id, component_id)
        return Response(status_code=204)

    @router.delete(
        config["routes"]["component_subscription"],
        status_code=204,
    )
    def delete_component_subscription(
        request: Request,
        component_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        user = require_current_user(current_user)
        unsubscribe_component(request.app.state.db_engine, user.user_id, component_id)
        return Response(status_code=204)

    @router.get(
        config["routes"]["component_preview_first"],
        response_model=ComponentPreviewResponse,
        summary="Get the first previewable Component Repo item",
        description=(
            "Returns Component metadata plus a signed URL for a cached meshopt-compressed "
            "GLB. The Component snapshot defines placement; Part geometry is resolved "
            "from the configured LDraw library when the matching POST materializes the cache."
        ),
        response_description=(
            "A render-ready Component assembly backed by a binary GLB model."
        ),
        responses={
            404: {"description": "No previewable Component Repo item exists."},
            409: {"description": "Required Part mesh geometry is unavailable."},
        },
    )
    @router.post(
        config["routes"]["component_preview_first"],
        response_model=ComponentPreviewResponse,
        summary="Materialize the first previewable Component Repo item",
        description=(
            "Idempotently creates the current user's GLB cache when missing, then "
            "returns the same preview contract as GET."
        ),
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
        current_user: CurrentUser | None = Depends(optional_current_user),
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
        return preview_with_model(
            request,
            config,
            preview,
            current_user,
            materialize=request.method == "POST",
        )

    @router.get(
        config["routes"]["component_version_preview"],
        response_model=ComponentVersionPreviewModelResponse,
        summary="Get one Component version GLB",
        description=(
            "Looks up the GLB directly through the immutable ComponentVersion. "
            "Use POST to materialize a missing or stale model."
        ),
        response_description="The version-linked GLB state and direct model URL.",
        responses={
            404: {"description": "The ComponentVersion does not exist."},
            409: {"description": "Required Part mesh geometry is unavailable."},
        },
    )
    @router.post(
        config["routes"]["component_version_preview"],
        response_model=ComponentVersionPreviewModelResponse,
        summary="Materialize one Component version GLB",
        description=(
            "Returns a directly linked GLB when present; otherwise builds it once and "
            "stores the artifact relation on ComponentVersion."
        ),
    )
    def get_component_version_preview(
        request: Request,
        version_id: str,
        contentLocale: str = Query(
            ...,
            description="BCP 47 locale for Component content; geometry is locale-neutral.",
        ),
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        storage = component_repo_storage(request, config, current_user)
        try:
            cached = component_version_preview_model(
                request.app.state.db_engine,
                config,
                storage,
                version_id,
            )
        except ArtifactStorageError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                params={"versionId": version_id},
                http_status=502,
            ) from error
        if cached is None:
            raise DomainError(
                "component_repo.version_not_found",
                params={"versionId": version_id},
                http_status=404,
            )
        if cached["model"] is not None or request.method == "GET":
            return cached
        try:
            preview = component_version_preview(
                request.app.state.db_engine,
                config,
                version_id,
                contentLocale,
            )
        except ValueError as error:
            locale_unsupported = str(error) == "request.locale_unsupported"
            if not locale_unsupported:
                mark_component_version_preview_failed(
                    request.app.state.db_engine,
                    version_id,
                )
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
        try:
            return materialize_component_version_preview_model(
                request.app.state.db_engine,
                config,
                storage,
                preview,
                version_id,
                owner_id=preview_cache_owner(config, storage, current_user),
                uploaded_by=audit_identity(config, current_user),
            )
        except ArtifactStorageError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                params={"versionId": version_id},
                http_status=502,
            ) from error
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.preview_unavailable",
                params={"versionId": version_id},
                http_status=409,
            ) from error

    @router.get(
        config["routes"]["component_version_parts"],
        response_model=ComponentVersionPartsResponse,
        summary="Get one Component version BOM",
    )
    def get_component_version_parts(
        request: Request,
        version_id: str,
        contentLocale: str = Query(...),
    ) -> dict:
        try:
            result = component_version_parts(
                request.app.state.db_engine,
                version_id,
                contentLocale,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.preview_unavailable",
                params={"versionId": version_id},
                http_status=400,
            ) from error
        if result is None:
            raise DomainError(
                "component_repo.version_not_found",
                params={"versionId": version_id},
                http_status=404,
            )
        return result

    @router.get(config["routes"]["component_preview_model"])
    def get_component_preview_model(
        request: Request,
        artifact_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> Response:
        """Local-storage fallback; Supabase previews use direct signed URLs."""
        storage = component_repo_storage(request, config, current_user)
        try:
            artifact, content = read_component_artifact(
                request.app.state.db_engine,
                config,
                storage,
                artifact_id,
            )
        except ArtifactStorageError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.storage_unavailable",
                params={"artifactId": artifact_id},
                http_status=502,
            ) from error
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.artifact_not_found",
                params={"artifactId": artifact_id},
                http_status=404,
            ) from error
        if artifact["artifactType"] != config["artifacts"]["component_preview_glb"]:
            raise DomainError(
                "component_repo.artifact_not_found",
                params={"artifactId": artifact_id},
                http_status=404,
            )
        return Response(
            content=content,
            media_type=config["storage"]["content_type_glb"],
            headers={
                "Cache-Control": "public, max-age=31536000, immutable",
                "ETag": f'"{artifact["sha256"]}"',
            },
        )

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
    def get_versions(
        request: Request,
        component_id: str,
        status: str | None = None,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> list[dict]:
        return list_component_versions(
            request.app.state.db_engine,
            config,
            component_id,
            status=status,
            actor=(
                audit_identity(config, current_user)
                if current_user is not None
                else None
            ),
        )

    @router.get(
        config["routes"]["component_version"],
        response_model=ComponentVersionResponse,
    )
    def get_version(
        request: Request,
        version_id: str,
        status: str | None = None,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        version = get_component_version(
            request.app.state.db_engine,
            config,
            version_id,
            status=status,
            actor=(
                audit_identity(config, current_user)
                if current_user is not None
                else None
            ),
        )
        if version is None:
            raise DomainError(
                "component_repo.version_not_found",
                params={"versionId": version_id},
                http_status=404,
            )
        return version

    @router.delete(
        config["routes"]["component_version_delete"],
        response_model=ComponentVersionDeleteResponse,
    )
    def delete_version(
        request: Request,
        version_id: str,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        user = require_current_user(current_user)
        return delete_component_version(
            request.app.state.db_engine,
            config,
            version_id,
            audit_identity(config, user),
        )

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
                    403
                    if str(error) == "component_repo.version_publish_forbidden"
                    else 409
                    if str(error) in {
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


def process_component_import_for_review(
    engine: Engine,
    config: dict,
    storage: ArtifactStorage,
    import_id: str,
) -> dict:
    """Run the automatic ingestion pipeline and return a reviewable draft."""

    pipeline_started = perf_counter()
    stage_started = perf_counter()
    result = parse_component_import(
        engine,
        config,
        storage,
        import_id,
    )
    log_component_ingestion_stage("parse_and_draft", stage_started, importId=import_id)

    stage_started = perf_counter()
    detect_relation_candidates(
        engine,
        config,
        result["candidate"]["id"],
    )
    log_component_ingestion_stage(
        "relation_detection",
        stage_started,
        importId=import_id,
        candidateId=result["candidate"]["id"],
    )

    stage_started = perf_counter()
    refreshed_candidate = get_component_candidate(
        engine,
        result["candidate"]["id"],
    )
    if refreshed_candidate is not None:
        result["candidate"] = refreshed_candidate
    source_artifact_id = result["importJob"]["sourceArtifactId"]
    exchange_artifact_id = result["importJob"].get("exchangeArtifactId")
    artifact_ids = {source_artifact_id}
    if exchange_artifact_id:
        artifact_ids.add(exchange_artifact_id)
    artifacts = get_component_artifacts(engine, artifact_ids)
    source_artifact = artifacts.get(source_artifact_id)
    if source_artifact is None:
        raise ValueError("Component source artifact does not exist")
    result["sourceArtifact"] = source_artifact
    result["exchangeArtifact"] = (
        artifacts.get(exchange_artifact_id)
        if exchange_artifact_id
        else None
    )
    log_component_ingestion_stage(
        "response_hydration",
        stage_started,
        importId=import_id,
    )
    log_component_ingestion_stage(
        "processing_pipeline",
        pipeline_started,
        importId=import_id,
        versionId=result["version"]["id"],
    )
    return result


def schedule_component_import_processing(
    request: Request,
    config: dict,
    storage: ArtifactStorage,
    completed: dict,
    current_user: CurrentUser,
) -> None:
    """Submit parsing and preview generation outside the ASGI response lifecycle."""

    import_job = completed["importJob"]
    import_id = str(import_job["id"])
    upload_session_id = str((import_job.get("metadata") or {}).get("uploadSessionId") or "")
    import_metadata = import_job.get("metadata") or {}
    processing_metadata = import_metadata.get("processing") or {}
    if processing_metadata.get("status") == "completed":
        logger.info(
            "Component background processing already completed importId=%s",
            import_id,
        )
        return
    executor = getattr(request.app.state, "component_import_executor", None)
    if executor is None:
        executor = ThreadPoolExecutor(
            max_workers=int(config["imports"].get("background_worker_count", 2)),
            thread_name_prefix="component-import",
        )
        request.app.state.component_import_executor = executor
    lock = getattr(request.app.state, "component_import_futures_lock", None)
    if lock is None:
        lock = Lock()
        request.app.state.component_import_futures_lock = lock
    futures = getattr(request.app.state, "component_import_futures", None)
    if futures is None:
        futures = {}
        request.app.state.component_import_futures = futures

    with lock:
        existing = futures.get(import_id)
        if existing is not None and not existing.done():
            logger.info(
                "Component background processing already scheduled importId=%s",
                import_id,
            )
            return
        future = executor.submit(
            process_component_import_in_background,
            request.app.state.db_engine,
            config,
            storage,
            import_id=import_id,
            upload_session_id=upload_session_id,
            content_locale=str(import_metadata.get("contentLocale") or "zh-CN"),
            timezone_name=str(import_metadata.get("timezone") or "UTC"),
            owner_id=preview_cache_owner(config, storage, current_user),
            uploaded_by=audit_identity(config, current_user),
        )
        futures[import_id] = future
    future.add_done_callback(
        lambda completed_future: forget_component_import_future(
            lock,
            futures,
            import_id,
            completed_future,
        )
    )
    logger.info(
        "Component background processing scheduled importId=%s uploadSessionId=%s",
        import_id,
        upload_session_id,
    )


def forget_component_import_future(
    lock: Lock,
    futures: dict[str, Future],
    import_id: str,
    completed_future: Future,
) -> None:
    with lock:
        if futures.get(import_id) is completed_future:
            futures.pop(import_id, None)


def process_component_import_in_background(
    engine: Engine,
    config: dict,
    storage: ArtifactStorage,
    *,
    import_id: str,
    upload_session_id: str,
    content_locale: str,
    timezone_name: str,
    owner_id: str,
    uploaded_by: str,
) -> None:
    """Build the review draft and cached GLB without holding an HTTP request open."""

    started = perf_counter()
    update_component_import_processing_metadata(
        engine,
        import_id,
        "processing",
        contentLocale=content_locale,
        timezone=timezone_name,
    )
    try:
        result = process_component_import_for_review(
            engine,
            config,
            storage,
            import_id,
        )
    except Exception as error:
        logger.warning(
            "Component background processing failed importId=%s uploadSessionId=%s "
            "durationMs=%.1f errorType=%s",
            import_id,
            upload_session_id,
            elapsed_milliseconds(started),
            type(error).__name__,
        )
        try:
            cleanup = discard_component_ingestion(
                engine,
                storage,
                import_id=import_id,
                upload_session_id=upload_session_id or None,
            )
            if cleanup["storageDeleteFailureCount"]:
                logger.warning(
                    "Component background cleanup completed with storage failures "
                    "importId=%s failureCount=%s",
                    import_id,
                    cleanup["storageDeleteFailureCount"],
                )
        except Exception as cleanup_error:
            logger.warning(
                "Component background cleanup deferred importId=%s errorType=%s",
                import_id,
                type(cleanup_error).__name__,
            )
        return

    preview_ready = prewarm_component_version_preview(
        engine,
        config,
        storage,
        import_id=import_id,
        version_id=str(result["version"]["id"]),
        content_locale=content_locale,
        owner_id=owner_id,
        uploaded_by=uploaded_by,
    )
    update_component_import_processing_metadata(
        engine,
        import_id,
        "completed",
        candidateId=str(result["candidate"]["id"]),
        componentId=str(result["component"]["id"]),
        versionId=str(result["version"]["id"]),
        previewStatus="ready" if preview_ready else "deferred",
        contentLocale=content_locale,
        timezone=timezone_name,
    )
    logger.info(
        "Component background processing completed importId=%s versionId=%s "
        "previewStatus=%s durationMs=%.1f",
        import_id,
        result["version"]["id"],
        "ready" if preview_ready else "deferred",
        elapsed_milliseconds(started),
    )


def schedule_component_preview_prewarm(
    background_tasks: BackgroundTasks,
    engine: Engine,
    config: dict,
    storage: ArtifactStorage,
    result: dict,
    current_user: CurrentUser | None,
) -> None:
    """Queue best-effort preview generation after the HTTP response is sent."""
    import_id = str(result["importJob"]["id"])
    version_id = str(result["version"]["id"])
    import_metadata = result["importJob"].get("metadata") or {}
    content_locale = str(import_metadata.get("contentLocale") or "zh-CN")
    background_tasks.add_task(
        prewarm_component_version_preview,
        engine,
        config,
        storage,
        import_id=import_id,
        version_id=version_id,
        content_locale=content_locale,
        owner_id=preview_cache_owner(config, storage, current_user),
        uploaded_by=audit_identity(config, current_user),
    )
    logger.info(
        "Component preview cache prewarm scheduled importId=%s versionId=%s",
        import_id,
        version_id,
    )


def prewarm_component_version_preview(
    engine: Engine,
    config: dict,
    storage: ArtifactStorage,
    *,
    import_id: str,
    version_id: str,
    content_locale: str,
    owner_id: str,
    uploaded_by: str,
) -> bool:
    """Materialize a cached GLB without extending the ingestion response time."""
    started = perf_counter()
    try:
        preview = component_version_preview(
            engine,
            config,
            version_id,
            content_locale,
        )
        if preview is None:
            raise ValueError("component_repo.preview_unavailable")
        materialize_component_version_preview_model(
            engine,
            config,
            storage,
            preview,
            version_id,
            owner_id=owner_id,
            uploaded_by=uploaded_by,
        )
    except Exception as error:
        mark_component_version_preview_failed(engine, version_id)
        logger.warning(
            "Component preview cache prewarm deferred importId=%s versionId=%s "
            "durationMs=%.1f errorType=%s",
            import_id,
            version_id,
            elapsed_milliseconds(started),
            type(error).__name__,
        )
        return False
    logger.info(
        "Component preview cache prewarm completed importId=%s versionId=%s "
        "durationMs=%.1f",
        import_id,
        version_id,
        elapsed_milliseconds(started),
    )
    return True


def log_component_ingestion_stage(
    stage: str,
    started: float,
    **identifiers: str,
) -> None:
    identifier_fields = " ".join(
        f"{key}={value}" for key, value in identifiers.items()
    )
    logger.info(
        "Component ingestion stage completed stage=%s durationMs=%.1f %s",
        stage,
        elapsed_milliseconds(started),
        identifier_fields,
    )


def elapsed_milliseconds(started: float) -> float:
    return (perf_counter() - started) * 1000


def discard_failed_component_ingestion(
    request: Request,
    storage: ArtifactStorage | None,
    *,
    import_id: str | None = None,
    upload_session_id: str | None = None,
    artifact_ids: set[str] | None = None,
) -> None:
    if storage is None:
        return
    try:
        result = discard_component_ingestion(
            request.app.state.db_engine,
            storage,
            import_id=import_id,
            upload_session_id=upload_session_id,
            artifact_ids=artifact_ids,
        )
        if result["storageDeleteFailureCount"]:
            logger.warning(
                "Component ingestion metadata discarded with %s Storage deletion failures",
                result["storageDeleteFailureCount"],
            )
    except Exception as error:
        logger.warning(
            "Component ingestion cleanup deferred after %s",
            type(error).__name__,
        )


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


def preview_with_model(
    request: Request,
    config: dict,
    preview: dict,
    current_user: CurrentUser | None,
    *,
    materialize: bool,
) -> dict:
    """Read or explicitly materialize a user-scoped binary preview cache."""
    storage = component_repo_storage(request, config, current_user)
    owner_id = preview_cache_owner(config, storage, current_user)
    try:
        if materialize:
            return materialize_preview_model(
                request.app.state.db_engine,
                config,
                storage,
                preview,
                owner_id=owner_id,
                uploaded_by=audit_identity(config, current_user),
            )
        cached = cached_preview_model(
            request.app.state.db_engine,
            config,
            storage,
            preview,
            owner_id=owner_id,
        )
        if cached is None:
            raise ValueError("component_repo.preview_unavailable")
        return cached
    except ArtifactStorageError as error:
        logger.warning(
            "Component preview storage operation failed: %s",
            error,
        )
        raise domain_error_from_exception(
            error,
            "component_repo.storage_unavailable",
            http_status=502,
        ) from error
    except ValueError as error:
        raise domain_error_from_exception(
            error,
            "component_repo.preview_unavailable",
            http_status=409,
        ) from error


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


def preview_cache_owner(
    config: dict,
    storage: object,
    current_user: CurrentUser | None,
) -> str:
    if getattr(storage, "provider", None) == config["storage"]["supabase_provider"]:
        return require_current_user(current_user).user_id
    if current_user is not None:
        return current_user.user_id
    return config["audit"]["system_user"]
