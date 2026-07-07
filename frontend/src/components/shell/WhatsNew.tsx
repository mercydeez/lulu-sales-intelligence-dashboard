'use client';

/**
 * What's-new panel (CX trust loop — Linear-style release notes in-app).
 * Sparkles button in the Topbar with an unread dot; the dot clears when the
 * panel is opened (localStorage last-seen keyed on the newest entry id).
 * Self-contained: owns its open state and click-outside handling so the
 * Topbar wiring stays a two-line change.
 */
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AnimatePresence, motion } from 'framer-motion';
import { Sparkles, Activity } from 'lucide-react';
import { Badge } from '@/components/ui';
import { useLanguage } from '@/contexts/LanguageContext';
import { CHANGELOG } from '@/data/changelog';
import { track } from '@/lib/telemetry';

const LAST_SEEN_KEY = 'whatsnew.lastSeen';

const tagVariant: Record<string, 'teal' | 'violet' | 'amber'> = {
  new: 'teal',
  improved: 'violet',
  fixed: 'amber',
};

export function WhatsNew() {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const latestId = CHANGELOG[0]?.id;

  useEffect(() => {
    if (!latestId) return;
    try {
      setUnread(window.localStorage.getItem(LAST_SEEN_KEY) !== latestId);
    } catch { /* private mode */ }
  }, [latestId]);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      if (next && latestId) {
        try { window.localStorage.setItem(LAST_SEEN_KEY, latestId); } catch { /* ignore */ }
        setUnread(false);
        track('whats_new_opened', { latest: latestId });
      }
      return next;
    });
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={toggle}
        aria-label={t('whatsnew.aria')}
        aria-expanded={open}
        className="relative p-2 rounded-lg text-ink-muted hover:text-ink hover:bg-surface-2 transition-all"
      >
        <Sparkles className="w-5 h-5" />
        {unread && (
          <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-teal-500" aria-hidden />
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.97 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="absolute right-0 mt-2 w-96 glass-strong rounded-xl shadow-2xl overflow-hidden z-50"
          >
            <div className="px-4 py-3 bg-surface-2 border-b border-line flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-teal-600" />
                <span className="font-semibold text-ink">{t('whatsnew.title')}</span>
              </div>
              <Link
                href="/status"
                onClick={() => setOpen(false)}
                className="flex items-center gap-1 text-xs text-teal-700 hover:text-teal-600 transition-colors"
              >
                <Activity className="w-3.5 h-3.5" />
                {t('whatsnew.viewStatus')}
              </Link>
            </div>

            <div className="max-h-96 overflow-y-auto">
              {CHANGELOG.length === 0 ? (
                <p className="p-6 text-center text-sm text-ink-muted">{t('whatsnew.empty')}</p>
              ) : (
                CHANGELOG.map((entry) => (
                  <div key={entry.id} className="px-4 py-3 border-b border-line last:border-b-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant={tagVariant[entry.tag] ?? 'neutral'} size="sm">{entry.tag}</Badge>
                      <p className="text-sm font-medium text-ink flex-1">{entry.title}</p>
                      <span className="text-[10px] text-ink-muted tabular-nums">{entry.date}</span>
                    </div>
                    <ul className="ms-1 space-y-1">
                      {entry.items.map((item, i) => (
                        <li key={i} className="text-xs text-ink-soft flex gap-2">
                          <span className="text-teal-600 mt-0.5" aria-hidden>·</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
