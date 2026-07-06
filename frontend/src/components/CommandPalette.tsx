'use client';

/**
 * Command palette (Part III-H) — Cmd/Ctrl-K to jump anywhere or fire a quick
 * action. Sources its commands from the nav (role-filtered) plus a couple of
 * procurement shortcuts.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { Search, CornerDownLeft } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { navItems } from '@/config/nav';

interface Command { label: string; href: string; hint?: string; }

// "g then <key>" jump targets. d/b/i only fire when the role's nav actually
// carries the page; t (Today, the role homepage) is available to every role.
const GO_SEQUENCES: Record<string, string> = {
  t: '/today', d: '/decisions', b: '/briefing', i: '/insights',
};

/** True when the key event happens inside a text-entry control. */
function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

export default function CommandPalette() {
  const router = useRouter();
  const { hasRole, hasPermission, isAuthenticated, authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [live, setLive] = useState<Command[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const openRef = useRef(false);
  openRef.current = open;
  const allowedHrefsRef = useRef<Set<string>>(new Set());
  const pendingG = useRef<number>(0); // timestamp of an armed "g", 0 = disarmed

  // Toggle on Cmd/Ctrl-K; close on Esc; "g then t/d/b/i" jumps (Gmail-style).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
        pendingG.current = 0;
        return;
      }
      if (e.key === 'Escape') {
        setOpen(false);
        pendingG.current = 0;
        return;
      }
      // Sequence shortcuts: plain keys only, never while typing or in the palette.
      if (e.metaKey || e.ctrlKey || e.altKey || openRef.current || isTyping(e)) return;
      if (e.key === 'g') {
        pendingG.current = Date.now();
        return;
      }
      if (pendingG.current && Date.now() - pendingG.current < 1500) {
        const href = GO_SEQUENCES[e.key];
        pendingG.current = 0;
        if (href && (href === '/today' || allowedHrefsRef.current.has(href))) {
          e.preventDefault();
          router.push(href);
        }
        return;
      }
      pendingG.current = 0;
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [router]);

  useEffect(() => { if (open) { setQuery(''); setActive(0); setTimeout(() => inputRef.current?.focus(), 20); } }, [open]);

  const commands: Command[] = useMemo(() => {
    const nav = navItems
      .filter((i) => (!i.roles || hasRole(i.roles)) && (!i.permission || hasPermission(i.permission)))
      .map((i) => ({ label: i.label, href: i.href, hint: 'Go to' }));
    const extra: Command[] = [];
    if (hasPermission('can_manage_inventory')) {
      extra.push({ label: 'Generate POs from forecast', href: '/procurement', hint: 'Action' });
      extra.push({ label: 'Review approval inbox', href: '/approvals', hint: 'Action' });
    }
    return [...nav, ...extra];
  }, [hasRole, hasPermission]);

  // The g-shortcuts respect the same role filtering as the palette itself.
  useEffect(() => {
    allowedHrefsRef.current = new Set(commands.map((c) => c.href));
  }, [commands]);

  // Live entity search (stores + items) — debounced, tenant-scoped via the API.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setLive([]); return; }
    const id = setTimeout(async () => {
      try {
        const res = await authFetch(`/api/search?q=${encodeURIComponent(q)}`);
        if (!res.ok) return;
        const data = await res.json();
        setLive((data.results || []).map((r: { title: string; href: string; type: string; subtitle?: string }) => ({
          label: r.subtitle ? `${r.title} · ${r.subtitle}` : r.title,
          href: r.href,
          hint: r.type,
        })));
      } catch { /* keep prior */ }
    }, 180);
    return () => clearTimeout(id);
  }, [query, authFetch]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pages = q ? commands.filter((c) => c.label.toLowerCase().includes(q)) : commands;
    return [...pages, ...live];
  }, [query, commands, live]);

  const run = useCallback((c: Command) => { setOpen(false); router.push(c.href); }, [router]);

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter' && results[active]) { e.preventDefault(); run(results[active]); }
  };

  if (!isAuthenticated) return null;

  return (
    <AnimatePresence>
    {open && (
    <motion.div className="fixed inset-0 z-[100] flex items-start justify-center pt-[12vh] bg-black/30 backdrop-blur-sm"
      onClick={() => setOpen(false)}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
      <motion.div className="w-full max-w-lg mx-4 rounded-2xl bg-surface border border-line shadow-card overflow-hidden"
        onClick={(e) => e.stopPropagation()}
        initial={{ opacity: 0, scale: 0.96, y: -12 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.97, y: -8 }} transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
        <div className="flex items-center gap-3 px-4 border-b border-line">
          <Search className="w-5 h-5 text-ink-muted shrink-0" />
          <input ref={inputRef} value={query} onChange={(e) => { setQuery(e.target.value); setActive(0); }}
            onKeyDown={onInputKey} placeholder="Search pages, stores, items…"
            className="flex-1 py-3.5 bg-transparent text-ink outline-none text-sm" />
          <kbd className="text-[10px] text-ink-muted border border-line rounded px-1.5 py-0.5">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-2">
          {results.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-ink-muted">No matches.</p>
          ) : results.map((c, i) => (
            <button key={c.href + c.label} onClick={() => run(c)} onMouseEnter={() => setActive(i)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm text-start transition-colors ${i === active ? 'bg-surface-2' : ''}`}>
              <span className="text-[10px] uppercase tracking-wide text-ink-muted w-12 shrink-0">{c.hint}</span>
              <span className="flex-1 text-ink">{c.label}</span>
              {i === active && <CornerDownLeft className="w-4 h-4 text-ink-muted" />}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 px-4 py-2 border-t border-line text-[11px] text-ink-muted">
          <span><kbd className="border border-line rounded px-1">↑↓</kbd> navigate</span>
          <span><kbd className="border border-line rounded px-1">↵</kbd> open</span>
          <span className="ms-auto">Tip: <kbd className="border border-line rounded px-1">g</kbd> then <kbd className="border border-line rounded px-1">d</kbd> jumps to Decisions (t/b/i too)</span>
        </div>
      </motion.div>
    </motion.div>
    )}
    </AnimatePresence>
  );
}
