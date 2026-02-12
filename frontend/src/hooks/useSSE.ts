'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { Sale } from '@/types';

const SSE_URL = process.env.NEXT_PUBLIC_SSE_URL || 'http://localhost:8000/api/stream';

export function useSSE() {
  const [streamingSales, setStreamingSales] = useState<Sale[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    
    const eventSource = new EventSource(SSE_URL);
    eventSourceRef.current = eventSource;
    
    eventSource.onopen = () => {
      setIsConnected(true);
      setError(null);
    };
    
    eventSource.addEventListener('new_sale', (event) => {
      try {
        const sale: Sale = JSON.parse(event.data);
        setStreamingSales((prev: Sale[]) => [sale, ...prev.slice(0, 99)]);
      } catch (e) {
        console.error('Failed to parse SSE data:', e);
      }
    });
    
    eventSource.onerror = () => {
      setIsConnected(false);
      setError('Connection lost. Reconnecting...');
      eventSource.close();
      
      // Reconnect after 5 seconds
      reconnectTimeoutRef.current = setTimeout(() => {
        connect();
      }, 5000);
    };
  }, []);
  
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
  
  return { streamingSales, isConnected, error };
}
