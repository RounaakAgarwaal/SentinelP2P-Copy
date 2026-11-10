import type { ReactNode, SVGProps } from 'react'

export type IconName =
  | 'dashboard' | 'invoice' | 'vendor' | 'network' | 'sparkles' | 'analytics'
  | 'settings' | 'search' | 'bell' | 'chevron-down' | 'chevron-left'
  | 'chevron-right' | 'panel' | 'close' | 'check' | 'info' | 'plus' | 'external'
  | 'menu' | 'arrow-up-right'

const paths: Record<IconName, ReactNode> = {
  dashboard: <><rect x="3" y="3" width="8" height="8" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="11" width="7" height="10" rx="1.5" /><rect x="3" y="14" width="8" height="7" rx="1.5" /></>,
  invoice: <><path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2Z" /><path d="M14 3.5v5h5M8.5 13h7M8.5 16.5h7" /></>,
  vendor: <><rect x="3.5" y="7" width="17" height="13" rx="2" /><path d="M8 7V5.5A2.5 2.5 0 0 1 10.5 3h3A2.5 2.5 0 0 1 16 5.5V7M3.5 12h17M10 12v2h4v-2" /></>,
  network: <><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="18" r="2.5" /><circle cx="19" cy="18" r="2.5" /><path d="m10.8 7.2-4.6 8.6m7-8.6 4.6 8.6M7.5 18h9" /></>,
  sparkles: <><path d="m12 3 1.3 5.7L19 10l-5.7 1.3L12 17l-1.3-5.7L5 10l5.7-1.3L12 3Z" /><path d="m19 15 .7 2.3L22 18l-2.3.7L19 21l-.7-2.3L16 18l2.3-.7L19 15ZM5 3l.5 1.5L7 5l-1.5.5L5 7l-.5-1.5L3 5l1.5-.5L5 3Z" /></>,
  analytics: <><path d="M4 19V5M4 19h17" /><path d="m7 15 3-4 3 2 5-7" /><path d="M17 6h1v1" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1 1.1.9-1.1 1.9-1.4-.5a7.8 7.8 0 0 1-1.6.9l-.3 1.5h-2.2l-.3-1.5a7.8 7.8 0 0 1-1.6-.9l-1.4.5-1.1-1.9 1.1-.9a7 7 0 0 1 0-1.8l-1.1-.9 1.1-1.9 1.4.5a7.8 7.8 0 0 1 1.6-.9l.3-1.5h2.2l.3 1.5a7.8 7.8 0 0 1 1.6.9l1.4-.5 1.1 1.9-1.1.9a7 7 0 0 1-.1 1.7Z" transform="translate(-1 -1)" /></>,
  search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.5 4.5" /></>,
  bell: <><path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9ZM10 21h4" /></>,
  'chevron-down': <path d="m6 9 6 6 6-6" />,
  'chevron-left': <path d="m14.5 5-7 7 7 7" />,
  'chevron-right': <path d="m9.5 5 7 7-7 7" />,
  panel: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  check: <path d="m5 12 4 4L19 6" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  external: <><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  'arrow-up-right': <><path d="M7 17 17 7M8 7h9v9" /></>,
}

type IconProps = SVGProps<SVGSVGElement> & { name: IconName; size?: number }

export function Icon({ name, size = 18, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {paths[name]}
    </svg>
  )
}
