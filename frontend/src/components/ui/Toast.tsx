'use client';

import { createContext, useCallback, useContext, useRef, useState, ReactNode } from 'react';
import { CheckCircle, AlertTriangle, AlertCircle, Info, X } from 'lucide-react';
import { cn } from '@/lib/cn';

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

interface ToastItem {
  id: number;
  title?: string;
  message: string;
  variant: ToastVariant;
}

export interface ToastOptions {
  title?: string;
  variant?: ToastVariant;
  /** ms before auto-dismiss; pass 0 to disable */
  duration?: number;
}

interface ToastContextValue {
  show: (message: string, options?: ToastOptions) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const variantConfig: Record<ToastVariant, { icon: typeof CheckCircle; classes: string; iconClass: string }> = {
  success: { icon: CheckCircle, classes: 'bg-emerald-50 border-emerald-200 text-emerald-700', iconClass: 'text-emerald-500' },
  error: { icon: AlertCircle, classes: 'bg-rose-50 border-rose-200 text-rose-700', iconClass: 'text-rose-500' },
  warning: { icon: AlertTriangle, classes: 'bg-amber-50 border-amber-200 text-amber-700', iconClass: 'text-amber-500' },
  info: { icon: Info, classes: 'bg-violet-50 border-violet-200 text-violet-700', iconClass: 'text-violet-500' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (message: string, options: ToastOptions = {}) => {
      const id = ++counter.current;
      setToasts((prev) => [...prev, { id, message, title: options.title, variant: options.variant ?? 'info' }]);
      const duration = options.duration ?? 4000;
      if (duration > 0) setTimeout(() => dismiss(id), duration);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ show, dismiss }}>
      {children}
      <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 w-80 pointer-events-none">
        {toasts.map((t) => {
          const config = variantConfig[t.variant];
          const Icon = config.icon;
          return (
            <div
              key={t.id}
              className={cn(
                'pointer-events-auto rounded-xl border shadow-soft p-3 flex items-start gap-3 animate-fade-in',
                config.classes
              )}
            >
              <Icon className={cn('w-5 h-5 shrink-0 mt-0.5', config.iconClass)} />
              <div className="flex-1 min-w-0">
                {t.title && <p className="text-sm font-semibold">{t.title}</p>}
                <p className="text-sm">{t.message}</p>
              </div>
              <button onClick={() => dismiss(t.id)} className="text-current/60 hover:text-current transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}
