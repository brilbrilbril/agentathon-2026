import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { MessageSquare, Play, Scale } from 'lucide-react'
import { api } from '../api/client'
import { Card, EmptyState, Skeleton, StatusPill } from '../components/ui'

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-800">{value || <span className="text-slate-400">—</span>}</dd>
    </div>
  )
}

export default function CaseDetail() {
  const { caseId = '' } = useParams()
  const navigate = useNavigate()

  const detail = useQuery({ queryKey: ['case', caseId], queryFn: () => api.getCase(caseId) })
  const screenings = useQuery({ queryKey: ['screenings', caseId], queryFn: () => api.listScreenings(caseId) })
  const golden = useQuery({
    queryKey: ['golden', caseId],
    queryFn: () => api.getGolden(caseId),
    retry: false,
  })

  const startScreening = useMutation({
    mutationFn: () => api.startScreening(caseId),
    onSuccess: (data) => navigate(`/screenings/${data.screening_id}`),
  })

  if (detail.isLoading) return <Skeleton rows={6} />
  if (!detail.data) return <EmptyState message="Case not found." />
  const c = detail.data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Request {c.request_id}</h1>
          <p className="text-sm text-slate-500">{c.request_type} · submitted {c.date_submitted}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => startScreening.mutate()}
            disabled={startScreening.isPending}
            className="flex items-center gap-1.5 rounded-lg bg-deloitte-green px-3 py-2 text-sm font-semibold text-slate-900 hover:brightness-95 disabled:opacity-50"
          >
            <Play className="h-4 w-4" /> {startScreening.isPending ? 'Starting…' : 'Run screening'}
          </button>
          {golden.data && (
            <Link
              to={`/cases/${caseId}/eval`}
              className="flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-700"
            >
              <Scale className="h-4 w-4" /> Run evaluation
            </Link>
          )}
          <Link
            to={`/cases/${caseId}/chat`}
            className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium hover:bg-slate-50"
          >
            <MessageSquare className="h-4 w-4" /> Ask
          </Link>
        </div>
      </div>

      <Card title="Engagement details">
        <dl className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <Field label="Service offering" value={c.service_offering} />
          <Field label="Originator" value={c.originator} />
          <Field label="Member firm" value={c.member_firm} />
          <Field label="Location" value={c.location} />
          <Field label="Office" value={c.office} />
          <Field label="Engagement" value={c.engagement_name} />
          <Field label="Lead partner" value={c.lead_partner} />
          <Field label="Lead manager" value={c.lead_manager} />
          <Field label="Inbound referral" value={c.is_inbound_referral ? `Yes (IWRF: ${c.has_iwrf ? 'yes' : 'no'})` : 'No'} />
        </dl>
        <div className="mt-4 border-t border-slate-100 pt-3">
          <Field label="Engagement description" value={c.engagement_details} />
        </div>
      </Card>

      <Card title={`Relevant parties (${c.parties.length})`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-400">
              <th className="pb-2 font-medium">Entity</th>
              <th className="pb-2 font-medium">Side</th>
              <th className="pb-2 font-medium">Role</th>
              <th className="pb-2 font-medium">Location</th>
              <th className="pb-2 font-medium">Stated designation</th>
              <th className="pb-2 font-medium">GUP</th>
            </tr>
          </thead>
          <tbody>
            {c.parties.map((p) => (
              <tr key={p.entity_name} className="border-b border-slate-50 last:border-0">
                <td className="py-2.5 font-medium">{p.entity_name}</td>
                <td className="py-2.5 text-slate-600">{p.party_side}</td>
                <td className="py-2.5 text-slate-600">{p.entity_role}</td>
                <td className="py-2.5 text-slate-600">{p.location}</td>
                <td className="py-2.5">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-700">
                    {p.stated_designation || '—'}
                  </span>
                </td>
                <td className="py-2.5 text-slate-600">{p.is_gup ? 'Yes' : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-slate-400">
          Designations shown here are what the <em>request</em> claims. DESC is authoritative (QRC slide 4) —
          the screening diffs them and flags any contradiction.
        </p>
      </Card>

      <Card title="Screening history">
        {screenings.isLoading ? <Skeleton rows={2} /> : !screenings.data?.length ? (
          <EmptyState message="No screenings run yet." />
        ) : (
          <ul className="divide-y divide-slate-50">
            {screenings.data.map((s) => (
              <li key={s.screening_id} className="flex items-center justify-between py-2">
                <Link to={`/screenings/${s.screening_id}`} className="text-sm text-sky-700 hover:underline">
                  {s.screening_id.slice(0, 8)}… · {s.final_result?.replaceAll('_', ' ') ?? 'in progress'}
                </Link>
                <div className="flex items-center gap-3 text-xs text-slate-400">
                  <span>{s.completed_at?.slice(0, 19).replace('T', ' ') ?? ''}</span>
                  <StatusPill status={s.status} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
