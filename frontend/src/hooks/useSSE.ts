'use client';

import { useState, useMemo } from 'react';
import { Sale } from '@/types';
import { useEventStream } from './useEventStream';

export function useSSE() {
  const [streamingSales, setStreamingSales] = useState<Sale[]>([]);

  const eventHandlers = useMemo(() => ({
    sales: (sale: Sale) => {
      setStreamingSales((prev: Sale[]) => [sale, ...prev.slice(0, 99)]);
    }
  }), []);

  const { isConnected, error } = useEventStream('/stream/sales', { eventHandlers });

  return { streamingSales, isConnected, error };
}

