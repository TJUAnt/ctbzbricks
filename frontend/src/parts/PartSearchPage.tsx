import React from 'react';
import { Map, Search, SlidersHorizontal } from 'lucide-react';
import { create } from 'zustand';

type Candidate = {
  ldrawPartNum: string;
  name: string | null;
  category: string | null;
  relationType: string | null;
  rebrickablePartNum: string | null;
  score: number;
  scoreReason: string;
  connectorCounts: Record<string, number>;
  logicalSize: Array<number | null>;
  bbox: Array<number | null>;
  imageUrl: string | null;
};

type SearchResponse = {
  query: string;
  parsed: Record<string, unknown>;
  count: number;
  candidates: Candidate[];
};

type SearchState = {
  query: string;
  strictBBox: boolean;
  includeSubstitutes: boolean;
  loading: boolean;
  error: string | null;
  response: SearchResponse | null;
  page: number;
  pageSize: number;
  setQuery: (query: string) => void;
  setStrictBBox: (strictBBox: boolean) => void;
  setIncludeSubstitutes: (includeSubstitutes: boolean) => void;
  setPage: (page: number) => void;
  search: () => Promise<void>;
};

const useSearchStore = create<SearchState>((set, get) => ({
  query: '2x4 plate',
  strictBBox: true,
  includeSubstitutes: false,
  loading: false,
  error: null,
  response: null,
  page: 1,
  pageSize: 24,
  setQuery: (query) => set({ query, page: 1 }),
  setStrictBBox: (strictBBox) => set({ strictBBox }),
  setIncludeSubstitutes: (includeSubstitutes) => set({ includeSubstitutes }),
  setPage: (page) => {
    set({ page });
    void get().search();
  },
  search: async () => {
    const state = get();
    set({ loading: true, error: null });
    try {
      const result = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: state.query,
          strict_bbox: state.strictBBox,
          include_substitutes: state.includeSubstitutes,
          page: state.page,
          page_size: state.pageSize,
        }),
      });
      if (!result.ok) {
        throw new Error(`HTTP ${result.status}`);
      }
      set({ response: await result.json(), loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'search failed',
        loading: false,
      });
    }
  },
}));

export function PartSearchPage({ onOpenTerrain }: { onOpenTerrain?: () => void }) {
  const query = useSearchStore((state) => state.query);
  const setQuery = useSearchStore((state) => state.setQuery);
  const strictBBox = useSearchStore((state) => state.strictBBox);
  const setStrictBBox = useSearchStore((state) => state.setStrictBBox);
  const includeSubstitutes = useSearchStore((state) => state.includeSubstitutes);
  const setIncludeSubstitutes = useSearchStore((state) => state.setIncludeSubstitutes);
  const loading = useSearchStore((state) => state.loading);
  const error = useSearchStore((state) => state.error);
  const response = useSearchStore((state) => state.response);
  const page = useSearchStore((state) => state.page);
  const pageSize = useSearchStore((state) => state.pageSize);
  const setPage = useSearchStore((state) => state.setPage);
  const searchParts = useSearchStore((state) => state.search);

  const totalPages = response ? Math.max(1, Math.ceil(response.count / pageSize)) : 1;

  React.useEffect(() => {
    void searchParts();
  }, [searchParts]);

  return (
    <main className="min-h-screen bg-zinc-100 text-zinc-950">
      <section className="border-b border-zinc-300 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-5 py-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold tracking-normal">零件搜索</h1>
              <p className="mt-1 text-sm text-zinc-500">geometry / xref / connector</p>
            </div>
            <div className="flex items-center gap-2">
              <div className="rounded border border-zinc-300 px-3 py-1 text-sm text-zinc-600">
                {response?.count ?? 0} results
              </div>
              {onOpenTerrain ? (
                <button
                  className="inline-flex h-9 items-center justify-center gap-2 rounded border border-zinc-300 bg-white px-3 text-sm text-zinc-700 transition hover:bg-zinc-50"
                  onClick={onOpenTerrain}
                  type="button"
                >
                  <Map className="h-4 w-4" />
                  DEM
                </button>
              ) : null}
            </div>
          </div>

          <form
            className="grid gap-3 md:grid-cols-[1fr_auto]"
            onSubmit={(event) => {
              event.preventDefault();
              void searchParts();
            }}
          >
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-zinc-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-11 w-full rounded border border-zinc-300 bg-white pl-10 pr-3 text-base outline-none ring-zinc-900 transition focus:ring-2"
                placeholder="2x4 plate / 3020 / side technic hole"
              />
            </label>
            <button
              className="inline-flex h-11 items-center justify-center gap-2 rounded bg-zinc-950 px-5 text-sm font-medium text-white transition hover:bg-zinc-800 disabled:opacity-60"
              disabled={loading}
              type="submit"
            >
              <Search className="h-4 w-4" />
              Search
            </button>
          </form>

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <SlidersHorizontal className="h-4 w-4 text-zinc-500" />
            <label className="inline-flex items-center gap-2">
              <input
                checked={strictBBox}
                onChange={(event) => setStrictBBox(event.target.checked)}
                className="h-4 w-4 accent-zinc-950"
                type="checkbox"
              />
              strict bbox
            </label>
            <label className="inline-flex items-center gap-2">
              <input
                checked={includeSubstitutes}
                onChange={(event) => setIncludeSubstitutes(event.target.checked)}
                className="h-4 w-4 accent-zinc-950"
                type="checkbox"
              />
              substitutes
            </label>
            {error ? <span className="text-red-600">{error}</span> : null}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {(response?.candidates ?? []).map((candidate, index) => (
            <CandidateCard candidate={candidate} index={index} key={candidate.ldrawPartNum} />
          ))}
        </div>

        {response && response.count > 0 ? (
          <div className="mt-6 flex items-center justify-center gap-2">
            <button
              className="inline-flex h-9 items-center justify-center rounded border border-zinc-300 bg-white px-3 text-sm text-zinc-700 transition hover:bg-zinc-50 disabled:opacity-40"
              disabled={page <= 1 || loading}
              onClick={() => setPage(page - 1)}
              type="button"
            >
              Prev
            </button>
            <span className="text-sm text-zinc-600">
              {page} / {totalPages}
            </span>
            <span className="text-sm text-zinc-400">({response.count} total)</span>
            <button
              className="inline-flex h-9 items-center justify-center rounded border border-zinc-300 bg-white px-3 text-sm text-zinc-700 transition hover:bg-zinc-50 disabled:opacity-40"
              disabled={page >= totalPages || loading}
              onClick={() => setPage(page + 1)}
              type="button"
            >
              Next
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function CandidateCard({ candidate, index }: { candidate: Candidate; index: number }) {
  return (
    <article className="overflow-hidden rounded border border-zinc-300 bg-white">
      <div className="flex aspect-[4/3] items-center justify-center bg-zinc-50">
        {candidate.imageUrl ? (
          <img
            alt={candidate.name ?? candidate.ldrawPartNum}
            className="h-full w-full object-contain p-4"
            loading="lazy"
            src={candidate.imageUrl}
          />
        ) : (
          <div className="text-sm text-zinc-400">no image</div>
        )}
      </div>
      <div className="space-y-3 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{candidate.ldrawPartNum}</div>
            <div className="mt-1 line-clamp-2 min-h-10 text-sm text-zinc-600">
              {candidate.name}
            </div>
          </div>
          <span className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-600">
            #{index + 1}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs text-zinc-600">
          <PartMetric label="score" value={candidate.score.toFixed(2)} />
          <PartMetric label="relation" value={candidate.relationType ?? 'ldraw'} />
          <PartMetric label="logical" value={candidate.logicalSize.join(' x ')} />
          <PartMetric label="bbox" value={candidate.bbox.map((value) => value ?? '-').join(' x ')} />
        </div>

        {Object.keys(candidate.connectorCounts).length > 0 ? (
          <div className="space-y-1 border-t border-zinc-200 pt-2">
            {Object.entries(candidate.connectorCounts).map(([key, value]) => (
              <div className="flex justify-between gap-2 text-xs text-zinc-600" key={key}>
                <span className="truncate">{key}</span>
                <span>{value}</span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function PartMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-zinc-50 px-2 py-1">
      <div className="text-[11px] uppercase text-zinc-400">{label}</div>
      <div className="truncate text-zinc-700">{value}</div>
    </div>
  );
}
