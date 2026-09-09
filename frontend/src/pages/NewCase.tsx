import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Party } from '../api/types'
import { Card } from '../components/ui'

const ROLES = ['Client', 'Shareholder', 'Global Ultimate Parent', 'Intermediate Parent',
  'Client Subsidiary', 'Client Side Entity', 'Principal Operating Entity', 'Target']

const emptyParty = (): Party => ({
  entity_name: '', party_side: 'CLIENT_SIDE', entity_role: 'Client',
  location: '', stated_designation: '', is_gup: false,
})

export default function NewCase() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    request_id: '', service_offering: '', engagement_name: '', engagement_details: '',
    location: '', is_inbound_referral: false, has_iwrf: false,
  })
  const [parties, setParties] = useState<Party[]>([emptyParty()])

  const create = useMutation({
    mutationFn: () => api.createCase({
      ...form,
      parties: parties
        .filter((p) => p.entity_name.trim())
        .map((p) => ({ ...p, stated_designation: p.stated_designation || null, location: p.location || null })),
    }),
    onSuccess: (data) => navigate(`/cases/${data.case_id}`),
  })

  const updateParty = (i: number, patch: Partial<Party>) =>
    setParties((prev) => prev.map((p, j) => (j === i ? { ...p, ...patch } : p)))

  const input = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none'
  const label = 'text-xs font-medium uppercase tracking-wide text-slate-400'

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold">New case</h1>
        <p className="text-sm text-slate-500">Screen an entity that is not already in an ingested DCCS export.</p>
      </div>

      <form onSubmit={(e) => { e.preventDefault(); create.mutate() }} className="space-y-6">
        <Card title="Request details">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className={label}>Request ID *</label>
              <input required value={form.request_id} onChange={(e) => setForm({ ...form, request_id: e.target.value })}
                placeholder="MANUAL-001" className={`mt-1 ${input}`} />
            </div>
            <div>
              <label className={label}>Requesting location</label>
              <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })}
                placeholder="Indonesia" className={`mt-1 ${input}`} />
            </div>
            <div>
              <label className={label}>Service offering</label>
              <input value={form.service_offering} onChange={(e) => setForm({ ...form, service_offering: e.target.value })}
                placeholder="Technology &amp; Transformation \ ..." className={`mt-1 ${input}`} />
            </div>
            <div>
              <label className={label}>Engagement name</label>
              <input value={form.engagement_name} onChange={(e) => setForm({ ...form, engagement_name: e.target.value })}
                className={`mt-1 ${input}`} />
            </div>
            <div className="md:col-span-2">
              <label className={label}>Engagement description</label>
              <textarea rows={3} value={form.engagement_details}
                onChange={(e) => setForm({ ...form, engagement_details: e.target.value })} className={`mt-1 ${input}`} />
            </div>
            <div className="flex items-center gap-6">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.is_inbound_referral}
                  onChange={(e) => setForm({ ...form, is_inbound_referral: e.target.checked })} />
                Inbound work referral
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.has_iwrf}
                  onChange={(e) => setForm({ ...form, has_iwrf: e.target.checked })} />
                IWRF obtained
              </label>
            </div>
          </div>
        </Card>

        <Card
          title="Relevant parties"
          right={
            <button type="button" onClick={() => setParties([...parties, emptyParty()])}
              className="flex items-center gap-1 rounded border border-slate-300 px-2 py-1 text-xs font-medium hover:bg-slate-50">
              <Plus className="h-3 w-3" /> Add party
            </button>
          }
        >
          <div className="space-y-3">
            {parties.map((p, i) => (
              <div key={i} className="grid items-end gap-3 rounded-lg border border-slate-100 bg-slate-50 p-3 md:grid-cols-6">
                <div className="md:col-span-2">
                  <label className={label}>Entity name</label>
                  <input value={p.entity_name} onChange={(e) => updateParty(i, { entity_name: e.target.value })}
                    className={`mt-1 ${input}`} />
                </div>
                <div>
                  <label className={label}>Role</label>
                  <select value={p.entity_role ?? ''} onChange={(e) => updateParty(i, { entity_role: e.target.value })}
                    className={`mt-1 ${input}`}>
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </div>
                <div>
                  <label className={label}>Location</label>
                  <input value={p.location ?? ''} onChange={(e) => updateParty(i, { location: e.target.value })}
                    className={`mt-1 ${input}`} />
                </div>
                <div>
                  <label className={label}>Stated designation</label>
                  <input value={p.stated_designation ?? ''}
                    onChange={(e) => updateParty(i, { stated_designation: e.target.value })} className={`mt-1 ${input}`} />
                </div>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-1.5 text-sm">
                    <input type="checkbox" checked={p.is_gup} onChange={(e) => updateParty(i, { is_gup: e.target.checked })} />
                    GUP
                  </label>
                  {parties.length > 1 && (
                    <button type="button" onClick={() => setParties(parties.filter((_, j) => j !== i))}
                      className="text-slate-400 hover:text-rose-600">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {create.isError && (
          <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{String(create.error)}</p>
        )}

        <button type="submit" disabled={create.isPending}
          className="rounded-lg bg-deloitte-green px-4 py-2 text-sm font-semibold text-slate-900 hover:brightness-95 disabled:opacity-50">
          {create.isPending ? 'Creating…' : 'Create case'}
        </button>
      </form>
    </div>
  )
}
