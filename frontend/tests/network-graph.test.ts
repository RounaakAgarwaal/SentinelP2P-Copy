import test from 'node:test'
import assert from 'node:assert/strict'

import type { NetworkEdge, NetworkEntityType, NetworkNode } from '../src/types/api.ts'
import { buildNeighborhood, chooseOverviewAnchor, clampZoom, edgeCurve, filterGraph, fitTransform, nodeRadius, panByPixels, radialLayout } from '../src/utils/network-graph.ts'

const makeNode = (type: NetworkEntityType, id: string, label: string): NetworkNode => ({
  id: `${type}:${id}`, entity_type: type, entity_id: id, label, properties: { name: label },
})

const nodes = [
  makeNode('employee', 'E1', 'Alex Auditor'),
  makeNode('employee', 'E2', 'Sam Employee'),
  makeNode('vendor', 'V1', 'Northwind Supply'),
  makeNode('vendor', 'V2', 'Quiet Vendor'),
  makeNode('purchase_order', 'PO1', 'PO1'),
  makeNode('purchase_order', 'PO2', 'PO2'),
  makeNode('purchase_order', 'PO3', 'PO3'),
  makeNode('invoice', 'I1', 'I1'),
  makeNode('invoice', 'I2', 'I2'),
  makeNode('contract', 'C1', 'C1'),
]

const link = (source: string, relationship_type: string, target: string): NetworkEdge => ({
  id: `${source}|${relationship_type}|${target}`, source, target, relationship_type,
  label: relationship_type.replaceAll('_', ' '),
  details: { matched_field: null, matched_value: null, source_entity_id: source, target_entity_id: target },
})

const edges = [
  link('employee:E1', 'created', 'vendor:V1'),
  link('employee:E1', 'raised', 'purchase_order:PO1'),
  link('employee:E1', 'raised', 'purchase_order:PO2'),
  link('employee:E1', 'approved', 'purchase_order:PO3'),
  link('vendor:V1', 'received', 'purchase_order:PO1'),
  link('vendor:V1', 'received', 'purchase_order:PO2'),
  link('vendor:V1', 'has_contract', 'contract:C1'),
  link('purchase_order:PO1', 'has_invoice', 'invoice:I1'),
  link('purchase_order:PO2', 'has_invoice', 'invoice:I2'),
  link('vendor:V1', 'shared_phone', 'vendor:V2'),
]

const allTypes: NetworkEntityType[] = ['employee', 'vendor', 'purchase_order', 'invoice', 'contract']

test('overview is centered on a connected vendor neighborhood with valid endpoints', () => {
  const anchor = chooseOverviewAnchor(nodes, edges)
  assert.equal(anchor, 'vendor:V1')
  const overview = buildNeighborhood({ nodes, edges, matches: [] }, anchor!, 2)
  const ids = new Set(overview.nodes.map((node) => node.id))
  assert.ok(overview.edges.length > 0)
  assert.ok(overview.nodes.some((node) => node.entity_type === 'invoice'))
  assert.ok(overview.edges.every((edge) => ids.has(edge.source) && ids.has(edge.target)))
})

test('employee with several purchase orders expands to its one-hop and two-hop records', () => {
  const base = { nodes, edges, matches: [] }
  const oneHop = buildNeighborhood(base, 'employee:E1', 1)
  const twoHop = buildNeighborhood(base, 'employee:E1', 2)
  assert.equal(oneHop.nodes.filter((node) => node.entity_type === 'purchase_order').length, 3)
  assert.equal(oneHop.nodes.some((node) => node.entity_type === 'invoice'), false)
  assert.equal(twoHop.nodes.filter((node) => node.entity_type === 'invoice').length, 2)
})

test('vendor with multiple POs and invoices expands without losing edge endpoints', () => {
  const result = buildNeighborhood({ nodes, edges, matches: [] }, 'vendor:V1', 2)
  assert.equal(result.nodes.filter((node) => node.entity_type === 'purchase_order').length, 3)
  assert.equal(result.nodes.filter((node) => node.entity_type === 'invoice').length, 2)
  const ids = new Set(result.nodes.map((node) => node.id))
  assert.ok(result.edges.every((edge) => ids.has(edge.source) && ids.has(edge.target)))
})

test('one-connection node stays visible and gets a readable degree-based size', () => {
  const result = buildNeighborhood({ nodes, edges, matches: [] }, 'vendor:V2', 1)
  assert.equal(result.nodes.length, 2)
  assert.equal(result.edges.length, 1)
  assert.equal(nodeRadius('vendor:V2', result.edges, null), 8.8)
  assert.equal(nodeRadius('vendor:V2', result.edges, 'vendor:V2'), 19)
})

test('search, entity filters, and relationship filters return connected valid records', () => {
  const search = filterGraph(nodes, edges, 'northwind', allTypes, 'all')
  assert.deepEqual(search.matches.map((node) => node.id), ['vendor:V1'])
  const neighborhood = buildNeighborhood(search, search.matches[0].id, 1)
  assert.ok(neighborhood.nodes.length > 1)
  assert.ok(neighborhood.edges.every((edge) => neighborhood.nodes.some((node) => node.id === edge.source)
    && neighborhood.nodes.some((node) => node.id === edge.target)))
  const filtered = filterGraph(nodes, edges, '', ['vendor', 'purchase_order'], 'received')
  assert.ok(filtered.edges.every((edge) => edge.relationship_type === 'received'))
  assert.ok(filtered.edges.every((edge) => filtered.nodes.some((node) => node.id === edge.source)
    && filtered.nodes.some((node) => node.id === edge.target)))
  assert.equal(filterGraph(nodes, edges, 'not-present', allTypes, 'all').matches.length, 0)
})

test('selected node is centered and ring-one coordinates stay stable when expanding', () => {
  const oneHop = buildNeighborhood({ nodes, edges, matches: [] }, 'employee:E1', 1)
  const twoHop = buildNeighborhood({ nodes, edges, matches: [] }, 'employee:E1', 2)
  const firstLayout = radialLayout(oneHop.nodes, oneHop.edges, 'employee:E1')
  const expandedLayout = radialLayout(twoHop.nodes, twoHop.edges, 'employee:E1')
  assert.deepEqual(firstLayout.get('employee:E1'), { x: 600, y: 410 })
  for (const node of oneHop.nodes) assert.deepEqual(expandedLayout.get(node.id), firstLayout.get(node.id))
  assert.match(edgeCurve({ x: 10, y: 10 }, { x: 100, y: 100 }, 0), /Q/)
})

test('zoom clamp and pointer pan preserve fit and drag behavior', () => {
  assert.equal(clampZoom(0.1), 0.45)
  assert.equal(clampZoom(4), 2.8)
  assert.deepEqual(panByPixels({ x: 0, y: 0 }, { x: 100, y: -50 }, { width: 600, height: 410 }), { x: 200, y: -100 })
  // Fit resets the SVG user transform to the viewBox baseline (100% and origin).
  assert.deepEqual(fitTransform(), { zoom: 1, pan: { x: 0, y: 0 } })
})
