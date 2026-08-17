import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { supabase } from './supabaseClient'
import Analytics from './Analytics'

const PAGE_SIZE = 30

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

function EnquiryRow({ row, onUpdate, selected, onToggleSelect }) {
  const [expanded, setExpanded] = useState(false)
  const [local, setLocal] = useState(row)
  const editingRef = useRef(false)

  // Skip syncing in a remote (realtime) update while the user has an
  // unsaved keystroke in a free-text field, so it doesn't get clobbered.
  useEffect(() => {
    if (!editingRef.current) setLocal(row)
  }, [row])

  const commit = (field, value) => {
    setLocal((prev) => ({ ...prev, [field]: value }))
    onUpdate(row.id, { [field]: value })
  }

  const startEdit = () => { editingRef.current = true }
  const endEdit = (field, value) => {
    editingRef.current = false
    commit(field, value)
  }

  const u = urgency(local)

  return (
    <div className={`card urgency-${u}${selected ? ' selected' : ''}`}>
      <div className="card-strip" />
      <div className="card-body">
        <div className="card-top">
          <input
            type="checkbox"
            className="select-checkbox"
            checked={selected}
            onChange={() => onToggleSelect(row.id)}
            aria-label="Select enquiry"
          />
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
          onFocus={startEdit}
          onChange={(e) => setLocal((p) => ({ ...p, summary: e.target.value }))}
          onBlur={(e) => endEdit('summary', e.target.value)}
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
              onFocus={startEdit}
              onChange={(e) => setLocal((p) => ({ ...p, assigned_to: e.target.value }))}
              onBlur={(e) => endEdit('assigned_to', e.target.value)}
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
                onFocus={startEdit}
                onChange={(e) => setLocal((p) => ({ ...p, notes: e.target.value }))}
                onBlur={(e) => endEdit('notes', e.target.value)}
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
  const [statusFilter, setStatusFilter] = useState('open') // open | needs_deadline | done | all
  const [sourceFilter, setSourceFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const [reassignValue, setReassignValue] = useState('')
  const [view, setView] = useState('list') // list | analytics
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

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

  // Live updates from other tabs/users, so the list stays current without
  // clicking Refresh. Requires the `enquiries` table to be added to the
  // `supabase_realtime` publication (see inquiry-dashboard-schema-update.sql).
  useEffect(() => {
    const channel = supabase
      .channel('enquiries-changes')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'enquiries' }, (payload) => {
        if (payload.eventType === 'INSERT') {
          setRows((prev) => (prev.some((r) => r.id === payload.new.id) ? prev : [payload.new, ...prev]))
        } else if (payload.eventType === 'UPDATE') {
          setRows((prev) => prev.map((r) => (r.id === payload.new.id ? { ...r, ...payload.new } : r)))
        } else if (payload.eventType === 'DELETE') {
          setRows((prev) => prev.filter((r) => r.id !== payload.old.id))
          setSelected((prev) => {
            if (!prev.has(payload.old.id)) return prev
            const next = new Set(prev)
            next.delete(payload.old.id)
            return next
          })
        }
      })
      .subscribe()

    return () => { supabase.removeChannel(channel) }
  }, [])

  const onUpdate = async (id, patch) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
    const { error: err } = await supabase.from('enquiries').update(patch).eq('id', id)
    if (err) setError(`Save failed: ${err.message}`)
  }

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const clearSelection = () => setSelected(new Set())

  const bulkMarkDone = async () => {
    const ids = Array.from(selected)
    if (ids.length === 0) return
    setRows((prev) => prev.map((r) => (ids.includes(r.id) ? { ...r, status: 'done' } : r)))
    clearSelection()
    const { error: err } = await supabase.from('enquiries').update({ status: 'done' }).in('id', ids)
    if (err) setError(`Bulk update failed: ${err.message}`)
  }

  const bulkReassign = async () => {
    const ids = Array.from(selected)
    const value = reassignValue.trim()
    if (ids.length === 0 || !value) return
    setRows((prev) => prev.map((r) => (ids.includes(r.id) ? { ...r, assigned_to: value } : r)))
    clearSelection()
    setReassignValue('')
    const { error: err } = await supabase.from('enquiries').update({ assigned_to: value }).in('id', ids)
    if (err) setError(`Bulk update failed: ${err.message}`)
  }

  const filtered = useMemo(() => {
    return rows
      .filter((r) => {
        if (statusFilter === 'open') return r.status !== 'done'
        if (statusFilter === 'done') return r.status === 'done'
        if (statusFilter === 'needs_deadline') return urgency(r) === 'flag'
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

  useEffect(() => { setVisibleCount(PAGE_SIZE) }, [statusFilter, sourceFilter, search])

  const visible = filtered.slice(0, visibleCount)

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
          <div className="header-actions">
            <div className="view-toggle">
              <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>List</button>
              <button className={view === 'analytics' ? 'active' : ''} onClick={() => setView('analytics')}>Analytics</button>
            </div>
            <button className="refresh-btn" onClick={fetchRows} disabled={loading}>
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>
        <div className="flute" />
        <div className="counts">
          <div className="count-item"><strong>{counts.open}</strong><span>Open</span></div>
          <div className="count-item count-overdue"><strong>{counts.overdue}</strong><span>Overdue</span></div>
          <button
            type="button"
            className="count-item count-flag count-item-btn"
            onClick={() => setStatusFilter('needs_deadline')}
          >
            <strong>{counts.flagged}</strong><span>No deadline</span>
          </button>
          <div className="count-item"><strong>{counts.total}</strong><span>Total logged</span></div>
        </div>
      </header>

      {view === 'analytics' ? (
        <Analytics rows={rows} />
      ) : (
        <>
          <div className="toolbar">
            <div className="tabs">
              <button className={statusFilter === 'open' ? 'active' : ''} onClick={() => setStatusFilter('open')}>Open</button>
              <button className={statusFilter === 'needs_deadline' ? 'active' : ''} onClick={() => setStatusFilter('needs_deadline')}>Needs Deadline</button>
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

          {selected.size > 0 && (
            <div className="bulk-bar">
              <span>{selected.size} selected</span>
              <button className="bulk-btn" onClick={bulkMarkDone}>Mark done</button>
              <div className="bulk-reassign">
                <input
                  type="text"
                  placeholder="Reassign to…"
                  value={reassignValue}
                  onChange={(e) => setReassignValue(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') bulkReassign() }}
                />
                <button className="bulk-btn" onClick={bulkReassign} disabled={!reassignValue.trim()}>Apply</button>
              </div>
              <button className="bulk-btn bulk-btn-clear" onClick={clearSelection}>Clear</button>
            </div>
          )}

          {error && <div className="error-banner">{error}</div>}

          <main className="list">
            {loading && rows.length === 0 && <p className="empty">Loading enquiries…</p>}
            {!loading && filtered.length === 0 && (
              <p className="empty">Nothing here. New enquiries will show up automatically.</p>
            )}
            {visible.map((row) => (
              <EnquiryRow
                key={row.id}
                row={row}
                onUpdate={onUpdate}
                selected={selected.has(row.id)}
                onToggleSelect={toggleSelect}
              />
            ))}
          </main>

          {visibleCount < filtered.length && (
            <button className="load-more-btn" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
              Load more ({filtered.length - visibleCount} remaining)
            </button>
          )}
        </>
      )}
    </div>
  )
}
