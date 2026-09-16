import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider } from 'react-i18next';
import { afterAll, describe, expect, it } from 'vitest';

import i18n from '../../i18n';
import { ComponentStarButton } from '../ComponentStarButton';

describe('ComponentStarButton', () => {
  afterAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  it.each([
    { locale: 'zh-CN', starred: false, label: '收藏组件' },
    { locale: 'zh-CN', starred: true, label: '取消收藏' },
    { locale: 'en-US', starred: false, label: 'Star component' },
    { locale: 'en-US', starred: true, label: 'Unstar component' },
  ])('uses a localized accessible name and native keyboard button semantics: $locale $starred', async ({ locale, starred, label }) => {
    await i18n.changeLanguage(locale);
    const markup = renderToStaticMarkup(
      <I18nextProvider i18n={i18n}>
        <ComponentStarButton onClick={() => undefined} starred={starred}>3</ComponentStarButton>
      </I18nextProvider>,
    );

    expect(markup).toContain(`<button aria-label="${label}" aria-pressed="${starred}"`);
    expect(markup).toContain('type="button"');
    expect(markup).not.toContain('tabindex="-1"');
  });
});
