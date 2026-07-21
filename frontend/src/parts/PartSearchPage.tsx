import React from 'react';
import { Box, Boxes, Check, Ruler, Search, Shapes } from 'lucide-react';
import { create } from 'zustand';
import { errorMessage, requestJson } from '../api/client';
import { currentTaskContext } from '../api/taskContext';
import { useAppTranslation } from '../i18n';
import { formatNumber } from '../i18n/formatters';

type LogicalSize = {
  logicalSize: {
    widthStud: number;
    depthStud: number;
    heightPlate: number;
  };
};

type RecallCandidate = {
  candidateType: 'part' | 'component' | 'submodel';
  candidateId: string;
  profileStatus: string;
  score: number;
  scoreReasons: string[];
  name: string | null;
  description: string | null;
  contentLocale: string;
  translationStatus: string;
  matchedType: string | null;
  typeScore: number | null;
  logicalSize: LogicalSize | null;
  appearanceTags: Record<string, unknown> | null;
};

type RecallResponse = {
  total: number;
  returned: number;
  includeIrregular: boolean;
  candidates: RecallCandidate[];
};

type RecallState = {
  lengthStud: string;
  widthStud: string;
  heightPlate: string;
  typeQuery: string;
  allowPlanarRotation: boolean;
  loading: boolean;
  error: string | null;
  response: RecallResponse | null;
  setLengthStud: (value: string) => void;
  setWidthStud: (value: string) => void;
  setHeightPlate: (value: string) => void;
  setTypeQuery: (value: string) => void;
  setAllowPlanarRotation: (value: boolean) => void;
  recall: () => Promise<void>;
};

const componentTypes = ['plate', 'tile', 'slope'] as const;

const useRecallStore = create<RecallState>((set, get) => ({
  lengthStud: '4',
  widthStud: '2',
  heightPlate: '1',
  typeQuery: 'plate',
  allowPlanarRotation: true,
  loading: false,
  error: null,
  response: null,
  setLengthStud: (lengthStud) => set({ lengthStud }),
  setWidthStud: (widthStud) => set({ widthStud }),
  setHeightPlate: (heightPlate) => set({ heightPlate }),
  setTypeQuery: (typeQuery) => set({ typeQuery }),
  setAllowPlanarRotation: (allowPlanarRotation) => set({ allowPlanarRotation }),
  recall: async () => {
    const state = get();
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
          typeQuery: state.typeQuery,
          allowPlanarRotation: state.allowPlanarRotation,
          includeIrregular: false,
          limit: 50,
          contentLocale: currentTaskContext().locale,
        }),
      });
      set({ response: result, loading: false });
    } catch (error) {
      set({ error: errorMessage(error, 'common.unknown'), loading: false });
    }
  },
}));

export function PartSearchPage() {
  const tr = useAppTranslation();
  const state = useRecallStore();

  React.useEffect(() => {
    void state.recall();
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
              void state.recall();
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
                  {tr('partSearch:type')}
                  <span className="font-normal text-zinc-400">{tr('partSearch:fuzzyMatch')}</span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {componentTypes.map((type) => (
                    <button
                      aria-pressed={state.typeQuery === type}
                      className={`h-11 rounded-lg border px-3 text-sm font-medium uppercase transition ${
                        state.typeQuery === type
                          ? 'border-zinc-950 bg-zinc-950 text-white'
                          : 'border-zinc-300 bg-white text-zinc-700 hover:border-zinc-500'
                      }`}
                      key={type}
                      onClick={() => state.setTypeQuery(type)}
                      type="button"
                    >
                      {type}
                    </button>
                  ))}
                </div>
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
              <span className="text-zinc-400">{tr('partSearch:exactDimensions')}</span>
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
        {state.loading && !state.response ? <RecallSkeleton /> : null}
        {!state.loading && state.response?.total === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-300 bg-white px-6 py-16 text-center">
            <Search className="mx-auto h-8 w-8 text-zinc-300" />
            <h2 className="mt-3 text-base font-medium">{tr('partSearch:noMatches')}</h2>
            <p className="mt-1 text-sm text-zinc-500">{tr('partSearch:noMatchesHint')}</p>
          </div>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(state.response?.candidates ?? []).map((candidate, index) => (
            <CandidateCard candidate={candidate} index={index} key={`${candidate.candidateType}:${candidate.candidateId}`} />
          ))}
        </div>
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

function CandidateCard({ candidate, index }: { candidate: RecallCandidate; index: number }) {
  const tr = useAppTranslation();
  const dimensions = candidate.logicalSize?.logicalSize;
  const isComponent = candidate.candidateType === 'component' || candidate.candidateType === 'submodel';
  return (
    <article className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${isComponent ? 'bg-blue-50 text-blue-600' : 'bg-amber-50 text-amber-600'}`}>
            {isComponent ? <Boxes className="h-5 w-5" /> : <Box className="h-5 w-5" />}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className={`rounded px-2 py-0.5 text-[11px] font-medium ${isComponent ? 'bg-blue-50 text-blue-700' : 'bg-amber-50 text-amber-700'}`}>
                {isComponent ? tr('partSearch:component') : tr('partSearch:part')}
              </span>
              <span className="text-xs text-zinc-400">#{index + 1}</span>
            </div>
            <h2 className="mt-1 truncate text-sm font-semibold">{candidate.name ?? candidate.candidateId}</h2>
            <div className="mt-0.5 truncate text-xs text-zinc-400">{candidate.candidateId}</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm font-semibold text-emerald-700">
            {formatNumber((candidate.typeScore ?? 0) * 100, { maximumFractionDigits: 0 })}%
          </div>
          <div className="text-[11px] text-zinc-400">{tr('partSearch:typeMatch')}</div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric label={tr('partSearch:length')} value={formatDimension(dimensions?.widthStud)} unit={tr('partSearch:stud')} />
        <Metric label={tr('partSearch:width')} value={formatDimension(dimensions?.depthStud)} unit={tr('partSearch:stud')} />
        <Metric label={tr('partSearch:height')} value={formatDimension(dimensions?.heightPlate)} unit={tr('partSearch:plateUnit')} />
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 border-t border-zinc-100 pt-3 text-xs">
        <span className="inline-flex min-w-0 items-center gap-1.5 text-zinc-500">
          <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
          <span className="truncate">{candidate.matchedType ?? tr('partSearch:typeMatched')}</span>
        </span>
        <span className="shrink-0 text-zinc-400">
          {tr('partSearch:score')} {formatNumber(candidate.score, { maximumFractionDigits: 1 })}
        </span>
      </div>
    </article>
  );
}

function Metric({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="rounded-lg bg-zinc-50 px-2.5 py-2">
      <div className="text-[11px] text-zinc-400">{label}</div>
      <div className="mt-0.5 truncate text-sm font-medium text-zinc-700">
        {value} <span className="text-[10px] font-normal text-zinc-400">{unit}</span>
      </div>
    </div>
  );
}

function formatDimension(value: number | undefined): string {
  return value === undefined ? '—' : formatNumber(value, { maximumFractionDigits: 2 });
}

function RecallSkeleton() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="h-48 animate-pulse rounded-xl border border-zinc-200 bg-white" key={index} />
      ))}
    </div>
  );
}
