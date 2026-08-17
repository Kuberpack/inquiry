import { useEffect, useState } from 'react'
import { fetchSalesEnquiries } from './salesClient'

export default function SalesEnquiryList({ onOpen, onCreate, refreshKey }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('all')

  const load = async () => {
    setLoading(true)
    setRows(await fetchSalesEnquiries())
    setLoading(false)
  }

  useEffect(() => { load() }, [refreshKey])

  const filtered = rows.filter((r) => statusFilter === 'all' || r.status === statusFilter)

  return (
    <div className="sales-list">
      <div className="toolbar">
        <div className="tabs">
          <button className={statusFilter === 'all' ? 'active' : ''} onClick={() => setStatusFilter('all')}>All</button>
          <button className={statusFilter === 'draft' ? 'active' : ''} onClick={() => setStatusFilter('draft')}>Draft</button>
          <button className={statusFilter === 'confirmed' ? 'active' : ''} onClick={() => setStatusFilter('confirmed')}>Confirmed</button>
        </div>
        <button className="refresh-btn" onClick={onCreate}>+ Create Sales Enquiry</button>
      </div>

      {loading && <p className="empty">Loading…</p>}
      {!loading && filtered.length === 0 && <p className="empty">No sales enquiries yet.</p>}

      {!loading && filtered.length > 0 && (
        <div className="sales-table-wrap">
          <table className="sales-table">
            <thead>
              <tr>
                <th>Doc #</th>
                <th>Buyer</th>
                <th>Date</th>
                <th>Reference</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} onClick={() => onOpen(r.id)}>
                  <td>{r.doc_number}</td>
                  <td>{r.buyer?.name || '—'}</td>
                  <td>{r.doc_date}</td>
                  <td>{r.customer_enquiry_number || '—'}</td>
                  <td><span className={`status-pill status-${r.status}`}>{r.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
