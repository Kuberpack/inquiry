const CATEGORY_LABELS = {
  enquiry: 'Enquiry',
  order: 'Order',
  complaint: 'Complaint',
  follow_up: 'Follow up',
  other: 'Other',
}

function daysBetween(a, b) {
  return (new Date(b) - new Date(a)) / (1000 * 60 * 60 * 24)
}

function compactNumber(n) {
  return n.toLocaleString('en-IN')
}

function StatTile({ label, value }) {
  return (
    <div className="stat-tile">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

function BarList({ title, entries }) {
  const max = Math.max(1, ...entries.map((e) => e.count))
  return (
    <div className="bar-list-card">
      <h3>{title}</h3>
      {entries.length === 0 && <p className="empty">No data yet.</p>}
      <div className="bar-list">
        {entries.map((e) => (
          <div className="bar-row" key={e.label}>
            <span className="bar-label" title={e.label}>{e.label}</span>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(e.count / max) * 100}%` }} />
            </div>
            <span className="bar-value">{e.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Analytics({ rows }) {
  const total = rows.length
  const open = rows.filter((r) => r.status !== 'done').length
  const done = rows.filter((r) => r.status === 'done').length

  const closeDurations = rows
    .filter((r) => r.status === 'done' && r.received_at && r.updated_at)
    .map((r) => daysBetween(r.received_at, r.updated_at))
    .filter((d) => d >= 0)
  const avgCloseDays = closeDurations.length
    ? closeDurations.reduce((sum, d) => sum + d, 0) / closeDurations.length
    : null

  const byCategory = {}
  const byAssignee = {}
  for (const r of rows) {
    const cat = r.category || 'other'
    byCategory[cat] = (byCategory[cat] || 0) + 1
    const who = (r.assigned_to || '').trim() || 'Unassigned'
    byAssignee[who] = (byAssignee[who] || 0) + 1
  }

  const categoryEntries = Object.entries(byCategory)
    .map(([key, count]) => ({ label: CATEGORY_LABELS[key] || key, count }))
    .sort((a, b) => b.count - a.count)

  const assigneeEntries = Object.entries(byAssignee)
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)

  return (
    <div className="analytics">
      <div className="kpi-row">
        <StatTile label="Total logged" value={compactNumber(total)} />
        <StatTile label="Open" value={compactNumber(open)} />
        <StatTile label="Done" value={compactNumber(done)} />
        <StatTile
          label="Avg time to close"
          value={avgCloseDays === null ? '—' : `${avgCloseDays.toFixed(1)}d`}
        />
      </div>
      <p className="analytics-note">
        Time to close is approximated from the last time each enquiry's row was
        updated, so an edit made after closing (e.g. a late note) can slightly
        inflate it.
      </p>

      <div className="bar-list-grid">
        <BarList title="By category" entries={categoryEntries} />
        <BarList title="By assignee" entries={assigneeEntries} />
      </div>
    </div>
  )
}
