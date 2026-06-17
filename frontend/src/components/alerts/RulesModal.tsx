import { Settings } from 'lucide-react';
import { Badge, EmptyState, Modal } from '@/components/ui';
import { AlertRule, severityBadgeVariant } from './types';
import { formatDateTime } from './format';

export interface RulesModalProps {
  open: boolean;
  rules: AlertRule[];
  onClose: () => void;
}

export default function RulesModal({ open, rules, onClose }: RulesModalProps) {
  return (
    <Modal open={open} onClose={onClose} title="Alert Rules" size="lg">
      {rules.length === 0 ? (
        <EmptyState icon={<Settings className="w-7 h-7" />} title="No alert rules configured" />
      ) : (
        <div className="space-y-3 max-h-[60vh] overflow-y-auto">
          {rules.map((rule) => (
            <div
              key={rule.id}
              className={`p-4 rounded-2xl border ${rule.is_active ? 'border-teal-200 bg-teal-50/40' : 'border-coral-100 bg-coral-50/30'}`}
            >
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium text-ink">{rule.name}</h3>
                <Badge variant={rule.is_active ? 'success' : 'neutral'} size="sm">
                  {rule.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </div>
              <div className="text-sm text-ink-muted space-y-1">
                <p>Type: {rule.rule_type} · Action: {rule.action}</p>
                <p className="flex items-center gap-2">
                  Severity: <Badge variant={severityBadgeVariant[rule.severity]} size="sm">{rule.severity}</Badge>
                </p>
                {rule.last_triggered && (
                  <p className="text-xs">Last triggered: {formatDateTime(rule.last_triggered)}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
