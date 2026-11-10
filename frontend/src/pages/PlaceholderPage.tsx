import { Icon, type IconName } from '@/components/icons'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'

const pageIcons: Record<string, IconName> = {
  'Invoice Intelligence': 'invoice',
  'Vendor Intelligence': 'vendor',
  'Vendor Network': 'network',
  'Sentinel AI': 'sparkles',
  'Risk & Model Analytics': 'analytics',
  Settings: 'settings',
}

export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <div>
      <PageHeader eyebrow="Workspace" title={title} description="Application shell placeholder. No business data or actions are connected on this screen." />
      <EmptyState
        title={`${title} is not configured yet`}
        description="This navigation destination is reserved for a future task. SentinelP2P business functionality has not been added here."
      />
      <div className="mt-5 flex items-center gap-2 text-xs text-muted-foreground"><Icon name={pageIcons[title] ?? 'dashboard'} size={15} /> Placeholder page</div>
    </div>
  )
}
