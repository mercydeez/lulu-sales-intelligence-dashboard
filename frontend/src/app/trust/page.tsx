'use client';

import Link from 'next/link';
import { PageHeader, Card, Stagger, RevealItem } from '@/components/ui';
import { ShieldCheck, Lock, ScrollText, UserCheck, Database, Server } from 'lucide-react';

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
