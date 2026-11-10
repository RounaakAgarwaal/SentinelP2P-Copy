import { useState } from 'react'

import { Icon } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { PageHeader } from '@/components/ui/page-header'
import { SearchInput } from '@/components/ui/search-input'
import { Select } from '@/components/ui/select'
import { StatusBadge } from '@/components/ui/status-badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function DesignSystemPage() {
  const [dialogOpen, setDialogOpen] = useState(false)

  return (
    <div>
      <PageHeader
        eyebrow="Application foundation"
        title="Design system preview"
        description="Reusable interface elements for the SentinelP2P application shell."
        actions={<StatusBadge tone="sage">Preview mode</StatusBadge>}
      />

      <div className="mb-7 flex items-start gap-3 rounded-lg border border-[#e9d7b5] bg-[#fbf4e5] p-4 text-sm text-[#6d5d3e]">
        <Icon name="info" size={18} className="mt-0.5 shrink-0" />
        <p><strong>Illustrative UI only.</strong> All sample labels and rows below demonstrate components. No operational SentinelP2P metrics or business records are shown.</p>
      </div>

      <section className="mb-7 grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardTitle>Buttons & status badges</CardTitle>
            <CardDescription>Action styles and semantic tones used throughout the interface.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex flex-wrap items-center gap-2.5">
              <Button><Icon name="plus" size={16} />Primary action</Button>
              <Button variant="secondary">Secondary</Button>
              <Button variant="outline">Outline</Button>
              <Button variant="ghost">Quiet action</Button>
              <Button variant="destructive">Critical action</Button>
              <Button disabled>Disabled</Button>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge tone="neutral">Neutral</StatusBadge>
              <StatusBadge tone="sage">Informational</StatusBadge>
              <StatusBadge tone="warning">Needs review</StatusBadge>
              <StatusBadge tone="critical">Critical</StatusBadge>
              <StatusBadge tone="accent">In progress</StatusBadge>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Form controls</CardTitle>
            <CardDescription>Consistent labels, borders, focus states, and placeholders.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-1.5 text-xs font-medium text-foreground">Text input<Input placeholder="Enter a value" /></label>
            <label className="space-y-1.5 text-xs font-medium text-foreground">Search input<SearchInput placeholder="Search this interface" /></label>
            <label className="space-y-1.5 text-xs font-medium text-foreground">Dropdown<Select defaultValue="all"><option value="all">All illustrative options</option><option value="one">Example option one</option><option value="two">Example option two</option></Select></label>
            <label className="space-y-1.5 text-xs font-medium text-foreground">Disabled input<Input placeholder="Unavailable" disabled /></label>
          </CardContent>
        </Card>
      </section>

      <section className="mb-7 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Reusable card</CardTitle>
            <CardDescription>Cards create clear groupings without heavy visual effects.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="rounded-md border border-dashed border-border bg-background p-4">
              <p className="text-xs font-medium text-muted-foreground">ILLUSTRATIVE COMPONENT SAMPLE</p>
              <p className="mt-2 text-sm font-medium">A neutral surface for future application content</p>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">This area contains no live values or operational status.</p>
            </div>
          </CardContent>
          <CardFooter className="justify-between text-xs text-muted-foreground"><span>Card footer</span><Button variant="ghost" size="sm">Example action <Icon name="arrow-up-right" size={14} /></Button></CardFooter>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Empty and loading states</CardTitle>
            <CardDescription>Helpful feedback when a section has no content or is waiting.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <EmptyState title="Nothing to display" description="A concise explanation can appear here when a future page has no records." />
            <LoadingState label="Illustrative loading state" />
          </CardContent>
        </Card>
      </section>

      <Card className="mb-7">
        <CardHeader>
          <CardTitle>Table</CardTitle>
          <CardDescription>Clearly illustrative rows for spacing and status presentation.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-3"><StatusBadge tone="warning">Illustrative sample rows — not live data</StatusBadge></div>
          <Table>
            <TableHeader><TableRow><TableHead>Reference</TableHead><TableHead>Example label</TableHead><TableHead>Example state</TableHead><TableHead>Source</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow><TableCell className="font-medium">SAMPLE-01</TableCell><TableCell>Illustrative record A</TableCell><TableCell><StatusBadge tone="sage">Example state</StatusBadge></TableCell><TableCell className="text-muted-foreground">Preview only</TableCell></TableRow>
              <TableRow><TableCell className="font-medium">SAMPLE-02</TableCell><TableCell>Illustrative record B</TableCell><TableCell><StatusBadge tone="warning">Example state</StatusBadge></TableCell><TableCell className="text-muted-foreground">Preview only</TableCell></TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dialog</CardTitle>
          <CardDescription>A reusable modal pattern with close, backdrop, and escape-key handling.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="secondary" onClick={() => setDialogOpen(true)}>Open illustrative dialog</Button>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} title="Illustrative dialog" description="This is a component preview. It does not submit or change SentinelP2P data.">
        <div className="rounded-md bg-background p-4 text-sm leading-6 text-muted-foreground">Dialog content can be composed from the shared UI components. No business action is attached.</div>
        <div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setDialogOpen(false)}>Close</Button><Button onClick={() => setDialogOpen(false)}>Got it</Button></div>
      </Dialog>
    </div>
  )
}
