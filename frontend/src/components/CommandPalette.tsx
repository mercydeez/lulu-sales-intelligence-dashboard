'use client';

/**
 * Command palette (Part III-H) — Cmd/Ctrl-K to jump anywhere or fire a quick
 * action. Sources its commands from the nav (role-filtered) plus a couple of
 * procurement shortcuts.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search, CornerDownLeft } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { navItems } from '@/components/shell/Sidebar';

interface Command { label: string; href: string; hint?: string; }

export default function CommandPalette() {
  const router = useRouter();
  const { hasRole, hasPermission, isAuthenticated } = useAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Toggle on Cmd/Ctrl-K; close on Esc.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

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

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? commands.filter((c) => c.label.toLowerCase().includes(q)) : commands;
  }, [query, commands]);

  const run = useCallback((c: Command) => { setOpen(false); router.push(c.href); }, [router]);

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter' && results[active]) { e.preventDefault(); run(results[active]); }
  };

  if (!isAuthenticated || !open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[12vh] bg-black/30 backdrop-blur-sm"
      onClick={() => setOpen(false)}>
      <div className="w-full max-w-lg mx-4 rounded-2xl bg-surface border border-line shadow-card overflow-hidden"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-4 border-b border-line">
          <Search className="w-5 h-5 text-ink-muted shrink-0" />
          <input ref={inputRef} value={query} onChange={(e) => { setQuery(e.target.value); setActive(0); }}
            onKeyDown={onInputKey} placeholder="Search pages and actions…"
            className="flex-1 py-3.5 bg-transparent text-ink outline-none text-sm" />
          <kbd className="text-[10px] text-ink-muted border border-line rounded px-1.5 py-0.5">ESC</kbd>
        </div>
        <div className="max-h-80 overflow-y-auto py-2">
          {results.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-ink-muted">No matches.</p>
          ) : results.map((c, i) => (
            <button key={c.href + c.label} onClick={() => run(c)} onMouseEnter={() => setActive(i)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left ${i === active ? 'bg-[#faf3ee]' : ''}`}>
              <span className="text-[10px] uppercase tracking-wide text-ink-muted w-12 shrink-0">{c.hint}</span>
              <span className="flex-1 text-ink">{c.label}</span>
              {i === active && <CornerDownLeft className="w-4 h-4 text-ink-muted" />}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
