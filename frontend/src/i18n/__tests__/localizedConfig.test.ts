import { afterAll, describe, expect, it } from 'vitest';

import appConfig from '../../app/appConfig';
import rawAppConfig from '../../app/appConfig.json';
import legoDesignConfig from '../../legoDesign/legoDesignConfig';
import rawLegoDesignConfig from '../../legoDesign/legoDesignConfig.json';
import legoTerrainConfig from '../../legoTerrain/legoTerrainConfig';
import rawLegoTerrainConfig from '../../legoTerrain/legoTerrainConfig.json';
import rawPixelArtConfig from '../../pixelArt/pixelArtConfig.json';
import rawTerrainConfig from '../../terrain/terrainConfig.json';
import i18n, { resolvedLocale, supportedLocales } from '../index';
import { namespaces, resources } from '../resources';

const sourceFiles = import.meta.glob('../../**/*.{ts,tsx,json}', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>;

describe('semantic i18n resources', () => {
  afterAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  it('translates configuration values while leaving behavior values unchanged', async () => {
    expect(rawAppConfig.texts.appSubtitle).toBe('app:texts.appSubtitle');

    await i18n.changeLanguage('en-US');
    expect(resolvedLocale()).toBe('en-US');
    expect(appConfig.texts.appSubtitle).toBe('3D LEGO Modeling Workbench');
    expect(appConfig.menuGroups[0].title).toBe('Model plaza');
    expect(appConfig.dashboard.sections[0].cards[0].action).toBe('Open');
    expect(appConfig.routePaths.dashboard).toBe('/dashboard');
    expect(legoDesignConfig.demGenerationStrategy.options[0].value).toBe('surface-plan');

    await i18n.changeLanguage('zh-CN');
    expect(resolvedLocale()).toBe('zh-CN');
    expect(legoTerrainConfig.texts.title).toBe('地形转 LEGO 高度图');
    expect(legoTerrainConfig.texts.saveHeightmap).toBe('保存高度图');
  });

  it('defines the same keys for every supported locale and namespace', () => {
    for (const namespace of namespaces) {
      const chineseKeys = Object.keys(resources['zh-CN'][namespace]).sort();
      for (const locale of supportedLocales) {
        expect(resources[locale], locale).toBeDefined();
        expect(Object.keys(resources[locale]![namespace]).sort(), `${locale}:${namespace}`).toEqual(chineseKeys);
      }
    }
  });

  it('resolves every semantic key used by source code and configuration', () => {
    const configuredKeys = [
      rawAppConfig,
      rawPixelArtConfig,
      rawTerrainConfig,
      rawLegoTerrainConfig,
      rawLegoDesignConfig,
    ].flatMap(collectSemanticKeys);
    const sourceKeys = Object.values(sourceFiles).flatMap((source) => [
      ...source.matchAll(/['"]([a-z][A-Za-z0-9]*:[^'"]+)['"]/g),
    ].map((match) => match[1]));

    for (const translationKey of new Set([...configuredKeys, ...sourceKeys])) {
      const [namespace, key] = translationKey.split(':', 2);
      expect(namespaces, translationKey).toContain(namespace);
      expect(resources['zh-CN'][namespace as keyof typeof resources['zh-CN']], translationKey).toHaveProperty(key);
      expect(resources['en-US'][namespace as keyof typeof resources['en-US']], translationKey).toHaveProperty(key);
      expect(resources['en-XA']![namespace as keyof NonNullable<typeof resources['en-XA']>], translationKey).toHaveProperty(key);
    }
  });
});

function collectSemanticKeys(value: unknown): string[] {
  if (typeof value === 'string') return /^[a-z][A-Za-z0-9]*:.+/.test(value) ? [value] : [];
  if (Array.isArray(value)) return value.flatMap(collectSemanticKeys);
  if (value && typeof value === 'object') return Object.values(value).flatMap(collectSemanticKeys);
  return [];
}
