import React from 'react';
import { Box, Boxes, Ruler, Search, Shapes } from 'lucide-react';
import { create } from 'zustand';
import { Link } from 'react-router-dom';
import { errorMessage, requestJson } from '../api/client';
import { useAppTranslation } from '../i18n';
import { formatNumber } from '../i18n/formatters';

type RecallCandidate = {
  candidateType: 'part' | 'component' | 'submodel';
  candidateId: string;
  name: string | null;
  imageUrl: string | null;
};

type RecallColumnCount = 2 | 3 | 4 | 5 | 6;

type RecallResponse = {
  total: number;
  returned: number;
  page: number;
  pageSize: number;
  totalPages: number;
  includeIrregular: boolean;
  candidates: RecallCandidate[];
};

type RecallState = {
  lengthStud: string;
  widthStud: string;
  heightPlate: string;
  key: string;
  columnsPerRow: RecallColumnCount;
  page: number;
  allowPlanarRotation: boolean;
  loading: boolean;
  error: string | null;
  response: RecallResponse | null;
  setLengthStud: (value: string) => void;
  setWidthStud: (value: string) => void;
  setHeightPlate: (value: string) => void;
  setKey: (value: string) => void;
  setColumnsPerRow: (value: RecallColumnCount) => void;
  setAllowPlanarRotation: (value: boolean) => void;
  recall: (page?: number) => Promise<void>;
};

const rowsPerPage = 4;

const useRecallStore = create<RecallState>((set, get) => ({
  lengthStud: '4',
  widthStud: '2',
  heightPlate: '1',
  key: 'plate',
  columnsPerRow: 5,
  page: 1,
  allowPlanarRotation: true,
  loading: false,
  error: null,
  response: null,
  setLengthStud: (lengthStud) => set({ lengthStud }),
  setWidthStud: (widthStud) => set({ widthStud }),
  setHeightPlate: (heightPlate) => set({ heightPlate }),
  setKey: (key) => set({ key }),
  setColumnsPerRow: (columnsPerRow) => {
    set({ columnsPerRow, page: 1 });
    void get().recall(1);
  },
  setAllowPlanarRotation: (allowPlanarRotation) => set({ allowPlanarRotation }),
  recall: async (requestedPage) => {
    const state = get();
    const page = requestedPage ?? state.page;
    set({ loading: true, error: null });
    try {
      const result = await requestJson<RecallResponse>('/api/fitting/candidates/recall', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidateTypes: ['component', 'part'],
          logicalSize: {
            widthStud: Number(state.lengthStud),
            depthStud: Number(state.widthStud),
            heightPlate: Number(state.heightPlate),
            tolerance: 0,
          },
          key: state.key.trim() || undefined,
          allowPlanarRotation: state.allowPlanarRotation,
          includeIrregular: false,
          page,
          pageSize: state.columnsPerRow * rowsPerPage,
        }),
      });
      set({ response: result, page: result.page, loading: false });
    } catch (error) {
      set({ error: errorMessage(error, 'common.unknown'), loading: false });
    }
  },
}));

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
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)_auto] lg:items-end">
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-700">
                  <Ruler className="h-4 w-4" />
                  {tr('partSearch:dimensions')}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <DimensionInput
                    label={tr('partSearch:length')}
                    onChange={state.setLengthStud}
                    unit={tr('partSearch:stud')}
                    value={state.lengthStud}
                  />
                  <DimensionInput
                    label={tr('partSearch:width')}
                    onChange={state.setWidthStud}
                    unit={tr('partSearch:stud')}
                    value={state.widthStud}
                  />
                  <DimensionInput
                    label={tr('partSearch:height')}
                    onChange={state.setHeightPlate}
                    unit={tr('partSearch:plateUnit')}
                    value={state.heightPlate}
                  />
                </div>
              </div>

              <div>
                <div className="mb-2 flex items-center gap-2 text-sm font-medium text-zinc-700">
                  <Shapes className="h-4 w-4" />
                  {tr('partSearch:nameKey')}
                </div>
                <input
                  className="h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm outline-none transition placeholder:text-zinc-400 focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950"
                  onChange={(event) => state.setKey(event.target.value)}
                  placeholder={tr('partSearch:nameKeyPlaceholder')}
                  type="search"
                  value={state.key}
                />
              </div>

              <button
                className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-6 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
                disabled={state.loading}
                type="submit"
              >
                <Search className="h-4 w-4" />
                {state.loading ? tr('partSearch:recalling') : tr('partSearch:recall')}
              </button>
            </div>

            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-200 pt-3 text-sm">
              <label className="inline-flex items-center gap-2 text-zinc-600">
                <input
                  checked={state.allowPlanarRotation}
                  className="h-4 w-4 accent-zinc-950"
                  onChange={(event) => state.setAllowPlanarRotation(event.target.checked)}
                  type="checkbox"
                />
                {tr('partSearch:allowRotation')}
              </label>
              <div className="flex flex-wrap items-center gap-4">
                <span className="text-zinc-400">{tr('partSearch:exactDimensions')}</span>
                <label className="inline-flex items-center gap-2 text-zinc-600">
                  <span>{tr('partSearch:itemsPerRow')}</span>
                  <select
                    className="h-9 rounded-lg border border-zinc-300 bg-white px-3 font-medium text-zinc-800 outline-none focus:border-zinc-950 focus:ring-1 focus:ring-zinc-950"
                    onChange={(event) => state.setColumnsPerRow(Number(event.target.value) as RecallColumnCount)}
                    value={state.columnsPerRow}
                  >
                    {[2, 3, 4, 5, 6].map((count) => (
                      <option key={count} value={count}>{count}</option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </form>

          {state.error ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {state.error}
            </div>
          ) : null}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-6">
        {state.loading && !state.response ? <RecallSkeleton columns={state.columnsPerRow} /> : null}
        {!state.loading && state.response?.total === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 bg-white px-6 py-16 text-center">
            <Search className="mx-auto h-8 w-8 text-zinc-300" />
            <h2 className="mt-3 text-base font-medium">{tr('partSearch:noMatches')}</h2>
            <p className="mt-1 text-sm text-zinc-500">{tr('partSearch:noMatchesHint')}</p>
          </div>
        ) : null}
        <div className={`grid gap-3 sm:grid-cols-2 ${recallGridColumns[state.columnsPerRow]}`}>
          {(state.response?.candidates ?? []).map((candidate) => (
            <CandidateCard candidate={candidate} key={`${candidate.candidateType}:${candidate.candidateId}`} />
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

function DimensionInput({
  label,
  unit,
  value,
  onChange,
}: {
  label: string;
  unit: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="rounded-lg border border-zinc-300 bg-white px-3 py-2 focus-within:border-zinc-950 focus-within:ring-1 focus-within:ring-zinc-950">
      <span className="block text-[11px] font-medium text-zinc-400">{label}</span>
      <span className="flex items-baseline gap-1">
        <input
          className="min-w-0 flex-1 bg-transparent text-lg font-semibold outline-none"
          min="0.01"
          onChange={(event) => onChange(event.target.value)}
          required
          step="0.01"
          type="number"
          value={value}
        />
        <span className="text-xs text-zinc-400">{unit}</span>
      </span>
    </label>
  );
}

function CandidateCard({ candidate }: { candidate: RecallCandidate }) {
  const isComponent = candidate.candidateType === 'component' || candidate.candidateType === 'submodel';
  const itemType = isComponent ? 'component' : 'part';
  return (
    <Link
      className="block overflow-hidden rounded-xl border border-zinc-200 bg-white p-3 shadow-sm transition hover:-translate-y-0.5 hover:border-zinc-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-950 focus-visible:ring-offset-2"
      to={`/library/${itemType}/${encodeURIComponent(candidate.candidateId)}`}
    >
      <div className="flex aspect-square items-center justify-center overflow-hidden rounded-lg bg-zinc-50">
        <CandidateImage
          alt={candidate.name ?? candidate.candidateId}
          isComponent={isComponent}
          src={candidate.imageUrl}
        />
      </div>
      <h2 className="mt-3 break-words text-sm font-semibold leading-5 text-zinc-900">
        {candidate.name ?? candidate.candidateId}
      </h2>
      <div className="mt-1 break-all text-xs text-zinc-400">{candidate.candidateId}</div>
    </Link>
  );
}

function CandidateImage({ alt, isComponent, src }: { alt: string; isComponent: boolean; src: string | null }) {
  const [failed, setFailed] = React.useState(false);
  React.useEffect(() => setFailed(false), [src]);
  if (!src || failed) {
    return isComponent
      ? <Boxes className="h-12 w-12 text-blue-300" />
      : <Box className="h-12 w-12 text-amber-300" />;
  }
  return (
    <img
      alt={alt}
      className="h-full w-full object-contain p-3"
      decoding="async"
      loading="lazy"
      onError={() => setFailed(true)}
      src={src}
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
