import { useEffect, useMemo, useState, useCallback } from 'react'
import { supabase } from './supabaseClient'

const STATUS_OPTIONS = ['new', 'in_progress', 'done']
const STATUS_LABELS = { new: 'New', in_progress: 'In Progress', done: 'Done' }
const PRIORITY_OPTIONS = ['low', 'medium', 'high']
const CATEGORY_OPTIONS = ['enquiry', 'order', 'complaint', 'follow_up', 'other']

function urgency(row) {
  if (row.status === 'done') return 'done'
  if (!row.deadline) return row.needs_deadline ? 'flag' : 'none'
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const dl = new Date(row.deadline)
  const diffDays = Math.floor((dl - today) / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return 'overdue'
  if (diffDays <= 2) return 'soon'
  return 'normal'
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

function EnquiryRow({ row, onUpdate }) {
  const [expanded, setExpanded] = useState(false)
  const [local, setLocal] = useState(row)

  useEffect(() => setLocal(row), [row])

  const commit = (field, value) => {
    setLocal((prev) => ({ ...prev, [field]: value }))
    onUpdate(row.id, { [field]: value })
  }

  const u = urgency(local)

  return (
    <div className={`card urgency-${u}`}>
      <div className="card-strip" />
      <div className="card-body">
        <div className="card-top">
          <span className={`badge badge-source badge-${row.source}`}>
            {row.source === 'gmail' ? 'Gmail' : 'WhatsApp'}
          </span>
          <span className="sender" title={row.sender_contact}>{row.sender_name || 'Unknown sender'}</span>
          <span className="received">{formatDateTime(row.received_at)}</span>
          {u === 'flag' && <span className="badge badge-flag">No deadline found</span>}
          {u === 'overdue' && <span className="badge badge-overdue">Overdue</span>}
        </div>

        <textarea
          className="summary-input"
          value={local.summary || ''}
          onChange={(e) => setLocal((p) => ({ ...p, summary: e.target.value }))}
          onBlur={(e) => commit('summary', e.target.value)}
          rows={2}
          placeholder="Summary…"
        />

        <div className="field-row">
          <label>
            <span>Category</span>
            <select value={local.category || 'other'} onChange={(e) => commit('category', e.target.value)}>
              {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c.replace('_', ' ')}</option>)}
            </select>
          </label>

          <label>
            <span>Priority</span>
            <select value={local.priority || 'medium'} onChange={(e) => commit('priority', e.target.value)}>
              {PRIORITY_OPTIONS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>

          <label>
            <span>Deadline</span>
            <input
              type="date"
              value={local.deadline ? local.deadline.slice(0, 10) : ''}
              onChange={(e) => commit('deadline', e.target.value || null)}
            />
          </label>

          <label>
            <span>Status</span>
            <select value={local.status} onChange={(e) => commit('status', e.target.value)}>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
          </label>

          <label>
            <span>Assigned to</span>
            <input
              type="text"
              value={local.assigned_to || ''}
              onChange={(e) => setLocal((p) => ({ ...p, assigned_to: e.target.value }))}
              onBlur={(e) => commit('assigned_to', e.target.value)}
              placeholder="Unassigned"
            />
          </label>
        </div>

        <button className="link-btn" onClick={() => setExpanded((x) => !x)}>
          {expanded ? 'Hide details' : 'Notes & original message'}
        </button>

        {expanded && (
          <div className="expanded">
            <label className="notes-label">
              <span>Notes</span>
              <textarea
                value={local.notes || ''}
                onChange={(e) => setLocal((p) => ({ ...p, notes: e.target.value }))}
                onBlur={(e) => commit('notes', e.target.value)}
                rows={3}
                placeholder="Add a note…"
              />
            </label>
            <div className="raw-text">
              <span>Original message</span>
              <pre>{row.raw_text}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [statusFilter, setStatusFilter] = useState('open') // open | all | done
  const [sourceFilter, setSourceFilter] = useState('all')
  const [search, setSearch] = useState('')

  const fetchRows = useCallback(async () => {
    setLoading(true)
    setError(null)
    const { data, error: err } = await supabase
      .from('enquiries')
      .select('*')
      .order('received_at', { ascending: false })
    if (err) setError(err.message)
    else setRows(data || [])
    setLoading(false)
  }, [])

  useEffect(() => { fetchRows() }, [fetchRows])

  const onUpdate = async (id, patch) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
    const { error: err } = await supabase.from('enquiries').update(patch).eq('id', id)
    if (err) setError(`Save failed: ${err.message}`)
  }

  const filtered = useMemo(() => {
    return rows
      .filter((r) => {
        if (statusFilter === 'open') return r.status !== 'done'
        if (statusFilter === 'done') return r.status === 'done'
        return true
      })
      .filter((r) => sourceFilter === 'all' || r.source === sourceFilter)
      .filter((r) => {
        if (!search.trim()) return true
        const q = search.toLowerCase()
        return (
          (r.sender_name || '').toLowerCase().includes(q) ||
          (r.summary || '').toLowerCase().includes(q) ||
          (r.raw_text || '').toLowerCase().includes(q)
        )
      })
      .sort((a, b) => {
        const rank = { overdue: 0, flag: 1, soon: 2, normal: 3, done: 4, none: 3 }
        const ra = rank[urgency(a)]
        const rb = rank[urgency(b)]
        if (ra !== rb) return ra - rb
        return new Date(b.received_at) - new Date(a.received_at)
      })
  }, [rows, statusFilter, sourceFilter, search])

  const counts = useMemo(() => {
    const open = rows.filter((r) => r.status !== 'done')
    const overdue = open.filter((r) => urgency(r) === 'overdue')
    const flagged = open.filter((r) => urgency(r) === 'flag')
    return { open: open.length, overdue: overdue.length, flagged: flagged.length, total: rows.length }
  }, [rows])

  return (
    <div className="app">
      <header className="header">
        <div className="header-top">
          <h1>Kuberpack <span>Enquiry Log</span></h1>
          <button className="refresh-btn" onClick={fetchRows} disabled={loading}>
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        <div className="flute" />
        <div className="counts">
          <div className="count-item"><strong>{counts.open}</strong><span>Open</span></div>
          <div className="count-item count-overdue"><strong>{counts.overdue}</strong><span>Overdue</span></div>
          <div className="count-item count-flag"><strong>{counts.flagged}</strong><span>No deadline</span></div>
          <div className="count-item"><strong>{counts.total}</strong><span>Total logged</span></div>
        </div>
      </header>

      <div className="toolbar">
        <div className="tabs">
          <button className={statusFilter === 'open' ? 'active' : ''} onClick={() => setStatusFilter('open')}>Open</button>
          <button className={statusFilter === 'done' ? 'active' : ''} onClick={() => setStatusFilter('done')}>Done</button>
          <button className={statusFilter === 'all' ? 'active' : ''} onClick={() => setStatusFilter('all')}>All</button>
        </div>
        <select className="source-select" value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
          <option value="all">All sources</option>
          <option value="gmail">Gmail</option>
          <option value="whatsapp">WhatsApp</option>
        </select>
        <input
          className="search-input"
          type="text"
          placeholder="Search sender or message…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="error-banner">{error}</div>}

      <main className="list">
        {loading && rows.length === 0 && <p className="empty">Loading enquiries…</p>}
        {!loading && filtered.length === 0 && (
          <p className="empty">Nothing here. New enquiries will show up automatically.</p>
        )}
        {filtered.map((row) => (
          <EnquiryRow key={row.id} row={row} onUpdate={onUpdate} />
        ))}
      </main>
    </div>
  )
}
