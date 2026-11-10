import { useCallback, useEffect, useState } from 'react'

import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { PageHeader } from '@/components/ui/page-header'
import { StatusBadge } from '@/components/ui/status-badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  getDashboardActivity, getDashboardSummary, getDetectionOverview, getRecentInvoices, getRiskDistribution, getVendorSignals,
} from '@/services/api'
import type { DashboardActivity, DashboardSummary, DetectionOverview, RecentInvoices, RiskDistribution, VendorSignals } from '@/types/api'

type Result<T> = { data: T | null; error: string | null }
type DashboardData = {
  summary: Result<DashboardSummary>
  risk: Result<RiskDistribution>
  detections: Result<DetectionOverview>
  invoices: Result<RecentInvoices>
  vendors: Result<VendorSignals>
  activity: Result<DashboardActivity>
}

const initial: DashboardData = {
  summary: { data: null, error: null }, risk: { data: null, error: null }, detections: { data: null, error: null },
  invoices: { data: null, error: null }, vendors: { data: null, error: null }, activity: { data: null, error: null },
}

function number(value: number | null | undefined, unit?: 'ratio' | 'count') {
  if (value == null) return 'Unavailable'
  if (unit === 'ratio') return `${(value * 100).toFixed(1)}%`
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(value)
}

function date(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function score(value: number | null) {
  return value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 4 })
}

function DataError({ label }: { label: string }) {
  return <EmptyState title={`${label} unavailable`} description="The API could not load this section. Check the backend connection and source files, then refresh." />
}

export default function DashboardPage({ onNavigate }: { onNavigate: (page: string) => void }) {
  const [data, setData] = useState<DashboardData>(initial)
  const [loading, setLoading] = useState(true)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    const calls = await Promise.allSettled([
      getDashboardSummary(signal), getRiskDistribution(signal), getDetectionOverview(signal),
      getRecentInvoices(signal), getVendorSignals(signal), getDashboardActivity(signal),
    ])
    if (signal?.aborted) return
    const keys: (keyof DashboardData)[] = ['summary', 'risk', 'detections', 'invoices', 'vendors', 'activity']
    const next = { ...initial }
    calls.forEach((call, index) => {
      const key = keys[index]
      if (call.status === 'fulfilled') (next[key] as { data: unknown; error: string | null }) = { data: call.value, error: null }
      else (next[key] as { data: unknown; error: string | null }) = { data: null, error: call.reason instanceof Error ? call.reason.message : 'Request failed' }
    })
    setData(next)
    setRefreshedAt(new Date())
    setLoading(false)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  const metrics = data.summary.data?.metrics
  const metricCards = [
    { label: 'Invoices in prepared data', key: 'total_invoices' as const, note: 'Rows in dashboard_data.csv', tone: 'text-foreground' },
    { label: 'Flagged for review', key: 'flagged_invoices' as const, note: 'Automated review signals', tone: 'text-[#9d5c49]' },
    { label: 'Flagged invoice share', key: 'flagged_invoice_share' as const, note: 'Not a fraud rate', tone: 'text-[#945d40]' },
    { label: 'Vendors', key: 'total_vendors' as const, note: 'Distinct vendor IDs', tone: 'text-[#536b58]' },
    { label: 'Pending audit reviews', key: 'pending_audit_reviews' as const, note: 'No explicit queue status available', tone: 'text-muted-foreground' },
    { label: 'Invoices with saved decisions', key: 'audited_invoices' as const, note: 'Distinct invoice IDs with audit decisions', tone: 'text-foreground' },
  ]

  return (
    <div className="space-y-6 sm:space-y-7">
      <PageHeader eyebrow="Overview" title="Dashboard" description="A read-only view of the latest available SentinelP2P artifacts." actions={
        <Button variant="secondary" onClick={() => void load()} disabled={loading}>
          <Icon name="panel" size={16} /> {loading ? 'Refreshing…' : 'Refresh data'}
        </Button>
      } />

      {loading && !data.summary.data && <LoadingState label="Loading dashboard artifacts…" />}
      {data.summary.error && !data.summary.data && <DataError label="Dashboard summary" />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        {metricCards.map((item) => {
          const metric = metrics?.[item.key]
          return <Card key={item.key}>
            <CardContent className="p-4 sm:p-5">
              <div className="flex min-h-10 items-start justify-between gap-2">
                <p className="text-xs font-medium leading-5 text-muted-foreground">{item.label}</p>
                {item.key === 'pending_audit_reviews' && <StatusBadge>Unavailable</StatusBadge>}
              </div>
              <p className={`mt-2 text-[26px] font-semibold tracking-tight ${item.tone}`}>{number(metric?.value, metric?.unit ?? undefined)}</p>
              <p className="mt-1 text-[11px] leading-4 text-muted-foreground" title={metric?.definition}>{item.note}</p>
            </CardContent>
          </Card>
        })}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader className="pb-2"><div className="flex items-start justify-between gap-4"><div><CardTitle>{data.risk.data?.kind === 'review_flag_counts' ? 'Invoice review status distribution' : 'GNN score distribution'}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{data.risk.data?.kind === 'review_flag_counts' ? 'Prepared Flagged/Clear statuses' : 'Observed invoice scores grouped by rank'}</p></div><StatusBadge tone="accent">Visualization only</StatusBadge></div></CardHeader>
          <CardContent>
            {data.risk.error ? <DataError label="Score distribution" /> : !data.risk.data?.available ? <EmptyState title="No score distribution available" description={data.risk.data?.note ?? 'Prepared dashboard data is not available.'} /> : <div className="space-y-4 pt-2">
              {data.risk.data.bins.map((bin, index) => {
                const max = Math.max(...data.risk.data!.bins.map((entry) => entry.invoice_count), 1)
                return <div key={bin.label} className="grid grid-cols-[82px_1fr_52px] items-center gap-3 text-xs">
                  <span className="text-muted-foreground">{bin.label}</span>
                  <div className="h-2.5 overflow-hidden rounded-full bg-background"><div className={`h-full rounded-full ${index === 3 ? 'bg-primary' : 'bg-[#b77952]/55'}`} style={{ width: `${Math.max(4, (bin.invoice_count / max) * 100)}%` }} /></div>
                  <span className="text-right font-medium tabular-nums">{number(bin.invoice_count)}</span>
                  <span className="col-start-2 -mt-2 text-[10px] text-muted-foreground">Score range: {score(bin.min_score)} – {score(bin.max_score)}</span>
                </div>
              })}
              <p className="border-t border-border pt-3 text-xs leading-5 text-muted-foreground">{data.risk.data.note}</p>
            </div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Detection channels</CardTitle><p className="mt-1 text-xs text-muted-foreground">Independent outputs from available artifacts</p></CardHeader>
          <CardContent className="space-y-3">
            {data.detections.error ? <DataError label="Detection overview" /> : data.detections.data ? <>
              {([
                ['Rules', data.detections.data.rules], ['GNN', data.detections.data.gnn], ['Contract RAG', data.detections.data.rag],
              ] as const).map(([label, channel]) => <div key={label} className="rounded-md border border-border p-3">
                <div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{label}</span><StatusBadge tone={channel.available ? 'sage' : 'neutral'}>{channel.available ? 'Available' : 'Unavailable'}</StatusBadge></div>
                <p className="mt-2 text-lg font-semibold">{number(channel.invoice_count)}</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">{channel.detail ?? channel.reason ?? 'No further detail available.'}</p>
              </div>)}
              <div className="pt-1"><p className="mb-2 text-xs font-medium text-muted-foreground">RAG status distribution</p><div className="flex flex-wrap gap-2">{Object.entries(data.detections.data.rag_status_counts).map(([status, count]) => <StatusBadge key={status} tone={status === 'mismatch' ? 'warning' : 'neutral'}>{status.replaceAll('_', ' ')} · {count}</StatusBadge>)}</div></div>
            </> : <LoadingState label="Loading detection outputs…" />}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between"><div><CardTitle>Flagged invoices</CardTitle><p className="mt-1 text-xs text-muted-foreground">Latest prepared review signals, with recorded human decisions shown separately</p></div><StatusBadge tone="warning">For auditor review</StatusBadge></CardHeader>
        <CardContent className="px-0 pb-1">
          {data.invoices.error ? <div className="px-5 pb-5"><DataError label="Recent invoices" /></div> : !data.invoices.data ? <LoadingState label="Loading flagged invoices…" /> : !data.invoices.data.available || data.invoices.data.items.length === 0 ? <div className="px-5 pb-5"><EmptyState title="No flagged invoice rows available" description={data.invoices.data.note} /></div> : <Table>
            <TableHeader><TableRow><TableHead>Invoice</TableHead><TableHead>Vendor</TableHead><TableHead>Amount</TableHead><TableHead>Date</TableHead><TableHead>GNN score</TableHead><TableHead>Signals</TableHead><TableHead>Human decision</TableHead></TableRow></TableHeader>
            <TableBody>{data.invoices.data.items.map((invoice) => <TableRow key={invoice.invoice_id}>
              <TableCell><button className="font-medium text-primary hover:underline" onClick={() => onNavigate('Invoice Intelligence')}>{invoice.invoice_id}</button></TableCell>
              <TableCell><div>{invoice.vendor_name ?? 'Name unavailable'}</div><div className="text-[11px] text-muted-foreground">{invoice.vendor_id ?? 'Vendor ID unavailable'}</div></TableCell>
              <TableCell className="tabular-nums">{number(invoice.amount)}</TableCell><TableCell>{date(invoice.invoice_date)}</TableCell><TableCell className="tabular-nums">{score(invoice.risk_score)}</TableCell>
              <TableCell><div className="flex max-w-[240px] flex-wrap gap-1">{invoice.detection_sources.length ? invoice.detection_sources.map((source) => <StatusBadge key={source} tone="warning">{source}</StatusBadge>) : <span className="text-xs text-muted-foreground">Signal details unavailable</span>}</div></TableCell>
              <TableCell>{invoice.human_decision ? <StatusBadge tone="sage">{invoice.human_decision}</StatusBadge> : <span className="text-xs text-muted-foreground">{invoice.review_status === 'no_decision_recorded' ? 'No decision recorded' : 'Unavailable'}</span>}</TableCell>
            </TableRow>)}</TableBody>
          </Table>}
          {data.invoices.data && <p className="px-5 pb-4 pt-2 text-[11px] text-muted-foreground">{data.invoices.data.note}</p>}
        </CardContent>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Vendors with highest observed signals</CardTitle><p className="mt-1 text-xs text-muted-foreground">Ranked by maximum observed related-invoice GNN score</p></CardHeader>
          <CardContent className="px-0 pb-1">
            {data.vendors.error ? <div className="px-5 pb-5"><DataError label="Vendor signals" /></div> : !data.vendors.data ? <LoadingState label="Loading vendor signals…" /> : !data.vendors.data.available ? <div className="px-5 pb-5"><EmptyState title="Vendor signal ranking unavailable" description={data.vendors.data.note} /></div> : <Table>
              <TableHeader><TableRow><TableHead>Vendor</TableHead><TableHead>Invoices</TableHead><TableHead>Flagged</TableHead><TableHead>Max GNN score</TableHead><TableHead>Investigation</TableHead></TableRow></TableHeader>
              <TableBody>{data.vendors.data.items.map((vendor) => <TableRow key={vendor.vendor_id}>
                <TableCell><button className="text-left font-medium text-primary hover:underline" onClick={() => onNavigate('Vendor Intelligence')}>{vendor.vendor_name ?? vendor.vendor_id}</button><div className="text-[11px] text-muted-foreground">{vendor.vendor_id}</div></TableCell>
                <TableCell>{vendor.related_invoice_count}</TableCell><TableCell>{vendor.flagged_invoice_count}</TableCell><TableCell className="tabular-nums">{score(vendor.max_gnn_score)}</TableCell>
                <TableCell>{vendor.investigation_status ? <StatusBadge tone="neutral">{vendor.investigation_status}</StatusBadge> : <span className="text-xs text-muted-foreground">No record shown</span>}</TableCell>
              </TableRow>)}</TableBody>
            </Table>}
            {data.vendors.data && <p className="px-5 pb-4 pt-2 text-[11px] text-muted-foreground">{data.vendors.data.note}</p>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Recent investigation activity</CardTitle><p className="mt-1 text-xs text-muted-foreground">Investigation records and human decisions are separate</p></CardHeader>
          <CardContent className="space-y-4">
            {data.activity.error ? <DataError label="Recent activity" /> : !data.activity.data ? <LoadingState label="Loading investigation activity…" /> : <>
              <div><div className="mb-2 flex items-center justify-between"><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Investigations</h4><StatusBadge tone={data.activity.data.investigations_available ? 'sage' : 'neutral'}>{data.activity.data.investigations_available ? 'SQLite records' : 'Unavailable'}</StatusBadge></div>
                {data.activity.data.investigations.length ? <div className="divide-y divide-border rounded-md border border-border">{data.activity.data.investigations.map((item) => <div key={item.investigation_id} className="flex items-center justify-between gap-3 p-3"><div className="min-w-0"><p className="truncate text-sm font-medium">{item.vendor_name ?? item.vendor_id}</p><p className="text-xs text-muted-foreground">{item.investigation_id}{item.invoice_id ? ` · ${item.invoice_id}` : ''} · {date(item.created_at)}</p></div><StatusBadge>{item.status}</StatusBadge></div>)}</div> : <p className="rounded-md border border-dashed border-border p-4 text-xs text-muted-foreground">No investigation records returned.</p>}
              </div>
              <div><div className="mb-2 flex items-center justify-between"><h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Recorded human decisions</h4><StatusBadge tone={data.activity.data.decisions_available ? 'sage' : 'neutral'}>{data.activity.data.decisions_available ? 'Audit log' : 'Unavailable'}</StatusBadge></div>
                {data.activity.data.human_decisions.length ? <div className="space-y-2">{data.activity.data.human_decisions.map((decision, index) => <div key={`${decision.invoice_id}-${decision.time}-${index}`} className="flex items-center justify-between gap-3 rounded-md bg-background px-3 py-2"><div><p className="text-sm font-medium">{decision.decision}</p><p className="text-xs text-muted-foreground">{decision.invoice_id} · {decision.vendor_id}</p></div><span className="text-xs text-muted-foreground">{date(decision.time)}</span></div>)}</div> : <p className="rounded-md border border-dashed border-border p-4 text-xs text-muted-foreground">No saved human decisions returned. This is not a pending-review count.</p>}
              </div>
              <p className="text-[11px] leading-5 text-muted-foreground">{data.activity.data.note}</p>
            </>}
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-col justify-between gap-2 border-t border-border pt-4 text-[11px] text-muted-foreground sm:flex-row">
        <p>Flagged means an automated review signal. It is not a finding of fraud or legitimacy.</p>
        <p>Source files last updated: {date(data.summary.data?.source_files_updated_at)}{refreshedAt ? ` · Dashboard fetched ${refreshedAt.toLocaleTimeString()}` : ''}</p>
      </div>
    </div>
  )
}
