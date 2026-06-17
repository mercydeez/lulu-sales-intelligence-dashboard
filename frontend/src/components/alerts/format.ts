export function formatRelativeTime(timestamp: string | null): string {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  if (hours < 24) return `${hours}h ago`;
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString('en-AE', { month: 'short', day: 'numeric' });
}

export function formatDateTime(timestamp: string | null): string {
  if (!timestamp) return '—';
  return new Date(timestamp).toLocaleDateString('en-AE', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
