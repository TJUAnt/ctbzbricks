# i18n loading evaluation

Measured on 2026-07-18 after M6. M6 added localization health labels and catalog-driven loading.

## Resource size

| Locale | Namespaces | Keys | Raw JSON | Gzip (concatenated) |
|---|---:|---:|---:|---:|
| `zh-CN` | 10 | 749 | 43,800 bytes | 11,878 bytes |
| `en-US` | 10 | 749 | 45,837 bytes | 10,866 bytes |

`en-XA` is generated from English resources only in development and is removed from the production catalog by the `import.meta.env.DEV` branch.

## Decision

Keep eager resource loading.

- Two production locales are well below the architecture threshold of four locales.
- Each locale is well below the 100 KB compressed threshold.
- The application bundle is dominated by 3D/rendering dependencies; namespace requests would add runtime complexity without a measurable first-load benefit at the current resource size.
- Eager loading guarantees instant language switching and keeps configuration proxy reads synchronous.
- `ja-JP` remains a validation locale and contributes no production bundle resources.

Re-evaluate when a production locale exceeds 100 KB compressed, when more than four production locales are enabled, or when bundle analysis attributes a material share of first-load JavaScript to translations.
