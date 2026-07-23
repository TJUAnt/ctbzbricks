# Frontend i18n conventions

- React components call `useAppTranslation()` and use the returned typed translator. Enum/key mapping boundaries use `useDynamicTranslation()`.
- Stores and API clients may call the typed `translate()` function. Validated runtime keys use `translateDynamic()` only at configuration and enum-mapping boundaries.
- `npm run i18n:types` generates `TranslationKey` and interpolation parameter types from `en-US` resources.
- `npm run i18n:check` fails when the generated types are stale; required interpolation parameters are checked by TypeScript.
- Do not pass `defaultValue`. Missing resources must fail tests instead of falling back to source text.
- Machine values such as API statuses are never translated in place; map them to translation keys at the rendering boundary.
- Date, number and relative-time output uses the helpers in `formatters.ts`.
- `en-XA` is a generated pseudo-locale for development and visual regression only.
- Locale support is declared in `catalog.json`; runtime resources are discovered from locale directories instead of imported one by one.
- `npm run i18n:validate` checks namespace/key parity, interpolation parameters, semantic keys, unsafe HTML, catalog hash, and release notes.
- Resource changes require a new `catalogVersion`, refreshed `contentHash`, and an entry in `I18N_RELEASE_NOTES.md`.
- Unreviewed languages stay in `validationLocales`; do not expose them in `productLocales`.
- Ownership, style, and PR approval rules are defined in the repository-level `I18N_GOVERNANCE.md`.
