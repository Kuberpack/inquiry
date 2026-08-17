import { useState } from 'react'
import { createCompany } from './salesClient'

const ROLE_OPTIONS = ['buyer', 'supplier', 'both']
const GST_TYPES = ['regular', 'composition', 'unregistered']

export default function CompanyModal({ defaultRole = 'buyer', onClose, onCreated }) {
  const [form, setForm] = useState({
    name: '', email: '', phone: '', role: defaultRole, gstin: '', gst_type: 'regular',
    address_line1: '', address_line2: '', city: '', state: '', country: 'India', pincode: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (!form.name.trim()) {
      setError('Company name is required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const company = await createCompany(form)
      onCreated(company)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Add Company</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">&times;</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            {error && <div className="error-banner">{error}</div>}
            <div className="modal-grid">
              <label><span>Name *</span><input value={form.name} onChange={set('name')} required /></label>
              <label><span>Email</span><input type="email" value={form.email} onChange={set('email')} /></label>
              <label><span>Phone</span><input value={form.phone} onChange={set('phone')} /></label>
              <label>
                <span>Role</span>
                <select value={form.role} onChange={set('role')}>
                  {ROLE_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label><span>GSTIN</span><input value={form.gstin} onChange={set('gstin')} /></label>
              <label>
                <span>GST type</span>
                <select value={form.gst_type} onChange={set('gst_type')}>
                  {GST_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </label>
              <label className="span-2"><span>Address line 1</span><input value={form.address_line1} onChange={set('address_line1')} /></label>
              <label className="span-2"><span>Address line 2</span><input value={form.address_line2} onChange={set('address_line2')} /></label>
              <label><span>City</span><input value={form.city} onChange={set('city')} /></label>
              <label><span>State</span><input value={form.state} onChange={set('state')} /></label>
              <label><span>Country</span><input value={form.country} onChange={set('country')} /></label>
              <label><span>Pincode</span><input value={form.pincode} onChange={set('pincode')} /></label>
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="bulk-btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="bulk-btn" disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
