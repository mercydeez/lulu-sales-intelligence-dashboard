'use client';

import { useEffect, useState, useRef } from 'react';
import { authFetch } from '@/contexts/AuthContext';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const RECONNECT_MS = 5000;

type Handler = (data: any) => void;

interface UseEventStreamOptions {
  eventHandlers: Record<string, Handler>;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

/**
 * Shared SSE connection manager.
 *
 * Multiple components asking for the same channel (e.g. several widgets all
 * watching `/stream/sales`) now share ONE EventSource instead of opening one
 * each. Browsers cap ~6 concurrent HTTP/1.1 connections per origin, so the old
 * per-component approach exhausted the pool (made worse by React StrictMode
 * double-mounting in dev), leaving streams stuck in a connect/timeout/retry
 * loop. One connection per channel, fanned out to all subscribers, fixes it.
 */
interface Conn {
  endpoint: string;
  es: EventSource | null;
  refCount: number;
  isConnected: boolean;
  error: string | null;
  /** eventName -> set of subscriber handlers */
  handlers: Map<string, Set<Handler>>;
  /** eventNames that currently have a live addEventListener on `es` */
  attached: Set<string>;
  /** components listening for connection-status changes */
  statusListeners: Set<() => void>;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  opening: boolean;
}

const conns = new Map<string, Conn>();

function getConn(endpoint: string): Conn {
  let c = conns.get(endpoint);
  if (!c) {
    c = {
      endpoint,
      es: null,
      refCount: 0,
      isConnected: false,
      error: null,
      handlers: new Map(),
      attached: new Set(),
      statusListeners: new Set(),
      reconnectTimer: null,
      opening: false,
    };
    conns.set(endpoint, c);
  }
  return c;
}

function notifyStatus(c: Conn) {
  c.statusListeners.forEach((fn) => fn());
}

/** Attach a DOM listener for one event name that fans out to all handlers. */
function attachEvent(c: Conn, eventName: string) {
  if (!c.es || c.attached.has(eventName)) return;
  c.attached.add(eventName);
  c.es.addEventListener(eventName, (event: MessageEvent) => {
    const set = c.handlers.get(eventName);
    if (!set || set.size === 0) return;
    let payload: any = event.data;
    try {
      payload = JSON.parse(event.data);
    } catch {
      /* pass raw string if not JSON */
    }
    set.forEach((h) => {
      try {
        h(payload);
      } catch (err) {
        console.error(`SSE handler error [${eventName}]`, err);
      }
    });
  });
}

async function openConnection(c: Conn) {
  if (c.opening || c.es || c.refCount === 0) return;
  c.opening = true;
  try {
    const ticketRes = await authFetch('/api/auth/stream-ticket', { method: 'POST' });
    if (!ticketRes.ok) throw new Error(`stream ticket ${ticketRes.status}`);
    const { ticket } = await ticketRes.json();

    // refCount may have dropped to 0 while awaiting the ticket
    if (c.refCount === 0) {
      c.opening = false;
      return;
    }

    const url = `${API_URL}${c.endpoint}${c.endpoint.includes('?') ? '&' : '?'}ticket=${ticket}`;
    const es = new EventSource(url);
    c.es = es;

    es.onopen = () => {
      c.isConnected = true;
      c.error = null;
      notifyStatus(c);
    };

    // (re)attach listeners for every event name currently subscribed
    c.attached.clear();
    for (const eventName of c.handlers.keys()) attachEvent(c, eventName);

    es.onerror = () => {
      c.isConnected = false;
      c.error = 'Connection lost. Reconnecting…';
      notifyStatus(c);
      es.close();
      c.es = null;
      c.attached.clear();
      if (c.reconnectTimer) clearTimeout(c.reconnectTimer);
      if (c.refCount > 0) {
        c.reconnectTimer = setTimeout(() => {
          c.reconnectTimer = null;
          openConnection(c);
        }, RECONNECT_MS);
      }
    };

    c.opening = false;
  } catch (err: any) {
    c.opening = false;
    c.isConnected = false;
    c.error = err?.message || 'Connection failed. Reconnecting…';
    notifyStatus(c);
    if (c.reconnectTimer) clearTimeout(c.reconnectTimer);
    if (c.refCount > 0) {
      c.reconnectTimer = setTimeout(() => {
        c.reconnectTimer = null;
        openConnection(c);
      }, RECONNECT_MS);
    }
  }
}

export function useEventStream(
  endpoint: string | null,
  { eventHandlers, onConnect, onDisconnect }: UseEventStreamOptions,
) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Keep the latest callbacks without forcing a re-subscribe each render.
  const handlersRef = useRef(eventHandlers);
  handlersRef.current = eventHandlers;
  const onConnectRef = useRef(onConnect);
  onConnectRef.current = onConnect;
  const onDisconnectRef = useRef(onDisconnect);
  onDisconnectRef.current = onDisconnect;

  useEffect(() => {
    if (!endpoint) {
      setIsConnected(false);
      setError(null);
      return;
    }

    const c = getConn(endpoint);
    c.refCount += 1;

    // Register a STABLE wrapper per event that dispatches to the LATEST handler
    // via handlersRef (refreshed every render). Registering the concrete closure
    // captured here would freeze consumers on their first-render state, since this
    // effect only re-runs when `endpoint` changes — so a handler that closes over
    // component state (active tab, filters, page) would forever see render-0 values.
    const mine: Array<[string, Handler]> = [];
    for (const eventName of Object.keys(handlersRef.current)) {
      let set = c.handlers.get(eventName);
      if (!set) {
        set = new Set();
        c.handlers.set(eventName, set);
      }
      const wrapper: Handler = (payload) => handlersRef.current[eventName]?.(payload);
      set.add(wrapper);
      mine.push([eventName, wrapper]);
      attachEvent(c, eventName);
    }

    let wasConnected = false;
    const onStatus = () => {
      setIsConnected(c.isConnected);
      setError(c.error);
      if (c.isConnected && !wasConnected) {
        wasConnected = true;
        onConnectRef.current?.();
      } else if (!c.isConnected && wasConnected) {
        wasConnected = false;
        onDisconnectRef.current?.();
      }
    };
    c.statusListeners.add(onStatus);
    onStatus();

    void openConnection(c);

    return () => {
      c.statusListeners.delete(onStatus);
      for (const [eventName, handler] of mine) {
        const set = c.handlers.get(eventName);
        if (set) {
          set.delete(handler);
          if (set.size === 0) c.handlers.delete(eventName);
        }
      }
      c.refCount -= 1;
      if (c.refCount <= 0) {
        c.refCount = 0;
        if (c.reconnectTimer) {
          clearTimeout(c.reconnectTimer);
          c.reconnectTimer = null;
        }
        if (c.es) {
          c.es.close();
          c.es = null;
        }
        c.isConnected = false;
        c.error = null;
        c.attached.clear();
        c.opening = false;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint]);

  return { isConnected, error };
}
