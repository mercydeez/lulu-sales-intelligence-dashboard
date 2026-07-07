'use client';

/**
 * Free-form product feedback (CX feedback loop — Y6). Opened from the Topbar
 * user menu; posts to /api/feedback (migration 051) so the customer's voice
 * has a durable, tenant-scoped home — not a mailto and not just telemetry.
 */
import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { Modal, Button, useToast } from '@/components/ui';
import { apiPost } from '@/lib/apiClient';
import { track } from '@/lib/telemetry';
import { MessageSquarePlus } from 'lucide-react';

export interface FeedbackDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function FeedbackDialog({ open, onClose }: FeedbackDialogProps) {
  const pathname = usePathname();
  const { show } = useToast();
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!comment.trim() || busy) return;
    setBusy(true);
    try {
      await apiPost('/api/feedback', { kind: 'feedback', comment: comment.trim(), page: pathname });
      track('feedback_submitted', { page: pathname ?? undefined });
      show('Thanks — your feedback went straight to the team.', { variant: 'success' });
      setComment('');
      onClose();
    } catch {
      show('Could not send feedback. Please try again.', { variant: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Send feedback" size="md">
      <p className="text-sm text-ink-muted mb-3">
        What&apos;s working, what&apos;s missing, what&apos;s annoying — it lands directly with the people building this.
      </p>
      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={5}
        maxLength={4000}
        placeholder="Tell us anything…"
        className="w-full rounded-xl bg-surface border border-line text-ink placeholder-ink-muted p-3 text-sm focus:outline-none focus:ring-4 focus:ring-teal-500/15 focus:border-teal-500 transition-all resize-y"
      />
      <div className="mt-4 flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button size="sm" onClick={submit} disabled={busy || !comment.trim()}>
          <MessageSquarePlus className="w-4 h-4" />
          {busy ? 'Sending…' : 'Send feedback'}
        </Button>
      </div>
    </Modal>
  );
}
