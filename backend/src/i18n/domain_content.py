"""Locale resolution and observability for localized domain content."""

from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any

from src.i18n.messages import normalize_task_locale
from src.i18n.observability import record_i18n_event


OFFICIAL_CONTENT = "official"
USER_CONTENT = "user"
CONTENT_KINDS = (OFFICIAL_CONTENT, USER_CONTENT)
TRANSLATION_DRAFT = "draft"
TRANSLATION_REVIEWED = "reviewed"
TRANSLATION_REJECTED = "rejected"
TRANSLATION_STATUSES = (
    TRANSLATION_DRAFT,
    TRANSLATION_REVIEWED,
    TRANSLATION_REJECTED,
)

_fallback_counts: Counter[tuple[str, str, str]] = Counter()
_fallback_lock = Lock()


def normalize_content_locale(locale: str) -> str:
    return normalize_task_locale(locale)


def validate_content_kind(content_kind: str) -> str:
    if content_kind not in CONTENT_KINDS:
        raise ValueError("request.content_kind_invalid")
    return content_kind


def validate_translation_status(status: str) -> str:
    if status not in TRANSLATION_STATUSES:
        raise ValueError("request.translation_status_invalid")
    return status


def record_translation_fallback(
    entity_type: str,
    requested_locale: str,
    content_locale: str,
) -> None:
    with _fallback_lock:
        _fallback_counts[(entity_type, requested_locale, content_locale)] += 1
    record_i18n_event(
        "locale_fallback",
        requested_locale,
        entity_type,
        content_locale,
    )


def translation_metrics() -> dict[str, Any]:
    with _fallback_lock:
        rows = [
            {
                "entityType": entity_type,
                "requestedLocale": requested_locale,
                "contentLocale": content_locale,
                "count": count,
            }
            for (entity_type, requested_locale, content_locale), count in sorted(
                _fallback_counts.items()
            )
        ]
    return {
        "missingOfficialTranslationCount": sum(row["count"] for row in rows),
        "fallbacks": rows,
    }


def reset_translation_metrics() -> None:
    with _fallback_lock:
        _fallback_counts.clear()
