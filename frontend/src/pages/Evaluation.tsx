import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Check, Play, X } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../api/client'
import { Card, EmptyState, Skeleton } from '../components/ui'

/**
 * DEV_C §3 screen 5 — the screen that wins the demo: our pipeline's output
 * beside the analyst's real determination, with a per-check pass/fail table.
 */
export default function Evaluation() {
  const { caseId = '' } = useParams()

  const golden = useQuery({ queryKey: ['golden', caseId], queryFn: () => api.getGolden(caseId) })
  const evaluation = useMutation({ mutationFn: () => api.evaluate(caseId) })
  const result = evaluation.data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Evaluation against ground truth</h1>
          <p className="text-sm text-slate-500">
            Case {golden.data?.request_id} was worked and closed by a human analyst. We score our pipeline against their answer.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {result && (
            <span className={clsx(
              'rounded-lg px-4 py-2 text-lg font-bold ring-1',
              result.passed === result.total
                ? 'bg-emerald-50 text-emerald-800 ring-emerald-300'
                : 'bg-amber-50 text-amber-900 ring-amber-300',
            )}>
              {result.score}
            </span>
          )}
          <button
            onClick={() => evaluation.mutate()}
            disabled={evaluation.isPending}
            className="flex items-center gap-1.5 rounded-lg bg-deloitte-green px-3 py-2 text-sm font-semibold text-slate-900 hover:brightness-95 disabled:opacity-50"
          >
            <Play className="h-4 w-4" /> {evaluation.isPending ? 'Running pipeline…' : 'Run evaluation'}
          </button>
        </div>
      </div>

      {evaluation.isPending && <Card title="Running"><Skeleton rows={5} /></Card>}

      {evaluation.isError && (
        <Card title="Evaluation failed">
          <p className="text-sm text-rose-700">{String(evaluation.error)}</p>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Analyst's determination (ground truth)">
          {golden.isLoading ? <Skeleton rows={4} /> : !golden.data ? (
            <EmptyState message="No stored answer key for this case." />
          ) : (
            <dl className="space-y-3 text-sm">
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Final result</dt>
                <dd className="mt-0.5 font-semibold">{golden.data.final_result}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Conditions</dt>
                <dd className="mt-0.5">
                  <ul className="list-inside list-disc">
                    {golden.data.conditions.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Analyst comments</dt>
                <dd className="mt-0.5">
                  <ul className="list-inside list-disc">
                    {golden.data.analyst_comments.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">Cross border</dt>
                <dd className="mt-0.5">
                  {golden.data.cross_border.map((cb, i) => (
                    <div key={i}>{cb.jurisdiction} → {cb.outcome} <span className="text-slate-400">({cb.comment})</span></div>
                  ))}
                </dd>
              </div>
            </dl>
          )}
        </Card>

        <Card
          title="Our pipeline"
          right={result && (
            <Link to={`/screenings/${result.screening_id}`} className="text-xs text-sky-700 hover:underline">
              view full screening →
            </Link>
          )}
        >
          {!result ? (
            <EmptyState message="Run the evaluation to populate this column." />
          ) : (
            <dl className="space-y-3 text-sm">
              {result.checks.map((c) => (
                <div key={c.name}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{c.name.replaceAll('_', ' ')}</dt>
                  <dd className="mt-0.5 flex items-center gap-2">
                    {c.passed
                      ? <Check className="h-4 w-4 shrink-0 text-emerald-600" />
                      : <X className="h-4 w-4 shrink-0 text-rose-600" />}
                    <span className={c.passed ? '' : 'text-rose-700'}>{c.actual}</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      </div>

      {result && (
        <Card title="Per-check scoring">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
                <th className="pb-2 pr-3 font-medium">Check</th>
                <th className="pb-2 pr-3 font-medium">Expected (analyst)</th>
                <th className="pb-2 pr-3 font-medium">Actual (pipeline)</th>
                <th className="pb-2 font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {result.checks.map((c) => (
                <tr key={c.name} className="border-b border-slate-50 last:border-0">
                  <td className="py-2 pr-3 font-medium">{c.name.replaceAll('_', ' ')}</td>
                  <td className="py-2 pr-3 text-slate-600">{c.expected}</td>
                  <td className="py-2 pr-3 text-slate-600">{c.actual}</td>
                  <td className="py-2">
                    <span className={clsx(
                      'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-bold',
                      c.passed ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800',
                    )}>
                      {c.passed ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                      {c.passed ? 'PASS' : 'FAIL'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-500">
            <strong>Honest limitation:</strong> this is one worked case, not a test set. It proves reproduction of a
            known-correct human determination, not generalisation.
          </p>
        </Card>
      )}
    </div>
  )
}
