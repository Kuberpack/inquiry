import { supabase } from '../supabaseClient'

// Kuberpack's own registered GST state — used to decide CGST+SGST (same
// state as the buyer) vs IGST (different state). Single-entity simplification
// for v1; change here if that ever needs to vary per document.
export const SUPPLIER_STATE = 'Maharashtra'

function sameState(a, b) {
  return !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase()
}

// ---------------------------------------------------------------------
// Companies
// ---------------------------------------------------------------------

export async function fetchCompanies(role) {
  let query = supabase.from('companies').select('*').order('name')
  if (role) query = query.in('role', [role, 'both'])
  const { data, error } = await query
  if (error) throw error
  return data || []
}

export async function createCompany(company) {
  const { data, error } = await supabase.from('companies').insert(company).select().single()
  if (error) throw error
  return data
}

// ---------------------------------------------------------------------
// Items
// ---------------------------------------------------------------------

export async function fetchItems() {
  const { data, error } = await supabase.from('items').select('*').order('description')
  if (error) throw error
  return data || []
}

export async function createItem(item) {
  const { data, error } = await supabase.from('items').insert(item).select().single()
  if (error) throw error
  return data
}

// ---------------------------------------------------------------------
// Sales Enquiries
// ---------------------------------------------------------------------

export async function fetchSalesEnquiries() {
  const { data, error } = await supabase
    .from('sales_enquiries')
    .select('*, buyer:companies(*)')
    .order('created_at', { ascending: false })
  if (error) throw error
  return data || []
}

export async function fetchSalesEnquiry(id) {
  const { data, error } = await supabase
    .from('sales_enquiries')
    .select('*, buyer:companies(*), items:sales_enquiry_items(*)')
    .eq('id', id)
    .single()
  if (error) throw error
  return data
}

export async function createSalesEnquiry(doc) {
  const { data, error } = await supabase.from('sales_enquiries').insert(doc).select().single()
  if (error) throw error
  return data
}

export async function updateSalesEnquiry(id, patch) {
  const { error } = await supabase.from('sales_enquiries').update(patch).eq('id', id)
  if (error) throw error
}

// Replaces every line item for a document — simplest correct approach for
// a form that submits its whole item table at once.
export async function replaceSalesEnquiryItems(salesEnquiryId, items) {
  const { error: delErr } = await supabase
    .from('sales_enquiry_items')
    .delete()
    .eq('sales_enquiry_id', salesEnquiryId)
  if (delErr) throw delErr

  if (items.length === 0) return
  const rows = items.map((it, i) => ({ ...it, sales_enquiry_id: salesEnquiryId, sort_order: i }))
  const { error: insErr } = await supabase.from('sales_enquiry_items').insert(rows)
  if (insErr) throw insErr
}

// Prefill a new draft Sales Enquiry from a row in the Gmail/WhatsApp
// `enquiries` table — the "Convert to Sales Enquiry" action.
export async function convertEnquiryToSalesEnquiry(enquiry) {
  return createSalesEnquiry({
    source_enquiry_id: enquiry.id,
    poc_name: enquiry.sender_name || null,
    poc_contact: enquiry.sender_contact || null,
    customer_enquiry_date: enquiry.received_at ? enquiry.received_at.slice(0, 10) : null,
    kind_attention: enquiry.sender_name || null,
    expected_reply_date: enquiry.deadline ? enquiry.deadline.slice(0, 10) : null,
  })
}

// ---------------------------------------------------------------------
// Sales Quotations
// ---------------------------------------------------------------------

export async function fetchSalesQuotations() {
  const { data, error } = await supabase
    .from('sales_quotations')
    .select('*, buyer:companies(*)')
    .order('created_at', { ascending: false })
  if (error) throw error
  return data || []
}

export async function fetchSalesQuotation(id) {
  const { data, error } = await supabase
    .from('sales_quotations')
    .select('*, buyer:companies(*), items:sales_quotation_items(*)')
    .eq('id', id)
    .single()
  if (error) throw error
  return data
}

export async function createSalesQuotation(doc) {
  const { data, error } = await supabase.from('sales_quotations').insert(doc).select().single()
  if (error) throw error
  return data
}

export async function updateSalesQuotation(id, patch) {
  const { error } = await supabase.from('sales_quotations').update(patch).eq('id', id)
  if (error) throw error
}

export async function replaceSalesQuotationItems(salesQuotationId, items) {
  const { error: delErr } = await supabase
    .from('sales_quotation_items')
    .delete()
    .eq('sales_quotation_id', salesQuotationId)
  if (delErr) throw delErr

  if (items.length === 0) return
  const rows = items.map((it, i) => ({ ...it, sales_quotation_id: salesQuotationId, sort_order: i }))
  const { error: insErr } = await supabase.from('sales_quotation_items').insert(rows)
  if (insErr) throw insErr
}

// Carries buyer/terms/items forward from a confirmed Sales Enquiry into a
// new draft Sales Quotation — the "Convert to Sales Quotation" action.
export async function convertSalesEnquiryToQuotation(salesEnquiry) {
  const quotation = await createSalesQuotation({
    sales_enquiry_id: salesEnquiry.id,
    buyer_id: salesEnquiry.buyer_id,
    delivery_address: salesEnquiry.delivery_address,
    payment_term: salesEnquiry.payment_term,
    poc_name: salesEnquiry.poc_name,
    poc_contact: salesEnquiry.poc_contact,
  })

  const items = (salesEnquiry.items || []).map((it) => ({
    item_id: it.item_id,
    description: it.description,
    quantity: it.quantity,
    unit: it.unit,
    price: it.price,
    tax_rate: 18,
  }))
  if (items.length > 0) {
    await replaceSalesQuotationItems(quotation.id, items)
  }
  return quotation
}

// ---------------------------------------------------------------------
// Totals / GST
// ---------------------------------------------------------------------

// Simplification: tax is computed on each line's full (undiscounted)
// value; the discount is subtracted once at the grand-total level rather
// than reducing the taxable base. Revisit if the company's actual
// invoicing policy needs the discount to affect tax.
export function calcTotals(items, discountAmount, buyerState) {
  const subtotal = items.reduce((sum, it) => sum + (it.quantity || 0) * (it.price || 0), 0)
  const useIgst = !sameState(buyerState, SUPPLIER_STATE)

  let cgst = 0
  let sgst = 0
  let igst = 0
  for (const it of items) {
    const lineValue = (it.quantity || 0) * (it.price || 0)
    const lineTax = (lineValue * (it.tax_rate || 0)) / 100
    if (useIgst) igst += lineTax
    else {
      cgst += lineTax / 2
      sgst += lineTax / 2
    }
  }

  const taxTotal = cgst + sgst + igst
  const discount = discountAmount || 0
  const grandTotal = subtotal - discount + taxTotal

  return { subtotal, cgst, sgst, igst, taxTotal, discount, grandTotal, useIgst }
}
