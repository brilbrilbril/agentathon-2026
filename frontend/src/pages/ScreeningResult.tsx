import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { AlertTriangle, ChevronDown, ChevronRight, Copy, Info, ShieldOff } from 'lucide-react'
import clsx from 'clsx'
import { POLL_INTERVAL_MS, api } from '../api/client'
import type { MatchRow } from '../api/types'
import { Card, EmptyState, ResultBadge, RiskBadge, RuleChip, SimilarityBadge, Skeleton, SourceBadge, StatusPill } from '../components/ui'
import { Markdown } from '../components/Markdown'

function MatchTable({ rows, showReason = false }: { rows: MatchRow[]; showReason?: boolean }) {
  if (!rows.length) return <EmptyState message="Nothing here." />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
            <th className="pb-2 pr-3 font-medium">Risk</th>
            <th className="pb-2 pr-3 font-medium">Entity</th>
            <th className="pb-2 pr-3 font-medium">Source</th>
            <th className="pb-2 pr-3 font-medium">Country</th>
            <th className="pb-2 pr-3 font-medium">Designation / BU</th>
            <th className="pb-2 pr-3 font-medium">Partner / LCSP</th>
            <th className="pb-2 pr-3 font-medium">Status</th>
            <th className="pb-2 pr-3 font-medium">Match</th>
            {showReason && <th className="pb-2 pr-3 font-medium">Reason</th>}
            <th className="pb-2 font-medium">Rule</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-slate-50 last:border-0 align-top hover:bg-slate-50">
              <td className="py-2 pr-3"><RiskBadge tier={r.risk_tier} /></td>
              <td className="py-2 pr-3 font-medium">
                {r.entity_name}
                {r.risk_reason && <p className="mt-0.5 max-w-xs text-[11px] font-normal text-slate-500">{r.risk_reason}</p>}
              </td>
              <td className="py-2 pr-3"><SourceBadge source={r.source} /></td>
              <td className="py-2 pr-3 text-slate-600">{r.country || r.practice_office || '—'}</td>
              <td className="py-2 pr-3 text-slate-600">{r.designation_type || r.business_unit || '—'}</td>
              <td className="py-2 pr-3 text-slate-600">{r.lcsp_rp || r.partner_name || '—'}</td>
              <td className="py-2 pr-3 text-slate-600">{r.status || r.entity_role || '—'}</td>
              <td className="py-2 pr-3"><SimilarityBadge value={r.similarity} /></td>
              {showReason && <td className="py-2 pr-3 max-w-xs text-xs text-slate-500">{r.exclusion_reason || r.note}</td>}
              <td className="py-2"><RuleChip citation={r.rule_citation} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Collapsible({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-800"
      >
        {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        {title}
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium tabular-nums text-slate-600">{count}</span>
      </button>
      {open && <div className="border-t border-slate-100 p-4">{children}</div>}
    </section>
  )
}

export default function ScreeningResult() {
  const { screeningId = '' } = useParams()
  const [copied, setCopied] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['screening', screeningId],
    queryFn: () => api.getScreening(screeningId),
    // C12: poll while RUNNING, stop on COMPLETE/FAILED
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'COMPLETE' || s === 'FAILED' ? false : POLL_INTERVAL_MS
    },
  })

  if (isLoading) return <Skeleton rows={8} />
  if (!data) return <EmptyState message="Screening not found." />

  if (data.status === 'PENDING' || data.status === 'RUNNING') {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">Screening in progress</h1>
          <StatusPill status={data.status} />
        </div>
        <Card title="Agents running">
          <p className="mb-4 text-sm text-slate-500">
            Orchestrator → Search → Rules &amp; Compliance → Synthesis
          </p>
          <Skeleton rows={6} />
        </Card>
      </div>
    )
  }

  if (data.status === 'FAILED') {
    return (
      <Card title="Screening failed">
        <p className="text-sm text-rose-700">{data.error}</p>
      </Card>
    )
  }

  const byTier = data.summary_table.reduce<Record<string, MatchRow[]>>((acc, row) => {
    (acc[row.risk_tier ?? 'Low'] ||= []).push(row)
    return acc
  }, {})
  const needsAttention = [...(byTier.High ?? []), ...(byTier.Medium ?? [])]

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Screening result</h1>
          <p className="text-sm text-slate-500">
            {data.summary_table.length} relationships identified
            {needsAttention.length > 0 && (
              <> · <span className="font-semibold text-rose-700">{needsAttention.length} need review</span></>
            )}
          </p>
        </div>
        <ResultBadge result={data.final_result} />
      </div>

      {/* Quality-check flags — the DESC contradiction is the best demo beat */}
      {data.quality_check_flags.length > 0 && (
        <div className="space-y-3">
          {data.quality_check_flags.map((f, i) => (
            <div
              key={i}
              className={clsx(
                'rounded-xl border-l-4 bg-white p-4 shadow-sm ring-1',
                f.severity === 'WARN'
                  ? 'border-l-amber-500 ring-amber-200'
                  : 'border-l-sky-400 ring-slate-200',
              )}
            >
              <div className="flex items-start gap-3">
                {f.severity === 'WARN'
                  ? <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                  : <Info className="mt-0.5 h-5 w-5 shrink-0 text-sky-500" />}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={clsx(
                      'rounded px-1.5 py-0.5 text-[11px] font-bold',
                      f.severity === 'WARN' ? 'bg-amber-100 text-amber-900' : 'bg-sky-100 text-sky-900',
                    )}>{f.severity}</span>
                    <RuleChip citation={f.rule_citation} />
                  </div>
                  <p className="mt-1.5 text-sm font-medium text-slate-900">{f.message}</p>
                  {f.action && <p className="mt-1 text-xs text-slate-600"><strong>Action:</strong> {f.action}</p>}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Triaged worklist: the reviewer reads High first and may never need Low. */}
      {needsAttention.length > 0 && (
        <Card
          title="Needs your attention"
          right={<span className="text-xs text-slate-500">{needsAttention.length} of {data.summary_table.length} matches</span>}
        >
          <div className="space-y-5">
            {(['High', 'Medium'] as const).map((tier) => {
              const rows = byTier[tier] ?? []
              if (!rows.length) return null
              return (
                <div key={tier}>
                  <div className="mb-2 flex items-center gap-2">
                    <RiskBadge tier={tier} />
                    <span className="text-xs text-slate-400">
                      {tier === 'High' ? 'independence risk — review first' : 'a condition is likely'}
                    </span>
                  </div>
                  <MatchTable rows={rows} />
                </div>
              )
            })}
          </div>
        </Card>
      )}

      <Collapsible
        title="For the record (low risk)"
        count={(byTier.Low ?? []).length}
      >
        <p className="mb-3 text-xs text-slate-500">
          Recorded for completeness. These carry no designation or engagement signal that raises risk,
          so they do not by themselves change the outcome.
        </p>
        <MatchTable rows={byTier.Low ?? []} />
      </Collapsible>

      <Collapsible title="Possible matches (analyst review)" count={data.possible_matches.length}>
        <MatchTable rows={data.possible_matches} showReason />
      </Collapsible>

      <Collapsible title="Excluded matches" count={data.excluded_matches.length}>
        <MatchTable rows={data.excluded_matches} showReason />
      </Collapsible>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Conditions to be satisfied">
          {data.conditions.length ? (
            <ul className="list-inside list-disc space-y-1.5 text-sm text-slate-700">
              {data.conditions.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          ) : <EmptyState message="No conditions." />}
        </Card>

        <Card title="Cross-border actions">
          {data.cross_border_actions.length ? (
            <ul className="space-y-2.5">
              {data.cross_border_actions.map((a, i) => (
                <li key={i} className="text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{a.jurisdiction}</span>
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium">{a.outcome}</span>
                    <RuleChip citation={a.rule_citation} />
                  </div>
                  {a.reason && <p className="mt-0.5 text-xs text-slate-500">{a.reason}</p>}
                </li>
              ))}
            </ul>
          ) : <EmptyState message="No cross-border actions." />}
        </Card>
      </div>

      {data.unchecked_sources.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="flex items-start gap-2">
            <ShieldOff className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
            <div>
              <h3 className="text-sm font-semibold text-slate-700">Sources not checked in this build</h3>
              <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
                {data.unchecked_sources.map((u, i) => <li key={i}><strong>{u.source}</strong> — {u.reason}</li>)}
              </ul>
            </div>
          </div>
        </div>
      )}

      <Card
        title="Draft response"
        right={
          <button
            onClick={() => {
              navigator.clipboard.writeText(data.draft_response ?? '')
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}
            className="flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs font-medium hover:bg-slate-50"
          >
            <Copy className="h-3 w-3" /> {copied ? 'Copied' : 'Copy'}
          </button>
        }
      >
        <div className="max-h-[28rem] overflow-auto rounded-lg border border-slate-200 bg-white p-4">
          <Markdown>{data.draft_response ?? ''}</Markdown>
        </div>
      </Card>
    </div>
  )
}
