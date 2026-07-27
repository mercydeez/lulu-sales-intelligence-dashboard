'use client';

import { useEffect, useState, useRef } from 'react';
import { authFetch } from '@/contexts/AuthContext';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Reconnect backoff: retry fast on the first blip, then back off. A flat 5s meant
// every transient drop cost a full 5 seconds of dead stream.
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 8000;

// Keep a channel open briefly after its last subscriber unmounts. Leaving a live
// page and coming back used to tear the EventSource down and redo the entire
// handshake on return — an awaited POST /api/auth/stream-ticket, then the SSE
// connect — which is what made those tab switches feel slow. Inside this window
// the existing connection is simply reused.
const STREAM_LINGER_MS = 30000;

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
  /** pending teardown while the channel lingers with no subscribers */
  idleTimer: ReturnType<typeof setTimeout> | null;
  /** consecutive failed opens, for backoff; reset on a successful connect */
  retryAttempt: number;
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
      idleTimer: null,
      retryAttempt: 0,
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

/** Full teardown. Only runs once the linger window expires with no subscribers. */
function closeConn(c: Conn) {
  if (c.reconnectTimer) {
    clearTimeout(c.reconnectTimer);
    c.reconnectTimer = null;
  }
  if (c.idleTimer) {
    clearTimeout(c.idleTimer);
    c.idleTimer = null;
  }
  if (c.es) {
    c.es.close();
    c.es = null;
  }
  c.isConnected = false;
  c.error = null;
  c.attached.clear();
  c.opening = false;
  c.retryAttempt = 0;
}

/** Exponential backoff, capped. Never schedules once the channel is unused. */
function scheduleReconnect(c: Conn) {
  if (c.reconnectTimer || c.refCount === 0) return;
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** c.retryAttempt, RECONNECT_MAX_MS);
  c.retryAttempt += 1;
  c.reconnectTimer = setTimeout(() => {
    c.reconnectTimer = null;
    void openConnection(c);
  }, delay);
}

/**
 * Close every channel immediately, ignoring the linger window. Called on logout
 * so no stream outlives the session it was authorized under. Wired via a window
 * event rather than an import from AuthContext, which would be a cycle (this
 * module already imports authFetch from there).
 */
export function closeAllEventStreams() {
  conns.forEach((c) => {
    c.refCount = 0;
    closeConn(c);
    notifyStatus(c);
  });
}

if (typeof window !== 'undefined') {
  window.addEventListener('auth:logout', () => closeAllEventStreams());
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
      c.retryAttempt = 0;
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
      scheduleReconnect(c);
    };

    c.opening = false;
  } catch (err: any) {
    c.opening = false;
    c.isConnected = false;
    c.error = err?.message || 'Connection failed. Reconnecting…';
    notifyStatus(c);
    scheduleReconnect(c);
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

    // A channel lingering from a recent unmount is still live: cancel its pending
    // teardown and reuse it. This is what makes navigating back to a live page
    // instant instead of re-running the ticket + connect handshake.
    if (c.idleTimer) {
      clearTimeout(c.idleTimer);
      c.idleTimer = null;
    }

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
        // Don't tear down yet — linger, so a quick navigation away and back
        // reuses this connection. Teardown only happens if nobody re-subscribes
        // before the window expires.
        if (c.idleTimer) clearTimeout(c.idleTimer);
        c.idleTimer = setTimeout(() => {
          c.idleTimer = null;
          if (c.refCount === 0) closeConn(c);
        }, STREAM_LINGER_MS);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint]);

  return { isConnected, error };
}
