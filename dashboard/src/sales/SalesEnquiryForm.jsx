import { useEffect, useState } from 'react'
import CompanyPicker from './CompanyPicker'
import LineItemsTable from './LineItemsTable'
import {
  fetchSalesEnquiry,
  createSalesEnquiry,
  updateSalesEnquiry,
  replaceSalesEnquiryItems,
  convertSalesEnquiryToQuotation,
} from './salesClient'

const emptyDoc = {
  buyer_id: null,
  delivery_address: '',
  payment_term: '',
  poc_name: '',
  poc_contact: '',
  customer_enquiry_number: '',
  customer_enquiry_date: '',
  expected_reply_date: '',
  kind_attention: '',
  status: 'draft',
}

export default function SalesEnquiryForm({ id, prefill, onSaved, onConvert, onCancel }) {
  const [id_, setId] = useState(id || null)
  const [doc, setDoc] = useState(prefill ? { ...emptyDoc, ...prefill } : emptyDoc)
  const [items, setItems] = useState([])
  const [docNumber, setDocNumber] = useState(null)
  const [loading, setLoading] = useState(!!id)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!id) return
    fetchSalesEnquiry(id).then((data) => {
      setDoc(data)
      setDocNumber(data.doc_number)
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

      let savedId = id_
      if (savedId) {
        await updateSalesEnquiry(savedId, payload)
      } else {
        const created = await createSalesEnquiry(payload)
        savedId = created.id
        setId(savedId)
        setDocNumber(created.doc_number)
      }
      await replaceSalesEnquiryItems(savedId, items.map(({ id: _drop, sales_enquiry_id: _drop2, ...rest }) => rest))
      setDoc((d) => ({ ...d, status: status || d.status }))
      onSaved(savedId)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleConvert = async () => {
    if (!id_) return
    setSaving(true)
    setError(null)
    try {
      const full = await fetchSalesEnquiry(id_)
      const quotation = await convertSalesEnquiryToQuotation(full)
      onConvert(quotation.id)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  if (loading) return <p className="empty">Loading…</p>

  return (
    <div className="sales-form">
      <div className="sales-form-header">
        <h2>{docNumber || 'New Sales Enquiry'}</h2>
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
        <label className="sales-field"><span>Customer enquiry number</span><input value={doc.customer_enquiry_number || ''} onChange={set('customer_enquiry_number')} /></label>
        <label className="sales-field"><span>Customer enquiry date</span><input type="date" value={doc.customer_enquiry_date || ''} onChange={set('customer_enquiry_date')} /></label>
        <label className="sales-field"><span>Expected reply date</span><input type="date" value={doc.expected_reply_date || ''} onChange={set('expected_reply_date')} /></label>
        <label className="sales-field"><span>Kind attention</span><input value={doc.kind_attention || ''} onChange={set('kind_attention')} /></label>
      </div>

      <h3>Items</h3>
      <LineItemsTable items={items} onChange={setItems} />

      <div className="sales-form-actions">
        <button type="button" className="bulk-btn btn-secondary" onClick={() => save('draft')} disabled={saving}>Save draft</button>
        <button type="button" className="bulk-btn" onClick={() => save('confirmed')} disabled={saving}>Save &amp; confirm</button>
        {id_ && doc.status === 'confirmed' && (
          <button type="button" className="bulk-btn" onClick={handleConvert} disabled={saving}>Convert to Sales Quotation</button>
        )}
      </div>
    </div>
  )
}
