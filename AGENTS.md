# Repository instructions for coding agents

These instructions apply to the entire repository.

## Mandatory i18n preflight

BrickBuilder uses an approved end-to-end multilingual architecture. Before changing any UI, API, background task, validation result, persisted content, configuration label, or export, read:

1. `I18N_CHANGE_GUARDRAILS.md` — mandatory task-level rules and decision table.
2. `I18N_ARCHITECTURE.md` — system architecture and invariants.
3. `I18N_FIELD_CLASSIFICATION.md` — machine, user-authored, official, and system-content boundaries.
4. `I18N_GOVERNANCE.md` — ownership, review, version, and release rules when resources change.

At the beginning of the task, tell the user which i18n surfaces are affected. If none are affected, explicitly state that the task has no user-visible or locale-sensitive impact. Do not begin implementation until this classification is made.

## Non-negotiable architecture rules

- UI text uses typed semantic keys. Never add user-visible hardcoded Chinese or English to TS/TSX or display configuration.
- Machine values, IDs, enum values, database keys, API codes, and JSON property names are never translated.
- Public API errors and task messages use stable `code + params`; never expose `str(error)`, stack traces, paths, SQL, or final translated text.
- User-authored content is preserved verbatim with `contentLocale`; never machine-translate it or treat it as a resource key.
- Official Component/Part content uses translation tables, and only `reviewed` translations may be selected.
- Locale-sensitive requests and tasks carry normalized locale/timezone context. Async work must not read the browser's later language state.
- Server-generated exports use frozen `ExportContext` and versioned server resources. Keep machine fields stable and localize only human-facing metadata.
- Adding a production language is catalog/resource work, not a business-code branch. Never add `if (locale === ...)` behavior to feature code.
- Missing resources fail CI. Do not add `defaultValue`, source-text fallbacks, compatibility shims, or silent missing-key behavior.
- Resource changes require catalog version, content hash, and `I18N_RELEASE_NOTES.md` updates.

## Required completion checks

For any i18n-affecting change, run:

```bash
cd frontend
npm run i18n:check
npm test
npm run build

cd ../backend
python -m pytest
```

Also update architecture, field classification, governance, or release documentation when a contract or boundary changes. In the final handoff, report the i18n impact and validation results.

If a requested change conflicts with these rules, stop and explain the conflict instead of introducing a parallel localization mechanism.
