'use client';

/**
 * UAE retail calendar for chart annotations (E4-7). One fetch per session
 * (module-level cache shared by every chart), auth-gated so it never fires
 * on public pages. Failure degrades to "no bands" — charts must render
 * identically if the calendar is unavailable.
 */
import { useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';

export interface UaeCalendarEvent {
  key: string;
  name: string;
  start: string; // YYYY-MM-DD
  end: string;   // YYYY-MM-DD
  approx?: boolean;
}

let cache: UaeCalendarEvent[] | null = null;
let inflight: Promise<UaeCalendarEvent[]> | null = null;

export function useUaeCalendar(): UaeCalendarEvent[] {
  const { isAuthenticated, authFetch } = useAuth();
  const [events, setEvents] = useState<UaeCalendarEvent[]>(cache ?? []);

  useEffect(() => {
    if (!isAuthenticated || cache) return;
    let active = true;
    inflight =
      inflight ??
      authFetch('/api/uae-intelligence/calendar')
        .then((r) => (r.ok ? r.json() : { calendar: [] }))
        .then((d) => {
          cache = (d.calendar ?? []) as UaeCalendarEvent[];
          return cache;
        })
        .catch(() => {
          inflight = null; // allow a retry on next mount
          return [] as UaeCalendarEvent[];
        });
    inflight.then((evts) => { if (active) setEvents(evts); });
    return () => { active = false; };
  }, [isAuthenticated, authFetch]);

  return events;
}
