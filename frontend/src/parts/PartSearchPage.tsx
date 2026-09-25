import React from 'react';
import { Box, Boxes, Search } from 'lucide-react';
import { create } from 'zustand';
import { Link } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { authenticatedRequestJson } from '../api/authenticatedClient';
import { resolvedLocale, useAppTranslation } from '../i18n';
import { formatNumber } from '../i18n/formatters';
import appConfig from '../app/appConfig';
import { loadGlbThumbnailBlob, type GlbThumbnailModel } from '../preview/glbThumbnailRenderer';

type PartSearchItem = {
  ldrawPartNum: string;
  name: string;
  imageUrl: string | null;
  previewModel: GlbThumbnailModel | null;
  logicalSize: {
    widthStud: number;
    depthStud: number;
    heightPlate: number;
  } | null;
  logicalSizeDerivationStatus: 'derived_exact' | 'derived_approximate';
};

type RecallColumnCount = 2 | 3 | 4 | 5 | 6;

type PartSearchResponse = {
  partLibraryVersionId: string;
  total: number;
  returned: number;
  page: number;
  pageSize: number;
  totalPages: number;
  items: PartSearchItem[];
};

type RecallState = {
  description: string;
  partNumber: string;
  widthStud: string;
  depthStud: string;
  heightPlate: string;
  page: number;
  loading: boolean;
  error: string | null;
  response: PartSearchResponse | null;
  setFilter: (field: 'description' | 'partNumber' | 'widthStud' | 'depthStud' | 'heightPlate', value: string) => void;
  recall: (page?: number) => Promise<void>;
};

const rowsPerPage = 4;
const columnsPerRow: RecallColumnCount = 5;

const useRecallStore = create<RecallState>((set, get) => ({
  description: '',
  partNumber: '',
  widthStud: '',
  depthStud: '',
  heightPlate: '',
  page: 1,
  loading: false,
  error: null,
  response: null,
  setFilter: (field, value) => set({ [field]: value } as Pick<RecallState, typeof field>),
  recall: async (requestedPage) => {
    const state = get();
    const page = requestedPage ?? state.page;
    set({ loading: true, error: null });
    try {
      const result = await authenticatedRequestJson<PartSearchResponse>(appConfig.componentRepoApi.partSearch, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: state.description.trim(),
          partNumber: state.partNumber.trim(),
          widthStud: optionalPositiveNumber(state.widthStud),
          depthStud: optionalPositiveNumber(state.depthStud),
          heightPlate: optionalPositiveNumber(state.heightPlate),
          locale: resolvedLocale(),
          page,
          pageSize: columnsPerRow * rowsPerPage,
        }),
      });
      set({ response: result, page: result.page, loading: false });
    } catch (error) {
      set({ error: errorMessage(error, 'common.unknown'), loading: false });
    }
  },
}));

/** PartSearchPage 只调用 Go Part Library 搜索与版本化 Part 详情，不再依赖 legacy fitting recall 路由。 */
export function PartSearchPage() {
  const tr = useAppTranslation();
  const state = useRecallStore();

  React.useEffect(() => {
    void state.recall(1);
  }, []);

  return (
    <main className="min-h-screen bg-zinc-100 text-zinc-950">
      <section className="border-b border-zinc-200 bg-white">
        <div className="mx-auto max-w-7xl px-5 py-6">
          <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-full bg-zinc-100 px-3 py-1 text-xs font-medium text-zinc-600">
                <Boxes className="h-3.5 w-3.5" />
                {tr('partSearch:mixedRecall')}
              </div>
              <h1 className="text-2xl font-semibold tracking-tight">{tr('partSearch:partSearch')}</h1>
              <p className="mt-1 max-w-2xl text-sm text-zinc-500">{tr('partSearch:subtitle')}</p>
            </div>
            <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 text-right">
              <div className="text-2xl font-semibold tabular-nums">{formatNumber(state.response?.total ?? 0)}</div>
              <div className="text-xs text-zinc-500">{tr('partSearch:matchedCandidates')}</div>
            </div>
          </div>

          <form
            className="mt-6 rounded-xl border border-zinc-200 bg-zinc-50 p-4"
            onSubmit={(event) => {
              event.preventDefault();
              void state.recall(1);
            }}
          >
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-5">
              <label className="min-w-0 lg:col-span-2">
                <span className="mb-1 block text-xs font-medium text-zinc-600">{tr('partSearch:description')}</span>
                <input
                  className="h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm outline-none transition placeholder:text-zinc-400 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950"
                  onChange={(event) => state.setFilter('description', event.target.value)}
                  placeholder={tr('partSearch:descriptionPlaceholder')}
                  type="search"
                  value={state.description}
                />
              </label>
              <label className="min-w-0">
                <span className="mb-1 block text-xs font-medium text-zinc-600">{tr('partSearch:partNumber')}</span>
                <input
                  className="h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm outline-none transition placeholder:text-zinc-400 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950"
                  onChange={(event) => state.setFilter('partNumber', event.target.value)}
                  placeholder={tr('partSearch:partNumberPlaceholder')}
                  type="search"
                  value={state.partNumber}
                />
              </label>
              <DimensionInput label={tr('partSearch:widthStud')} onChange={(value) => state.setFilter('widthStud', value)} value={state.widthStud} />
              <DimensionInput label={tr('partSearch:depthStud')} onChange={(value) => state.setFilter('depthStud', value)} value={state.depthStud} />
              <DimensionInput label={tr('partSearch:heightPlate')} onChange={(value) => state.setFilter('heightPlate', value)} value={state.heightPlate} />
              <button
                className="inline-flex h-11 items-center justify-center gap-2 self-end rounded-lg bg-blue-600 px-6 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60 lg:col-span-2"
                disabled={state.loading}
                type="submit"
              >
                <Search className="h-4 w-4" />
                {state.loading ? tr('partSearch:recalling') : tr('partSearch:recall')}
              </button>
            </div>
            <p className="mt-3 text-xs text-zinc-500">{tr('partSearch:sizeSearchHint')}</p>
          </form>

          {state.error ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {state.error}
            </div>
          ) : null}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-6">
        {state.loading && !state.response ? <RecallSkeleton columns={columnsPerRow} /> : null}
        {!state.loading && state.response?.total === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 bg-white px-6 py-16 text-center">
            <Search className="mx-auto h-8 w-8 text-zinc-300" />
            <h2 className="mt-3 text-base font-medium">{tr('partSearch:noMatches')}</h2>
            <p className="mt-1 text-sm text-zinc-500">{tr('partSearch:noMatchesHint')}</p>
          </div>
        ) : null}
        <div className={`grid gap-3 sm:grid-cols-2 ${recallGridColumns[columnsPerRow]}`}>
          {(state.response?.items ?? []).map((candidate) => (
            <CandidateCard
              candidate={candidate}
              key={candidate.ldrawPartNum}
              partLibraryVersionId={state.response?.partLibraryVersionId ?? null}
            />
          ))}
        </div>
        {state.response && state.response.totalPages > 1 ? (
          <div className="mt-6 flex items-center justify-center gap-3">
            <button
              className="h-9 rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-700 transition hover:border-zinc-500 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={state.loading || state.page <= 1}
              onClick={() => void state.recall(state.page - 1)}
              type="button"
            >
              {tr('partSearch:prev')}
            </button>
            <span className="min-w-20 text-center text-sm tabular-nums text-zinc-500">
              {formatNumber(state.page)} / {formatNumber(state.response.totalPages)}
            </span>
            <button
              className="h-9 rounded-lg border border-zinc-300 bg-white px-4 text-sm font-medium text-zinc-700 transition hover:border-zinc-500 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={state.loading || state.page >= state.response.totalPages}
              onClick={() => void state.recall(state.page + 1)}
              type="button"
            >
              {tr('partSearch:next')}
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function CandidateCard({
  candidate,
  partLibraryVersionId,
}: {
  candidate: PartSearchItem;
  partLibraryVersionId: string | null;
}) {
  const tr = useAppTranslation();
  const content = (
    <>
      <div className="flex aspect-square items-center justify-center overflow-hidden rounded-lg bg-zinc-200">
        <CandidateImage
          alt={candidate.name}
          model={candidate.previewModel}
          src={candidate.imageUrl}
        />
      </div>
      <h2 className="mt-3 break-words text-sm font-semibold leading-5 text-zinc-900">
        {candidate.name}
      </h2>
      <div className="mt-1 break-all text-xs text-zinc-400">{candidate.ldrawPartNum}</div>
      {candidate.logicalSize ? (
        <div className="mt-2 text-xs tabular-nums text-zinc-500">
          {tr('partSearch:sizeValue', {
            width: formatNumber(candidate.logicalSize.widthStud),
            depth: formatNumber(candidate.logicalSize.depthStud),
            height: formatNumber(candidate.logicalSize.heightPlate),
          })}
          <span className="ml-1 text-zinc-400">
            ({candidate.logicalSizeDerivationStatus === 'derived_exact'
              ? tr('partSearch:sizeNominal')
              : tr('partSearch:sizeBoundingBox')})
          </span>
        </div>
      ) : null}
    </>
  );
  const className = "block overflow-hidden rounded-xl border border-zinc-200 bg-white p-3 shadow-sm transition hover:-translate-y-0.5 hover:border-zinc-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-950 focus-visible:ring-offset-2";
  if (!partLibraryVersionId) {
    return <article aria-disabled="true" className={`${className} opacity-60`}>{content}</article>;
  }
  return (
    <Link
      className={className}
      to={`/parts/${encodeURIComponent(partLibraryVersionId)}/${encodeURIComponent(candidate.ldrawPartNum)}`}
    >
      {content}
    </Link>
  );
}

function DimensionInput({ label, onChange, value }: { label: string; onChange: (value: string) => void; value: string }) {
  return (
    <label className="min-w-0">
      <span className="mb-1 block text-xs font-medium text-zinc-600">{label}</span>
      <input
        className="h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm outline-none transition placeholder:text-zinc-400 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950"
        min="0.1"
        onChange={(event) => onChange(event.target.value)}
        step="0.1"
        type="number"
        value={value}
      />
    </label>
  );
}

function optionalPositiveNumber(value: string): number | undefined {
  const normalized = value.trim();
  return normalized === '' ? undefined : Number(normalized);
}

/** CandidateImage 进入视口附近才下载 GLB，并只展示共享渲染器生成的静态图像。 */
function CandidateImage({ alt, model, src }: { alt: string; model: GlbThumbnailModel | null; src: string | null }) {
  const mountRef = React.useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = React.useState(false);
  const [generatedURL, setGeneratedURL] = React.useState<string | null>(null);
  const [failed, setFailed] = React.useState(false);

  React.useEffect(() => {
    const mount = mountRef.current;
    if (!mount || src || !model) return undefined;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '400px' },
    );
    observer.observe(mount);
    return () => observer.disconnect();
  }, [model?.artifactId, src]);

  React.useEffect(() => {
    setFailed(false);
    setGeneratedURL(null);
    if (src || !model || !visible) return undefined;
    const controller = new AbortController();
    let objectURL: string | null = null;
    void loadGlbThumbnailBlob(model, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectURL = URL.createObjectURL(blob);
        setGeneratedURL(objectURL);
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === 'AbortError')) setFailed(true);
      });
    return () => {
      controller.abort();
      if (objectURL) URL.revokeObjectURL(objectURL);
    };
  }, [model?.artifactId, model?.sha256, model?.url, src, visible]);

  const imageURL = src ?? generatedURL;
  if (!imageURL || failed) {
    return (
      <div className="flex h-full w-full items-center justify-center" ref={mountRef}>
        <Box className={`h-12 w-12 text-amber-300 ${visible && model && !failed ? 'animate-pulse' : ''}`} />
      </div>
    );
  }
  return (
    <img
      alt={alt}
      className="h-full w-full object-contain p-3"
      decoding="async"
      loading="lazy"
      onError={() => setFailed(true)}
      src={imageURL}
    />
  );
}

const recallGridColumns: Record<RecallColumnCount, string> = {
  2: `lg:grid-cols-2`,
  3: `lg:grid-cols-3`,
  4: `lg:grid-cols-4`,
  5: `lg:grid-cols-5`,
  6: `lg:grid-cols-6`,
};

function RecallSkeleton({ columns }: { columns: RecallColumnCount }) {
  return (
    <div className={`grid gap-3 sm:grid-cols-2 ${recallGridColumns[columns]}`}>
      {Array.from({ length: 6 }, (_, index) => (
        <div className="aspect-[4/5] animate-pulse rounded-xl border border-zinc-200 bg-white" key={index} />
      ))}
    </div>
  );
}
