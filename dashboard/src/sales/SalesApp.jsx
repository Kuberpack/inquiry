import { useState } from 'react'
import SalesEnquiryList from './SalesEnquiryList'
import SalesEnquiryForm from './SalesEnquiryForm'
import SalesQuotationList from './SalesQuotationList'
import SalesQuotationForm from './SalesQuotationForm'

// screen: { doc: 'enquiry' | 'quotation', mode: 'list' | 'form', id?: string, prefill?: object }
export default function SalesApp({ initialScreen }) {
  const [doc, setDoc] = useState(initialScreen?.doc || 'enquiry')
  const [screen, setScreen] = useState(initialScreen || { mode: 'list' })
  const [refreshKey, setRefreshKey] = useState(0)

  const goToList = (whichDoc) => {
    setDoc(whichDoc)
    setScreen({ mode: 'list' })
    setRefreshKey((k) => k + 1)
  }

  return (
    <div className="sales-app">
      <div className="view-toggle sales-doc-toggle">
        <button className={doc === 'enquiry' ? 'active' : ''} onClick={() => goToList('enquiry')}>Sales Enquiry</button>
        <button className={doc === 'quotation' ? 'active' : ''} onClick={() => goToList('quotation')}>Sales Quotation</button>
      </div>

      {doc === 'enquiry' && screen.mode === 'list' && (
        <SalesEnquiryList
          refreshKey={refreshKey}
          onOpen={(id) => setScreen({ mode: 'form', id })}
          onCreate={() => setScreen({ mode: 'form', id: null })}
        />
      )}

      {doc === 'enquiry' && screen.mode === 'form' && (
        <SalesEnquiryForm
          id={screen.id}
          prefill={screen.prefill}
          onSaved={() => setRefreshKey((k) => k + 1)}
          onConvert={(quotationId) => {
            setDoc('quotation')
            setScreen({ mode: 'form', id: quotationId })
            setRefreshKey((k) => k + 1)
          }}
          onCancel={() => goToList('enquiry')}
        />
      )}

      {doc === 'quotation' && screen.mode === 'list' && (
        <SalesQuotationList
          refreshKey={refreshKey}
          onOpen={(id) => setScreen({ mode: 'form', id })}
        />
      )}

      {doc === 'quotation' && screen.mode === 'form' && (
        <SalesQuotationForm
          id={screen.id}
          onSaved={() => setRefreshKey((k) => k + 1)}
          onCancel={() => goToList('quotation')}
        />
      )}
    </div>
  )
}
