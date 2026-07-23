import catalog from '../catalog.json';
import { pseudoLocalizeResources } from './pseudoLocale';

export const namespaces = [
  'common',
  'app',
  'pixelArt',
  'terrain',
  'legoTerrain',
  'legoDesign',
  'componentRepo',
  'partSearch',
  'errors',
  'tasks',
] as const;

export type Namespace = (typeof namespaces)[number];
export type LocaleResources = Record<Namespace, Record<string, string>>;

const resourceModules = import.meta.glob('./*/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, Record<string, string>>;

export const productLocales = catalog.productLocales;
const productResources = Object.fromEntries(
  productLocales.map((locale) => [locale, loadLocaleResources(locale)]),
) as Record<string, LocaleResources>;
const englishResources = productResources[catalog.sourceLocale];

if (!englishResources) {
  throw new Error(`Missing source locale resources: ${catalog.sourceLocale}`);
}

export const resources: Record<string, LocaleResources> = {
  ...productResources,
  ...(import.meta.env.DEV ? { 'en-XA': pseudoLocalizeResources(englishResources) } : {}),
};

function loadLocaleResources(locale: string): LocaleResources {
  return Object.fromEntries(namespaces.map((namespace) => {
    const resource = resourceModules[`./${locale}/${namespace}.json`];
    if (!resource) throw new Error(`Missing i18n resource: ${locale}/${namespace}.json`);
    return [namespace, resource];
  })) as LocaleResources;
}
