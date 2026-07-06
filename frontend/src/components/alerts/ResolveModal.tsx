import { useState, useEffect } from 'react';
import { CheckCircle } from 'lucide-react';
import { Modal, Button } from '@/components/ui';
import { Alert } from './types';

export interface ResolveModalProps {
  open: boolean;
  alert: Alert | null;
  onCancel: () => void;
  onConfirm: (notes: string) => void;
}

function recommendedAction(alert: Alert): string {
  if (alert.alert_type === 'expiry') {
    return 'Confirm the expiring batch has been checked, removed, discounted, transferred, or otherwise handled according to store policy.';
  }
  if (alert.alert_type === 'inventory') {
    return 'Confirm the stock issue has been checked and a replenishment, transfer, or supplier follow-up has been started.';
  }
  if (alert.alert_type === 'sales') {
    return 'Confirm the sales anomaly has been reviewed and any shelf, pricing, promotion, or returns issue has been handled.';
  }
  return 'Confirm the operational issue has been reviewed and handled before marking this alert resolved.';
}

export default function ResolveModal({ open, alert, onCancel, onConfirm }: ResolveModalProps) {
  const [notes, setNotes] = useState('');

  useEffect(() => {
    if (open) setNotes('');
  }, [open, alert?.id]);

  if (!alert) return null;

  return (
    <Modal open={open} onClose={onCancel} title="Confirm alert resolution">
      <div className="flex items-center gap-2 mb-4 text-coral-500">
        <CheckCircle className="w-5 h-5" />
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-ink font-medium">{alert.title}</p>
          <p className="text-sm text-ink-muted mt-1">{alert.message}</p>
          <p className="text-sm text-ink mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
            {recommendedAction(alert)}
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-ink-soft mb-2" htmlFor="resolution-notes">
            Resolution notes / action taken (optional)
          </label>
          <textarea
            id="resolution-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Example: removed expired batch from shelf and notified duty supervisor"
            className="w-full py-3 px-4 rounded-2xl bg-surface border border-line text-ink placeholder-ink-muted shadow-sm transition-all focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-400"
          />
        </div>
      </div>

      <div className="flex gap-3 mt-6">
        <Button variant="secondary" className="flex-1" onClick={onCancel}>Cancel</Button>
        <Button className="flex-1" onClick={() => onConfirm(notes)}>Confirm resolved after action</Button>
      </div>
    </Modal>
  );
}
