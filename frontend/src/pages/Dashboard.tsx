import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Database, FileCheck2, Plus } from 'lucide-react'
import { api } from '../api/client'
import { Card, EmptyState, Skeleton, StatusPill } from '../components/ui'

const SOURCES: { key: keyof NonNullable<Awaited<ReturnType<typeof api.getStats>>>; label: string }[] = [
  { key: 'desc_entities', label: 'DESC entities' },
  { key: 'wbs_engagements', label: 'WBS engagements' },
  { key: 'cot_requests', label: 'COT requests' },
  { key: 'dccs_search_results', label: 'DCCS history rows' },
  { key: 'rule_chunks', label: 'QRC rule chunks' },
]

export default function Dashboard() {
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.getStats })
  const cases = useQuery({ queryKey: ['cases'], queryFn: api.listCases })
  const health = useQuery({ queryKey: ['health'], queryFn: api.getHealth })

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Dashboard</h1>
          <p className="text-sm text-slate-500">Ingested conflict databases and open cases</p>
        </div>
        <Link
          to="/cases/new"
          className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          <Plus className="h-4 w-4" /> New case
        </Link>
      </div>

      <Card
        title="Data sources"
        right={
          health.data && (
            <span className="text-xs text-slate-500">
              Postgres {health.data.postgres ? 'ok' : 'down'} · LLM {health.data.llm ? 'configured' : 'not configured'}
            </span>
          )
        }
      >
        {stats.isLoading ? <Skeleton rows={2} /> : stats.data ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {SOURCES.map(({ key, label }) => (
              <div key={key} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
                  <Database className="h-3.5 w-3.5" /> {label}
                </div>
                <div className="mt-1 text-2xl font-bold tabular-nums">
                  {(stats.data[key] as number).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        ) : <EmptyState message="Could not load stats — is the API running?" />}
      </Card>

      <Card title="Cases">
        {cases.isLoading ? <Skeleton rows={3} /> : !cases.data?.items.length ? (
          <EmptyState message="No cases ingested. Run scripts/run_ingestion.py." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="pb-2 font-medium">Request</th>
                <th className="pb-2 font-medium">Service offering</th>
                <th className="pb-2 font-medium">Location</th>
                <th className="pb-2 font-medium">Parties</th>
                <th className="pb-2 font-medium">Ground truth</th>
                <th className="pb-2 font-medium">Last screening</th>
              </tr>
            </thead>
            <tbody>
              {cases.data.items.map((c) => (
                <tr key={c.case_id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                  <td className="py-2.5">
                    <Link to={`/cases/${c.case_id}`} className="font-semibold text-sky-700 hover:underline">
                      {c.request_id}
                    </Link>
                  </td>
                  <td className="max-w-md truncate py-2.5 text-slate-600">{c.service_offering}</td>
                  <td className="py-2.5 text-slate-600">{c.location}</td>
                  <td className="py-2.5 tabular-nums text-slate-600">{c.party_count}</td>
                  <td className="py-2.5">
                    {c.has_golden && (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200">
                        <FileCheck2 className="h-3 w-3" /> answer key
                      </span>
                    )}
                  </td>
                  <td className="py-2.5"><StatusPill status={c.latest_screening_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  )
}
