import { useEffect, useState } from 'react'
import CompanyPicker from './CompanyPicker'
import LineItemsTable from './LineItemsTable'
import {
  fetchSalesQuotation,
  updateSalesQuotation,
  replaceSalesQuotationItems,
  calcTotals,
  SUPPLIER_STATE,
} from './salesClient'

export default function SalesQuotationForm({ id, onSaved, onCancel }) {
  const [doc, setDoc] = useState(null)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchSalesQuotation(id).then((data) => {
      setDoc(data)
      setItems((data.items || []).map((it) => ({ ...it })))
      setLoading(false)
    }).catch((err) => { setError(err.message); setLoading(false) })
  }, [id])

  const set = (field) => (e) => setDoc((d) => ({ ...d, [field]: e.target.value }))

  const save = async (status) => {
    setSaving(true)
    setError(null)
    try {
      const payload = { ...doc, status: status || doc.status }
      delete payload.buyer
      delete payload.items
      delete payload.id
      delete payload.doc_number
      delete payload.created_at
      delete payload.updated_at
      delete payload.sales_enquiry_id

      await updateSalesQuotation(id, payload)
      await replaceSalesQuotationItems(id, items.map(({ id: _drop, sales_quotation_id: _drop2, ...rest }) => rest))
      setDoc((d) => ({ ...d, status: status || d.status }))
      onSaved(id)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading || !doc) return <p className="empty">Loading…</p>

  const totals = calcTotals(items, Number(doc.discount_amount) || 0, doc.buyer?.state)

  return (
    <div className="sales-form">
      <div className="sales-form-header">
        <h2>{doc.doc_number}</h2>
        <button type="button" className="link-btn" onClick={onCancel}>Back to list</button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="sales-grid">
        <CompanyPicker
          role="buyer"
          value={doc.buyer_id}
          onChange={(v) => setDoc((d) => ({ ...d, buyer_id: v }))}
          label="Buyer"
        />
        <label className="sales-field span-2">
          <span>Delivery address</span>
          <textarea rows={2} value={doc.delivery_address || ''} onChange={set('delivery_address')} />
        </label>
        <label className="sales-field"><span>Payment term</span><input value={doc.payment_term || ''} onChange={set('payment_term')} /></label>
        <label className="sales-field"><span>POC name</span><input value={doc.poc_name || ''} onChange={set('poc_name')} /></label>
        <label className="sales-field"><span>POC contact</span><input value={doc.poc_contact || ''} onChange={set('poc_contact')} /></label>
        <label className="sales-field"><span>Discount amount</span><input type="number" min="0" step="0.01" value={doc.discount_amount ?? 0} onChange={set('discount_amount')} /></label>
      </div>

      <h3>Items</h3>
      <LineItemsTable items={items} onChange={setItems} showTax />

      <div className="sales-totals">
        <div className="sales-totals-row"><span>Subtotal</span><span>₹{totals.subtotal.toFixed(2)}</span></div>
        <div className="sales-totals-row"><span>Discount</span><span>−₹{totals.discount.toFixed(2)}</span></div>
        {totals.useIgst ? (
          <div className="sales-totals-row"><span>IGST</span><span>₹{totals.igst.toFixed(2)}</span></div>
        ) : (
          <>
            <div className="sales-totals-row"><span>CGST</span><span>₹{totals.cgst.toFixed(2)}</span></div>
            <div className="sales-totals-row"><span>SGST</span><span>₹{totals.sgst.toFixed(2)}</span></div>
          </>
        )}
        <div className="sales-totals-row sales-totals-grand"><span>Grand total</span><span>₹{totals.grandTotal.toFixed(2)}</span></div>
      </div>
      <p className="analytics-note">
        {doc.buyer?.state
          ? `Buyer state: ${doc.buyer.state} — ${totals.useIgst ? 'IGST applies (different state from ' + SUPPLIER_STATE + ')' : 'CGST+SGST applies (same state as ' + SUPPLIER_STATE + ')'}.`
          : `No buyer state set — defaulting to IGST. Set the buyer's state for an accurate CGST/SGST split.`}
      </p>

      <div className="sales-form-actions">
        <button type="button" className="bulk-btn btn-secondary" onClick={() => save('draft')} disabled={saving}>Save draft</button>
        <button type="button" className="bulk-btn" onClick={() => save('confirmed')} disabled={saving}>Save &amp; confirm</button>
      </div>
    </div>
  )
}
