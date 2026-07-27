'use client';

/**
 * Sage first-run nudge (A1 — Sage-guided onboarding, CX_LOOPS_PLAN).
 * One dismissible, role-aware suggestion that opens the Sage panel — the
 * concierge pilot's "the AI knows my job" moment. Shows until used or
 * dismissed (localStorage), then never again on this browser.
 */
import { useEffect, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useExperience } from '@/contexts/ExperienceContext';
import { useAI } from '@/components/AIProvider';
import { Button } from '@/components/ui';
import { track } from '@/lib/telemetry';

const DISMISSED_KEY = 'sage.firstrun.dismissed';

const ROLE_QUESTION: Record<string, string> = {
  super_admin: 'What changed across my stores this week?',
  regional_manager: 'How is my region trending versus last week?',
  store_manager: 'What needs my attention in my store today?',
};

export default function SageFirstRun() {
  const { user } = useAuth();
  const { config } = useExperience();
  const { openChat } = useAI();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      setVisible(window.localStorage.getItem(DISMISSED_KEY) !== '1');
    } catch { /* private mode — stay hidden */ }
  }, []);

  // Roles whose experience config hides the assistant get no nudge —
  // never render a button that opens nothing (Experience Engine v2).
  if (!visible || config?.assistant_mode === 'hidden') return null;

  const question = ROLE_QUESTION[user?.role ?? ''] ?? ROLE_QUESTION.super_admin;

  const dismiss = () => {
    try { window.localStorage.setItem(DISMISSED_KEY, '1'); } catch { /* ignore */ }
    setVisible(false);
  };

  const ask = () => {
    track('sage_nudge_clicked', { role: user?.role ?? 'unknown' });
    openChat();
    dismiss();
  };

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-line bg-surface px-5 py-4">
      <span className="flex items-center justify-center w-9 h-9 rounded-xl bg-violet-50 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300 shrink-0">
        <Sparkles className="w-4 h-4" />
      </span>
      <div className="flex-1 min-w-[200px]">
        <p className="text-sm font-medium text-ink">New here? Ask Sage your first question.</p>
        <p className="text-xs text-ink-muted mt-0.5">Try: “{question}”</p>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={ask}>
          <Sparkles className="w-4 h-4" />
          Ask Sage
        </Button>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss suggestion"
          className="p-2 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-2 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
