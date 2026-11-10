import type { NetworkEdge, NetworkEntityType, NetworkNode } from '@/types/api'

export interface GraphSlice {
  nodes: NetworkNode[]
  edges: NetworkEdge[]
  matches: NetworkNode[]
}

export interface GraphPoint { x: number; y: number }

export function filterGraph(
  nodes: NetworkNode[],
  edges: NetworkEdge[],
  query: string,
  entityTypes: NetworkEntityType[],
  relationshipType: string,
): GraphSlice {
  const allowedTypes = new Set(entityTypes)
  const availableNodes = nodes.filter((node) => allowedTypes.has(node.entity_type))
  const ids = new Set(availableNodes.map((node) => node.id))
  const availableEdges = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)
    && (relationshipType === 'all' || edge.relationship_type === relationshipType))
  const normalizedQuery = query.trim().toLocaleLowerCase()
  if (!normalizedQuery) return { nodes: availableNodes, edges: availableEdges, matches: [] }

  const matches = availableNodes.filter((node) => [node.label, node.entity_id, ...Object.values(node.properties)]
    .some((value) => String(value ?? '').toLocaleLowerCase().includes(normalizedQuery)))
  return {
    // Keep the filtered graph intact so a selected search result can expand to
    // its second hop without another backend request.
    nodes: availableNodes,
    edges: availableEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
    matches,
  }
}

export function buildNeighborhood(slice: GraphSlice, anchorId: string, depth: 1 | 2): GraphSlice {
  const byId = new Map(slice.nodes.map((node) => [node.id, node]))
  if (!byId.has(anchorId)) return { nodes: [], edges: [], matches: [] }
  const distance = new Map<string, number>([[anchorId, 0]])
  const adjacency = new Map<string, string[]>()
  for (const edge of slice.edges) {
    adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target])
    adjacency.set(edge.target, [...(adjacency.get(edge.target) ?? []), edge.source])
  }
  const queue = [anchorId]
  while (queue.length) {
    const current = queue.shift()!
    const currentDepth = distance.get(current)!
    if (currentDepth >= depth) continue
    for (const neighbor of adjacency.get(current) ?? []) {
      if (distance.has(neighbor)) continue
      distance.set(neighbor, currentDepth + 1)
      queue.push(neighbor)
    }
  }
  const visibleIds = new Set(distance.keys())
  const visibleNodes = slice.nodes.filter((node) => visibleIds.has(node.id))
  return {
    nodes: visibleNodes,
    edges: slice.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)),
    matches: slice.matches.filter((node) => visibleIds.has(node.id)),
  }
}

export function chooseOverviewAnchor(nodes: NetworkNode[], edges: NetworkEdge[]): string | null {
  if (!nodes.length) return null
  const degree = new Map<string, number>()
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  }
  const vendors = nodes.filter((node) => node.entity_type === 'vendor')
  const pool = vendors.length ? vendors : nodes
  return [...pool].sort((left, right) => (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0)
    || left.id.localeCompare(right.id))[0]?.id ?? null
}

export function radialLayout(nodes: NetworkNode[], edges: NetworkEdge[], anchorId: string, width = 1200, height = 820): Map<string, GraphPoint> {
  const points = new Map<string, GraphPoint>()
  const anchor = nodes.find((node) => node.id === anchorId)
  if (!anchor) return points
  const depth = new Map<string, number>([[anchorId, 0]])
  const adjacent = new Map<string, string[]>()
  for (const edge of edges) {
    adjacent.set(edge.source, [...(adjacent.get(edge.source) ?? []), edge.target])
    adjacent.set(edge.target, [...(adjacent.get(edge.target) ?? []), edge.source])
  }
  const queue = [anchorId]
  while (queue.length) {
    const current = queue.shift()!
    for (const next of adjacent.get(current) ?? []) {
      if (depth.has(next)) continue
      depth.set(next, (depth.get(current) ?? 0) + 1)
      queue.push(next)
    }
  }
  const center = { x: width / 2, y: height / 2 }
  points.set(anchorId, center)
  const maxDepth = Math.max(0, ...depth.values())
  for (let level = 1; level <= maxDepth; level += 1) {
    const ring = nodes.filter((node) => depth.get(node.id) === level).sort((a, b) => a.id.localeCompare(b.id))
    const radius = Math.min(Math.min(width, height) * 0.44, 145 + (level - 1) * 125, Math.max(145, ring.length * 22))
    ring.forEach((node, index) => {
      const angle = -Math.PI / 2 + 2 * Math.PI * index / Math.max(1, ring.length)
      points.set(node.id, { x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle) })
    })
  }
  // Search may return more than one disconnected match. Keep those visible on
  // a calm outer ring rather than dropping them from the canvas.
  const disconnected = nodes.filter((node) => !points.has(node.id)).sort((a, b) => a.id.localeCompare(b.id))
  disconnected.forEach((node, index) => {
    const angle = -Math.PI / 2 + 2 * Math.PI * index / Math.max(1, disconnected.length)
    const radius = Math.min(width, height) * 0.46
    points.set(node.id, { x: center.x + radius * Math.cos(angle), y: center.y + radius * Math.sin(angle) })
  })
  return points
}

export function nodeRadius(nodeId: string, edges: NetworkEdge[], selectedId: string | null): number {
  if (nodeId === selectedId) return 19
  const degree = edges.reduce((count, edge) => count + Number(edge.source === nodeId || edge.target === nodeId), 0)
  return Math.max(8, Math.min(15, 8 + degree * 0.8))
}

export function edgeCurve(source: GraphPoint, target: GraphPoint, index: number): string {
  const dx = target.x - source.x
  const dy = target.y - source.y
  const length = Math.max(1, Math.hypot(dx, dy))
  const direction = index % 2 === 0 ? 1 : -1
  const offset = 16 + (index % 4) * 7
  const controlX = (source.x + target.x) / 2 - dy / length * offset * direction
  const controlY = (source.y + target.y) / 2 + dx / length * offset * direction
  return `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`
}

export function clampZoom(value: number): number { return Math.max(0.45, Math.min(2.8, value)) }

export function fitTransform(): { zoom: number; pan: GraphPoint } {
  // The SVG viewBox itself fits the complete radial extent to its viewport.
  return { zoom: 1, pan: { x: 0, y: 0 } }
}

export function panByPixels(
  origin: GraphPoint,
  delta: GraphPoint,
  bounds: { width: number; height: number },
  view: { width: number; height: number } = { width: 1200, height: 820 },
): GraphPoint {
  const scale = Math.min(bounds.width / view.width, bounds.height / view.height) || 1
  return { x: origin.x + delta.x / scale, y: origin.y + delta.y / scale }
}
