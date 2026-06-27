'use client';

/**
 * Getting-started checklist (go-to-market onboarding). Shows a new tenant the
 * next step to value and hides itself once onboarding is complete, so it never
 * clutters an established workspace.
 */
import { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { CheckCircle2, Circle } from 'lucide-react';

interface Step { key: string; label: string; done: boolean; }
interface Onboarding { steps: Step[]; progress_pct: number; complete: boolean; }

export default function OnboardingChecklist() {
  const { authFetch } = useAuth();
  const [data, setData] = useState<Onboarding | null>(null);

  useEffect(() => {
    let active = true;
    authFetch('/api/auth/onboarding')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (active && d) setData(d); })
      .catch(() => {});
    return () => { active = false; };
  }, [authFetch]);

  // Hide entirely once complete (or until loaded) — never clutter the dashboard.
  if (!data || data.complete) return null;

  return (
    <Card padding="lg" className="mb-6 border border-teal-100">
      <CardHeader>
        <CardTitle><span className="me-2">🚀</span>Get started</CardTitle>
        <span className="text-sm font-medium text-ink-muted">{data.progress_pct}% complete</span>
      </CardHeader>

      <div className="h-2 w-full rounded-full bg-ink/5 mb-4 overflow-hidden">
        <div className="h-full sunset-gradient rounded-full transition-all"
          style={{ width: `${data.progress_pct}%` }} />
      </div>

      <ul className="space-y-2">
        {data.steps.map((s) => (
          <li key={s.key} className="flex items-center gap-3">
            {s.done
              ? <CheckCircle2 className="w-5 h-5 text-teal-500 flex-shrink-0" />
              : <Circle className="w-5 h-5 text-ink-muted flex-shrink-0" />}
            <span className={s.done ? 'text-ink-muted line-through' : 'text-ink'}>{s.label}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
