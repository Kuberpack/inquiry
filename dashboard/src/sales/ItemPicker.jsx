import { useEffect, useState } from 'react'
import { fetchItems } from './salesClient'
import ItemModal from './ItemModal'

export default function ItemPicker({ value, onChange }) {
  const [items, setItems] = useState([])
  const [showModal, setShowModal] = useState(false)

  const load = async () => {
    const data = await fetchItems()
    setItems(data)
    return data
  }

  useEffect(() => { load() }, [])

  const handleSelect = (e) => {
    if (e.target.value === '__add_new__') {
      setShowModal(true)
      return
    }
    const item = items.find((i) => i.id === e.target.value) || null
    onChange(item)
  }

  const handleCreated = async (item) => {
    setShowModal(false)
    await load()
    onChange(item)
  }

  return (
    <>
      <select value={value?.id || ''} onChange={handleSelect}>
        <option value="">Select item…</option>
        {items.map((i) => <option key={i.id} value={i.id}>{i.description}</option>)}
        <option value="__add_new__">+ Add new item…</option>
      </select>
      {showModal && <ItemModal onClose={() => setShowModal(false)} onCreated={handleCreated} />}
    </>
  )
}
