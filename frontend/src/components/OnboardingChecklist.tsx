'use client';

/**
 * Getting-started checklist (go-to-market onboarding). Shows a new tenant the
 * next step to value and hides itself once onboarding is complete, so it never
 * clutters an established workspace.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, Button } from '@/components/ui';
import { useAuth } from '@/contexts/AuthContext';
import { CheckCircle2, Circle, ArrowRight } from 'lucide-react';

interface Step { key: string; label: string; done: boolean; href?: string | null; }
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

  // The first not-done step is the one we actively nudge with a CTA.
  const nextStep = data.steps.find((s) => !s.done);

  return (
    <Card padding="lg" className="mb-6 border border-teal-100">
      <CardHeader>
        <CardTitle><span className="me-2">🚀</span>Get started</CardTitle>
        <Link href="/welcome" className="text-sm font-medium text-teal-700 hover:text-teal-600">
          {data.progress_pct}% complete →
        </Link>
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
            <span className={`flex-1 ${s.done ? 'text-ink-muted line-through' : 'text-ink'}`}>{s.label}</span>
            {!s.done && s.href && s.key === nextStep?.key && (
              <Link href={s.href}>
                <Button variant="secondary" size="sm">Start <ArrowRight className="w-4 h-4 ms-1" /></Button>
              </Link>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
