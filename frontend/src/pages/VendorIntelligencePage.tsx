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
import { getVendor, getVendors, startVendorInvestigation, type VendorListParams } from '@/services/api'
import type { VendorDetail, VendorListItem, VendorListResponse } from '@/types/api'

const PAGE_SIZE = 25

function formatted(value: number | null | undefined) {
  return value == null ? 'Unavailable' : new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
}

function titleCase(value: string) {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase())
}

function toneForEvidence(status: string): StatusTone {
  if (status === 'no_match') return 'sage'
  if (status === 'match_found' || status === 'possible_match' || status === 'third_party_match') return 'warning'
  if (status === 'official_registry_verified') return 'sage'
  if (status === 'official_company_document' || status === 'stock_exchange_filing') return 'accent'
  return 'neutral'
}

function FieldGrid({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values).filter(([, value]) => value !== null && value !== undefined && value !== '')
  return entries.length ? <dl className="grid gap-x-5 gap-y-3 sm:grid-cols-2">{entries.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{titleCase(key)}</dt><dd className="mt-1 break-words text-sm">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl> : <p className="text-sm text-muted-foreground">No values are present in this vendor record.</p>
}

function SourceLink({ url }: { url: string | null }) {
  if (!url) return <span className="text-xs text-muted-foreground">No source URL stored</span>
  if (!/^https?:\/\//i.test(url)) return <span className="break-all text-xs text-muted-foreground">{url}</span>
  return <a href={url} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 break-all text-xs text-primary hover:underline">{url}<Icon name="external" size={13} className="shrink-0" /></a>
}

function MatchState({ status }: { status: string }) {
  if (status === 'match_found') return <StatusBadge tone="warning">Match found · review lead</StatusBadge>
  if (status === 'no_match') return <StatusBadge tone="sage">No match in available records</StatusBadge>
  if (status === 'not_run_missing_value') return <StatusBadge>Not run · vendor value missing</StatusBadge>
  if (status.startsWith('unavailable') || status.startsWith('incomplete')) return <StatusBadge>Unavailable or partial coverage</StatusBadge>
  return <StatusBadge>{titleCase(status)}</StatusBadge>
}

function VendorInspector({
  detail, loading, error, starting, notice, onStart,
}: {
  detail: VendorDetail | null
  loading: boolean
  error: string | null
  starting: boolean
  notice: string | null
  onStart: () => void
}) {
  if (loading && !detail) return <LoadingState label="Loading vendor profile…" />
  if (error && !detail) return <EmptyState title="Vendor detail unavailable" description={error} />
  if (!detail) return <EmptyState title="Select a vendor" description="Choose a vendor to review its profile, transactions, matching checks, investigations, evidence, and saved audit decisions." />

  const investigations = detail.investigations
  return <div className="space-y-4">
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 pb-3"><div className="min-w-0"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Vendor inspector</p><CardTitle className="mt-1 break-words text-lg">{detail.vendor.vendor_name ?? detail.vendor_id}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{detail.vendor_id}{detail.vendor.vendor_category ? ` · ${detail.vendor.vendor_category}` : ''}</p></div><StatusBadge tone={detail.flagged_invoice_count ? 'warning' : 'neutral'}>{detail.flagged_invoice_count == null ? 'Signals unavailable' : `${detail.flagged_invoice_count} flagged invoices`}</StatusBadge></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2"><Button onClick={onStart} disabled={starting}><Icon name="plus" size={16} />{starting ? 'Starting…' : 'Start Investigation'}</Button><StatusBadge tone="neutral">No invoice required</StatusBadge></div>
        {notice && <p role="status" className="rounded-md bg-sage/10 p-3 text-sm text-[#536b58]">{notice}</p>}
        {error && <p role="alert" className="rounded-md bg-critical/10 p-3 text-sm text-[#9d5c49]">{error}</p>}
        <p className="text-xs leading-5 text-muted-foreground">Starting creates a vendor-level investigation with the existing internal checks. It does not make a payment decision. Previously stored external research is displayed below when available.</p>
      </CardContent>
    </Card>

    <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Vendor profile and registration</CardTitle></CardHeader><CardContent><FieldGrid values={detail.vendor} /><p className="mt-3 text-[11px] text-muted-foreground">Registration fields above are supplied by the internal vendor record. They are not external registry verification.</p></CardContent></Card>

    <div className="grid gap-3 sm:grid-cols-3"><Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Associated invoices</p><p className="mt-2 text-xl font-semibold">{formatted(detail.invoice_count)}</p></CardContent></Card><Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total invoice transaction value</p><p className="mt-2 text-xl font-semibold">{formatted(detail.total_transaction_value)}</p></CardContent></Card><Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Flagged for review</p><p className="mt-2 text-xl font-semibold text-[#9d5c49]">{formatted(detail.flagged_invoice_count)}</p></CardContent></Card></div>
    <p className="-mt-2 text-[11px] leading-5 text-muted-foreground">Transaction value sums associated invoice amounts from the available records. Flagged counts are automated review signals, not confirmed fraud.</p>

    <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Associated invoices and transaction history</CardTitle></CardHeader><CardContent className="px-0 pb-1">{detail.sources.invoices.available && detail.sources.purchase_orders.available ? detail.invoices.length ? <Table><TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>PO</TableHead><TableHead>Amount</TableHead><TableHead>Date</TableHead><TableHead>Signals</TableHead></TableRow></TableHeader><TableBody>{detail.invoices.map((item) => <TableRow key={String(item.invoice.invoice_id)}><TableCell className="font-medium">{item.invoice.invoice_id}</TableCell><TableCell>{item.po_id ?? '—'}</TableCell><TableCell>{formatted(item.amount)}</TableCell><TableCell>{item.date ?? '—'}</TableCell><TableCell><div className="flex max-w-44 flex-wrap gap-1">{item.signals.length ? item.signals.slice(0, 3).map((signal) => <StatusBadge key={signal} tone="warning">{signal}</StatusBadge>) : <span className="text-xs text-muted-foreground">No signals listed</span>}</div></TableCell></TableRow>)}</TableBody></Table> : <div className="px-5 pb-5"><EmptyState title="No associated invoices" description="The available invoice and PO records contain no linked invoices for this vendor. You can still start an investigation." /></div> : <div className="p-5"><EmptyState title="Invoice relationship data unavailable" description="Both invoice and purchase-order records are needed to determine associated transactions." /></div>}</CardContent></Card>

    <div className="grid gap-4 xl:grid-cols-2">
      <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Purchase orders</CardTitle></CardHeader><CardContent>{detail.sources.purchase_orders.available ? detail.purchase_orders.length ? <div className="space-y-3">{detail.purchase_orders.map((po, index) => <div key={`${po.po_id ?? 'po'}-${index}`} className="rounded-md bg-background p-3"><FieldGrid values={po} /></div>)}</div> : <p className="text-sm text-muted-foreground">No purchase orders are linked to this vendor.</p> : <p className="text-sm text-muted-foreground">Purchase-order source unavailable.</p>}</CardContent></Card>
      <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Contracts</CardTitle></CardHeader><CardContent>{detail.sources.contracts.available ? detail.contracts.length ? <div className="space-y-3">{detail.contracts.map((contract, index) => <div key={`${contract.contract_id ?? 'contract'}-${index}`} className="rounded-md bg-background p-3"><FieldGrid values={contract} /></div>)}</div> : <p className="text-sm text-muted-foreground">No contract is present for this vendor in contracts.csv.</p> : <p className="text-sm text-muted-foreground">Contract source unavailable.</p>}</CardContent></Card>
    </div>

    <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Internal matching checks</CardTitle><p className="text-xs text-muted-foreground">Current comparisons against available vendor and employee records. A match is a lead for review.</p></CardHeader><CardContent className="space-y-3">{detail.internal_verification_findings.map((finding, index) => <div key={`${finding.check_type}-${index}`} className="rounded-md border border-border p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm font-medium">{titleCase(finding.check_type)}</p><MatchState status={finding.verification_status} /></div><p className="mt-2 text-sm leading-5 text-muted-foreground">{finding.finding}</p>{finding.matched_entity && <div className="mt-2 rounded bg-background p-2 text-xs"><span className="text-muted-foreground">Matched entity: </span>{Object.entries(finding.matched_entity).map(([key, value]) => `${titleCase(key)} ${value}`).join(' · ')}</div>}{finding.coverage_status && finding.coverage_status !== 'complete' && <p className="mt-1 text-[11px] text-muted-foreground">Coverage: {titleCase(finding.coverage_status)}</p>}</div>)}</CardContent></Card>

    <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Investigation history and evidence</CardTitle></CardHeader><CardContent>{!investigations.available ? <EmptyState title="Investigation database unavailable" description={investigations.reason ?? 'Investigation records could not be read.'} /> : investigations.investigations.length ? <div className="space-y-3">{investigations.investigations.map((record) => <div key={record.investigation_id} className="rounded-md border border-border p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-semibold">Investigation {record.investigation_id.slice(0, 8)}</p><p className="mt-1 text-xs text-muted-foreground">Created {record.created_at}{record.invoice_id ? ` · ${record.invoice_id}` : ' · vendor-level'}</p></div><StatusBadge>{record.status}</StatusBadge></div>{record.evidence.length ? <div className="mt-3 space-y-2">{record.evidence.map((evidence) => <div key={evidence.evidence_id} className="rounded-md bg-background p-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="text-xs font-semibold">{titleCase(evidence.check_type)} · {titleCase(evidence.source_type)}</p><StatusBadge tone={toneForEvidence(evidence.verification_status)}>{titleCase(evidence.verification_status)}</StatusBadge></div><p className="mt-2 whitespace-pre-wrap text-sm leading-5">{evidence.finding}</p><p className="mt-1 text-[11px] text-muted-foreground">Created {evidence.created_at}{evidence.retrieved_at ? ` · Retrieved ${evidence.retrieved_at}` : ''}</p><div className="mt-2"><SourceLink url={evidence.source_url} /></div></div>)}</div> : <p className="mt-3 text-sm text-muted-foreground">No evidence records stored for this investigation.</p>}</div>)}</div> : <EmptyState title="No investigation history" description="No investigation is recorded for this vendor. Start Investigation to run the existing internal checks." />}</CardContent></Card>

    <Card><CardHeader className="pb-3"><CardTitle className="text-sm">Human audit decisions</CardTitle><p className="text-xs text-muted-foreground">Recorded decisions from audit_log.csv; separate from internal checks and investigation status.</p></CardHeader><CardContent>{detail.sources.audit.available ? detail.human_decisions.length ? <div className="space-y-2">{detail.human_decisions.map((decision, index) => <div key={`${decision.invoice_id}-${decision.time}-${index}`} className="rounded-md border border-border p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div><StatusBadge tone="sage">{decision.decision ?? 'Decision unavailable'}</StatusBadge><p className="mt-1 text-xs text-muted-foreground">Invoice {decision.invoice_id ?? 'unavailable'}</p></div><span className="text-xs text-muted-foreground">{decision.time ?? 'Timestamp unavailable'}</span></div>{decision.note && <p className="mt-2 text-sm text-muted-foreground">{decision.note}</p>}</div>)}</div> : <p className="text-sm text-muted-foreground">No human decision is recorded for this vendor.</p> : <p className="text-sm text-muted-foreground">Audit log unavailable; human decision status cannot be determined.</p>}</CardContent></Card>
  </div>
}

export default function VendorIntelligencePage() {
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [status, setStatus] = useState<'all' | 'flagged' | 'clear' | 'no_invoices'>('all')
  const [category, setCategory] = useState('')
  const [signal, setSignal] = useState('')
  const [sortBy, setSortBy] = useState<NonNullable<VendorListParams['sort_by']>>('vendor_name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [page, setPage] = useState(0)
  const [listing, setListing] = useState<VendorListResponse | null>(null)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<VendorDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => { setDebouncedSearch(search); setPage(0) }, 250)
    return () => window.clearTimeout(timer)
  }, [search])

  const params = useMemo<VendorListParams>(() => ({ q: debouncedSearch, status, category, signal, sort_by: sortBy, sort_dir: sortDir, limit: PAGE_SIZE, offset: page * PAGE_SIZE }), [debouncedSearch, status, category, signal, sortBy, sortDir, page])
  const loadList = useCallback(async (request: VendorListParams = params, abort?: AbortSignal) => {
    setListLoading(true)
    setListError(null)
    try {
      const response = await getVendors(request, abort)
      if (!abort?.aborted) {
        setListing(response)
        setSelectedId((current) => current && response.items.some((item) => item.vendor_id === current) ? current : response.items[0]?.vendor_id ?? null)
      }
    } catch (error) {
      if (!abort?.aborted) setListError(error instanceof Error ? error.message : 'Vendor request failed')
    } finally {
      if (!abort?.aborted) setListLoading(false)
    }
  }, [params])

  useEffect(() => {
    const controller = new AbortController()
    void loadList(params, controller.signal)
    return () => controller.abort()
  }, [params, loadList])

  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    const controller = new AbortController()
    setDetailLoading(true)
    setDetailError(null)
    getVendor(selectedId, controller.signal).then((result) => {
      if (!controller.signal.aborted) setDetail(result)
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) { setDetail(null); setDetailError(error instanceof Error ? error.message : 'Vendor detail request failed') }
    }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false) })
    return () => controller.abort()
  }, [selectedId])

  async function startSelected() {
    if (!selectedId) return
    setStarting(true)
    setNotice(null)
    setDetailError(null)
    try {
      const result = await startVendorInvestigation(selectedId)
      setNotice(result.message)
      const refreshed = await getVendor(selectedId)
      setDetail(refreshed)
      await loadList()
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Could not start investigation')
    } finally {
      setStarting(false)
    }
  }

  function sort(column: NonNullable<VendorListParams['sort_by']>) {
    if (column === sortBy) setSortDir((current) => current === 'asc' ? 'desc' : 'asc')
    else { setSortBy(column); setSortDir(column === 'vendor_name' || column === 'vendor_id' ? 'asc' : 'desc') }
    setPage(0)
  }

  const total = listing?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const sortHeaders: [NonNullable<VendorListParams['sort_by']>, string][] = [['vendor_name', 'Vendor'], ['invoice_count', 'Invoices'], ['total_transaction_value', 'Transaction value'], ['flagged_invoice_count', 'Flagged']]

  return <div className="space-y-6">
    <PageHeader eyebrow="Workspace" title="Vendor Intelligence" description="Review vendor profiles, transaction context, internal matching checks, and persisted investigation evidence. Signals support auditor review; they do not establish fraud or legitimacy." actions={<Button variant="secondary" onClick={() => void loadList()} disabled={listLoading}><Icon name="panel" size={16} /> Refresh</Button>} />
    <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_minmax(400px,0.78fr)]">
      <section className="min-w-0 space-y-4">
        <Card><CardContent className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="sm:col-span-2"><label htmlFor="vendor-search" className="mb-1.5 block text-xs font-medium text-muted-foreground">Search vendor records</label><div className="relative"><Icon name="search" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><Input id="vendor-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name, ID, email, phone or registration number" className="pl-9" /></div></div>
          <div><label htmlFor="vendor-review-status" className="mb-1.5 block text-xs font-medium text-muted-foreground">Invoice signal status</label><Select id="vendor-review-status" value={status} onChange={(event) => { setStatus(event.target.value as typeof status); setPage(0) }}><option value="all">All vendors</option><option value="flagged">Has flagged invoices</option><option value="clear">No flagged invoices</option><option value="no_invoices">No associated invoices</option></Select></div>
          <div><label htmlFor="vendor-category" className="mb-1.5 block text-xs font-medium text-muted-foreground">Category</label><Select id="vendor-category" value={category} onChange={(event) => { setCategory(event.target.value); setPage(0) }}><option value="">All categories</option>{(listing?.available_categories ?? []).map((item) => <option key={item} value={item}>{item}</option>)}</Select></div>
          <div className="sm:col-span-2 xl:col-span-4"><label htmlFor="vendor-signal" className="mb-1.5 block text-xs font-medium text-muted-foreground">Available risk indicator</label><Select id="vendor-signal" value={signal} onChange={(event) => { setSignal(event.target.value); setPage(0) }}><option value="">All indicators</option>{(listing?.available_signals ?? []).map((item) => <option key={item} value={item}>{item}</option>)}</Select></div>
        </CardContent></Card>

        <Card><CardHeader className="flex-row items-center justify-between gap-3"><div><CardTitle>Vendors</CardTitle><p className="mt-1 text-xs text-muted-foreground">{listing?.total == null ? 'Vendor count unavailable' : `${formatted(total)} records`}</p></div>{listing?.available && <StatusBadge>Page {page + 1} of {pageCount}</StatusBadge>}</CardHeader><CardContent className="px-0 pb-0">
          {listError ? <div className="px-5 pb-5"><EmptyState title="Vendor records could not be loaded" description={listError} action={<Button variant="secondary" onClick={() => void loadList()}>Try again</Button>} /></div> : listLoading && !listing ? <div className="p-5"><LoadingState label="Loading vendors…" /></div> : listing && !listing.available ? <div className="px-5 pb-5"><EmptyState title="Vendor source unavailable" description={listing.reason ?? 'The vendor dataset could not be read.'} /></div> : listing && listing.items.length === 0 ? <div className="px-5 pb-5"><EmptyState title="No vendors match these filters" description="Try another search term or clear one or more filters." /></div> : <>
            {listLoading && <div className="px-5 pb-3"><LoadingState label="Updating vendor results…" /></div>}
            <Table><TableHeader><TableRow><TableHead><button type="button" onClick={() => sort('vendor_name')} className="inline-flex items-center gap-1 hover:text-foreground">Vendor{sortBy === 'vendor_name' && (sortDir === 'asc' ? '↑' : '↓')}</button></TableHead><TableHead>Contact</TableHead><TableHead>Registration</TableHead><TableHead>Bank account</TableHead>{sortHeaders.slice(1).map(([key, heading]) => <TableHead key={key}><button type="button" onClick={() => sort(key)} className="inline-flex items-center gap-1 hover:text-foreground">{heading}{sortBy === key && (sortDir === 'asc' ? '↑' : '↓')}</button></TableHead>)}<TableHead>Indicators</TableHead></TableRow></TableHeader><TableBody>{(listing?.items ?? []).map((vendor: VendorListItem) => <TableRow key={vendor.vendor_id} className={selectedId === vendor.vendor_id ? 'bg-primary/5' : ''}>
              <TableCell><button type="button" onClick={() => setSelectedId(vendor.vendor_id)} className="text-left font-semibold text-primary hover:underline">{vendor.vendor_name ?? 'Name unavailable'}</button><div className="text-[11px] text-muted-foreground">{vendor.vendor_id}</div></TableCell>
              <TableCell><div className="max-w-36 truncate text-xs" title={vendor.email ?? undefined}>{vendor.email ?? 'Email unavailable'}</div><div className="text-[11px] text-muted-foreground">{vendor.phone ?? 'Phone unavailable'}</div></TableCell>
              <TableCell className="max-w-36 truncate text-xs" title={vendor.registration_number ?? undefined}>{vendor.registration_number ?? 'Unavailable'}</TableCell>
              <TableCell className="whitespace-nowrap font-mono text-xs">{vendor.bank_account ?? 'Unavailable'}</TableCell>
              <TableCell className="tabular-nums">{vendor.invoice_count == null ? 'Unavailable' : vendor.invoice_count}</TableCell>
              <TableCell className="tabular-nums">{formatted(vendor.total_transaction_value)}</TableCell>
              <TableCell><div className="tabular-nums">{vendor.flagged_invoice_count == null ? 'Unavailable' : vendor.flagged_invoice_count}</div><div className="text-[11px] text-muted-foreground">review signals</div></TableCell>
              <TableCell><div className="flex max-w-44 flex-wrap gap-1">{vendor.risk_indicators == null ? <StatusBadge>Unavailable</StatusBadge> : vendor.risk_indicators.length ? vendor.risk_indicators.slice(0, 2).map((indicator) => <StatusBadge key={indicator.label} tone="warning" title={`${indicator.invoice_count} related invoices`}>{indicator.label}</StatusBadge>) : <span className="text-xs text-muted-foreground">No signals listed</span>}{vendor.risk_indicators?.length ? <StatusBadge>+{Math.max(0, vendor.risk_indicators.length - 2)}</StatusBadge> : null}</div></TableCell>
            </TableRow>)}</TableBody></Table>
            <div className="flex items-center justify-between border-t border-border px-5 py-3"><p className="text-xs text-muted-foreground">Risk indicators are automated signals, not fraud findings.</p><div className="flex items-center gap-2"><Button variant="secondary" size="sm" disabled={page === 0 || listLoading} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</Button><Button variant="secondary" size="sm" disabled={page + 1 >= pageCount || listLoading} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>Next</Button></div></div>
          </>}
        </CardContent></Card>
      </section>

      <aside className="min-w-0 2xl:max-h-[calc(100vh-128px)] 2xl:overflow-y-auto 2xl:pr-1" aria-label="Selected vendor detail">
        <VendorInspector detail={detail} loading={detailLoading} error={detailError} starting={starting} notice={notice} onStart={() => void startSelected()} />
      </aside>
    </div>
  </div>
}
