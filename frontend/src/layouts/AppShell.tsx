import { useState } from 'react'

import { Icon, type IconName } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/components/ui/search-input'
import DashboardPage from '@/pages/DashboardPage'
import InvoiceIntelligencePage from '@/pages/InvoiceIntelligencePage'
import VendorIntelligencePage from '@/pages/VendorIntelligencePage'
import VendorNetworkPage from '@/pages/VendorNetworkPage'
import SentinelAIPage from '@/pages/SentinelAIPage'
import PlaceholderPage from '@/pages/PlaceholderPage'
import type { ApiConnectionState } from '@/types/api'
import { cn } from '@/utils/cn'

const navigation: { label: string; icon: IconName }[] = [
  { label: 'Dashboard', icon: 'dashboard' },
  { label: 'Invoice Intelligence', icon: 'invoice' },
  { label: 'Vendor Intelligence', icon: 'vendor' },
  { label: 'Vendor Network', icon: 'network' },
  { label: 'Sentinel AI', icon: 'sparkles' },
  { label: 'Risk & Model Analytics', icon: 'analytics' },
  { label: 'Settings', icon: 'settings' },
]

type AppShellProps = { apiState: ApiConnectionState; apiMessage?: string }

export default function AppShell({ apiState, apiMessage }: AppShellProps) {
  const [activePage, setActivePage] = useState('Dashboard')
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  const pageTitle = activePage
  const apiLabel = apiState === 'connected' ? 'API connected' : apiState === 'checking' ? 'Checking API' : 'API unavailable'

  function navigate(page: string) {
    setActivePage(page)
    setMobileOpen(false)
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      {mobileOpen && <button aria-label="Close navigation" className="fixed inset-0 z-30 bg-foreground/25 lg:hidden" onClick={() => setMobileOpen(false)} />}
      <aside className={cn(
        'fixed inset-y-0 left-0 z-40 flex flex-col border-r border-border bg-surface transition-[width,transform] duration-200 lg:translate-x-0',
        collapsed ? 'w-[76px]' : 'w-[256px]',
        mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
        'max-lg:!w-[256px]',
      )}>
        <div className={cn('flex h-[76px] shrink-0 items-center border-b border-border px-5', collapsed && 'lg:justify-center lg:px-0')}>
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Icon name="network" size={20} />
          </div>
          <div className={cn('ml-3 min-w-0', collapsed && 'lg:hidden')}>
            <div className="text-[15px] font-semibold tracking-[-0.03em]">Sentinel<span className="text-primary">P2P</span></div>
            <div className="text-[10px] font-medium uppercase tracking-[0.12em] text-muted-foreground">Financial intelligence</div>
          </div>
          <Button variant="ghost" size="icon" aria-label="Collapse sidebar" className="ml-auto hidden size-8 text-muted-foreground lg:inline-flex" onClick={() => setCollapsed((value) => !value)}>
            <Icon name="panel" size={17} />
          </Button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-5" aria-label="Main navigation">
          <p className={cn('mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground/80', collapsed && 'lg:hidden')}>Workspace</p>
          {navigation.map((item) => {
            const active = activePage === item.label
            return (
              <button key={item.label} type="button" onClick={() => navigate(item.label)} aria-current={active ? 'page' : undefined}
                title={collapsed ? item.label : undefined}
                className={cn('group flex h-10 w-full items-center gap-3 rounded-md px-3 text-left text-[13px] font-medium transition-colors',
                  active ? 'bg-primary/10 text-[#945d40]' : 'text-muted-foreground hover:bg-background hover:text-foreground',
                  collapsed && 'lg:justify-center lg:px-0')}>
                <Icon name={item.icon} size={18} className={cn('shrink-0', active ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground')} />
                <span className={cn('truncate', collapsed && 'lg:hidden')}>{item.label}</span>
              </button>
            )
          })}
        </nav>

        <div className={cn('border-t border-border p-4', collapsed && 'lg:px-2')}>
          <div className={cn('flex items-center gap-2.5 rounded-md bg-background p-2.5', collapsed && 'lg:justify-center lg:bg-transparent lg:p-0')}>
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[#e9ded0] text-xs font-semibold text-[#74553f]">U</span>
            <div className={cn('min-w-0', collapsed && 'lg:hidden')}>
              <p className="truncate text-xs font-medium">User profile</p>
              <p className="truncate text-[11px] text-muted-foreground">Placeholder account</p>
            </div>
          </div>
        </div>
      </aside>

      <div className={cn('min-h-screen transition-[margin] duration-200', collapsed ? 'lg:ml-[76px]' : 'lg:ml-[256px]')}>
        <header className="sticky top-0 z-20 flex h-[76px] items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur-sm sm:px-6 lg:px-8">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>
            <Icon name="menu" />
          </Button>
          <div className="min-w-0 flex-1">
            <div className="hidden items-center gap-2 text-[11px] text-muted-foreground sm:flex">
              <span>SentinelP2P</span><Icon name="chevron-right" size={13} /><span>{activePage}</span>
            </div>
            <h1 className="truncate text-sm font-semibold sm:mt-1">{pageTitle}</h1>
          </div>
          <div className="hidden w-full max-w-[340px] md:block">
            <SearchInput aria-label="Search" placeholder="Search invoices, vendors, evidence…" className="h-9 bg-surface text-xs" />
          </div>
          <span className="hidden items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1.5 text-[11px] text-muted-foreground xl:inline-flex" title={apiMessage}>
            <i className={cn('size-1.5 rounded-full', apiState === 'connected' ? 'bg-sage' : apiState === 'checking' ? 'bg-warning' : 'bg-critical')} />
            {apiLabel}
          </span>
          <Button variant="ghost" size="icon" aria-label="Notifications (placeholder)" title="Notifications are not configured" className="relative text-muted-foreground">
            <Icon name="bell" size={18} />
          </Button>
          <button type="button" aria-label="User profile placeholder" className="flex size-9 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-xs font-semibold text-foreground">U</button>
        </header>

        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
          {activePage === 'Dashboard'
            ? <DashboardPage onNavigate={navigate} />
            : activePage === 'Invoice Intelligence'
              ? <InvoiceIntelligencePage />
              : activePage === 'Vendor Intelligence'
                ? <VendorIntelligencePage />
              : activePage === 'Vendor Network'
                ? <VendorNetworkPage />
              : activePage === 'Sentinel AI'
                ? <SentinelAIPage apiState={apiState} />
            : <PlaceholderPage title={activePage} />}
        </main>
      </div>
    </div>
  )
}
