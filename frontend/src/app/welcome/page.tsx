'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Button, SkeletonCard, Stagger, RevealItem } from '@/components/ui';
import { Rocket, CheckCircle2, Circle, ArrowRight } from 'lucide-react';

interface Step { key: string; label: string; done: boolean; href: string | null; }
interface Onboarding { steps: Step[]; progress_pct: number; complete: boolean;
  stores: number; users: number; sales_records: number; inventory_records: number; }

const STEP_HINT: Record<string, string> = {
  create_account: 'Done — your workspace is live.',
  company_profile: 'Add your TRN, trade licence and emirate so invoices are UAE-ready.',
  load_data: 'Upload sales & inventory as CSV — or download a sample to try it.',
  review_value: 'See dead-stock, stockout loss and cash tied up — in dirhams.',
  invite_team: 'Bring in your store and regional managers.',
};

export default function WelcomePage() {
  const { user } = useAuth();
  const [data, setData] = useState<Onboarding | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { authFetch } = await import('@/lib/apiClient');
      const res = await authFetch('/api/auth/onboarding');
      if (res.ok) setData(await res.json());
    } catch { /* ignore */ } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const firstName = user?.first_name || 'there';

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-3xl mx-auto">
        <PageHeader
          title={`Welcome, ${firstName}`}
          description="A few steps to your first dirham of value. Most teams finish in under 10 minutes."
          icon={<Rocket className="w-5 h-5" />}
        />

        {loading ? <div className="space-y-4"><SkeletonCard /><SkeletonCard /></div> : data && (
          <Stagger className="space-y-6">
            <RevealItem><Card padding="lg">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">Getting started</h3>
                <span className="text-sm font-medium text-teal-700">{data.progress_pct}% complete</span>
              </div>
              <div className="h-2 rounded-full bg-ink/5 overflow-hidden mb-4">
                <div className="h-full rounded-full bg-teal-500 transition-all" style={{ width: `${data.progress_pct}%` }} />
              </div>
              <div className="space-y-2">
                {data.steps.map((s) => (
                  <div key={s.key} className={`flex items-center gap-3 rounded-xl border p-3 ${
                    s.done ? 'border-teal-200 bg-teal-50/40' : 'border-line'}`}>
                    {s.done ? <CheckCircle2 className="w-5 h-5 text-teal-600 shrink-0" />
                            : <Circle className="w-5 h-5 text-ink-muted shrink-0" />}
                    <div className="min-w-0 flex-1">
                      <p className={`text-sm font-medium ${s.done ? 'text-ink-soft line-through' : 'text-ink'}`}>{s.label}</p>
                      <p className="text-xs text-ink-muted">{STEP_HINT[s.key]}</p>
                    </div>
                    {!s.done && s.href && (
                      <Link href={s.href}>
                        <Button variant="secondary" size="sm">Start <ArrowRight className="w-4 h-4 ms-1" /></Button>
                      </Link>
                    )}
                  </div>
                ))}
              </div>
              {data.complete && (
                <p className="text-sm text-teal-700 mt-4">🎉 You&apos;re all set. Explore your dashboard and Value screen.</p>
              )}
            </Card></RevealItem>

            <RevealItem>
              <div className="grid grid-cols-3 gap-4">
                <Mini label="Stores" value={data.stores} />
                <Mini label="Team" value={data.users} />
                <Mini label="Sales records" value={data.sales_records} />
              </div>
            </RevealItem>
          </Stagger>
        )}
      </div>
    </main>
  );
}

function Mini({ label, value }: { label: string; value: number }) {
  return (
    <Card padding="lg" className="text-center">
      <p className="text-2xl font-semibold text-ink">{value.toLocaleString()}</p>
      <p className="text-xs text-ink-muted mt-0.5">{label}</p>
    </Card>
  );
}
