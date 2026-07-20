'use client';

/**
 * Models & honesty.
 *
 * This page exists to state limitations as prominently as capabilities. A
 * retention product that shows a churn score without showing what produced it,
 * on what data, with what calibration, is asking to be trusted rather than
 * earning it.
 *
 * The metric emphasis is deliberate: PR-AUC over ROC-AUC (churn is imbalanced),
 * Brier over accuracy (the optimizer multiplies by probability, so calibration
 * matters more than ranking), and Qini for uplift (outcome AUC is the wrong
 * question entirely).
 */
import { useCallback, useEffect, useState } from 'react';
import { Brain, RefreshCw } from 'lucide-react';
import {
  Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton,
} from '@/components/ui';
import { Reveal, Stagger, StaggerItem, SyntheticBadge } from '@/components/flywheel/motion';
import { fetchModels } from '@/lib/flywheel';
import type { ModelVersion } from '@/types/flywheel';

/** What each metric actually tells you — shown inline, not in a footnote. */
const METRIC_HELP: Record<string, string> = {
  pr_auc: 'Precision-recall AUC — the right headline for imbalanced churn data',
  roc_auc: 'ROC AUC — flattering on imbalanced data; read PR-AUC first',
  brier: 'Brier score — calibration. Lower is better; this drives spend accuracy',
  precision: 'Of those flagged, how many actually churned',
  recall: 'Of those who churned, how many we flagged',
  qini: 'Qini coefficient — does the uplift ranking carry real information',
  auuc: 'Area under the uplift curve',
  base_rate: 'Share of the population that actually churned',
};

const KIND_LABEL: Record<string, string> = {
  churn: 'Churn risk',
  uplift: 'Offer uplift',
  sequence: 'Sequence model (GRU)',
  tabular_dl: 'Tabular deep learning (FT-Transformer)',
  ensemble: 'Calibrated ensemble',
};

export default function ModelsPage() {
  const [models, setModels] = useState<ModelVersion[]>([]);
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await fetchModels();
      setModels(result.models);
      setNote(result.honesty_note);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load models');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return <div className="p-6 space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-64" /></div>;
  }
  if (error) {
    return <div className="p-6"><ErrorState title="Models unavailable" description={error} onRetry={load} /></div>;
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <PageHeader
        eyebrow="Flywheel"
        title="Models & honesty"
        description="What is scoring your customers, how well it does it, and what it is not entitled to claim."
        icon={<Brain className="w-5 h-5" />}
        actions={
          <div className="flex items-center gap-2">
            <SyntheticBadge />
            <Button variant="ghost" onClick={load} aria-label="Refresh"><RefreshCw className="w-4 h-4" /></Button>
          </div>
        }
      />

      <Reveal>
        <Card padding="lg" className="mb-6 border-amber-200 dark:border-amber-500/30">
          <h2 className="text-sm font-semibold text-amber-900 dark:text-amber-300">
            What these numbers do and do not mean
          </h2>
          <ul className="mt-3 space-y-2 text-xs text-slate-600 dark:text-slate-400">
            <li>
              <strong className="text-slate-800 dark:text-slate-200">The data is synthetic.</strong>{' '}
              Customers, events and outcomes are generated with a fixed seed. Metrics describe
              performance on that synthetic holdout and say nothing about real-world accuracy.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">Trees usually win on tabular data.</strong>{' '}
              A calibrated gradient-boosted baseline is the reference model. Deep learning is applied
              where it genuinely earns its place — over the ordered event sequence, which a flattened
              snapshot discards — and is reported honestly even when it loses.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">Calibration matters more than ranking here.</strong>{' '}
              The optimizer multiplies probability by customer value, so a model that ranks well but
              is overconfident will systematically overspend. That is why Brier score sits beside PR-AUC.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">No sensitive attributes are used.</strong>{' '}
              Gender, ethnicity, religion and nationality are neither stored nor used as features or
              offer-decision inputs. Every feature is behavioural.
            </li>
            <li>
              <strong className="text-slate-800 dark:text-slate-200">A model never moves money.</strong>{' '}
              Scores are proposals. Every action that touches budget or stock passes through a
              deterministic, policy-checked service with an audit trail.
            </li>
          </ul>
        </Card>
      </Reveal>

      {models.length === 0 ? (
        <Card padding="lg">
          <EmptyState title="No models registered"
                      description="Score churn from the Flywheel command centre — the deterministic rule-based scorer registers itself on first use." />
        </Card>
      ) : (
        <Stagger className="space-y-4">
          {models.map((model) => (
            <StaggerItem key={model.id}>
              <Card padding="lg">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {KIND_LABEL[model.kind] ?? model.kind}
                      </h2>
                      {model.is_active && <Badge variant="success">active</Badge>}
                      <Badge variant={model.algorithm === 'rule_based' ? 'neutral' : 'violet'}>
                        {model.algorithm.replace(/_/g, ' ')}
                      </Badge>
                    </div>
                    <p className="mt-1 font-mono text-[11px] text-slate-500">{model.version}</p>
                  </div>
                  <div className="text-right text-[11px] text-slate-500">
                    <p>seed {model.random_seed}</p>
                    <p>
                      features {model.feature_window_days}d → outcome {model.outcome_window_days}d
                    </p>
                    {model.trained_at && <p>trained {new Date(model.trained_at).toLocaleDateString()}</p>}
                  </div>
                </div>

                {model.notes && (
                  <p className="mt-3 text-xs text-slate-600 dark:text-slate-400">{model.notes}</p>
                )}

                {Object.keys(model.metrics).length > 0 ? (
                  <dl className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
                    {Object.entries(model.metrics).map(([key, value]) => (
                      <div key={key} className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50">
                        <dd className="font-mono text-lg text-slate-900 dark:text-slate-100">
                          {typeof value === 'number' ? value.toFixed(4) : String(value)}
                        </dd>
                        <dt className="text-[11px] font-medium text-slate-600 dark:text-slate-400">
                          {key.replace(/_/g, ' ')}
                        </dt>
                        {METRIC_HELP[key] && (
                          <p className="mt-0.5 text-[10px] leading-tight text-slate-400">
                            {METRIC_HELP[key]}
                          </p>
                        )}
                      </div>
                    ))}
                  </dl>
                ) : (
                  <p className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-800/50">
                    No metrics recorded — this is the deterministic fallback tier. It is not fitted to
                    data, so it has no holdout score. It exists so scoring never hard-depends on a
                    trained artifact being present and loadable.
                  </p>
                )}
              </Card>
            </StaggerItem>
          ))}
        </Stagger>
      )}

      <p className="mt-6 text-xs text-slate-400">{note}</p>
    </div>
  );
}
