import i18n, { type TOptions } from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { useCallback } from 'react';
import { initReactI18next, useTranslation } from 'react-i18next';

import type { TranslationKey, TranslationParamsByKey } from './generated';
import catalog from './catalog.json';
import { namespaces, productLocales, resources } from './resources';
import { recordI18nEvent } from './telemetry';

export type { TranslationKey } from './generated';

export { productLocales };
export type SupportedLocale = string;
export const supportedLocales: readonly string[] = [
  ...productLocales,
  ...(import.meta.env.DEV ? ['en-XA' as const] : []),
];

type SafeTOptions = Omit<TOptions, 'defaultValue'>;
type TranslationArguments<Key extends TranslationKey> = Key extends keyof TranslationParamsByKey
  ? [key: Key, options: TranslationParamsByKey[Key] & SafeTOptions]
  : [key: Key, options?: SafeTOptions];

export type AppTranslator = <Key extends TranslationKey>(...args: TranslationArguments<Key>) => string;
export type DynamicTranslator = (key: TranslationKey, options?: SafeTOptions) => string;

const localeStorageKey = 'brickBuilder.locale';

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    initAsync: false,
    supportedLngs: [...supportedLocales],
    nonExplicitSupportedLngs: false,
    fallbackLng: catalog.defaultLocale,
    defaultNS: 'common',
    ns: [...namespaces],
    keySeparator: false,
    interpolation: { escapeValue: false },
    saveMissing: true,
    missingKeyHandler: (languages, namespace, key) => {
      recordI18nEvent({
        kind: 'unknown_key',
        locale: languages[0] ?? catalog.defaultLocale,
        namespace,
        code: key,
      });
    },
    react: { useSuspense: false },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      lookupLocalStorage: localeStorageKey,
      caches: ['localStorage'],
      convertDetectedLanguage: (locale: string) => normalizeLocale(locale),
    },
  });

export function resolveLocaleForCatalog(
  locale: string,
  locales: readonly string[],
  fallbackLocale: string,
  aliases: Readonly<Record<string, string>> = {},
): string {
  const normalized = locale.trim().replace(/_/g, '-').toLowerCase();
  const exact = locales.find((candidate) => candidate.toLowerCase() === normalized);
  if (exact) return exact;
  const alias = Object.entries(aliases)
    .sort(([left], [right]) => right.length - left.length)
    .find(([prefix]) => normalized === prefix || normalized.startsWith(`${prefix}-`));
  if (alias && locales.includes(alias[1])) return alias[1];
  const language = normalized.split('-')[0];
  const candidates = locales.filter((candidate) => candidate.toLowerCase().split('-')[0] === language);
  return candidates.length === 1 ? candidates[0] : fallbackLocale;
}

export function normalizeLocale(locale: string): SupportedLocale {
  const locales = import.meta.env.DEV ? supportedLocales : productLocales;
  const resolved = resolveLocaleForCatalog(locale, locales, catalog.defaultLocale, catalog.localeAliases);
  if (!isRecognizedLocale(locale, locales, catalog.localeAliases)) {
    recordI18nEvent({
      kind: 'locale_fallback',
      locale: resolved,
      namespace: 'locale',
      code: locale.trim().slice(0, 160) || 'unknown',
    });
  }
  return resolved;
}

export function textDirection(locale: string): 'ltr' | 'rtl' {
  const language = locale.trim().toLowerCase().split(/[-_]/)[0];
  return catalog.rtlLanguageCodes.includes(language) ? 'rtl' : 'ltr';
}

function isRecognizedLocale(
  locale: string,
  locales: readonly string[],
  aliases: Readonly<Record<string, string>>,
): boolean {
  const normalized = locale.trim().replace(/_/g, '-').toLowerCase();
  if (locales.some((candidate) => candidate.toLowerCase() === normalized)) return true;
  if (Object.entries(aliases).some(([prefix, target]) => (
    (normalized === prefix || normalized.startsWith(`${prefix}-`)) && locales.includes(target)
  ))) return true;
  const languageMatches = locales.filter(
    (candidate) => candidate.toLowerCase().split('-')[0] === normalized.split('-')[0],
  );
  return languageMatches.length === 1;
}

function syncDocumentLocale(locale: string) {
  if (typeof document === 'undefined') return;
  const resolvedLocale = normalizeLocale(locale);
  document.documentElement.lang = resolvedLocale;
  document.documentElement.dir = textDirection(resolvedLocale);
  document.title = i18n.t('common:appTitle');
}

i18n.on('initialized', () => syncDocumentLocale(i18n.resolvedLanguage ?? i18n.language));
i18n.on('languageChanged', syncDocumentLocale);
syncDocumentLocale(i18n.resolvedLanguage ?? i18n.language);

export function translate<Key extends TranslationKey>(...args: TranslationArguments<Key>): string {
  const [key, options] = args as [TranslationKey, SafeTOptions | undefined];
  return i18n.t(key, options ?? {});
}

export function translateDynamic(key: TranslationKey, options?: SafeTOptions): string {
  return i18n.t(key, options ?? {});
}

export function useAppTranslation(): AppTranslator {
  const { t } = useTranslation([...namespaces]);
  return useCallback(
    ((key: TranslationKey, options?: SafeTOptions) => t(key, options)) as AppTranslator,
    [t],
  );
}

export function useDynamicTranslation(): DynamicTranslator {
  const { t } = useTranslation([...namespaces]);
  return useCallback((key: TranslationKey, options?: SafeTOptions) => t(key, options), [t]);
}

export function resolvedLocale(): SupportedLocale {
  return normalizeLocale(i18n.resolvedLanguage ?? i18n.language);
}

export default i18n;
