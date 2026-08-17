import { useEffect, useState } from 'react'
import { fetchCompanies } from './salesClient'
import CompanyModal from './CompanyModal'

export default function CompanyPicker({ role, value, onChange, label = 'Company' }) {
  const [companies, setCompanies] = useState([])
  const [showModal, setShowModal] = useState(false)

  const load = async () => {
    const data = await fetchCompanies(role)
    setCompanies(data)
    return data
  }

  useEffect(() => { load() }, [role])

  const handleSelect = (e) => {
    if (e.target.value === '__add_new__') {
      setShowModal(true)
      return
    }
    onChange(e.target.value || null)
  }

  const handleCreated = async (company) => {
    setShowModal(false)
    await load()
    onChange(company.id)
  }

  return (
    <>
      <label className="sales-field">
        <span>{label}</span>
        <select value={value || ''} onChange={handleSelect}>
          <option value="">Select…</option>
          {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          <option value="__add_new__">+ Add new company…</option>
        </select>
      </label>
      {showModal && (
        <CompanyModal
          defaultRole={role || 'buyer'}
          onClose={() => setShowModal(false)}
          onCreated={handleCreated}
        />
      )}
    </>
  )
}
