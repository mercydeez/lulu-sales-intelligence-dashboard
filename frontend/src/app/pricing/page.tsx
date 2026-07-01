'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/contexts/AuthContext';
import { PageHeader, Card, Badge, Button, SkeletonCard, Stagger, RevealItem } from '@/components/ui';
import { Tag, Check } from 'lucide-react';

interface Plan { plan: string; tagline: string; monthly_price_aed: number | null; custom_pricing: boolean;
  limits: { users: number | null; api_requests_month: number | null; sage_messages_month: number | null };
  features: string[]; }

const TITLE: Record<string, string> = { free: 'Trial', starter: 'Starter', growth: 'Growth', enterprise: 'Enterprise' };

export default function PricingPage() {
  const { authFetch } = useAuth();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authFetch('/api/billing/plans');
      if (r.ok) setPlans((await r.json()).plans ?? []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [authFetch]);
  useEffect(() => { load(); }, [load]);

  const price = (p: Plan) =>
    p.custom_pricing ? 'Custom' : p.monthly_price_aed === 0 ? 'Free' : `AED ${p.monthly_price_aed!.toLocaleString('en-AE')}`;

  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-5xl mx-auto">
        <PageHeader
          title="Pricing"
          description="AED-first plans for UAE retailers. Pay monthly, by manual invoice, or on outcomes. VAT applies."
          icon={<Tag className="w-5 h-5" />}
        />

        {loading ? <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">{[0,1,2,3].map((i) => <SkeletonCard key={i} />)}</div> : (
          <Stagger className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {plans.map((p) => (
              <RevealItem key={p.plan}>
                <Card padding="lg" className={`h-full flex flex-col ${p.plan === 'growth' ? 'border-2 border-teal-300' : ''}`}>
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-semibold text-ink">{TITLE[p.plan] ?? p.plan}</h3>
                    {p.plan === 'growth' && <Badge variant="teal">Popular</Badge>}
                  </div>
                  <p className="text-xs text-ink-muted">{p.tagline}</p>
                  <p className="text-2xl font-bold text-ink mt-3">{price(p)}
                    {!p.custom_pricing && p.monthly_price_aed !== 0 && <span className="text-sm font-normal text-ink-muted">/mo</span>}
                  </p>
                  <ul className="mt-4 space-y-2 flex-1">
                    {p.features.map((f, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-ink-soft">
                        <Check className="w-4 h-4 text-teal-600 mt-0.5 shrink-0" />{f}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-4">
                    {p.custom_pricing
                      ? <Link href="/settings/billing"><Button variant="secondary" className="w-full">Contact sales</Button></Link>
                      : <Link href="/settings/billing"><Button className="w-full">Choose {TITLE[p.plan]}</Button></Link>}
                  </div>
                </Card>
              </RevealItem>
            ))}
          </Stagger>
        )}

        <p className="text-xs text-ink-muted mt-6">
          Prices are AED and exclude 5% VAT. Enterprise is billed by manual invoice / purchase order.
          Ask about <Link href="/outcome-pricing" className="text-teal-700">outcome-based pricing</Link> — pay a share of
          the savings we prove. Draft — confirm pricing with sales; VAT/legal terms require UAE professional review.
        </p>
      </div>
    </main>
  );
}
