import clsx from 'clsx'
import type { ReactNode } from 'react'

/** C16: similarity as a percentage with a colour ramp. */
export function SimilarityBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="text-slate-400">—</span>
  const pct = Math.round(value * 100)
  const tone =
    value >= 0.95 ? 'bg-emerald-100 text-emerald-800'
      : value >= 0.8 ? 'bg-slate-100 text-slate-700'
        : 'bg-amber-100 text-amber-800'
  return <span className={clsx('rounded px-1.5 py-0.5 text-xs font-medium tabular-nums', tone)}>{pct}%</span>
}

const SOURCE_TONES: Record<string, string> = {
  DESC: 'bg-violet-100 text-violet-800 ring-violet-200',
  WBS: 'bg-sky-100 text-sky-800 ring-sky-200',
  COT: 'bg-teal-100 text-teal-800 ring-teal-200',
  DCCS_HISTORY: 'bg-orange-100 text-orange-800 ring-orange-200',
  ONE_WINDOW: 'bg-slate-100 text-slate-600 ring-slate-200',
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <span className={clsx('rounded px-1.5 py-0.5 text-xs font-semibold ring-1', SOURCE_TONES[source] ?? SOURCE_TONES.ONE_WINDOW)}>
      {source === 'DCCS_HISTORY' ? 'DCCS' : source}
    </span>
  )
}

const TIER_TONES: Record<string, string> = {
  High: 'bg-rose-100 text-rose-900 ring-rose-300',
  Medium: 'bg-amber-100 text-amber-900 ring-amber-300',
  Low: 'bg-slate-100 text-slate-600 ring-slate-200',
}

export function RiskBadge({ tier }: { tier: string | null }) {
  if (!tier) return <span className="text-slate-400">—</span>
  return (
    <span className={clsx('rounded px-1.5 py-0.5 text-xs font-bold ring-1', TIER_TONES[tier] ?? TIER_TONES.Low)}>
      {tier}
    </span>
  )
}

export function RuleChip({ citation }: { citation: string | null }) {
  if (!citation) return null
  return (
    <span className="inline-block rounded-full bg-deloitte-green/15 px-2 py-0.5 text-[11px] font-medium text-emerald-900 ring-1 ring-deloitte-green/30">
      {citation}
    </span>
  )
}

export function StatusPill({ status }: { status: string | null }) {
  if (!status) return <span className="text-slate-400">—</span>
  const tone: Record<string, string> = {
    COMPLETE: 'bg-emerald-100 text-emerald-800',
    RUNNING: 'bg-sky-100 text-sky-800 animate-pulse',
    PENDING: 'bg-slate-100 text-slate-700',
    FAILED: 'bg-rose-100 text-rose-800',
  }
  return <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', tone[status] ?? 'bg-slate-100')}>{status}</span>
}

export function ResultBadge({ result }: { result: string | null }) {
  if (!result) return null
  const isClean = result === 'NO_CONFLICTS_IDENTIFIED'
  return (
    <span className={clsx(
      'rounded-lg px-3 py-1.5 text-sm font-bold ring-1',
      isClean ? 'bg-emerald-50 text-emerald-800 ring-emerald-300' : 'bg-amber-50 text-amber-900 ring-amber-300',
    )}>
      {result.replaceAll('_', ' ')}
    </span>
  )
}

export function Card({ title, children, right }: { title?: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      {title && (
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  )
}

/** C17: skeleton loaders, not spinners. */
export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-slate-200" style={{ width: `${70 + (i % 3) * 10}%` }} />
      ))}
    </div>
  )
}

export function EmptyState({ message }: { message: string }) {
  return <p className="py-6 text-center text-sm text-slate-400">{message}</p>
}
