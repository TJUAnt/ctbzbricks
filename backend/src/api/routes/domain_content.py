"""Translation administration and i18n observability routes."""

from fastapi import APIRouter, Depends, Request

from src.api.errors import domain_error_from_exception
from src.api.schemas.domain_content import (
    ComponentTranslationRequest,
    ComponentTranslationResponse,
    PartTranslationResponse,
    TranslationContentRequest,
    TranslationMetricsResponse,
    I18nEventRequest,
)
from src.auth.current_user import (
    CurrentUser,
    audit_identity,
    optional_current_user,
    require_component_repo_auth_if_configured,
)
from src.i18n.domain_content import translation_metrics
from src.i18n.observability import record_i18n_event, runtime_i18n_metrics
from src.services.domain_content_service import (
    upsert_component_translation,
    upsert_part_translation,
)


def create_domain_content_router(config: dict) -> APIRouter:
    router = APIRouter()

    @router.put(
        config["routes"]["component_translation"],
        response_model=ComponentTranslationResponse,
    )
    def put_component_translation(
        component_id: str,
        locale: str,
        payload: ComponentTranslationRequest,
        request: Request,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        actor = audit_identity(config, current_user)
        try:
            return upsert_component_translation(
                request.app.state.db_engine,
                component_id,
                locale,
                payload.name,
                payload.description,
                payload.tags,
                payload.translationStatus,
                actor,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "component_repo.translation_update_failed",
                params={"componentId": component_id, "locale": locale},
                http_status=400,
            ) from error

    @router.put(
        config["routes"]["part_translation"],
        response_model=PartTranslationResponse,
    )
    def put_part_translation(
        part_number: str,
        locale: str,
        payload: TranslationContentRequest,
        request: Request,
        current_user: CurrentUser | None = Depends(optional_current_user),
    ) -> dict:
        require_component_repo_auth_if_configured(current_user)
        actor = audit_identity(config, current_user)
        try:
            return upsert_part_translation(
                request.app.state.db_engine,
                part_number,
                locale,
                payload.name,
                payload.description,
                payload.translationStatus,
                actor,
            )
        except ValueError as error:
            raise domain_error_from_exception(
                error,
                "part_search.translation_update_failed",
                params={"partNumber": part_number, "locale": locale},
                http_status=400,
            ) from error

    @router.get(
        config["routes"]["i18n_metrics"],
        response_model=TranslationMetricsResponse,
    )
    def get_translation_metrics() -> dict:
        return {**translation_metrics(), **runtime_i18n_metrics()}

    @router.post(config["routes"]["i18n_events"], status_code=204)
    def post_i18n_event(payload: I18nEventRequest) -> None:
        record_i18n_event(
            payload.kind,
            payload.locale,
            payload.namespace,
            payload.code,
        )

    return router
