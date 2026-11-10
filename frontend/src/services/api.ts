import type {
  DashboardActivity,
  DashboardSummary,
  DetectionOverview,
  HealthResponse,
  InvoiceDetail,
  InvoiceInvestigationsResponse,
  InvoiceListResponse,
  StartInvoiceInvestigationResponse,
  StartVendorInvestigationResponse,
  VendorDetail,
  VendorListResponse,
  RecentInvoices,
  RiskDistribution,
  VendorSignals,
  NetworkGraph,
  NetworkNodeDetail,
  NetworkEntityType,
  AIChatRequest,
  AIChatResponse,
} from '@/types/api'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/health`, { signal })
  if (!response.ok) throw new Error(`Health request failed with HTTP ${response.status}`)
  return response.json() as Promise<HealthResponse>
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, { signal })
  if (!response.ok) throw new Error(`Request failed with HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export const getDashboardSummary = (signal?: AbortSignal) => getJson<DashboardSummary>('/dashboard/summary', signal)
export const getRiskDistribution = (signal?: AbortSignal) => getJson<RiskDistribution>('/dashboard/risk-distribution', signal)
export const getDetectionOverview = (signal?: AbortSignal) => getJson<DetectionOverview>('/dashboard/detections', signal)
export const getRecentInvoices = (signal?: AbortSignal) => getJson<RecentInvoices>('/dashboard/recent-invoices?limit=8', signal)
export const getVendorSignals = (signal?: AbortSignal) => getJson<VendorSignals>('/dashboard/vendors?limit=6', signal)
export const getDashboardActivity = (signal?: AbortSignal) => getJson<DashboardActivity>('/dashboard/activity?limit=6', signal)

export interface InvoiceListParams {
  q?: string
  status?: 'all' | 'flagged' | 'clear'
  vendor_id?: string
  signal?: string
  sort_by?: 'invoice_id' | 'vendor_name' | 'amount' | 'date' | 'risk_score' | 'overall_status'
  sort_dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export function getInvoices(params: InvoiceListParams = {}, signal?: AbortSignal) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return getJson<InvoiceListResponse>(`/invoices?${query.toString()}`, signal)
}

export const getInvoice = (invoiceId: string, signal?: AbortSignal) => getJson<InvoiceDetail>(`/invoices/${encodeURIComponent(invoiceId)}`, signal)
export const getInvoiceInvestigations = (invoiceId: string, signal?: AbortSignal) => getJson<InvoiceInvestigationsResponse>(`/invoices/${encodeURIComponent(invoiceId)}/investigations`, signal)

export async function startInvoiceInvestigation(invoiceId: string): Promise<StartInvoiceInvestigationResponse> {
  const response = await fetch(`${API_BASE_URL}/invoices/${encodeURIComponent(invoiceId)}/investigations`, { method: 'POST' })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail || `Investigation request failed with HTTP ${response.status}`)
  }
  return response.json() as Promise<StartInvoiceInvestigationResponse>
}

export interface VendorListParams {
  q?: string
  status?: 'all' | 'flagged' | 'clear' | 'no_invoices'
  category?: string
  signal?: string
  sort_by?: 'vendor_id' | 'vendor_name' | 'invoice_count' | 'total_transaction_value' | 'flagged_invoice_count' | 'vendor_category'
  sort_dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export function getVendors(params: VendorListParams = {}, signal?: AbortSignal) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)) })
  return getJson<VendorListResponse>(`/vendors?${query.toString()}`, signal)
}

export const getVendor = (vendorId: string, signal?: AbortSignal) => getJson<VendorDetail>(`/vendors/${encodeURIComponent(vendorId)}`, signal)

export async function startVendorInvestigation(vendorId: string): Promise<StartVendorInvestigationResponse> {
  const response = await fetch(`${API_BASE_URL}/vendors/${encodeURIComponent(vendorId)}/investigations`, { method: 'POST' })
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(payload?.detail || `Investigation request failed with HTTP ${response.status}`)
  }
  return response.json() as Promise<StartVendorInvestigationResponse>
}

export interface NetworkParams {
  q?: string
  entity_type?: NetworkEntityType[]
  relationship_type?: string[]
  overview?: boolean
}

export function getNetworkGraph(params: NetworkParams = {}, signal?: AbortSignal) {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  if (params.overview) query.set('overview', 'true')
  params.entity_type?.forEach((value) => query.append('entity_type', value))
  params.relationship_type?.forEach((value) => query.append('relationship_type', value))
  return getJson<NetworkGraph>(`/network?${query.toString()}`, signal)
}

export const getNetworkNode = (type: NetworkEntityType, id: string, signal?: AbortSignal) =>
  getJson<NetworkNodeDetail>(`/network/nodes/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, signal)

export async function postAIChat(payload: AIChatRequest, signal?: AbortSignal): Promise<AIChatResponse> {
  const response = await fetch(`${API_BASE_URL}/ai/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    throw new Error(body?.detail || `Chat request failed with HTTP ${response.status}`)
  }
  return response.json() as Promise<AIChatResponse>
}
