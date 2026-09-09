import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { RuleChunk } from '../api/types'
import { Card, EmptyState, Skeleton } from '../components/ui'

export default function Guide() {
  const { data, isLoading } = useQuery({ queryKey: ['rules'], queryFn: api.listRules })

  if (isLoading) return <Skeleton rows={8} />
  if (!data?.length) return <EmptyState message="No rule chunks ingested." />

  const grouped = data.reduce<Record<string, RuleChunk[]>>((acc, chunk) => {
    (acc[chunk.source_db] ||= []).push(chunk)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">QRC rulebook</h1>
        <p className="text-sm text-slate-500">
          {data.length} semantic chunks from the Quick Reference Card, grouped by the database each rule governs.
          Every classification in a screening cites one of these.
        </p>
      </div>

      {Object.entries(grouped).map(([sourceDb, chunks]) => (
        <Card key={sourceDb} title={`${sourceDb} (${chunks.length})`}>
          <div className="space-y-4">
            {chunks.map((c) => (
              <article key={c.chunk_id} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                <header className="mb-1.5 flex items-center gap-2">
                  <span className="rounded bg-slate-900 px-1.5 py-0.5 text-[11px] font-semibold text-white">
                    Slide {c.slide_number}
                  </span>
                  <h3 className="text-sm font-semibold">{c.title}</h3>
                  <span className="text-xs text-slate-400">{c.chunk_type}</span>
                </header>
                <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-700">{c.text}</pre>
              </article>
            ))}
          </div>
        </Card>
      ))}
    </div>
  )
}
