import ItemPicker from './ItemPicker'

export default function LineItemsTable({ items, onChange, showTax = false }) {
  const updateRow = (index, patch) => {
    onChange(items.map((it, i) => (i === index ? { ...it, ...patch } : it)))
  }

  const removeRow = (index) => onChange(items.filter((_, i) => i !== index))

  const addRow = () => onChange([
    ...items,
    { item_id: null, description: '', quantity: 1, unit: 'Nos', price: 0, ...(showTax ? { tax_rate: 18 } : {}) },
  ])

  const pickItem = (index) => (item) => {
    if (!item) return
    updateRow(index, {
      item_id: item.id,
      description: item.description,
      unit: item.unit || 'Nos',
      price: item.default_price ?? 0,
    })
  }

  return (
    <div className="line-items">
      <div className="line-items-table-wrap">
        <table className="line-items-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Description</th>
              <th>Qty</th>
              <th>Unit</th>
              <th>Price</th>
              {showTax && <th>Tax %</th>}
              <th>Total</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                <td><ItemPicker value={it.item_id ? { id: it.item_id } : null} onChange={pickItem(i)} /></td>
                <td><input value={it.description} onChange={(e) => updateRow(i, { description: e.target.value })} /></td>
                <td><input className="qty-input" type="number" min="0" step="0.01" value={it.quantity} onChange={(e) => updateRow(i, { quantity: Number(e.target.value) })} /></td>
                <td><input className="unit-input" value={it.unit} onChange={(e) => updateRow(i, { unit: e.target.value })} /></td>
                <td><input className="price-input" type="number" min="0" step="0.01" value={it.price} onChange={(e) => updateRow(i, { price: Number(e.target.value) })} /></td>
                {showTax && (
                  <td><input className="qty-input" type="number" min="0" step="0.01" value={it.tax_rate} onChange={(e) => updateRow(i, { tax_rate: Number(e.target.value) })} /></td>
                )}
                <td className="line-total">{((it.quantity || 0) * (it.price || 0)).toFixed(2)}</td>
                <td><button type="button" className="link-btn" onClick={() => removeRow(i)}>Remove</button></td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={showTax ? 8 : 7} className="empty">No items yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <button type="button" className="load-more-btn" onClick={addRow}>+ Add item</button>
    </div>
  )
}
