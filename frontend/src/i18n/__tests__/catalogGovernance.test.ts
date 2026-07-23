import { describe, expect, it } from 'vitest';

import catalog from '../catalog.json';
import { normalizeLocale, productLocales, resolveLocaleForCatalog, textDirection } from '../index';

describe('catalog-driven language expansion', () => {
  it('resolves the Japanese validation locale without language-specific business logic', () => {
    const validationCatalog = [...productLocales, ...catalog.validationLocales];
    expect(resolveLocaleForCatalog('ja', validationCatalog, catalog.defaultLocale, catalog.localeAliases)).toBe('ja-JP');
    expect(resolveLocaleForCatalog('ja_JP', validationCatalog, catalog.defaultLocale, catalog.localeAliases)).toBe('ja-JP');
    expect(normalizeLocale('ja-JP')).toBe(catalog.defaultLocale);
  });

  it('uses platform Japanese date and number rules', () => {
    const date = new Intl.DateTimeFormat('ja-JP', {
      year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
    }).format(new Date('2026-07-18T00:00:00Z'));
    expect(date).toContain('2026年');
    expect(new Intl.NumberFormat('ja-JP').format(1234567)).toContain('1,234,567');
  });

  it('derives RTL direction from catalog metadata', () => {
    expect(textDirection('ar-XB')).toBe('rtl');
    expect(textDirection('ja-JP')).toBe('ltr');
  });
});
