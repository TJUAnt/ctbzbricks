import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterAll, describe, expect, it } from 'vitest';

import { ComponentRepoPage } from '../../componentRepo/ComponentRepoPage';
import { ComponentWatchListPage } from '../../componentRepo/ComponentWatchListPage';
import { LegoDesignPage } from '../../archive/dem/LegacyLegoDesignPage';
import { LegoTerrainBuilderPage } from '../../archive/dem/LegoTerrainBuilderPage';
import { PartSearchPage } from '../../parts/PartSearchPage';
import { PartViewerPage } from '../../parts/PartViewerPage';
import { PixelArtProjectsPage } from '../../pixelArt/PixelArtProjectsPage';
import { TerrainDemPage } from '../../archive/dem/TerrainDemPage';
import { DashboardPage } from '../../main';
import i18n from '../index';

const pages = [
  { component: <DashboardPage />, english: 'Welcome back, Brick Master!', chinese: '欢迎回来，Brick Master!' },
  { component: <PixelArtProjectsPage />, english: 'Saved Pixel Art', chinese: '已保存像素图' },
  { component: <TerrainDemPage />, english: 'Taiwan DEM Terrain', chinese: '台湾 DEM 地形' },
  { component: <LegoTerrainBuilderPage />, english: 'Terrain to LEGO Heightmap', chinese: '地形转 LEGO 高度图' },
  { component: <LegoDesignPage />, english: 'LEGO Design', chinese: 'LEGO 设计图' },
  { component: <ComponentRepoPage />, english: 'My models &amp; components', chinese: '我的模型组件' },
  { component: <ComponentWatchListPage />, english: 'Manage subscriptions', chinese: '管理订阅' },
  { component: <PartSearchPage />, english: 'Part search', chinese: '零件搜索' },
  { component: <PartViewerPage />, english: '3D Part Viewer', chinese: '零件 3D 查看器' },
];

describe('localized page shells', () => {
  afterAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  it.each(pages)('renders $english in both supported product languages', async ({ component, english, chinese }) => {
    await i18n.changeLanguage('zh-CN');
    expect(renderPage(component)).toContain(chinese);

    await i18n.changeLanguage('en-US');
    expect(renderPage(component)).toContain(english);
  });

  it('separates the public plaza from personal management and hides DEM entry points', async () => {
    await i18n.changeLanguage('en-US');
    const plaza = renderPage(<ComponentRepoPage mode="plaza" />);
    expect(plaza).toContain('Model plaza');
    expect(plaza).not.toContain('component-library-upload-button');
    expect(plaza).toContain('component-library-tabs');
    expect(plaza).toContain('Public');
    expect(plaza).toContain('Subscriptions');
    const dashboard = renderPage(<DashboardPage />);
    expect(dashboard).toContain('/model-plaza');
    expect(dashboard).not.toContain('/dem-builder');
    expect(dashboard).not.toContain('/lego-builder');
    expect(renderPage(<LegoDesignPage />)).not.toContain('Choose DEM');
  });

  it('selects the immutable Part detail shell from its library version and number', async () => {
    await i18n.changeLanguage('en-US');
    const markup = renderToStaticMarkup(
      <I18nextProvider i18n={i18n}>
        <MemoryRouter initialEntries={['/parts/00000000-0000-0000-0000-000000000001/10247.dat']}>
          <Routes>
            <Route element={<PartViewerPage />} path="/parts/:partLibraryVersionId/:ldrawPartNum" />
          </Routes>
        </MemoryRouter>
      </I18nextProvider>,
    );

    expect(markup).toContain('3D Part Viewer');
    expect(markup).toContain('Loading item');
  });

  it('localizes the Component list occupied-size heading', async () => {
    await i18n.changeLanguage('zh-CN');
    expect(renderPage(<ComponentRepoPage />)).toContain('占用尺寸');

    await i18n.changeLanguage('en-US');
    expect(renderPage(<ComponentRepoPage />)).toContain('Occupied size');
  });

  it('renders the Watch Feed in the plaza subscription tab and keeps the management page separate', async () => {
    await i18n.changeLanguage('zh-CN');
    const chinese = renderPage(<ComponentRepoPage mode="plaza" />, '/model-plaza?tab=subscriptions');
    expect(chinese).toContain('个人订阅');
    expect(chinese).toContain('订阅更新');
    expect(chinese).toContain('最近 7 天');
    expect(chinese).toContain('最近 30 天');
    expect(chinese).toContain('最近 90 天');
    expect(renderPage(<ComponentWatchListPage />)).not.toContain('订阅更新');

    await i18n.changeLanguage('en-US');
    const english = renderPage(<ComponentRepoPage mode="plaza" />, '/model-plaza?tab=subscriptions');
    expect(english).toContain('Subscription Updates');
    expect(english).toContain('Last 7 days');
    expect(english).toContain('Last 30 days');
    expect(english).toContain('Last 90 days');
    expect(english).toContain('Manage subscriptions');
    expect(renderPage(<ComponentWatchListPage />)).not.toContain('Subscription Updates');
  });
});

function renderPage(component: React.ReactElement, initialEntry = '/'): string {
  return renderToStaticMarkup(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter initialEntries={[initialEntry]}>{component}</MemoryRouter>
    </I18nextProvider>,
  );
}
