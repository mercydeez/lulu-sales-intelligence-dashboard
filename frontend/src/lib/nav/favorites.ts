'use client';

/**
 * Nav favorites — client-only pinned routes, persisted to localStorage.
 *
 * A small, forward-looking module: the context rail / command palette can offer
 * a "Favorites" group later without any backend change (favorites are a personal
 * UI preference, not an authorization concern). SSR-safe: guarded on `window`.
 */
import { useCallback, useEffect, useState } from 'react';

const KEY = 'riq.nav.favorites.v1';

function read(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((x) => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function write(hrefs: string[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(hrefs));
    // Notify same-tab listeners (storage event only fires cross-tab).
    window.dispatchEvent(new CustomEvent('riq:favorites'));
  } catch {
    /* ignore quota / disabled storage */
  }
}

export function getFavorites(): string[] {
  return read();
}

export function isFavorite(href: string): boolean {
  return read().includes(href);
}

export function toggleFavorite(href: string): string[] {
  const cur = read();
  const next = cur.includes(href) ? cur.filter((h) => h !== href) : [...cur, href];
  write(next);
  return next;
}

/** Reactive favorites for components; stays in sync across tabs and same-tab writes. */
export function useFavorites(): {
  favorites: string[];
  isFavorite: (href: string) => boolean;
  toggle: (href: string) => void;
} {
  const [favorites, setFavorites] = useState<string[]>([]);

  useEffect(() => {
    setFavorites(read());
    const sync = () => setFavorites(read());
    window.addEventListener('storage', sync);
    window.addEventListener('riq:favorites', sync as EventListener);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener('riq:favorites', sync as EventListener);
    };
  }, []);

  const toggle = useCallback((href: string) => setFavorites(toggleFavorite(href)), []);
  return { favorites, isFavorite: (href) => favorites.includes(href), toggle };
}
