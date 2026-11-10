import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'

import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { LoadingState } from '@/components/ui/loading-state'
import { PageHeader } from '@/components/ui/page-header'
import { postAIChat } from '@/services/api'
import type { AIChatMessage, AIChatResponse, AIChatSource, ApiConnectionState } from '@/types/api'
import { cn } from '@/utils/cn'

type ChatTurn = AIChatMessage & {
  id: string
  createdAt: string
  response?: AIChatResponse
}

const suggestions = [
  'Why was invoice INV001 flagged?',
  'Show me the risk signals associated with a vendor.',
  'Find invoices linked to a particular vendor.',
  'What evidence was collected during an investigation?',
  'Explain the difference between rule-based and GNN detection.',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'Not available'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function shortValue(value: unknown, max = 180): string {
  const text = displayValue(value)
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function sourceSummary(source: AIChatSource): [string, unknown][] {
  const fields = source.fields
  const invoice = source.record_type === 'invoice' && isRecord(fields.invoice) ? fields.invoice : fields
  const choices: Record<string, string[]> = {
    invoice: ['invoice_id', 'amount', 'date', 'payment_status', 'description', 'vendor_id', 'po_id'],
    vendor: ['vendor_name', 'vendor_id', 'registration_number', 'email', 'phone'],
    purchase_order: ['po_id', 'vendor_id', 'amount', 'date', 'item_category', 'created_by_employee_id', 'approved_by_employee_id'],
    contract: ['contract_id', 'vendor_id', 'contract_text', 'agreed_rate', 'start_date', 'end_date'],
    employee: ['name', 'employee_id', 'department', 'role', 'email'],
    rule_signal: ['label', 'rule', 'explanation'],
    gnn_result: ['risk_score', 'prediction'],
    contract_rag_result: ['rag_status', 'similarity', 'best_match_service', 'evidence'],
    audit_decision: ['decision', 'time', 'note', 'invoice_id'],
    investigation_evidence: ['finding', 'verification_status', 'source_type', 'source_url', 'retrieved_at'],
  }
  const rows = (choices[source.record_type] ?? Object.keys(fields)).flatMap((key) => {
    const value = invoice[key] ?? fields[key]
    return value === undefined || value === null || value === '' ? [] : [[key.replaceAll('_', ' '), value] as [string, unknown]]
  })
  return rows.slice(0, 4)
}

function provenanceEntries(source: AIChatSource): [string, unknown][] {
  return Object.entries(source.provenance).filter(([, value]) => value !== null && value !== undefined && value !== '')
}

function safeSourceUrl(source: AIChatSource): string | null {
  const raw = source.fields.source_url ?? source.provenance.source_url
  if (typeof raw !== 'string') return null
  return /^https?:\/\//i.test(raw) ? raw : null
}

function EvidenceCard({ source, cited }: { source: AIChatSource; cited: boolean }) {
  const summary = sourceSummary(source)
  const verification = source.fields.verification_status
  const sourceUrl = safeSourceUrl(source)
  return (
    <details className="group rounded-lg border border-border bg-white">
      <summary className="flex cursor-pointer list-none items-start justify-between gap-3 p-4 [&::-webkit-details-marker]:hidden">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[#78917d]/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[#58735d]">{source.source_type.replaceAll('_', ' ')}</span>
            {cited && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-[#945d40]">Cited</span>}
            {typeof verification === 'string' && <span className="rounded-full bg-[#d9b66f]/20 px-2 py-0.5 text-[10px] font-medium text-[#765f2d]">{verification.replaceAll('_', ' ')}</span>}
          </div>
          <p className="mt-2 truncate font-mono text-xs text-foreground">{source.source_id}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {summary.map(([key, value]) => <span key={key} className="text-xs text-muted-foreground"><span className="capitalize">{key}:</span> {shortValue(value)}</span>)}
            {sourceUrl && <a className="inline-flex items-center gap-1 text-xs font-medium text-[#945d40] hover:underline" href={sourceUrl} target="_blank" rel="noreferrer">Source URL <Icon name="external" size={12} /></a>}
          </div>
        </div>
        <Icon name="chevron-down" size={16} className="mt-1 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-border px-4 py-3">
        <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">Provenance</h4>
        {provenanceEntries(source).length > 0 ? (
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            {provenanceEntries(source).map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-[10px] capitalize text-muted-foreground">{key.replaceAll('_', ' ')}</dt><dd className="break-words text-xs text-foreground">{shortValue(value, 260)}</dd></div>)}
          </dl>
        ) : <p className="mt-2 text-xs text-muted-foreground">No provenance details were returned.</p>}
        <h4 className="mt-4 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">Returned record fields</h4>
        <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 text-[11px] leading-5 text-foreground">{JSON.stringify(source.fields, null, 2)}</pre>
      </div>
    </details>
  )
}

function AvailabilityNote({ response }: { response: AIChatResponse }) {
  if (response.retrieval_status === 'matched') return null
  const unavailable = response.retrieval_status === 'unavailable'
  const sources = Object.entries(response.source_availability).flatMap(([group, value]) => {
    if (!isRecord(value)) return []
    return Object.entries(value).filter(([, status]) => isRecord(status) && status.available === false)
      .map(([name, status]) => `${group}: ${name}${isRecord(status) && status.reason ? ` (${String(status.reason).replaceAll('_', ' ')})` : ''}`)
  })
  return (
    <div className={cn('mt-3 rounded-lg border px-3.5 py-3 text-xs leading-5', unavailable ? 'border-[#d9b66f]/50 bg-[#d9b66f]/10 text-[#6e5a30]' : 'border-border bg-background text-muted-foreground')}>
      <p className="font-medium">{unavailable ? 'Some information sources are unavailable.' : 'No matching records were returned.'}</p>
      <p className="mt-0.5">{unavailable ? 'This limits what can be checked; it is not a negative finding.' : 'No match in the retrieved data does not establish that an event or relationship is absent.'}</p>
      {sources.length > 0 && <ul className="mt-2 list-inside list-disc">{sources.map((item) => <li key={item}>{item}</li>)}</ul>}
    </div>
  )
}

function AssistantContent({ response }: { response: AIChatResponse }) {
  if (response.status === 'greeting') {
    return <p className="text-sm leading-6">{response.answer ?? response.message}</p>
  }
  if (response.status === 'entity_not_found') {
    return <div role="status" className="rounded-lg border border-[#d9b66f]/50 bg-[#d9b66f]/10 p-3.5 text-sm leading-6 text-[#66552f]"><p className="font-semibold">Record not found</p><p className="mt-1">{response.message}</p></div>
  }
  if (response.status === 'unsupported_question') {
    return <div role="status" className="rounded-lg border border-border bg-background p-3.5 text-sm leading-6 text-muted-foreground"><p className="font-semibold text-foreground">Question outside supported records</p><p className="mt-1">{response.message}</p></div>
  }
  if (response.status === 'provider_not_configured') {
    return (
      <div className="rounded-lg border border-[#d9b66f]/50 bg-[#d9b66f]/10 p-3.5 text-sm leading-6 text-[#66552f]">
        <p className="font-semibold">Answer generation is not configured</p>
        <p className="mt-1">{response.retrieval_status === 'matched' ? 'Evidence retrieval succeeded.' : 'Evidence retrieval did not find matching records or some sources are unavailable.'} The conversational answer provider has not been configured, so no AI answer was generated.</p>
      </div>
    )
  }
  if (response.status === 'grounding_failed') {
    return <div role="alert" className="rounded-lg border border-[#c77d65]/40 bg-[#c77d65]/10 p-3.5 text-sm leading-6 text-[#754638]">{response.message}</div>
  }
  return response.answer ? <p className="whitespace-pre-wrap text-sm leading-6">{response.answer}</p> : <p className="text-sm leading-6 text-muted-foreground">{response.message}</p>
}

export default function SentinelAIPage({ apiState }: { apiState: ApiConnectionState }) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [draft, setDraft] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const statusText = apiState === 'connected' ? 'API connected' : apiState === 'checking' ? 'Checking API' : 'API unavailable'
  const conversationHistory = useMemo(() => turns.slice(-12).map(({ role, content }) => ({ role, content })), [turns])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, pending])

  async function sendMessage(event?: FormEvent) {
    event?.preventDefault()
    const message = draft.trim()
    if (!message || pending) return
    const priorHistory = conversationHistory
    const userTurn: ChatTurn = { id: crypto.randomUUID(), role: 'user', content: message, createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
    setTurns((current) => [...current, userTurn])
    setDraft('')
    setPending(true)
    setError(null)
    try {
      const response = await postAIChat({
        message,
        conversation_history: priorHistory,
        ...(conversationId ? { conversation_id: conversationId } : {}),
      })
      if (response.conversation_id) setConversationId(response.conversation_id)
      setTurns((current) => [...current, {
        id: crypto.randomUUID(), role: 'assistant', content: response.message,
        createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), response,
      }])
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The chat request failed. Please try again.')
      setDraft(message)
    } finally {
      setPending(false)
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  function startNewConversation() {
    if (pending) return
    setTurns([])
    setDraft('')
    setConversationId(null)
    setError(null)
  }

  return (
    <div>
      <PageHeader
        eyebrow="Workspace"
        title="Sentinel AI"
        description="AI-powered procurement intelligence assistant. Ask about records and review the sources behind each response."
        actions={<div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-2 text-xs text-muted-foreground"><i className={cn('size-1.5 rounded-full', apiState === 'connected' ? 'bg-sage' : apiState === 'checking' ? 'bg-warning' : 'bg-critical')} />{statusText}</span>
          <Button variant="secondary" size="sm" onClick={startNewConversation} disabled={pending}><Icon name="plus" size={14} /> New conversation</Button>
        </div>}
      />

      <Card className="overflow-hidden">
        <div ref={scrollRef} className="h-[min(68vh,720px)] min-h-[400px] space-y-5 overflow-y-auto px-4 py-5 sm:px-7 sm:py-7" aria-live="polite">
          {turns.length === 0 ? (
            <div className="mx-auto max-w-3xl py-5 sm:py-10">
              <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Icon name="sparkles" size={24} /></div>
              <h2 className="mt-4 text-center text-xl font-semibold tracking-tight">Hello! I’m Sentinel AI.</h2>
              <p className="mx-auto mt-2 max-w-2xl text-center text-sm leading-6 text-muted-foreground">I can help you investigate invoices, understand vendor relationships, review detection signals, and explore supporting evidence.</p>
              <div className="mt-7 grid gap-2 sm:grid-cols-2">
                {suggestions.map((suggestion) => <button key={suggestion} type="button" onClick={() => setDraft(suggestion)} className="group flex min-h-12 items-center justify-between gap-3 rounded-lg border border-border bg-white px-4 py-3 text-left text-xs leading-5 text-foreground transition-colors hover:border-primary/40 hover:bg-primary/[0.03]">
                  <span>{suggestion}</span><Icon name="arrow-up-right" size={15} className="shrink-0 text-muted-foreground group-hover:text-primary" />
                </button>)}
              </div>
            </div>
          ) : turns.map((turn) => (
            <article key={turn.id} className={cn('flex gap-3', turn.role === 'user' ? 'justify-end' : 'justify-start')}>
              {turn.role === 'assistant' && <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon name="sparkles" size={16} /></div>}
              <div className={cn('min-w-0 max-w-[92%] sm:max-w-[82%]', turn.role === 'user' && 'flex flex-col items-end')}>
                <div className={cn('rounded-2xl px-4 py-3', turn.role === 'user' ? 'rounded-tr-sm bg-[#b77952] text-white' : 'w-full rounded-tl-sm border border-border bg-white text-foreground')}>
                  {turn.role === 'user' ? <p className="whitespace-pre-wrap text-sm leading-6">{turn.content}</p> : turn.response ? <AssistantContent response={turn.response} /> : <p className="text-sm leading-6">{turn.content}</p>}
                </div>
                <p className="mt-1.5 px-1 text-[10px] text-muted-foreground">{turn.role === 'user' ? 'You' : 'Sentinel AI'} · {turn.createdAt}</p>
                {turn.response && <div className="mt-3 w-full space-y-3">
                  <AvailabilityNote response={turn.response} />
                  {turn.response.citations.length > 0 && <div className="flex flex-wrap items-center gap-1.5" aria-label="Citations">
                    <span className="mr-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">Citations</span>
                    {turn.response.citations.map((citation) => <a key={citation.source_id} href={`#${encodeURIComponent(citation.source_id)}`} className="rounded-md border border-border bg-white px-2 py-1 font-mono text-[10px] text-[#945d40] hover:bg-primary/5">{citation.source_id}</a>)}
                  </div>}
                  <div>
                    <h3 className="mb-2 text-[10px] font-semibold uppercase tracking-[0.13em] text-muted-foreground">Retrieved evidence · {turn.response.sources.length}</h3>
                    {turn.response.sources.length === 0 ? <EmptyState title="No evidence to display" description="The API returned no source records for this question. Check source availability before drawing conclusions." /> : (
                      <div className="space-y-2">
                        {turn.response.sources.map((source) => <div id={source.source_id} key={source.source_id} className="scroll-mt-24"><EvidenceCard source={source} cited={turn.response!.citations.some((citation) => citation.source_id === source.source_id)} /></div>)}
                      </div>
                    )}
                  </div>
                </div>}
              </div>
              {turn.role === 'user' && <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-white text-[11px] font-semibold text-muted-foreground">You</div>}
            </article>
          ))}
          {pending && <div className="flex items-start gap-3"><div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Icon name="sparkles" size={16} /></div><div className="w-full max-w-md"><LoadingState label="Retrieving supporting records…" /></div></div>}
        </div>
        <div className="border-t border-border bg-[#fffefa] p-3 sm:p-4">
          {error && <div role="alert" className="mb-3 flex items-start justify-between gap-3 rounded-lg border border-[#c77d65]/40 bg-[#c77d65]/10 px-3.5 py-2.5 text-xs text-[#754638]"><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss error"><Icon name="close" size={14} /></button></div>}
          <form onSubmit={(event) => void sendMessage(event)} className="flex items-end gap-2 rounded-xl border border-input bg-white p-2 shadow-card focus-within:border-primary/60">
            <label className="sr-only" htmlFor="sentinel-ai-message">Message Sentinel AI</label>
            <textarea id="sentinel-ai-message" rows={2} maxLength={4000} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleKeyDown} placeholder="Ask about an invoice, vendor, relationship, or investigation evidence…" disabled={pending} className="max-h-40 min-h-11 flex-1 resize-y bg-transparent px-2 py-2 text-sm leading-5 outline-none placeholder:text-muted-foreground/80 disabled:opacity-60" />
            <Button type="submit" size="sm" disabled={pending || !draft.trim()} className="mb-0.5"><span className="hidden sm:inline">Send</span><Icon name="arrow-up-right" size={15} className="rotate-45" /><span className="sr-only sm:hidden">Send</span></Button>
          </form>
          <p className="mt-2 px-1 text-[10px] leading-4 text-muted-foreground">Enter to send · Shift+Enter for a new line. Retrieved signals and evidence support auditor review; they are not fraud or payment decisions.</p>
        </div>
      </Card>
    </div>
  )
}
