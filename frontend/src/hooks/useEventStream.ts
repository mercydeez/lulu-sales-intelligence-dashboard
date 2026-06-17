'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { authFetch } from '@/contexts/AuthContext';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface UseEventStreamOptions {
  eventHandlers: Record<string, (data: any) => void>;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export function useEventStream(endpoint: string | null, options: UseEventStreamOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const optionsRef = useRef(options);
  
  // Keep options updated to avoid re-running effect on handler changes
  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const connect = useCallback(async () => {
    if (!endpoint) {
      setIsConnected(false);
      return;
    }

    // Clear any existing connections or reconnect timers
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    try {
      // 1. Get a short-lived ticket
      const ticketRes = await authFetch('/api/auth/stream-ticket', { method: 'POST' });
      if (!ticketRes.ok) {
        throw new Error(`Failed to obtain stream ticket: ${ticketRes.statusText}`);
      }
      
      const { ticket } = await ticketRes.json();
      
      // 2. Establish SSE connection with the ticket
      const url = `${API_URL}${endpoint}${endpoint.includes('?') ? '&' : '?'}ticket=${ticket}`;
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      // 3. Setup standard listeners
      eventSource.onopen = () => {
        setIsConnected(true);
        setError(null);
        if (optionsRef.current.onConnect) {
          optionsRef.current.onConnect();
        }
      };

      // 4. Setup custom event handlers
      Object.entries(optionsRef.current.eventHandlers).forEach(([eventName, handler]) => {
        eventSource.addEventListener(eventName, (event: MessageEvent) => {
          try {
            const parsedData = JSON.parse(event.data);
            handler(parsedData);
          } catch (err) {
            console.error(`Failed to parse SSE event [${eventName}]:`, err);
            // Fallback: pass raw string data if parsing fails
            handler(event.data);
          }
        });
      });

      // 5. Handle errors and reconnects
      eventSource.onerror = () => {
        setIsConnected(false);
        setError('Connection lost. Reconnecting...');
        if (optionsRef.current.onDisconnect) {
          optionsRef.current.onDisconnect();
        }
        eventSource.close();
        eventSourceRef.current = null;

        // Schedule reconnection with a fresh ticket after 5 seconds
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, 5000);
      };

    } catch (err: any) {
      console.error(`SSE connection to ${endpoint} failed:`, err);
      setIsConnected(false);
      setError(err.message || 'Authentication failed. Reconnecting...');
      
      // Schedule reconnection with a fresh ticket after 5 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 5000);
    }
  }, [endpoint]);

  useEffect(() => {
    connect();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

  return { isConnected, error };
}
