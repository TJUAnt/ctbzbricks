"""Bounded in-process i18n telemetry with hourly trend buckets."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from src.i18n.messages import locale_catalog


EVENT_KINDS = ("unknown_key", "unknown_api_code", "locale_fallback")
_event_counts: Counter[tuple[str, str, str, str]] = Counter()
_hourly_counts: Counter[tuple[str, str, str, str, str]] = Counter()
_overflow_count = 0
_metrics_lock = Lock()


def record_i18n_event(kind: str, locale: str, namespace: str, code: str) -> None:
    if kind not in EVENT_KINDS:
        raise ValueError("request.i18n_event_kind_invalid")
    config = locale_catalog()
    maximum_length = int(config["maximum_metric_value_length"])
    dimensions = tuple(
        _normalize_dimension(value, maximum_length)
        for value in (kind, locale, namespace, code)
    )
    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    global _overflow_count
    with _metrics_lock:
        if (
            dimensions not in _event_counts
            and len(_event_counts) >= int(config["maximum_metric_dimensions"])
        ):
            _overflow_count += 1
            return
        _event_counts[dimensions] += 1
        _hourly_counts[(hour, *dimensions)] += 1


def runtime_i18n_metrics() -> dict[str, Any]:
    with _metrics_lock:
        events = [
            {
                "kind": kind,
                "locale": locale,
                "namespace": namespace,
                "code": code,
                "count": count,
            }
            for (kind, locale, namespace, code), count in sorted(_event_counts.items())
        ]
        hourly = [
            {
                "hour": hour,
                "kind": kind,
                "locale": locale,
                "namespace": namespace,
                "code": code,
                "count": count,
            }
            for (hour, kind, locale, namespace, code), count in sorted(_hourly_counts.items())
        ]
        overflow_count = _overflow_count
    totals = Counter()
    for event in events:
        totals[event["kind"]] += event["count"]
    return {
        "unknownKeyCount": totals["unknown_key"],
        "unknownApiCodeCount": totals["unknown_api_code"],
        "localeFallbackCount": totals["locale_fallback"],
        "metricOverflowCount": overflow_count,
        "events": events,
        "hourly": hourly,
    }


def reset_runtime_i18n_metrics() -> None:
    global _overflow_count
    with _metrics_lock:
        _event_counts.clear()
        _hourly_counts.clear()
        _overflow_count = 0


def _normalize_dimension(value: str, maximum_length: int) -> str:
    normalized = " ".join(str(value).strip().split())
    return (normalized or "unknown")[:maximum_length]
