'use client';

import { WifiOff, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/cn';

export interface ConnectionBannerProps {
  /** True when the live (SSE) stream is connected. When false, the degraded banner shows. */
  connected: boolean;
  /** Hide entirely until the first disconnect (avoids a flash on initial connect). */
  show?: boolean;
  className?: string;
}

/**
 * Slim banner shown when a live data stream is degraded/disconnected.
 * Uses aria-live so screen readers are notified of the status change.
 */
export function ConnectionBanner({ connected, show = true, className }: ConnectionBannerProps) {
  return (
    <div aria-live="polite" role="status" className={className}>
      {show && !connected && (
        <div
          className={cn(
            'flex items-center gap-2 px-4 py-2.5 mb-4 rounded-2xl border text-sm',
            'bg-amber-50 border-amber-200 text-amber-800 animate-fade-in'
          )}
        >
          <WifiOff className="w-4 h-4 shrink-0" />
          <span className="flex-1">
            Live updates are paused — reconnecting to the data stream. Figures may be briefly out of date.
          </span>
          <RefreshCw className="w-4 h-4 animate-spin shrink-0" />
        </div>
      )}
    </div>
  );
}
