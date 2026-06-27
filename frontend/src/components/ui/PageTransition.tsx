'use client';

/**
 * Route-change transition. Wraps the routed `{children}` in AppShell so every
 * navigation cross-fades + rises instead of hard-cutting. Keyed on the pathname
 * so AnimatePresence runs an exit→enter cycle per route. Honors
 * prefers-reduced-motion via the global `MotionConfig reducedMotion="user"`.
 */
import { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';

const EASE = [0.22, 1, 0.36, 1] as const; // expo-out, matches motion.tsx

export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={pathname}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.32, ease: EASE }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
