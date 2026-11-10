import { useCallback, useEffect, useMemo, useState } from 'react'

import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { StatusBadge, type StatusTone } from '@/components/ui/status-badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  getInvoice, getInvoiceInvestigations, getInvoices, startInvoiceInvestigation, type InvoiceListParams,
} from '@/services/api'
import type { InvoiceDetail, InvoiceInvestigationsResponse, InvoiceListItem, InvoiceListResponse } from '@/types/api'

const PAGE_SIZE = 25

function formatNumber(value: number | null | undefined) {
  return value == null ? 'Unavailable' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
}

function formatDate(value: string | null | undefined) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function label(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

function statusTone(value: string): StatusTone {
  if (value === 'official_registry_verified' || value === 'no_match') return value === 'no_match' ? 'neutral' : 'sage'
  if (value === 'official_company_document' || value === 'stock_exchange_filing') return 'accent'
  if (value === 'possible_match' || value === 'third_party_match') return 'warning'
  if (value === 'unavailable' || value.startsWith('unavailable_')) return 'neutral'
  return 'neutral'
}

function FieldGrid({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values).filter(([, value]) => value !== null && value !== undefined && value !== '')
  if (!entries.length) return <p className="text-sm text-muted-foreground">No fields are available in the source record.</p>
  return <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">
    {entries.map(([key, value]) => <div key={key} className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label(key)}</dt>
      <dd className="mt-1 break-words text-sm text-foreground">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
    </div>)}
  </dl>
}

function SourceLink({ url }: { url: string | null }) {
  if (!url) return <span className="text-xs text-muted-foreground">No source URL stored</span>
  if (!/^https?:\/\//i.test(url)) return <span className="break-all text-xs text-muted-foreground">{url}</span>
  return <a href={url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 break-all text-xs text-primary hover:underline">{url}<Icon name="external" size={13} className="shrink-0" /></a>
}

function DetailPanel({
  detail, investigations, investigationsLoading, investigationError, starting,
  onStart,
}: {
  detail: InvoiceDetail
  investigations: InvoiceInvestigationsResponse | null
  investigationsLoading: boolean
  investigationError: string | null
  starting: boolean
  onStart: () => void
}) {
  const invoiceFields = detail.invoice
  const sourceEvidence = investigations?.investigations.flatMap((investigation) =>
    investigation.evidence.filter((record) => record.source_url || record.source_type !== 'internal_records').map((record) => ({ ...record, caseId: investigation.investigation_id })),
  ) ?? []

  return <div className="space-y-4">
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 pb-3">
        <div className="min-w-0"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Invoice inspector</p><CardTitle className="mt-1 break-all text-lg">{detail.invoice_id}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{detail.vendor?.vendor_name ?? detail.vendor_id ?? 'Vendor relationship unavailable'}</p></div>
        <StatusBadge tone={detail.overall_status === 'Flagged' ? 'warning' : 'sage'}>{detail.overall_status === 'Flagged' ? 'Flagged for review' : detail.overall_status ?? 'Status unavailable'}</StatusBadge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button onClick={onStart} disabled={starting || !detail.vendor_id || detail.vendor_mapping_conflict}>
            <Icon name="plus" size={16} /> {starting ? 'Starting…' : 'Start investigation'}
          </Button>
          {detail.vendor_mapping_conflict && <StatusBadge tone="warning">PO vendor mapping conflict</StatusBadge>}
        </div>
        <p className="text-xs leading-5 text-muted-foreground">Investigation creation runs the existing internal checks. Existing external research evidence is displayed below when stored. No payment action is available here.</p>
      </CardContent>
    </Card>

    <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Invoice information</CardTitle></CardHeader><CardContent><FieldGrid values={invoiceFields} /></CardContent></Card>

    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-sm">Vendor and transaction context</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        <div><h4 className="mb-3 text-xs font-semibold text-muted-foreground">Vendor · {detail.vendor_id ?? 'relationship unavailable'}</h4>{detail.vendor ? <FieldGrid values={detail.vendor} /> : <p className="text-sm text-muted-foreground">{detail.sources.vendors.available ? 'Vendor details are not linked to this invoice.' : 'Vendor source unavailable.'}</p>}</div>
        <div className="border-t border-border pt-4"><h4 className="mb-3 text-xs font-semibold text-muted-foreground">Related purchase orders</h4>{detail.purchase_orders.length ? <div className="space-y-3">{detail.purchase_orders.map((po, index) => <div key={`${po.po_id ?? 'po'}-${index}`} className="rounded-md bg-background p-3"><FieldGrid values={po} /></div>)}</div> : <p className="text-sm text-muted-foreground">{detail.sources.purchase_orders.available ? 'No matching purchase-order record is available.' : 'Purchase-order source unavailable.'}</p>}</div>
        <div className="border-t border-border pt-4"><h4 className="mb-3 text-xs font-semibold text-muted-foreground">Vendor contracts</h4>{detail.contracts.length ? <div className="space-y-3">{detail.contracts.map((contract, index) => <div key={`${contract.contract_id ?? 'contract'}-${index}`} className="rounded-md bg-background p-3"><FieldGrid values={contract} /></div>)}</div> : <p className="text-sm text-muted-foreground">{detail.sources.contracts.available ? 'No contract record is linked to this vendor in contracts.csv.' : 'Contract source unavailable.'}</p>}</div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-sm">Detection evidence</CardTitle><p className="text-xs text-muted-foreground">Stored model and rule outputs; signals do not establish fraud.</p></CardHeader>
      <CardContent className="space-y-4">
        <section><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Rules</h4>{detail.detection.rules.length ? <div className="space-y-2">{detail.detection.rules.map((rule) => <div key={rule.rule} className="rounded-md border border-border p-3"><div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{rule.label}</span><StatusBadge tone="warning">Triggered</StatusBadge></div><p className="mt-1 text-xs text-muted-foreground">{rule.explanation}</p><p className="mt-1 text-[10px] text-muted-foreground">Flag field: {rule.rule} · Definition source: src/utils/rules_pandas.py</p></div>)}</div> : <p className="rounded-md bg-background p-3 text-sm text-muted-foreground">No triggered rule flags were found in this invoice’s prepared rule fields.</p>}</section>
        <section className="border-t border-border pt-4"><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Graph neural network</h4><div className="grid grid-cols-2 gap-3"><div className="rounded-md bg-background p-3"><p className="text-[11px] text-muted-foreground">Risk score</p><p className="mt-1 text-sm font-semibold">{detail.detection.gnn.risk_score == null ? 'Unavailable' : formatNumber(detail.detection.gnn.risk_score)}</p></div><div className="rounded-md bg-background p-3"><p className="text-[11px] text-muted-foreground">Prediction output</p><p className="mt-1 text-sm font-semibold">{detail.detection.gnn.prediction == null ? 'Unavailable' : detail.detection.gnn.prediction ? '1' : '0'}</p></div></div><p className="mt-2 text-xs text-muted-foreground">The score and binary prediction are model outputs, not a human decision.</p></section>
        <section className="border-t border-border pt-4"><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Contract RAG</h4>{detail.detection.rag ? <div className="space-y-3"><FieldGrid values={detail.detection.rag} /><p className="text-xs leading-5 text-muted-foreground">RAG fields are copied from the invoice-linked rag_similarity_scores.csv record.</p></div> : <p className="rounded-md bg-background p-3 text-sm text-muted-foreground">{detail.sources.rag.available ? 'No invoice-linked RAG record is available.' : 'RAG source unavailable.'}</p>}</section>
      </CardContent>
    </Card>

    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-sm">Human audit decisions</CardTitle><p className="text-xs text-muted-foreground">From audit_log.csv; kept separate from model and investigation status.</p></CardHeader>
      <CardContent>{detail.human_decisions.length ? <div className="space-y-2">{detail.human_decisions.map((decision, index) => <div key={`${decision.time}-${index}`} className="rounded-md border border-border p-3"><div className="flex flex-wrap items-center justify-between gap-2"><StatusBadge tone="sage">{decision.decision ?? 'Decision unavailable'}</StatusBadge><span className="text-xs text-muted-foreground">{decision.time ?? 'Timestamp unavailable'}</span></div>{decision.note && <p className="mt-2 text-sm text-muted-foreground">{decision.note}</p>}</div>)}</div> : <p className="text-sm text-muted-foreground">{detail.sources.audit.available ? 'No human decision is recorded for this invoice.' : 'Audit log unavailable; decision status cannot be determined.'}</p>}</CardContent>
    </Card>

    <Card>
      <CardHeader className="pb-3"><CardTitle className="text-sm">Vendor investigations and evidence</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {investigationError && <p role="alert" className="rounded-md bg-critical/10 p-3 text-sm text-[#9d5c49]">{investigationError}</p>}
        {investigationsLoading ? <LoadingState label="Loading investigation records…" /> : !investigations?.available ? <EmptyState title="Investigation records unavailable" description={investigations?.reason ?? 'The investigation database could not be read.'} /> : investigations.investigations.length ? investigations.investigations.map((investigation) => <div key={investigation.investigation_id} className="rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold">Investigation {investigation.investigation_id.slice(0, 8)}</p><p className="mt-1 text-xs text-muted-foreground">Created {investigation.created_at}{investigation.invoice_id ? ` · ${investigation.invoice_id}` : ' · vendor-level record'}</p></div><StatusBadge>{investigation.status}</StatusBadge></div>
          {investigation.evidence.length ? <div className="mt-3 space-y-2">{investigation.evidence.map((evidence) => <div key={evidence.evidence_id} className="rounded-md bg-background p-3">
            <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold">{label(evidence.check_type)}</p><StatusBadge tone={statusTone(evidence.verification_status)}>{label(evidence.verification_status)}</StatusBadge></div>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-5">{evidence.finding}</p>
            <p className="mt-1 text-[11px] text-muted-foreground">Source type: {label(evidence.source_type)}{evidence.retrieved_at ? ` · Retrieved ${evidence.retrieved_at}` : ''}</p>
            {evidence.matched_entity != null && <p className="mt-1 break-words text-xs text-muted-foreground">Matched entity: {typeof evidence.matched_entity === 'object' ? JSON.stringify(evidence.matched_entity) : String(evidence.matched_entity)}</p>}
            <div className="mt-2"><SourceLink url={evidence.source_url} /></div>
          </div>)}</div> : <p className="mt-3 text-sm text-muted-foreground">No evidence records are stored for this investigation.</p>}
        </div>) : <EmptyState title="No investigation records yet" description="Use Start investigation to create one for this invoice’s vendor. It will not be created automatically." />}
        {sourceEvidence.length > 0 && <p className="text-[11px] text-muted-foreground">External evidence with stored provenance is shown with its source URL and retrieval timestamp when available.</p>}
      </CardContent>
    </Card>
  </div>
}

export default function InvoiceIntelligencePage() {
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [status, setStatus] = useState<'all' | 'flagged' | 'clear'>('all')
  const [vendorId, setVendorId] = useState('')
  const [signal, setSignal] = useState('')
  const [sortBy, setSortBy] = useState<NonNullable<InvoiceListParams['sort_by']>>('date')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [list, setList] = useState<InvoiceListResponse | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<InvoiceDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [investigations, setInvestigations] = useState<InvoiceInvestigationsResponse | null>(null)
  const [investigationsLoading, setInvestigationsLoading] = useState(false)
  const [investigationError, setInvestigationError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => { setDebouncedSearch(search); setPage(0) }, 250)
    return () => window.clearTimeout(timer)
  }, [search])

  const params = useMemo<InvoiceListParams>(() => ({
    q: debouncedSearch, status, vendor_id: vendorId, signal, sort_by: sortBy, sort_dir: sortDir,
    limit: PAGE_SIZE, offset: page * PAGE_SIZE,
  }), [debouncedSearch, status, vendorId, signal, sortBy, sortDir, page])

  const reloadList = useCallback(async (request: InvoiceListParams = params, signalController?: AbortSignal) => {
    setListLoading(true)
    setListError(null)
    try {
      const result = await getInvoices(request, signalController)
      if (!signalController?.aborted) {
        setList(result)
        setSelectedId((current) => current && result.items.some((item) => item.invoice_id === current) ? current : result.items[0]?.invoice_id ?? null)
      }
    } catch (error) {
      if (!signalController?.aborted) setListError(error instanceof Error ? error.message : 'Invoice request failed')
    } finally {
      if (!signalController?.aborted) setListLoading(false)
    }
  }, [params])

  useEffect(() => {
    const controller = new AbortController()
    void reloadList(params, controller.signal)
    return () => controller.abort()
  }, [params, reloadList])

  useEffect(() => {
    if (!selectedId) { setDetail(null); setInvestigations(null); return }
    const controller = new AbortController()
    setDetailLoading(true)
    setDetailError(null)
    setInvestigationsLoading(true)
    setInvestigationError(null)
    Promise.allSettled([getInvoice(selectedId, controller.signal), getInvoiceInvestigations(selectedId, controller.signal)]).then(([detailResult, investigationResult]) => {
      if (controller.signal.aborted) return
      if (detailResult.status === 'fulfilled') setDetail(detailResult.value)
      else { setDetail(null); setDetailError(detailResult.reason instanceof Error ? detailResult.reason.message : 'Invoice detail request failed') }
      if (investigationResult.status === 'fulfilled') setInvestigations(investigationResult.value)
      else { setInvestigations(null); setInvestigationError(investigationResult.reason instanceof Error ? investigationResult.reason.message : 'Investigation request failed') }
      setDetailLoading(false)
      setInvestigationsLoading(false)
    })
    return () => controller.abort()
  }, [selectedId])

  async function startSelectedInvestigation() {
    if (!selectedId) return
    setStarting(true)
    setNotice(null)
    setInvestigationError(null)
    try {
      const response = await startInvoiceInvestigation(selectedId)
      setNotice(response.message)
      const cases = await getInvoiceInvestigations(selectedId)
      setInvestigations(cases)
      await reloadList()
    } catch (error) {
      setInvestigationError(error instanceof Error ? error.message : 'Could not start investigation')
    } finally {
      setStarting(false)
    }
  }

  function sort(column: NonNullable<InvoiceListParams['sort_by']>) {
    if (sortBy === column) setSortDir((current) => current === 'asc' ? 'desc' : 'asc')
    else { setSortBy(column); setSortDir(column === 'invoice_id' || column === 'vendor_name' ? 'asc' : 'desc') }
    setPage(0)
  }

  const total = list?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return <div className="space-y-6">
    <PageHeader eyebrow="Workspace" title="Invoice Intelligence" description="Search invoice records, review detector evidence, and open a vendor investigation. Automated signals are evidence for auditors, not fraud decisions." actions={
      <Button variant="secondary" onClick={() => void reloadList()} disabled={listLoading}><Icon name="panel" size={16} /> Refresh</Button>
    } />

    {notice && <div role="status" className="rounded-md border border-sage/30 bg-sage/10 px-4 py-3 text-sm text-[#536b58]">{notice}</div>}

    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_minmax(380px,0.78fr)]">
      <section className="min-w-0 space-y-4">
        <Card>
          <CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
            <div className="sm:col-span-2"><label htmlFor="invoice-search" className="mb-1.5 block text-xs font-medium text-muted-foreground">Search invoices and vendors</label><div className="relative"><Icon name="search" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><Input id="invoice-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Invoice ID, vendor name or vendor ID" className="pl-9" /></div></div>
            <div><label htmlFor="invoice-status" className="mb-1.5 block text-xs font-medium text-muted-foreground">Review status</label><Select id="invoice-status" value={status} onChange={(event) => { setStatus(event.target.value as typeof status); setPage(0) }}><option value="all">All invoices</option><option value="flagged">Flagged for review</option><option value="clear">Clear status</option></Select></div>
            <div><label htmlFor="invoice-vendor" className="mb-1.5 block text-xs font-medium text-muted-foreground">Vendor</label><Select id="invoice-vendor" value={vendorId} onChange={(event) => { setVendorId(event.target.value); setPage(0) }}><option value="">All vendors</option>{(list?.available_vendors ?? []).map((vendor) => <option key={vendor.vendor_id} value={vendor.vendor_id}>{vendor.vendor_name ?? vendor.vendor_id} · {vendor.vendor_id}</option>)}</Select></div>
            <div className="sm:col-span-2 xl:col-span-4"><label htmlFor="invoice-signal" className="mb-1.5 block text-xs font-medium text-muted-foreground">Detection signal</label><Select id="invoice-signal" value={signal} onChange={(event) => { setSignal(event.target.value); setPage(0) }}><option value="">All signals</option>{(list?.available_signals ?? []).map((value) => <option key={value} value={value}>{value}</option>)}</Select></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3"><div><CardTitle>Invoices</CardTitle><p className="mt-1 text-xs text-muted-foreground">{list?.total == null ? 'Invoice count unavailable' : `${formatNumber(total)} records`}</p></div>{list?.available && <StatusBadge tone="neutral">Page {page + 1} of {pageCount}</StatusBadge>}</CardHeader>
          <CardContent className="px-0 pb-0">
            {listError ? <div className="px-5 pb-5"><EmptyState title="Invoice data could not be loaded" description={listError} action={<Button variant="secondary" onClick={() => void reloadList()}>Try again</Button>} /></div> : listLoading && !list ? <div className="p-5"><LoadingState label="Loading invoice data…" /></div> : list && !list.available ? <div className="px-5 pb-5"><EmptyState title="Invoice data unavailable" description={list.reason ?? 'Prepared invoice data could not be read.'} /></div> : list && list.items.length === 0 ? <div className="px-5 pb-5"><EmptyState title="No invoices match these filters" description="Try another search term or clear one or more filters." /></div> : <>
              {listLoading && <div className="px-5 pb-3"><LoadingState label="Updating invoice results…" /></div>}
              <Table>
                <TableHeader><TableRow>
                  {([['invoice_id', 'Invoice'], ['vendor_name', 'Vendor'], ['amount', 'Amount'], ['date', 'Date'], ['risk_score', 'GNN score'], ['overall_status', 'Status']] as [NonNullable<InvoiceListParams['sort_by']>, string][]).map(([key, title]) => <TableHead key={key}><button type="button" onClick={() => sort(key)} className="inline-flex items-center gap-1 hover:text-foreground">{title}{sortBy === key && <span aria-label={sortDir === 'asc' ? 'ascending' : 'descending'}>{sortDir === 'asc' ? '↑' : '↓'}</span>}</button></TableHead>)}
                </TableRow></TableHeader>
                <TableBody>{(list?.items ?? []).map((invoice: InvoiceListItem) => <TableRow key={invoice.invoice_id} className={selectedId === invoice.invoice_id ? 'bg-primary/5' : ''}>
                  <TableCell><button type="button" onClick={() => setSelectedId(invoice.invoice_id)} className="font-semibold text-primary hover:underline">{invoice.invoice_id}</button><div className="mt-1 flex max-w-[200px] flex-wrap gap-1">{invoice.signals.slice(0, 2).map((entry) => <StatusBadge key={entry} tone="warning" className="max-w-full truncate">{entry}</StatusBadge>)}{invoice.signals.length > 2 && <StatusBadge>+{invoice.signals.length - 2}</StatusBadge>}</div></TableCell>
                  <TableCell><div className="max-w-36 truncate font-medium">{invoice.vendor_name ?? 'Name unavailable'}</div><div className="text-[11px] text-muted-foreground">{invoice.vendor_id ?? 'ID unavailable'}</div></TableCell>
                  <TableCell className="tabular-nums">{formatNumber(invoice.amount)}</TableCell><TableCell className="whitespace-nowrap">{formatDate(invoice.date)}</TableCell><TableCell className="tabular-nums">{invoice.risk_score == null ? '—' : formatNumber(invoice.risk_score)}</TableCell>
                  <TableCell><div>{invoice.overall_status === 'Flagged' ? <StatusBadge tone="warning">Flagged</StatusBadge> : invoice.overall_status === 'Clear' ? <StatusBadge tone="sage">Clear</StatusBadge> : <StatusBadge>Status unavailable</StatusBadge>}</div><div className="mt-1">{invoice.human_decision ? <StatusBadge tone="sage" className="max-w-36 truncate" title={`${invoice.human_decision} · ${invoice.human_decision_time ?? ''}`}>{invoice.human_decision}</StatusBadge> : <span className="text-[10px] text-muted-foreground">{invoice.human_decision_status === 'unavailable' ? 'Audit log unavailable' : 'No decision recorded'}</span>}</div></TableCell>
                </TableRow>)}</TableBody>
              </Table>
              <div className="flex items-center justify-between border-t border-border px-5 py-3"><p className="text-xs text-muted-foreground">Flagged is an automated review status, not a finding of fraud.</p><div className="flex items-center gap-2"><Button variant="secondary" size="sm" disabled={page === 0 || listLoading} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</Button><Button variant="secondary" size="sm" disabled={page + 1 >= pageCount || listLoading} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>Next</Button></div></div>
            </>}
          </CardContent>
        </Card>
      </section>

      <aside className="min-w-0 2xl:max-h-[calc(100vh-128px)] 2xl:overflow-y-auto 2xl:pr-1" aria-label="Selected invoice detail">
        {detailLoading && !detail && <LoadingState label="Loading selected invoice…" />}
        {detailError && !detail && <EmptyState title="Invoice detail unavailable" description={detailError} />}
        {!detailLoading && !detail && !detailError && <EmptyState title="Select an invoice" description="Choose a row to inspect invoice attributes, vendor and PO context, detector evidence, and saved investigation records." />}
        {detail && <DetailPanel detail={detail} investigations={investigations} investigationsLoading={investigationsLoading} investigationError={investigationError} starting={starting} onStart={() => void startSelectedInvestigation()} />}
      </aside>
    </div>
  </div>
}
