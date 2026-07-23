"""M6 runtime observability and extensible locale resolver contracts."""

from src.i18n.messages import locale_catalog, normalize_locale_for_catalog
from src.i18n.observability import (
    record_i18n_event,
    reset_runtime_i18n_metrics,
    runtime_i18n_metrics,
)


def test_runtime_i18n_metrics_include_totals_dimensions_and_hourly_trends() -> None:
    reset_runtime_i18n_metrics()
    record_i18n_event("unknown_key", "zh-CN", "common", "missing.title")
    record_i18n_event("unknown_key", "zh-CN", "common", "missing.title")
    record_i18n_event("unknown_api_code", "en-US", "errors", "new.error")
    record_i18n_event("locale_fallback", "zh-CN", "component", "en-US")

    metrics = runtime_i18n_metrics()
    assert metrics["unknownKeyCount"] == 2
    assert metrics["unknownApiCodeCount"] == 1
    assert metrics["localeFallbackCount"] == 1
    assert metrics["metricOverflowCount"] == 0
    assert len(metrics["events"]) == 3
    assert sum(row["count"] for row in metrics["hourly"]) == 4
    assert all(row["hour"].endswith(":00:00Z") for row in metrics["hourly"])


def test_japanese_validation_locale_uses_generic_catalog_resolver() -> None:
    catalog = locale_catalog()
    candidates = tuple(catalog["product_locales"] + catalog["validation_locales"])
    assert normalize_locale_for_catalog("ja", candidates, catalog["locale_aliases"]) == "ja-JP"
    assert normalize_locale_for_catalog("ja_JP", candidates, catalog["locale_aliases"]) == "ja-JP"
