export interface HealthResponse {
  status: 'ok'
  message: string
}

export type AIChatRole = 'user' | 'assistant'
export interface AIChatMessage { role: AIChatRole; content: string }
export interface AIChatRequest {
  message: string
  conversation_history: AIChatMessage[]
  conversation_id?: string | null
}
export interface AIChatSource {
  source_id: string
  source_type: string
  record_type: string
  fields: Record<string, unknown>
  provenance: Record<string, unknown>
}
export interface AIChatCitation {
  source_id: string
  source_type: string
  record_type: string
  provenance: Record<string, unknown>
}
export interface AIChatResponse {
  status: 'greeting' | 'unsupported_question' | 'entity_not_found' | 'provider_not_configured' | 'provider_error' | 'answered' | 'retrieval_unavailable' | 'grounding_failed'
  conversation_id: string | null
  answer: string | null
  error_code: string | null
  message: string
  retrieval_status: 'matched' | 'no_match' | 'unavailable'
  sources: AIChatSource[]
  citations: AIChatCitation[]
  source_availability: Record<string, unknown>
  safety: Record<string, unknown>
}

export type ApiConnectionState = 'checking' | 'connected' | 'unavailable'

export interface MetricValue {
  value: number | null
  available: boolean
  unit: 'count' | 'ratio' | null
  definition: string
  reason: string | null
}

export interface DashboardSummary {
  metrics: {
    total_invoices: MetricValue
    flagged_invoices: MetricValue
    flagged_invoice_share: MetricValue
    total_vendors: MetricValue
    pending_audit_reviews: MetricValue
    audited_invoices: MetricValue
  }
  source_files_updated_at: string | null
  notes: string[]
}

export interface RiskDistribution {
  available: boolean
  kind: 'gnn_score_quartiles' | 'review_flag_counts' | 'unavailable'
  bins: { label: string; min_score: number | null; max_score: number | null; invoice_count: number }[]
  note: string
}

export interface DetectionOverview {
  invoice_count: number | null
  rules: { available: boolean; reason: string | null; invoice_count: number | null; detail: string | null }
  rule_counts: { rule: string; flagged_invoices: number }[]
  gnn: { available: boolean; reason: string | null; invoice_count: number | null; detail: string | null }
  rag: { available: boolean; reason: string | null; invoice_count: number | null; detail: string | null }
  rag_status_counts: Record<string, number>
  notes: string[]
}

export interface RecentInvoices {
  available: boolean
  items: {
    invoice_id: string
    vendor_id: string | null
    vendor_name: string | null
    amount: number | null
    invoice_date: string | null
    risk_score: number | null
    detection_sources: string[]
    review_status: 'decision_recorded' | 'no_decision_recorded' | 'unavailable'
    human_decision: string | null
  }[]
  reason: string | null
  note: string
}

export interface VendorSignals {
  available: boolean
  items: {
    vendor_id: string
    vendor_name: string | null
    related_invoice_count: number
    flagged_invoice_count: number
    max_gnn_score: number | null
    risk_indicator: string
    investigation_status: string | null
    investigation_recorded: boolean | null
  }[]
  reason: string | null
  note: string
}

export interface DashboardActivity {
  investigations_available: boolean
  investigations: {
    investigation_id: string
    vendor_id: string
    vendor_name: string | null
    invoice_id: string | null
    status: string
    created_at: string
    completed_at: string | null
  }[]
  investigations_reason: string | null
  decisions_available: boolean
  human_decisions: { time: string; invoice_id: string; vendor_id: string; decision: string }[]
  decisions_reason: string | null
  note: string
}

export interface InvoiceListItem {
  invoice_id: string
  vendor_id: string | null
  vendor_name: string | null
  amount: number | null
  date: string | null
  overall_status: string | null
  risk_score: number | null
  gnn_prediction: boolean | null
  signals: string[]
  human_decision: string | null
  human_decision_time: string | null
  human_decision_status: 'decision_recorded' | 'no_decision_recorded' | 'unavailable'
}

export interface InvoiceListResponse {
  available: boolean
  items: InvoiceListItem[]
  total: number | null
  limit: number
  offset: number
  available_signals: string[]
  available_vendors: { vendor_id: string; vendor_name: string | null }[]
  reason: string | null
}

export interface InvoiceDetail {
  invoice_id: string
  invoice: Record<string, string | null>
  overall_status: string | null
  vendor_id: string | null
  vendor_mapping_conflict: boolean
  vendor: Record<string, string | null> | null
  purchase_orders: Record<string, string | null>[]
  contracts: Record<string, string | null>[]
  detection: {
    rules: { rule: string; label: string; explanation: string }[]
    gnn: { risk_score: number | null; prediction: boolean | null }
    rag: Record<string, string | number | null> | null
  }
  human_decisions: { time: string | null; decision: string | null; vendor_id: string | null; note: string | null }[]
  sources: Record<string, { available: boolean; reason: string | null; missing_columns: string[]; row_count: number | null }>
}

export interface InvestigationEvidence {
  evidence_id: string
  investigation_id: string
  check_type: string
  finding: string
  matched_entity: unknown
  verification_status: string
  source_type: string
  created_at: string
  source_url: string | null
  retrieved_at: string | null
}

export interface InvoiceInvestigation {
  investigation_id: string
  vendor_id: string
  invoice_id: string | null
  status: string
  created_at: string
  completed_at: string | null
  evidence: InvestigationEvidence[]
}

export interface InvoiceInvestigationsResponse {
  available: boolean
  investigations: InvoiceInvestigation[]
  reason: string | null
}

export interface StartInvoiceInvestigationResponse {
  created: boolean
  investigation: InvoiceInvestigation
  message: string
}

export interface VendorListItem {
  vendor_id: string
  vendor_name: string | null
  email: string | null
  phone: string | null
  registration_number: string | null
  bank_account: string | null
  vendor_category: string | null
  invoice_count: number | null
  total_transaction_value: number | null
  flagged_invoice_count: number | null
  risk_indicators: { label: string; invoice_count: number }[] | null
  risk_indicators_available: boolean
}

export interface VendorListResponse {
  available: boolean
  items: VendorListItem[]
  total: number | null
  limit: number
  offset: number
  available_categories: string[]
  available_signals: string[]
  sources: Record<string, { available: boolean; reason: string | null; missing_columns: string[]; row_count: number | null }>
  invoice_metrics_available: boolean
  reason: string | null
}

export interface VendorInternalFinding {
  evidence_id?: string | null
  check_type: string
  finding: string
  matched_entity: Record<string, string> | null
  verification_status: string
  coverage_status?: string
  source_type: string
  created_at: string | null
}

export interface VendorInvestigationEvidence {
  evidence_id: string
  investigation_id: string
  check_type: string
  finding: string
  matched_entity: unknown
  verification_status: string
  source_type: string
  created_at: string
  source_url: string | null
  retrieved_at: string | null
}

export interface VendorInvestigation {
  investigation_id: string
  vendor_id: string
  invoice_id: string | null
  status: string
  created_at: string
  completed_at: string | null
  evidence: VendorInvestigationEvidence[]
}

export interface VendorDetail {
  vendor_id: string
  vendor: Record<string, string | null>
  invoice_count: number | null
  total_transaction_value: number | null
  flagged_invoice_count: number | null
  risk_indicators: string[] | null
  risk_indicators_available: boolean
  invoices: {
    invoice: Record<string, string | null>
    po_id: string | null
    amount: number | null
    date: string | null
    item_category: string | null
    payment_status: string | null
    overall_status: string | null
    signals: string[]
    risk_score: number | null
    gnn_prediction: boolean | null
    rag_status: string | null
    human_decision: string | null
    human_decision_time: string | null
    human_decision_status: 'decision_recorded' | 'no_decision_recorded' | 'unavailable'
  }[]
  purchase_orders: Record<string, string | null>[]
  contracts: Record<string, string | null>[]
  internal_verification_findings: VendorInternalFinding[]
  investigations: { available: boolean; investigations: VendorInvestigation[]; reason: string | null }
  human_decisions: { time: string | null; invoice_id: string | null; vendor_id: string | null; decision: string | null; note: string | null }[]
  sources: Record<string, { available: boolean; reason: string | null; missing_columns: string[]; row_count: number | null }>
}

export interface StartVendorInvestigationResponse {
  created: boolean
  investigation: VendorInvestigation
  message: string
}

export type NetworkEntityType = 'employee' | 'vendor' | 'purchase_order' | 'invoice' | 'contract'

export interface NetworkNode {
  id: string
  entity_type: NetworkEntityType
  entity_id: string
  label: string
  properties: Record<string, string | null>
}

export interface NetworkEdge {
  id: string
  source: string
  target: string
  relationship_type: string
  label: string
  details: { matched_field: string | null; matched_value: string | null; source_entity_id: string; target_entity_id: string }
}

export interface NetworkGraph {
  available: boolean
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  total_nodes: number
  total_edges: number
  available_relationship_types: string[]
  sources: Record<string, { available: boolean; reason: string | null; missing_columns: string[]; row_count: number }>
}

export interface NetworkNodeDetail {
  node: NetworkNode
  connections: { node: NetworkNode; relationship: NetworkEdge }[]
  connection_count: number
  sources: NetworkGraph['sources']
}
