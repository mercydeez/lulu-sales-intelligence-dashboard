'use client';

import { useState } from 'react';
import { MailWarning, Loader2, Check } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';

/** Slim banner prompting unverified users to confirm their email. Hidden once
 * verified (the backend defaults existing/demo users to verified, so it only
 * shows for fresh self-serve signups). */
export default function VerifyEmailBanner() {
  const { user, authFetch } = useAuth();
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  // `email_verified` may be absent on older cached user objects → treat as verified.
  const verified = (user as { email_verified?: boolean })?.email_verified !== false;
  if (!user || verified) return null;

  const resend = async () => {
    setBusy(true);
    try {
      const res = await authFetch('/api/auth/resend-verification', { method: 'POST' });
      if (res.ok) setSent(true);
    } finally { setBusy(false); }
  };

  return (
    <div className="flex items-center gap-3 px-4 md:px-6 py-2.5 bg-amber-50 border-b border-amber-200 text-sm">
      <MailWarning className="w-4 h-4 text-amber-600 shrink-0" />
      <span className="text-amber-800 flex-1">
        Please verify your email{user.email ? ` (${user.email})` : ''} to secure your account.
      </span>
      {sent ? (
        <span className="inline-flex items-center gap-1.5 text-teal-700 font-medium">
          <Check className="w-4 h-4" /> Sent — check your inbox
        </span>
      ) : (
        <button
          onClick={resend}
          disabled={busy}
          className="inline-flex items-center gap-1.5 font-medium text-amber-800 hover:text-amber-900 underline disabled:opacity-60"
        >
          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          Resend verification
        </button>
      )}
    </div>
  );
}
