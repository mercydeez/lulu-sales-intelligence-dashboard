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

export default function ResolveModal({ open, alert, onCancel, onConfirm }: ResolveModalProps) {
  const [notes, setNotes] = useState('');

  useEffect(() => {
    if (open) setNotes('');
  }, [open, alert?.id]);

  if (!alert) return null;

  return (
    <Modal open={open} onClose={onCancel} title="Resolve Alert">
      <div className="flex items-center gap-2 mb-4 text-coral-500">
        <CheckCircle className="w-5 h-5" />
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-ink font-medium">{alert.title}</p>
          <p className="text-sm text-ink-muted mt-1">{alert.message}</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-ink-soft mb-2" htmlFor="resolution-notes">
            Resolution notes (optional)
          </label>
          <textarea
            id="resolution-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="What was done to resolve this?"
            className="w-full py-3 px-4 rounded-2xl bg-surface border border-coral-100 text-ink placeholder-ink-muted shadow-sm transition-all focus:outline-none focus:ring-4 focus:ring-coral-500/15 focus:border-coral-400"
          />
        </div>
      </div>

      <div className="flex gap-3 mt-6">
        <Button variant="secondary" className="flex-1" onClick={onCancel}>Cancel</Button>
        <Button className="flex-1" onClick={() => onConfirm(notes)}>Mark Resolved</Button>
      </div>
    </Modal>
  );
}
