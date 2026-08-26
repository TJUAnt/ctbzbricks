import React from 'react';
import ReactDOM from 'react-dom/client';
import type { Root as ReactRoot } from 'react-dom/client';
import {
  Bell,
  Box,
  Boxes,
  ChevronDown,
  ChevronRight,
  Database,
  HelpCircle,
  Home,
  Image as ImageIcon,
  Languages,
  Map,
  Search,
  Upload,
  User,
  Wand2,
} from 'lucide-react';
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import appConfig from './app/appConfig';
import { ModelAssetsPage } from './assets/ModelAssetsPage';
import { ModelViewerPage } from './assets/ModelViewerPage';
import type { ModelAsset } from './assets/modelAssetApi';
import { requestJson } from './api/client';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { ComponentCandidateWorkbenchPage } from './componentRepo/ComponentCandidateWorkbenchPage';
import { ComponentImportPage } from './componentRepo/ComponentImportPage';
import { ComponentImportHistoryPage } from './componentRepo/ComponentImportHistoryPage';
import { ComponentImportStatusPage } from './componentRepo/ComponentImportStatusPage';
import { ComponentRepoPage } from './componentRepo/ComponentRepoPage';
import { ComponentDetailPage } from './componentRepo/ComponentDetailPage';
import { LegoDesignPage } from './legoDesign/LegoDesignPage';
import { LegoTerrainBuilderPage } from './legoTerrain/LegoTerrainBuilderPage';
import { DirectModelImportPage } from './modelImport/DirectModelImportPage';
import { PartSearchPage } from './parts/PartSearchPage';
import { PartViewerPage } from './parts/PartViewerPage';
import { PixelArtPage } from './pixelArt/PixelArtPage';
import { PixelArtProjectsPage } from './pixelArt/PixelArtProjectsPage';
import { TerrainDemPage } from './terrain/TerrainDemPage';
import i18n, {
  productLocales,
  resolvedLocale,
  useAppTranslation,
  useDynamicTranslation,
  type TranslationKey,
} from './i18n';
import i18nCatalog from './i18n/catalog.json';
import { formatNumber } from './i18n/formatters';
import { I18nextProvider } from 'react-i18next';
import './styles.css';

const iconByName = {
  bell: Bell,
  box: Box,
  boxes: Boxes,
  cube: Box,
  database: Database,
  help: HelpCircle,
  home: Home,
  image: ImageIcon,
  map: Map,
  search: Search,
  upload: Upload,
  user: User,
  wand: Wand2,
};

type IconName = keyof typeof iconByName;
type PageKey = keyof typeof appConfig.pages;
type RoutePaths = Record<PageKey, string>;

type MenuItemConfig = {
  id: string;
  icon: IconName;
  label: string;
  page: PageKey;
};

type MenuGroupConfig = {
  id: string;
  icon: IconName;
  items: MenuItemConfig[];
  title: string;
  tone: string;
};

type DashboardCardConfig = {
  action: string;
  features: string[];
  icon: IconName;
  id: string;
  page: PageKey;
  title: string;
  tone: string;
  visual: string;
};

type DashboardSectionConfig = {
  cards: DashboardCardConfig[];
  icon: IconName;
  id: string;
  title: string;
  tone: string;
};

type DashboardConfig = {
  heroIcon: IconName;
  sections: DashboardSectionConfig[];
  welcomeSubtitle: string;
  welcomeTitle: string;
};

const routePaths = appConfig.routePaths as RoutePaths;
const menuGroups = appConfig.menuGroups as MenuGroupConfig[];
const dashboardConfig = appConfig.dashboard as DashboardConfig;

function Root() {
  return (
    <I18nextProvider i18n={i18n}>
      <App />
    </I18nextProvider>
  );
}

function App() {
  useAppTranslation();
  return (
    <AuthProvider>
      <BrowserRouter>
        <WorkbenchShell />
      </BrowserRouter>
    </AuthProvider>
  );
}

function WorkbenchShell() {
  const [selectedModelAsset, setSelectedModelAsset] = React.useState<ModelAsset | null>(null);

  return (
    <main className="workbench">
      <WorkbenchTopbar />
      <aside className="workbench-nav">
        <WorkbenchNav clearSelectedModel={() => setSelectedModelAsset(null)} />
      </aside>

      <section className="workbench-content">
        <WorkbenchRoutes
          clearSelectedModel={() => setSelectedModelAsset(null)}
          openAsset={(asset) => setSelectedModelAsset(asset)}
          selectedModelAsset={selectedModelAsset}
        />
      </section>
    </main>
  );
}

function WorkbenchTopbar() {
  const { error, isConfigured, isLoading, signInWithGoogle, signOut, user } = useAuth();
  const userLabel = authUserLabel(user?.email ?? null, isConfigured, isLoading);
  const userAction = user ? signOut : signInWithGoogle;

  return (
    <header className="workbench-topbar">
      <NavLink
        aria-label={appConfig.topbar.homeLabel}
        className="workbench-brand"
        to={routePathFor(appConfig.pages.dashboard as PageKey)}
      >
        <span className="brand-mark">
          <Boxes aria-hidden="true" />
        </span>
        <span>
          <strong>{appConfig.texts.appTitle}</strong>
          <em>{appConfig.texts.appSubtitle}</em>
        </span>
      </NavLink>

      <div className="topbar-actions">
        <LanguageSwitcher />
        <NavLink
          aria-label={appConfig.topbar.homeLabel}
          className="topbar-icon-button"
          to={routePathFor(appConfig.pages.dashboard as PageKey)}
        >
          <Home aria-hidden="true" />
        </NavLink>
        <button aria-label={appConfig.topbar.helpLabel} className="topbar-icon-button" type="button">
          <HelpCircle aria-hidden="true" />
        </button>
        <button aria-label={appConfig.topbar.notificationLabel} className="topbar-icon-button" type="button">
          <Bell aria-hidden="true" />
          <span>{appConfig.topbar.notificationCount}</span>
        </button>
        <button
          aria-label={userLabel}
          className="topbar-user-button"
          disabled={!isConfigured || isLoading}
          onClick={() => {
            void userAction();
          }}
          title={error ?? undefined}
          type="button"
        >
          <span className="topbar-avatar">
            <User aria-hidden="true" />
          </span>
          <span className="topbar-user-label">{userLabel}</span>
          <ChevronDown aria-hidden="true" className="topbar-user-chevron" />
        </button>
      </div>
    </header>
  );
}

function LanguageSwitcher() {
  const tr = useAppTranslation();
  const translateLocale = useDynamicTranslation();
  const locale = resolvedLocale();

  return (
    <label className="topbar-language-select">
      <Languages aria-hidden="true" />
      <span className="sr-only">{tr('common:changeLanguage')}</span>
      <select
        aria-label={tr('common:changeLanguage')}
        onChange={(event) => {
          void i18n.changeLanguage(event.target.value);
        }}
        value={locale}
      >
        {productLocales.map((productLocale) => (
          <option key={productLocale} value={productLocale}>
            {translateLocale(
              i18nCatalog.localeLabelKeys[
                productLocale as keyof typeof i18nCatalog.localeLabelKeys
              ] as TranslationKey,
            )}
          </option>
        ))}
        {import.meta.env.DEV ? <option value="en-XA">{tr('common:pseudoEnglish')}</option> : null}
      </select>
    </label>
  );
}

function WorkbenchNav({
  clearSelectedModel,
}: {
  clearSelectedModel: () => void;
}) {
  return (
    <nav className="workbench-menu" aria-label={appConfig.texts.appTitle}>
      {menuGroups.map((group) => (
        <section className="menu-group" key={group.id}>
          <div className={`menu-title menu-title-${group.tone}`}>
            <Icon name={group.icon} />
            <span>{group.title}</span>
            <ChevronDown aria-hidden="true" />
          </div>
          {group.items.map((item) => (
            <MenuLink
              icon={item.icon}
              key={item.id}
              label={item.label}
              onNavigate={clearSelectedModel}
              page={item.page}
              tone={group.tone}
            />
          ))}
        </section>
      ))}
      <div className="menu-brick-scene" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </nav>
  );
}

function MenuLink({
  icon,
  label,
  onNavigate,
  page,
  tone,
}: {
  icon: IconName;
  label: string;
  onNavigate: () => void;
  page: PageKey;
  tone: string;
}) {
  return (
    <NavLink
      className={({ isActive }) =>
        isActive ? `menu-button menu-button-${tone} menu-button-active` : `menu-button menu-button-${tone}`
      }
      onClick={onNavigate}
      to={routePathFor(page)}
    >
      <Icon name={icon} />
      <span>{label}</span>
    </NavLink>
  );
}

function WorkbenchRoutes({
  clearSelectedModel,
  openAsset,
  selectedModelAsset,
}: {
  clearSelectedModel: () => void;
  openAsset: (asset: ModelAsset) => void;
  selectedModelAsset: ModelAsset | null;
}) {
  const navigate = useNavigate();

  if (selectedModelAsset) {
    return (
      <ModelViewerPage
        modelAsset={selectedModelAsset}
        onBack={() => {
          clearSelectedModel();
          navigate(routePathFor(appConfig.pages.modelAssets as PageKey));
        }}
      />
    );
  }

  return (
    <Routes>
      <Route
        element={<Navigate replace to={routePathFor(appConfig.initialPage as PageKey)} />}
        path={appConfig.router.rootPath}
      />
      <Route element={<DashboardPage />} path={routePathFor(appConfig.pages.dashboard as PageKey)} />
      <Route element={<DirectModelImportPage />} path={routePathFor(appConfig.pages.directImport as PageKey)} />
      <Route element={<TerrainDemPage />} path={routePathFor(appConfig.pages.demBuilder as PageKey)} />
      <Route
        element={<ModelAssetsPage onOpenAsset={openAsset} />}
        path={routePathFor(appConfig.pages.modelAssets as PageKey)}
      />
      <Route element={<LegoTerrainBuilderPage />} path={routePathFor(appConfig.pages.legoBuilder as PageKey)} />
      <Route element={<LegoDesignPage />} path={routePathFor(appConfig.pages.legoDesign as PageKey)} />
      <Route element={<PixelArtPage />} path={routePathFor(appConfig.pages.pixelArt as PageKey)} />
      <Route element={<PixelArtProjectsPage />} path={routePathFor(appConfig.pages.pixelArtProjects as PageKey)} />
      <Route element={<PartSearchPage />} path={routePathFor(appConfig.pages.partSearch as PageKey)} />
      <Route element={<PartViewerPage />} path={routePathFor(appConfig.pages.partViewer as PageKey)} />
      <Route element={<ComponentRepoPage />} path={routePathFor(appConfig.pages.componentRepo as PageKey)} />
      <Route element={<ComponentImportPage />} path={routePathFor(appConfig.pages.componentRepoImport as PageKey)} />
      <Route
        element={<ComponentImportHistoryPage />}
        path={routePathFor(appConfig.pages.componentRepoImportHistory as PageKey)}
      />
      <Route
        element={<ComponentImportStatusPage />}
        path={routePathFor(appConfig.pages.componentRepoImportStatus as PageKey)}
      />
      <Route
        element={<ComponentCandidateWorkbenchPage />}
        path={routePathFor(appConfig.pages.componentRepoCandidate as PageKey)}
      />
      <Route
        element={<ComponentDetailPage />}
        path={routePathFor(appConfig.pages.componentRepoDetail as PageKey)}
      />
      <Route
        element={<Navigate replace to={routePathFor(appConfig.initialPage as PageKey)} />}
        path={appConfig.router.unmatchedPath}
      />
    </Routes>
  );
}

export function DashboardPage() {
  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-welcome">
          <span className="dashboard-hero-icon">
            <Icon name={dashboardConfig.heroIcon} />
          </span>
          <div>
            <h1>{dashboardConfig.welcomeTitle}</h1>
            <p>{dashboardConfig.welcomeSubtitle}</p>
          </div>
        </div>
        <div className="dashboard-hero-model" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </div>
      </header>

      <div className="dashboard-sections">
        {dashboardConfig.sections.map((section) => (
          <DashboardSection key={section.id} section={section} />
        ))}
      </div>
      <I18nHealthPanel />
    </section>
  );
}

type I18nMetrics = {
  unknownKeyCount: number;
  unknownApiCodeCount: number;
  localeFallbackCount: number;
  metricOverflowCount: number;
  hourly: Array<{ hour: string; count: number }>;
};

function I18nHealthPanel() {
  const t = useAppTranslation();
  const [metrics, setMetrics] = React.useState<I18nMetrics | null>(null);
  const [unavailable, setUnavailable] = React.useState(false);
  React.useEffect(() => {
    let active = true;
    void requestJson<I18nMetrics>('/api/i18n/metrics')
      .then((value) => { if (active) setMetrics(value); })
      .catch(() => { if (active) setUnavailable(true); });
    return () => { active = false; };
  }, []);
  const latestHour = metrics?.hourly[metrics.hourly.length - 1]?.hour;
  const values = metrics ? [
    [t('app:dashboard.i18nHealth.unknownKeys'), metrics.unknownKeyCount],
    [t('app:dashboard.i18nHealth.unknownApiCodes'), metrics.unknownApiCodeCount],
    [t('app:dashboard.i18nHealth.localeFallbacks'), metrics.localeFallbackCount],
    [t('app:dashboard.i18nHealth.metricOverflow'), metrics.metricOverflowCount],
  ] as const : [];
  return (
    <section className="dashboard-i18n-health">
      <div>
        <h2>{t('app:dashboard.i18nHealth.title')}</h2>
        <p>{t('app:dashboard.i18nHealth.subtitle')}</p>
      </div>
      {unavailable ? <p>{t('app:dashboard.i18nHealth.unavailable')}</p> : null}
      {metrics ? (
        <>
          <div className="dashboard-i18n-metrics">
            {values.map(([label, value]) => (
              <div key={label}><span>{label}</span><strong>{formatNumber(value)}</strong></div>
            ))}
          </div>
          {latestHour ? <small>{t('app:dashboard.i18nHealth.latestHour', { hour: latestHour })}</small> : null}
        </>
      ) : null}
    </section>
  );
}

function DashboardSection({ section }: { section: DashboardSectionConfig }) {
  return (
    <section className={`dashboard-section dashboard-section-${section.tone}`}>
      <div className={`dashboard-section-tab dashboard-section-tab-${section.tone}`}>
        <Icon name={section.icon} />
        <span>{section.title}</span>
      </div>
      <div className={`dashboard-card-grid dashboard-card-grid-${section.cards.length}`}>
        {section.cards.map((card) => (
          <DashboardCard card={card} key={card.id} />
        ))}
      </div>
    </section>
  );
}

function DashboardCard({ card }: { card: DashboardCardConfig }) {
  return (
    <NavLink className={`dashboard-card dashboard-card-${card.tone}`} to={routePathFor(card.page)}>
      <h2>{card.title}</h2>
      <DashboardVisual card={card} />
      <div className="dashboard-card-body">
        <ul>
          {card.features.map((feature) => (
            <li key={feature}>{feature}</li>
          ))}
        </ul>
        <span className={`dashboard-card-action dashboard-card-action-${card.tone}`}>
          {card.action}
          <ChevronRight aria-hidden="true" />
        </span>
      </div>
    </NavLink>
  );
}

function DashboardVisual({ card }: { card: DashboardCardConfig }) {
  return (
    <div className={`dashboard-card-visual dashboard-visual-${card.visual}`}>
      <span className="dashboard-visual-base">
        <Icon name={card.icon} />
      </span>
      <span className="dashboard-visual-stud" />
      <span className="dashboard-visual-stud" />
      <span className="dashboard-visual-stud" />
    </div>
  );
}

function Icon({ name }: { name: IconName }) {
  const IconComponent = iconByName[name];
  if (!IconComponent) {
    throw new Error(appConfig.errors.unknownIcon);
  }
  return <IconComponent aria-hidden="true" />;
}

function routePathFor(page: PageKey) {
  const routePath = routePaths[page];
  if (!routePath) {
    throw new Error(appConfig.errors.unknownRoute);
  }
  return routePath;
}

function authUserLabel(email: string | null, isConfigured: boolean, isLoading: boolean): string {
  if (!isConfigured) {
    return appConfig.topbar.authNotConfiguredLabel;
  }
  if (isLoading) {
    return appConfig.texts.loading;
  }
  return email ?? appConfig.topbar.authSignInLabel;
}

if (typeof document !== 'undefined') {
  const rootElement = document.getElementById('root');
  if (rootElement) {
    const root = (import.meta.hot?.data.brickBuilderRoot as ReactRoot | undefined)
      ?? ReactDOM.createRoot(rootElement);
    if (import.meta.hot) {
      import.meta.hot.data.brickBuilderRoot = root;
    }
    root.render(<Root />);
  }
}
