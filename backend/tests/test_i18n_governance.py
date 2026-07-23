"""Standard-library governance checks that can run in a minimal CI image."""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_CATALOG = json.loads((ROOT / "backend/config/i18n.json").read_text(encoding="utf-8"))
FRONTEND_CATALOG = json.loads(
    (ROOT / "frontend/src/i18n/catalog.json").read_text(encoding="utf-8")
)
EXPORT_ROOT = ROOT / "backend/src/i18n/export_resources"
OWNERS = json.loads((ROOT / "backend/config/i18n_owners.json").read_text(encoding="utf-8"))
INTERPOLATION_PATTERN = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}")
MARKUP_PATTERN = re.compile(r"</?[A-Za-z][^>]*>|javascript\s*:|\bon[A-Za-z]+\s*=", re.I)


class I18nGovernanceTest(unittest.TestCase):
    def test_repository_agent_guardrails_are_mandatory_and_linked(self) -> None:
        agent_rules = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        guardrails = (ROOT / "I18N_CHANGE_GUARDRAILS.md").read_text(encoding="utf-8")
        architecture = (ROOT / "I18N_ARCHITECTURE.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Mandatory i18n preflight", agent_rules)
        self.assertIn("I18N_CHANGE_GUARDRAILS.md", agent_rules)
        self.assertIn("Non-negotiable architecture rules", agent_rules)
        self.assertIn("每个任务开始前必须回答", guardrails)
        self.assertIn("Definition of Done", guardrails)
        self.assertIn("强制变更入口", architecture)
        self.assertIn("I18N_CHANGE_GUARDRAILS.md", readme)

    def test_translation_owners_glossary_and_pr_review_gate_are_declared(self) -> None:
        self.assertEqual(
            set(OWNERS["requiredReviewRoles"]),
            {"resource-owner", "native-language-reviewer"},
        )
        self.assertTrue(OWNERS["primaryOwner"])
        glossary = json.loads(
            (ROOT / "backend/config/i18n_glossary.json").read_text(encoding="utf-8")
        )
        for term in glossary["terms"]:
            for locale in BACKEND_CATALOG["product_locales"]:
                self.assertIn(locale, term, f"{term['term']}:{locale}")
        template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
        self.assertIn("资源所有者审核者", template)
        self.assertIn("目标语言审核者", template)

    def test_frontend_backend_locale_catalogs_are_aligned(self) -> None:
        self.assertEqual(
            BACKEND_CATALOG["product_locales"],
            FRONTEND_CATALOG["productLocales"],
        )
        self.assertEqual(
            BACKEND_CATALOG["validation_locales"],
            FRONTEND_CATALOG["validationLocales"],
        )
        self.assertIn("ja-JP", BACKEND_CATALOG["validation_locales"])

    def test_export_catalogs_have_matching_shape_parameters_and_no_html(self) -> None:
        catalogs = {
            locale: json.loads((EXPORT_ROOT / f"{locale}.json").read_text(encoding="utf-8"))
            for locale in BACKEND_CATALOG["product_locales"]
        }
        source = catalogs["en-US"]
        source_entries = dict(flatten(source))
        for locale, catalog in catalogs.items():
            entries = dict(flatten(catalog))
            self.assertEqual(set(entries), set(source_entries), locale)
            for key, value in entries.items():
                self.assertIsInstance(value, str, f"{locale}:{key}")
                self.assertIsNone(MARKUP_PATTERN.search(value), f"{locale}:{key}")
                self.assertEqual(
                    set(INTERPOLATION_PATTERN.findall(value)),
                    set(INTERPOLATION_PATTERN.findall(source_entries[key])),
                    f"{locale}:{key}",
                )

    def test_release_notes_track_frontend_and_export_catalog_versions(self) -> None:
        release_notes = (ROOT / "I18N_RELEASE_NOTES.md").read_text(encoding="utf-8")
        export_catalog = json.loads((EXPORT_ROOT / "en-US.json").read_text(encoding="utf-8"))
        self.assertIn(FRONTEND_CATALOG["catalogVersion"], release_notes)
        self.assertIn(export_catalog["catalogVersion"], release_notes)


def flatten(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            yield from flatten(child, child_prefix)
    else:
        yield prefix, value


if __name__ == "__main__":
    unittest.main()
