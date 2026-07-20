'use client';

/**
 * Contact governance — the restraint the system exercises on the customer's behalf.
 *
 * WHY THIS SURFACE EXISTS. Frequency caps, cooldowns and offer suppression have
 * been enforced since migration 076 and have never been visible anywhere in the
 * product. A marketer could not see the caps they were subject to, could not see
 * who had been suppressed, and could not see how often the system declined to
 * send. Enforcement you cannot inspect is enforcement you will not trust, and
 * the first thing an operator does with a system they do not trust is find a way
 * around it.
 *
 * THE FRAMING RULE. The suppressed count is presented as a FEATURE, not a loss.
 * Each suppression is a message a customer did not receive because they had
 * already heard enough. Rendered in warning colours with a downward arrow it
 * would read as lost reach, and the rational response to that framing is to
 * raise the caps until the number goes away — defeating the entire mechanism.
 * So it is styled neutrally and captioned explicitly.
 */
import { useCallback, useEffect, useState } from 'react';
import { BellOff, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
  Table, TableBody, TableHead, TableRow, Td, Th,
} from '@/components/ui';
import { Reveal, Stagger, StaggerItem, SyntheticBadge } from '@/components/flywheel/motion';
import { fetchGovernance } from '@/lib/flywheel';
import type { GovernanceOverview } from '@/types/flywheel';

const REASON_LABEL: Record<string, string> = {
  CONTACT_CAP_REACHED: 'Weekly contact cap reached',
  DAILY_CAP_REACHED: 'Daily cap reached',
  COOLDOWN_ACTIVE: 'In cooldown after ignored offers',
  NO_CONSENT: 'No marketing consent',
  LOWER_PRIORITY_CAMPAIGN: 'A higher-value campaign won this customer',
  LOWER_EIV: 'A higher-value offer won this customer',
};

/** Utilisation against a cap. Purely visual — never a reported number. */
function CapBar({ used, cap }: { used: number; cap: number }) {
  const ratio = cap > 0 ? Math.min(1, used / cap) : 0;
  const tone = ratio >= 0.9 ? 'var(--danger)' : ratio >= 0.6 ? 'var(--warning)' : 'var(--success)';
  return (
    <div className="h-2 w-full rounded bg-[var(--surface-2)] overflow-hidden">
      <div className="h-full rounded transition-all"
        style={{ width: `${ratio * 100}%`, background: tone }} />
    </div>
  );
}

export default function GovernancePage() {
  const [data, setData] = useState<GovernanceOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try { setData(await fetchGovernance()); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load governance'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-80" /></div>;
  }
  if (error) {
    return <div className="p-6"><ErrorState title="Governance unavailable" description={error} onRetry={load} /></div>;
  }

  const policies = data?.policies ?? [];
  const fatigue = data?.fatigue ?? [];
  const suppressions = data?.recent_suppressions ?? [];
  const byReason = data?.suppressions_by_reason ?? {};

  return (
    <div className="p-6">
      <PageHeader
        eyebrow="Flywheel"
        title="Contact governance"
        description="Caps belong to the customer, not the campaign. Three live campaigns each capped at two would otherwise contact the same person six times a week."
        icon={<ShieldCheck className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={load} aria-label="Refresh">
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        }
      />

      <Reveal>
        <Card padding="lg" className="mb-6">
          <div className="flex flex-wrap items-center justify-between gap-6">
            <div className="flex items-start gap-3">
              <BellOff className="w-5 h-5 mt-1 text-[var(--accent)] shrink-0" />
              <div>
                <div className="text-3xl font-semibold tabular-nums">
                  {data?.suppressed_30d ?? 0}
                </div>
                <div className="text-sm text-[var(--muted)]">
                  contacts withheld in the last 30 days
                </div>
              </div>
            </div>
            <p className="text-sm text-[var(--muted)] max-w-xl">
              {data?.interpretation}
            </p>
          </div>
        </Card>
      </Reveal>

      <Stagger>
        <StaggerItem>
          <Card padding="lg" className="mb-4">
            <h3 className="font-medium mb-3">Channel policy and current load</h3>
            {policies.length === 0 ? (
              <EmptyState title="No contact policy configured"
                description="Migration 076 seeds a default policy per channel." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Channel</Th><Th>Weekly cap</Th><Th>Daily cap</Th>
                      <Th>Cooldown</Th><Th>Sent (7d)</Th><Th>Reach (7d)</Th><Th>Load</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {policies.map((p) => (
                      <TableRow key={p.channel}>
                        <Td className="font-medium">
                          {p.channel}
                          {!p.is_active && <Badge variant="neutral" className="ml-2">inactive</Badge>}
                        </Td>
                        <Td className="tabular-nums">{p.max_per_week}</Td>
                        <Td className="tabular-nums">{p.max_per_day}</Td>
                        <Td className="tabular-nums">
                          {p.cooldown_days_after_ignores}d after {p.ignores_before_cooldown} ignores
                        </Td>
                        <Td className="tabular-nums">{p.volume.last_7d}</Td>
                        <Td className="tabular-nums">{p.volume.distinct_customers_7d}</Td>
                        <Td className="w-32">
                          <CapBar
                            used={p.volume.distinct_customers_7d
                              ? p.volume.last_7d / p.volume.distinct_customers_7d : 0}
                            cap={p.max_per_week}
                          />
                        </Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            <p className="text-xs text-[var(--muted)] mt-3">
              Load is average contacts per reached customer against the weekly cap — it shows
              whether the population is near its ceiling, which a raw send count cannot.
            </p>
          </Card>
        </StaggerItem>

        <StaggerItem>
          <Card padding="lg" className="mb-4">
            <h3 className="font-medium mb-1">Most-contacted customers</h3>
            <p className="text-sm text-[var(--muted)] mb-3">
              The people closest to over-contact. This is the list to check before
              launching another campaign into the same audience.
            </p>
            {fatigue.length === 0 ? (
              <EmptyState title="No fatigue signal"
                description="Nobody has received two or more contacts in the last 7 days." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow><Th>Customer</Th><Th>Contacts (7d)</Th><Th>Last contacted</Th></TableRow>
                  </TableHead>
                  <TableBody>
                    {fatigue.map((f) => (
                      <TableRow key={f.customer_id}>
                        <Td className="tabular-nums">#{f.customer_id}</Td>
                        <Td className="tabular-nums">{f.contacts_7d}</Td>
                        <Td className="text-[var(--muted)]">
                          {f.last_contact ? new Date(f.last_contact).toLocaleString() : '—'}
                        </Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </Card>
        </StaggerItem>

        <StaggerItem>
          <Card padding="lg">
            <h3 className="font-medium mb-1">Suppressions</h3>
            <p className="text-sm text-[var(--muted)] mb-3">
              When a customer qualifies for several live campaigns, exactly one wins. Every
              loser is recorded — a marketer whose campaign silently stops reaching people
              would never trust the system again.
            </p>

            {Object.keys(byReason).length > 0 ? (
              <div className="flex flex-wrap gap-2 mb-4">
                {Object.entries(byReason).map(([reason, count]) => (
                  <Badge key={reason} variant="neutral">
                    {REASON_LABEL[reason] ?? reason}: {count}
                  </Badge>
                ))}
              </div>
            ) : null}

            {suppressions.length === 0 ? (
              <EmptyState title="No suppressions recorded"
                description="No customer has been withheld from a campaign yet." />
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHead>
                    <TableRow>
                      <Th>Customer</Th><Th>Suppressed campaign</Th>
                      <Th>Won by</Th><Th>Reason</Th><Th>When</Th>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {suppressions.map((s, i) => (
                      <TableRow key={`${s.customer_id}-${i}`}>
                        <Td className="tabular-nums">#{s.customer_id}</Td>
                        <Td>{s.suppressed_campaign_name ?? `#${s.suppressed_campaign_id ?? '—'}`}</Td>
                        <Td className="text-[var(--muted)]">
                          {s.winning_campaign_name ?? (s.winning_campaign_id ? `#${s.winning_campaign_id}` : '—')}
                        </Td>
                        <Td>
                          <Badge variant="neutral">
                            {REASON_LABEL[s.reason_code] ?? s.reason_code}
                          </Badge>
                        </Td>
                        <Td className="text-[var(--muted)]">
                          {s.created_at ? new Date(s.created_at).toLocaleString() : '—'}
                        </Td>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </Card>
        </StaggerItem>
      </Stagger>

      <div className="mt-6 flex items-start gap-2 text-xs text-[var(--muted)] max-w-3xl">
        <Users className="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          Consent is re-checked at issue time, not at audience build. An audience assembled on
          Monday and executed on Friday must not contact someone who revoked consent on
          Wednesday.
        </span>
      </div>
    </div>
  );
}
