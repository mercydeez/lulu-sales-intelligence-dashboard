'use client';

/**
 * NPS micro-pulse (CX feedback loop — Y6). Cadence, not nag: first ask 7 days
 * after the user's first visit, then every 90 days; dismissing counts as
 * answered for the cadence. Posts to /api/feedback (kind='nps').
 */
import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import { Button, useToast } from '@/components/ui';
import { apiPost } from '@/lib/apiClient';
import { track } from '@/lib/telemetry';
import { X } from 'lucide-react';

const FIRST_SEEN_KEY = 'nps.firstSeen';
const LAST_ASKED_KEY = 'nps.lastAsked';
const FIRST_ASK_AFTER_MS = 7 * 24 * 60 * 60 * 1000;   // 7 days of usage first
const RE_ASK_AFTER_MS = 90 * 24 * 60 * 60 * 1000;     // then quarterly

function shouldAsk(now: number): boolean {
  try {
    const firstSeen = Number(window.localStorage.getItem(FIRST_SEEN_KEY));
    if (!firstSeen) {
      window.localStorage.setItem(FIRST_SEEN_KEY, String(now));
      return false;
    }
    if (now - firstSeen < FIRST_ASK_AFTER_MS) return false;
    const lastAsked = Number(window.localStorage.getItem(LAST_ASKED_KEY));
    return !lastAsked || now - lastAsked > RE_ASK_AFTER_MS;
  } catch {
    return false; // private mode — never ask
  }
}

export default function NpsPulse() {
  const pathname = usePathname();
  const { show } = useToast();
  const [visible, setVisible] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setVisible(shouldAsk(Date.now()));
  }, []);

  if (!visible) return null;

  const markAsked = () => {
    try { window.localStorage.setItem(LAST_ASKED_KEY, String(Date.now())); } catch { /* ignore */ }
    setVisible(false);
  };

  const submit = async () => {
    if (score === null || busy) return;
    setBusy(true);
    try {
      await apiPost('/api/feedback', {
        kind: 'nps',
        score,
        comment: comment.trim() || undefined,
        page: pathname,
      });
      track('nps_submitted', { score });
      show('Thank you — that genuinely helps.', { variant: 'success' });
      markAsked();
    } catch {
      show('Could not send right now — we will ask again another time.', { variant: 'error' });
      markAsked(); // never retry-nag a failing user
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-line bg-surface px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-ink">
          How likely are you to recommend this to a colleague?
        </p>
        <button
          type="button"
          onClick={markAsked}
          aria-label="Dismiss survey"
          className="p-1.5 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors shrink-0"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5" role="group" aria-label="Score from 0 to 10">
        {Array.from({ length: 11 }, (_, i) => (
          <button
            key={i}
            type="button"
            onClick={() => setScore(i)}
            aria-pressed={score === i}
            className={`w-8 h-8 rounded-lg text-xs font-semibold tabular-nums transition-colors ${
              score === i ? 'bg-teal-600 text-white' : 'border border-line text-ink-soft hover:bg-surface-2'
            }`}
          >
            {i}
          </button>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ink-muted px-0.5">
        <span>Not likely</span>
        <span>Very likely</span>
      </div>

      {score !== null && (
        <div className="mt-3 flex flex-col sm:flex-row gap-2">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={4000}
            placeholder="What's the main reason? (optional)"
            className="flex-1 rounded-xl bg-surface border border-line text-ink placeholder-ink-muted px-3 py-2 text-sm focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-500 transition-all"
          />
          <Button size="sm" onClick={submit} disabled={busy}>
            {busy ? 'Sending…' : 'Send'}
          </Button>
        </div>
      )}
    </div>
  );
}
