import { useState } from 'react'
import { createItem } from './salesClient'

export default function ItemModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ description: '', hsn_sac_code: '', unit: 'Nos', default_price: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    if (!form.description.trim()) {
      setError('Description is required.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const item = await createItem({
        ...form,
        default_price: form.default_price ? Number(form.default_price) : null,
      })
      onCreated(item)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Add Item</h2>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close">&times;</button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            {error && <div className="error-banner">{error}</div>}
            <div className="modal-grid">
              <label className="span-2"><span>Description *</span><input value={form.description} onChange={set('description')} required /></label>
              <label><span>HSN/SAC code</span><input value={form.hsn_sac_code} onChange={set('hsn_sac_code')} /></label>
              <label><span>Unit</span><input value={form.unit} onChange={set('unit')} /></label>
              <label><span>Default price</span><input type="number" step="0.01" min="0" value={form.default_price} onChange={set('default_price')} /></label>
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
