type LoadingStateProps = { label?: string }

export function LoadingState({ label = 'Loading' }: LoadingStateProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface p-4 text-sm text-muted-foreground" role="status" aria-busy="true">
      <span className="size-4 animate-spin rounded-full border-2 border-primary/25 border-t-primary motion-reduce:animate-none" />
      {label}
    </div>
  )
}
