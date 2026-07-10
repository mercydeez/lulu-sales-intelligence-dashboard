'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { PageHeader, Card, Stagger, RevealItem } from '@/components/ui';
import { ShieldCheck, Lock, ScrollText, UserCheck, Database, Server, Globe } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Live data-residency posture (E5-3). Public endpoint, no auth; returns 404 when
// the operator has disabled the statement, in which case we render nothing.
interface ResidencyPosture {
  status: 'in_region' | 'out_of_region' | 'undeclared' | 'non_compliant';
  region: string | null;
  region_approved: boolean;
  approved_regions: string[];
  backup_region: string | null;
  backup_in_region: boolean;
  cross_border_transfer_allowed: boolean;
  external_ai_may_leave_region: boolean;
  log_retention_days: number;
  residency_required: boolean;
  statement: string;
  checked_at?: string;
}

const RESIDENCY_LABELS: Record<ResidencyPosture['status'], { label: string; tone: string }> = {
  in_region: { label: 'In-region', tone: 'text-teal-700 bg-teal-50 border-teal-200' },
  out_of_region: { label: 'Out of region', tone: 'text-amber-800 bg-amber-50 border-amber-200' },
  non_compliant: { label: 'Non-compliant', tone: 'text-red-700 bg-red-50 border-red-200' },
  undeclared: { label: 'Not declared', tone: 'text-ink-soft bg-paper-2 border-line' },
};

function ResidencySection() {
  const [posture, setPosture] = useState<ResidencyPosture | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'hidden'>('loading');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/monitoring/residency`, { cache: 'no-store' });
        if (!alive) return;
        if (!res.ok) {
          setState('hidden'); // 404 = statement disabled by the operator
          return;
        }
        setPosture(await res.json());
        setState('ready');
      } catch {
        if (alive) setState('hidden'); // backend unreachable — don't render a broken card
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (state !== 'ready' || !posture) return null;

  const badge = RESIDENCY_LABELS[posture.status] ?? RESIDENCY_LABELS.undeclared;

  return (
    <RevealItem>
      <Card padding="lg">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <Globe className="w-4 h-4 text-teal-600" />
            <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">
              Data residency
            </h3>
          </div>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${badge.tone}`}>
            {badge.label}
          </span>
        </div>

        <p className="text-sm text-ink-soft mb-3">{posture.statement}</p>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-ink-faint">Hosting region</dt>
          <dd className="text-ink-soft">{posture.region ?? 'Not declared'}</dd>

          <dt className="text-ink-faint">Backup region</dt>
          <dd className="text-ink-soft">
            {posture.backup_region ?? 'Same as hosting'}
            {posture.backup_region && !posture.backup_in_region && (
              <span className="text-amber-700"> (out of region)</span>
            )}
          </dd>

          <dt className="text-ink-faint">Cross-border transfer</dt>
          <dd className="text-ink-soft">
            {posture.cross_border_transfer_allowed ? 'Permitted' : 'Not permitted'}
          </dd>

          <dt className="text-ink-faint">External AI processing</dt>
          <dd className="text-ink-soft">
            {posture.external_ai_may_leave_region ? 'May leave region' : 'None'}
          </dd>

          <dt className="text-ink-faint">Log retention</dt>
          <dd className="text-ink-soft">{posture.log_retention_days} days</dd>
        </dl>

        {posture.checked_at && (
          <p className="text-xs text-ink-faint mt-3">
            Reported live from the running system · {new Date(posture.checked_at).toLocaleString()}
          </p>
        )}
      </Card>
    </RevealItem>
  );
}

const SECTIONS = [
  {
    icon: Database, title: 'Tenant isolation',
    points: [
      'Every customer is a separate tenant with its own data boundary.',
      'PostgreSQL Row-Level Security (FORCE RLS, non-owner role) enforces isolation at the database — an app bug cannot leak across tenants.',
      'Proven by an automated isolation test.',
    ],
  },
  {
    icon: UserCheck, title: 'Access control',
    points: [
      'JWT (Bearer or httpOnly cookie) auth with optional TOTP two-factor + backup codes.',
      'Role-based access scoped region → store, enforced server-side on every endpoint.',
      'Sage AI is read-only, tenant- and RBAC-scoped, and injection-resistant.',
    ],
  },
  {
    icon: ScrollText, title: 'Audit & privacy (PDPL readiness)',
    points: [
      'Sensitive actions are recorded per tenant and exportable as CSV/JSON for evidence.',
      'Data export (portability) and human-approved deletion (erasure) on request.',
      'No passwords, tokens, full API keys, or payment details are ever logged.',
    ],
    links: [{ href: '/audit', label: 'Audit log' }, { href: '/settings', label: 'Data rights' }],
  },
  {
    icon: Server, title: 'Operations & resilience',
    points: [
      'Documented backup/restore and incident runbooks.',
      'Health/readiness checks, structured logs with request IDs.',
      'Secrets are environment-injected; production refuses default secrets.',
    ],
  },
  {
    icon: Lock, title: 'What we never do',
    points: [
      'Never sell or share customer data.',
      'Never auto-execute orders or money movement — actions are drafted and require human approval.',
      'No mandatory third-party data processors in the core product.',
    ],
  },
];

export default function TrustPage() {
  return (
    <main className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <PageHeader
          title="Trust & security"
          description="How your data is isolated, protected, and governed. Built for a UAE retailer's security review."
          icon={<ShieldCheck className="w-5 h-5" />}
        />

        <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 mb-6 text-sm text-amber-800">
          The security posture below is implemented and testable. Legal/compliance wording is a draft
          and requires review by a qualified UAE legal/tax professional before contractual use.
        </div>

        <Stagger className="space-y-4">
          <ResidencySection />
          {SECTIONS.map((s) => (
            <RevealItem key={s.title}>
              <Card padding="lg">
                <div className="flex items-center gap-2 mb-3">
                  <s.icon className="w-4 h-4 text-teal-600" />
                  <h3 className="text-sm font-semibold text-ink-soft uppercase tracking-wide">{s.title}</h3>
                </div>
                <ul className="space-y-1.5 text-sm text-ink-soft list-disc ms-5">
                  {s.points.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
                {s.links && (
                  <div className="flex flex-wrap gap-3 mt-3">
                    {s.links.map((l) => (
                      <Link key={l.href} href={l.href} className="text-sm text-teal-700 hover:text-teal-600">
                        {l.label} →
                      </Link>
                    ))}
                  </div>
                )}
              </Card>
            </RevealItem>
          ))}
        </Stagger>
      </div>
    </main>
  );
}
