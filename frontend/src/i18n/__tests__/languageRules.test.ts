import { afterAll, describe, expect, it } from 'vitest';

import i18n, { resolvedLocale, translate } from '../index';
import { formatDateTime, formatNumber, formatRelativeTime, intlLocale } from '../formatters';
import { pseudoLocalizeText } from '../resources/pseudoLocale';

describe('language rules', () => {
  afterAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  it('applies plural rules and requires interpolation values', async () => {
    await i18n.changeLanguage('en-US');
    expect(translate('partSearch:resultCount', { count: 1 })).toBe('1 result');
    expect(translate('partSearch:resultCount', { count: 2 })).toBe('2 results');
    expect(translate('componentRepo:uploadProgressValue', { percent: 42 })).toBe('Upload progress: 42%');

    await i18n.changeLanguage('zh-CN');
    expect(translate('partSearch:resultCount', { count: 2 })).toBe('共 2 个结果');
    expect(translate('componentRepo:uploadProgressValue', { percent: 42 })).toBe('上传进度：42%');
  });

  it('formats dates, numbers and relative time with an explicit locale', () => {
    const date = Date.UTC(2026, 6, 18, 12);
    expect(formatNumber(1234.5, undefined, 'en-US')).toBe('1,234.5');
    expect(formatDateTime(date, { dateStyle: 'long', timeZone: 'UTC' }, 'en-US')).toContain('July');
    expect(formatDateTime(date, { dateStyle: 'long', timeZone: 'UTC' }, 'zh-CN')).toContain('2026年');
    expect(formatRelativeTime(-1, 'day', { numeric: 'auto' }, 'en-US')).toBe('yesterday');
    expect(formatRelativeTime(-1, 'day', { numeric: 'auto' }, 'zh-CN')).toBe('昨天');
    expect(intlLocale('en-XA')).toBe('en-US');
  });

  it('generates an expanded pseudo-locale without changing interpolation tokens', async () => {
    const pseudo = pseudoLocalizeText('Upload {{count}} .io files');
    expect(pseudo).toContain('{{count}}');
    expect(pseudo).toContain('.io');
    expect(pseudo.length).toBeGreaterThan('Upload {{count}} .io files'.length);

    await i18n.changeLanguage('en-XA');
    expect(resolvedLocale()).toBe('en-XA');
    expect(translate('common:changeLanguage')).toMatch(/^\[!!/);
  });
});
