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
          openCo