import { useEffect, useMemo, useRef, useState, type FormEvent, type PointerEvent, type WheelEvent } from 'react'

import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { getNetworkGraph, getNetworkNode } from '@/services/api'
import type { NetworkEdge, NetworkEntityType, NetworkGraph, NetworkNode, NetworkNodeDetail } from '@/types/api'
import { buildNeighborhood, chooseOverviewAnchor, clampZoom, edgeCurve, filterGraph, fitTransform, nodeRadius, panByPixels, radialLayout } from '@/utils/network-graph'

const entities: { value: NetworkEntityType; label: string; color: string }[] = [
  { value: 'vendor', label: 'Vendor', color: '#B77952' },
  { value: 'employee', label: 'Employee', color: '#78917D' },
  { value: 'invoice', label: 'Invoice', color: '#D9B66F' },
  { value: 'purchase_order', label: 'Purchase order', color: '#8B8AA6' },
  { value: 'contract', label: 'Contract', color: '#C77D65' },
]

const VIEW = { width: 1200, height: 820 }
const colorFor = (type: NetworkEntityType) => entities.find((entity) => entity.value === type)?.color ?? '#81786F'
const displayName = (node: NetworkNode) => node.label || node.entity_id
const sharedEdge = (edge: NetworkEdge) => edge.relationship_type.startsWith('shared_')

export default function VendorNetworkPage() {
  const [graph, setGraph] = useState<NetworkGraph | null>(null)
  const [detail, setDetail] = useState<NetworkNodeDetail | null>(null)
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [selectedEntityTypes, setSelectedEntityTypes] = useState<NetworkEntityType[]>(entities.map((item) => item.value))
  const [relationshipFilter, setRelationshipFilter] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expansionDepth, setExpansionDepth] = useState<1 | 2>(2)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [drag, setDrag] = useState<{ x: number; y: number; origin: { x: number; y: number } } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    // Load the full read-only API graph once. Search, filters and hop expansion
    // operate on this same response, so a second hop is not clipped by a search slice.
    getNetworkGraph({}, controller.signal)
      .then(setGraph)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'The network data could not be loaded.')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!selectedId) { setDetail(null); return }
    const [type, ...parts] = selectedId.split(':')
    const controller = new AbortController()
    getNetworkNode(type as NetworkEntityType, parts.join(':'), controller.signal)
      .then(setDetail)
      .catch(() => { if (!controller.signal.aborted) setDetail(null) })
    return () => controller.abort()
  }, [selectedId])

  const filtered = useMemo(() => graph
    ? filterGraph(graph.nodes, graph.edges, submittedQuery, selectedEntityTypes, relationshipFilter)
    : { nodes: [] as NetworkNode[], edges: [] as NetworkEdge[], matches: [] as NetworkNode[] },
  [graph, submittedQuery, selectedEntityTypes, relationshipFilter])
  const overviewAnchor = useMemo(() => chooseOverviewAnchor(filtered.nodes, filtered.edges), [filtered.nodes, filtered.edges])
  const focusId = selectedId ?? (submittedQuery ? filtered.matches[0]?.id ?? null : overviewAnchor)
  const visible = useMemo(() => {
    if (!graph) return { nodes: [] as NetworkNode[], edges: [] as NetworkEdge[], matches: [] as NetworkNode[] }
    if (selectedId) return buildNeighborhood(filtered, selectedId, expansionDepth)
    if (submittedQuery) {
      const nodes = new Map<string, NetworkNode>()
      const edges = new Map<string, NetworkEdge>()
      // Keep every matching entity and its chosen number of relationship hops.
      filtered.matches.slice(0, 12).forEach((match) => {
        const neighborhood = buildNeighborhood(filtered, match.id, expansionDepth)
        neighborhood.nodes.forEach((node) => nodes.set(node.id, node))
        neighborhood.edges.forEach((edge) => edges.set(edge.id, edge))
      })
      const resultNodes = [...nodes.values()]
      const ids = new Set(resultNodes.map((node) => node.id))
      return { nodes: resultNodes, edges: [...edges.values()].filter((edge) => ids.has(edge.source) && ids.has(edge.target)), matches: filtered.matches }
    }
    return overviewAnchor ? buildNeighborhood(filtered, overviewAnchor, expansionDepth) : { nodes: [], edges: [], matches: [] }
  }, [graph, filtered, selectedId, submittedQuery, expansionDepth, overviewAnchor])

  const positions = useMemo(() => focusId
    ? radialLayout(visible.nodes, visible.edges, focusId, VIEW.width, VIEW.height)
    : new Map<string, { x: number; y: number }>(), [visible.nodes, visible.edges, focusId])
  const directConnectionIds = useMemo(() => new Set(visible.edges
    .filter((edge) => edge.source === selectedId || edge.target === selectedId)
    .map((edge) => edge.source === selectedId ? edge.target : edge.source)), [visible.edges, selectedId])
  const relationshipOptions = graph?.available_relationship_types ?? []
  const visibleMatches = submittedQuery ? filtered.matches : []
  const noData = !loading && !error && graph && !graph.available
  const noMatches = !loading && !error && graph?.available && submittedQuery.length > 0 && visibleMatches.length === 0
  const selectedVisibleEdges = visible.edges.filter((edge) => edge.source === selectedId || edge.target === selectedId)
  const displayedDetails = detail?.connections.filter(({ node, relationship }) => selectedEntityTypes.includes(node.entity_type)
    && (relationshipFilter === 'all' || relationship.relationship_type === relationshipFilter)) ?? []
  const degreeMap = useMemo(() => {
    const values = new Map<string, number>()
    graph?.edges.forEach((edge) => {
      values.set(edge.source, (values.get(edge.source) ?? 0) + 1)
      values.set(edge.target, (values.get(edge.target) ?? 0) + 1)
    })
    return values
  }, [graph])

  function chooseNode(node: NetworkNode) {
    setSelectedId(node.id)
    setExpansionDepth(1)
    setPan({ x: 0, y: 0 })
    setZoom(1)
  }

  function returnToOverview() {
    setQuery('')
    setSubmittedQuery('')
    setSelectedId(null)
    setExpansionDepth(2)
    setPan({ x: 0, y: 0 })
    setZoom(1)
  }

  function fitGraph() {
    const transform = fitTransform()
    setZoom(transform.zoom)
    setPan(transform.pan)
  }

  function onWheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault()
    setZoom((value) => clampZoom(value * (event.deltaY < 0 ? 1.12 : 0.89)))
  }

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    if ((event.target as Element).closest('[data-graph-node]')) return
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({ x: event.clientX, y: event.clientY, origin: pan })
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!drag || !svgRef.current) return
    const bounds = svgRef.current.getBoundingClientRect()
    setPan(panByPixels(drag.origin, { x: event.clientX - drag.x, y: event.clientY - drag.y }, bounds, VIEW))
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmittedQuery(query.trim())
    setSelectedId(null)
    setExpansionDepth(1)
    setPan({ x: 0, y: 0 })
    setZoom(1)
  }

  function toggleEntity(value: NetworkEntityType) {
    setSelectedEntityTypes((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value])
    setSelectedId(null)
  }

  return (
    <div>
      <PageHeader eyebrow="Relationship exploration" title="Vendor Network" description="Trace source-supported links between vendors and related business records. A connection is an investigation lead, not a fraud conclusion." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
        <div className="space-y-4">
          <Card>
            <CardContent className="flex flex-col gap-4 pt-5">
              <form onSubmit={submitSearch} className="flex gap-2">
                <div className="relative min-w-0 flex-1">
                  <Icon name="search" size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search vendors, invoices, employees, or IDs" aria-label="Search network entities" className="pl-9" />
                </div>
                <Button type="submit">Search network</Button>
                {submittedQuery && <Button variant="outline" onClick={returnToOverview}>Clear</Button>}
                {(selectedId || submittedQuery) && <Button variant="ghost" onClick={returnToOverview}>Overview</Button>}
              </form>
              <div className="flex flex-col gap-3 border-t border-border pt-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex flex-wrap gap-x-4 gap-y-2" aria-label="Filter entity types">
                  {entities.map((entity) => <label key={entity.value} className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                    <input type="checkbox" checked={selectedEntityTypes.includes(entity.value)} onChange={() => toggleEntity(entity.value)} className="accent-[#B77952]" />
                    <span className="size-2 rounded-full" style={{ backgroundColor: entity.color }} />{entity.label}
                  </label>)}
                </div>
                <div className="w-full lg:w-56">
                  <Select aria-label="Filter relationship type" value={relationshipFilter} onChange={(event) => setRelationshipFilter(event.target.value)}>
                    <option value="all">All relationship types</option>
                    {relationshipOptions.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader className="flex-col gap-3 border-b border-border sm:flex-row sm:items-center sm:justify-between">
              <div><CardTitle>Relationship graph</CardTitle><p className="mt-1 text-xs text-muted-foreground">Select a node to center it. Drag to pan; scroll or use the controls to zoom.</p></div>
              <div className="flex items-center gap-1">
                <Button variant="outline" size="icon" aria-label="Zoom out" onClick={() => setZoom((value) => clampZoom(value * 0.82))}>−</Button>
                <span className="min-w-12 text-center text-xs tabular-nums text-muted-foreground">{Math.round(zoom * 100)}%</span>
                <Button variant="outline" size="icon" aria-label="Zoom in" onClick={() => setZoom((value) => clampZoom(value * 1.22))}>+</Button>
                <Button variant="outline" size="sm" className="ml-1" onClick={fitGraph}>Fit</Button>
              </div>
            </CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-[#fbf9f5] px-5 py-3">
              <p className="text-xs text-muted-foreground">{graph && <>{submittedQuery ? `${visibleMatches.length} matching ${visibleMatches.length === 1 ? 'entity' : 'entities'}` : selectedId ? `Focused on ${detail?.node.label ?? selectedId}` : 'Connected overview'} · {visible.nodes.length} nodes · {visible.edges.length} relationships</>}</p>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground">Expand</span>
                <Button variant={expansionDepth === 1 ? 'primary' : 'outline'} size="sm" aria-pressed={expansionDepth === 1} onClick={() => setExpansionDepth(1)}>1 hop</Button>
                <Button variant={expansionDepth === 2 ? 'primary' : 'outline'} size="sm" aria-pressed={expansionDepth === 2} onClick={() => setExpansionDepth(2)}>2 hops</Button>
              </div>
            </div>
            {selectedId && detail && <div className="flex flex-wrap items-center gap-x-2 border-b border-border px-5 py-2 text-xs">
              <span className="font-semibold">{detail.connection_count} direct source connections</span>
              <span className="text-muted-foreground">· {selectedVisibleEdges.length} shown under current filters. Links describe recorded relationships and do not establish wrongdoing.</span>
            </div>}
            <div className="relative h-[540px] w-full touch-none overflow-hidden bg-[#fcfbf8] sm:h-[620px]">
              {loading ? <div className="p-5"><LoadingState label="Loading relationship records…" /></div>
                : error ? <div className="p-5"><EmptyState title="Network data unavailable" description={error} /></div>
                  : noData ? <div className="p-5"><EmptyState title="Source data unavailable" description="The required entity CSV files could not be read. No relationships have been inferred." /></div>
                    : noMatches ? <div className="p-5"><EmptyState title="No matching entities" description="No source record matched this search and filter combination." /></div>
                      : visible.nodes.length === 0 ? <div className="p-5"><EmptyState title="No entities in this view" description="Adjust the entity or relationship filters to see source records." /></div>
                        : visible.edges.length === 0 && <div className="absolute left-3 right-3 top-3 z-10 rounded-md border border-[#ead8b2] bg-[#fffaf0] px-3 py-2 text-xs text-[#75633f]">
                          {submittedQuery ? 'Matching entities were found, but no relationships to other current source records are available.' : 'These records have no connections under the current filters.'}
                        </div>}
              {!loading && !error && !noData && !noMatches && visible.nodes.length > 0 && <svg ref={svgRef} viewBox={`0 0 ${VIEW.width} ${VIEW.height}`} className="h-full w-full cursor-grab active:cursor-grabbing" role="img" aria-label="Vendor relationship graph" onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
                <defs>
                  <marker id="network-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9b8f82" /></marker>
                  <marker id="network-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#B77952" /></marker>
                </defs>
                <g transform={`translate(${pan.x} ${pan.y}) translate(${VIEW.width / 2} ${VIEW.height / 2}) scale(${zoom}) translate(${-VIEW.width / 2} ${-VIEW.height / 2})`}>
                  {visible.edges.map((edge, index) => {
                    const source = positions.get(edge.source); const target = positions.get(edge.target)
                    if (!source || !target) return null
                    const shared = sharedEdge(edge)
                    const active = !selectedId || edge.source === selectedId || edge.target === selectedId
                    const edgeActive = hoveredEdgeId === edge.id || (selectedId !== null && active)
                    const color = shared ? '#B77952' : edgeActive ? '#78917D' : '#b9afa3'
                    const showLabel = hoveredEdgeId === edge.id || (selectedId !== null && active)
                    const directed = !shared
                    const path = edgeCurve(source, target, index)
                    return <g key={edge.id} opacity={active ? 1 : 0.24} onMouseEnter={() => setHoveredEdgeId(edge.id)} onMouseLeave={() => setHoveredEdgeId(null)}>
                      <path d={path} fill="none" stroke="transparent" strokeWidth="16" className="cursor-pointer" />
                      <path d={path} fill="none" stroke={color} strokeWidth={edgeActive ? 2.6 : shared ? 2.2 : 1.35} strokeDasharray={shared ? '6 4' : undefined} markerEnd={directed ? edgeActive ? 'url(#network-arrow-active)' : 'url(#network-arrow)' : undefined} />
                      {showLabel && <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 8} textAnchor="middle" className="pointer-events-none select-none fill-[#5f564e]" fontSize="11" fontWeight="600" stroke="#fcfbf8" strokeWidth="4" paintOrder="stroke">{edge.label}</text>}
                      <title>{`${edge.source} —${edge.relationship_type}→ ${edge.target}${edge.details.matched_field ? ` · matched field: ${edge.details.matched_field}` : ''}`}</title>
                    </g>
                  })}
                  {visible.nodes.map((node) => {
                    const point = positions.get(node.id)
                    if (!point) return null
                    const selected = node.id === selectedId
                    const directlyConnected = directConnectionIds.has(node.id)
                    const opacity = selectedId ? selected || directlyConnected ? 1 : 0.58 : 1
                    const radius = nodeRadius(node.id, graph?.edges ?? [], selectedId)
                    const label = displayName(node).length > 22 ? `${displayName(node).slice(0, 20)}…` : displayName(node)
                    const labelOnRight = point.x >= VIEW.width / 2
                    const labelX = labelOnRight ? radius + 7 : -radius - 7
                    const labelAnchor = labelOnRight ? 'start' : 'end'
                    return <g key={node.id} data-graph-node="true" transform={`translate(${point.x} ${point.y})`} onPointerDown={(event) => event.stopPropagation()} onClick={() => chooseNode(node)} onMouseEnter={() => setHoveredNodeId(node.id)} onMouseLeave={() => setHoveredNodeId(null)} className="cursor-pointer" opacity={opacity}>
                      {selected && <circle r={radius + 9} fill={colorFor(node.entity_type)} opacity="0.14" />}
                      <circle r={radius} fill={colorFor(node.entity_type)} stroke={selected ? '#302A24' : '#fff'} strokeWidth={selected ? 3 : 2} />
                      <text x={labelX} y="-2" textAnchor={labelAnchor} className="pointer-events-none select-none fill-[#302A24]" fontSize={selected || hoveredNodeId === node.id ? 12 : 10} fontWeight={selected ? 700 : 550} stroke="#fcfbf8" strokeWidth="4" paintOrder="stroke">{label}</text>
                      <text x={labelX} y="11" textAnchor={labelAnchor} className="pointer-events-none select-none fill-[#81786F]" fontSize="9" stroke="#fcfbf8" strokeWidth="3" paintOrder="stroke">{node.entity_id}</text>
                      <title>{`${displayName(node)} · ${node.entity_id} · ${node.entity_type.replaceAll('_', ' ')} · ${degreeMap.get(node.id) ?? 0} connections`}</title>
                    </g>
                  })}
                </g>
              </svg>}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-5 py-3">
              {entities.map((entity) => <span key={entity.value} className="inline-flex items-center gap-2 text-[11px] text-muted-foreground"><i className="size-2.5 rounded-full" style={{ backgroundColor: entity.color }} />{entity.label}</span>)}
              <span className="ml-auto inline-flex items-center gap-2 text-[11px] text-muted-foreground"><i className="w-5 border-t-2 border-dashed border-primary" />Shared vendor attribute</span>
            </div>
          </Card>
        </div>

        <Card className="h-fit xl:sticky xl:top-24">
          <CardHeader className="border-b border-border"><CardTitle>Entity details</CardTitle><p className="text-xs text-muted-foreground">Source attributes and direct relationships</p></CardHeader>
          <CardContent className="pt-5">
            {!selectedId || !detail ? <EmptyState title="Select a graph node" description="Click a vendor, employee, invoice, purchase order, or contract to inspect its source attributes and connections." /> : <div className="space-y-5">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.13em] text-muted-foreground">{detail.node.entity_type.replaceAll('_', ' ')}</p>
                <h2 className="mt-1 break-words text-lg font-semibold">{detail.node.label}</h2>
                <p className="font-mono text-xs text-muted-foreground">{detail.node.entity_id}</p>
                <p className="mt-2 rounded-md bg-background px-3 py-2 text-xs text-muted-foreground"><strong className="text-foreground">{detail.connection_count}</strong> recorded direct connection{detail.connection_count === 1 ? '' : 's'}. These links are contextual evidence, not a fraud determination.</p>
              </div>
              <div className="space-y-2 border-t border-border pt-4">
                {Object.entries(detail.node.properties).filter(([key, value]) => value && key !== 'contract_text' && key !== 'description').map(([key, value]) => <div key={key} className="grid grid-cols-[110px_minmax(0,1fr)] gap-2 text-xs"><span className="text-muted-foreground">{key.replaceAll('_', ' ')}</span><span className="break-all">{value}</span></div>)}
              </div>
              <div className="border-t border-border pt-4">
                <p className="mb-3 text-xs font-semibold">Connected records <span className="font-normal text-muted-foreground">({displayedDetails.length} shown)</span></p>
                {displayedDetails.length ? <ul className="space-y-2">{displayedDetails.map(({ node, relationship }) => <li key={relationship.id}>
                  <button type="button" onClick={() => chooseNode(node)} className="w-full rounded-md border border-border p-3 text-left hover:bg-background">
                    <span className="flex items-center justify-between gap-2 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"><span>{relationship.label}</span><span>{node.entity_type.replaceAll('_', ' ')}</span></span>
                    <span className="mt-1 block truncate text-xs font-semibold">{node.label}</span>
                    <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">{node.entity_id}</span>
                    {relationship.details.matched_field && <span className="mt-1 block text-[10px] text-[#945d40]">Matched field: {relationship.details.matched_field}{relationship.details.matched_value ? ` · ${relationship.details.matched_value}` : ''}</span>}
                  </button>
                </li>)}</ul> : <p className="text-xs text-muted-foreground">No relationship records are available for this entity.</p>}
              </div>
              <p className="rounded-md bg-background p-3 text-[11px] leading-5 text-muted-foreground">A missing link means the source records do not show a relationship. It does not establish that no relationship exists outside these datasets.</p>
            </div>}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
