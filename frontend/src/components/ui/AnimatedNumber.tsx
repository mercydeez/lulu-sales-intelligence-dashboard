'use client';

import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/cn';
import { useReducedMotion } from '@/hooks/useReducedMotion';

export interface AnimatedNumberProps {
  value: number;
  duration?: number;
  formatter?: (val: number) => string;
  /** Briefly flash green on increase / red on decrease when the value changes. */
  flashOnChange?: boolean;
  className?: string;
}

const defaultFormat = (n: number) => new Intl.NumberFormat().format(n);

/**
 * Count-up number ticker. Respects `prefers-reduced-motion` (jumps straight to
 * the final value). Optionally flashes on change for live values.
 */
export function AnimatedNumber({
  value,
  duration = 1000,
  formatter = defaultFormat,
  flashOnChange = false,
  className,
}: AnimatedNumberProps) {
  const reducedMotion = useReducedMotion();
  const [display, setDisplay] = useState(value);
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const prev = useRef(value);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    const start = prev.current;
    const end = value;
    let flashTimer: ReturnType<typeof setTimeout> | undefined;

    if (flashOnChange && end !== start) {
      setFlash(end > start ? 'up' : 'down');
      flashTimer = setTimeout(() => setFlash(null), 700);
    }

    if (reducedMotion || start === end) {
      setDisplay(end);
      prev.current = end;
      return () => {
        if (flashTimer) clearTimeout(flashTimer);
      };
    }

    const startTime = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 4);
      setDisplay(start + (end - start) * eased);
      if (progress < 1) {
        frame.current = requestAnimationFrame(tick);
      } else {
        prev.current = end;
      }
    };
    frame.current = requestAnimationFrame(tick);

    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      if (flashTimer) clearTimeout(flashTimer);
    };
  }, [value, duration, reducedMotion, flashOnChange]);

  return (
    <span
      className={cn(
        flash === 'up' && 'flash-up',
        flash === 'down' && 'flash-down',
        className
      )}
    >
      {formatter(Math.round(display))}
    </span>
  );
}
