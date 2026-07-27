'use client';

import { HTMLAttributes, ReactNode } from 'react';
import { motion } from 'framer-motion';
import { Inbox } from 'lucide-react';
import { cn } from '@/lib/cn';
import { EASE } from './motion';

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action, className, ...props }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center py-12 px-6', className)} {...props}>
      {/* Illustrative icon: layered glow + soft float for a screenshot-ready empty state. */}
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
        className="relative mb-4"
      >
        <span className="absolute inset-0 -z-10 rounded-full bg-teal-300/20 blur-xl" aria-hidden />
        <motion.div
          animate={{ y: [0, -4, 0] }}
          transition={{ duration: 4, ease: 'easeInOut', repeat: Infinity }}
          className="w-16 h-16 rounded-2xl bg-gradient-to-br from-teal-50 to-surface text-teal-400 flex items-center justify-center ring-1 ring-teal-100 shadow-card"
        >
          {icon ?? <Inbox className="w-7 h-7" />}
        </motion.div>
      </motion.div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description && <p className="text-sm text-ink-muted mt-1 max-w-sm">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
