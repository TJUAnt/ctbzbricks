import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterAll, describe, expect, it } from 'vitest';

import i18n from '../../i18n';
import { ComponentImportStatusPage } from '../ComponentImportStatusPage';

describe('ComponentImportStatusPage durable progress', () => {
  afterAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  it.each([
    { locale: 'zh-CN', upload: '文件上传', parse: '解析与零件清单', preview: '3D 预览' },
    { locale: 'en-US', upload: 'File upload', parse: 'Parsing and parts list', preview: '3D preview' },
  ])('renders the three persistent processing stages in $locale', async ({ locale, upload, parse, preview }) => {
    await i18n.changeLanguage(locale);
    const markup = renderToStaticMarkup(
      <I18nextProvider i18n={i18n}>
        <MemoryRouter initialEntries={['/component-repo/imports/import-1']}>
          <Routes>
            <Route element={<ComponentImportStatusPage />} path="/component-repo/imports/:importId" />
          </Routes>
        </MemoryRouter>
      </I18nextProvider>,
    );

    expect(markup).toContain(upload);
    expect(markup).toContain(parse);
    expect(markup).toContain(preview);
    expect(markup).toContain('role="progressbar"');
    expect(markup).toContain('aria-valuenow="15"');
  });
});
