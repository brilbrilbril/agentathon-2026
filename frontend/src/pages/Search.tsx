import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Search as SearchIcon } from 'lucide-react'
import { api } from '../api/client'
import { Card, EmptyState, RuleChip, SimilarityBadge, Skeleton, SourceBadge } from '../components/ui'

const SOURCES = ['DESC', 'WBS', 'COT', 'DCCS_HISTORY']

export default function SearchPage() {
  const [query, setQuery] = useState('KDDI Corporation')
  const [threshold, setThreshold] = useState(0.8)
  const search = useMutation({ mutationFn: () => api.searchEntities(query, threshold) })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">Entity search</h1>
        <p className="text-sm text-slate-500">
          Two-stage matching: Postgres <code className="text-xs">pg_trgm</code> prefilter, then rapidfuzz rerank.
        </p>
      </div>

      <Card>
        <form
          onSubmit={(e) => { e.preventDefault(); search.mutate() }}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="min-w-64 flex-1">
            <label className="text-xs font-medium uppercase tracking-wide text-slate-400">Entity name</label>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs font-medium uppercase tracking-wide text-slate-400">
              Threshold: {threshold.toFixed(2)}
            </label>
            <input
              type="range" min={0} max={1} step={0.05} value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="mt-2 block w-48"
            />
          </div>
          <button
            type="submit"
            className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            <SearchIcon className="h-4 w-4" /> Search
          </button>
        </form>
      </Card>

      {search.isPending && <Card><Skeleton rows={4} /></Card>}

      {search.data && (
        <div className="grid gap-4 md:grid-cols-2">
          {SOURCES.map((source) => {
            const rows = search.data.results[source] ?? []
            return (
              <Card key={source} title={`${source === 'DCCS_HISTORY' ? 'DCCS history' : source} (${rows.length})`}>
                {!rows.length ? <EmptyState message="No matches above threshold." /> : (
                  <ul className="divide-y divide-slate-50">
                    {rows.slice(0, 25).map((m, i) => (
                      <li key={i} className="flex items-start justify-between gap-3 py-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <SourceBadge source={m.source} />
                            <span className="truncate text-sm font-medium">{m.matched_name}</span>
                          </div>
                          <p className="mt-0.5 text-xs text-slate-500">
                            {[m.country, m.designation_type, m.business_unit, m.status, m.partner_name]
                              .filter(Boolean).join(' · ') || '—'}
                          </p>
                          <div className="mt-1"><RuleChip citation={m.rule_citation} /></div>
                        </div>
                        <SimilarityBadge value={m.similarity} />
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
