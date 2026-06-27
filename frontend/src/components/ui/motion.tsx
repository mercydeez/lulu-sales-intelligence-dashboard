'use client';

/**
 * Shared framer-motion primitives — one place for the app's motion language so
 * every screen animates consistently (and respects prefers-reduced-motion via
 * framer's `MotionConfig reducedMotion="user"`, set in AppShell).
 *
 * Usage:
 *   <Reveal>…</Reveal>                      // single fade/rise-in
 *   <Stagger><RevealItem/>…<RevealItem/>    // staggered children
 *   <MotionCard>…</MotionCard>              // Card with hover lift + entrance
 */
import { ReactNode } from 'react';
import { motion, Variants, HTMLMotionProps } from 'framer-motion';
import { Card, CardProps } from './Card';

const EASE = [0.22, 1, 0.36, 1] as const; // expo-out: confident, premium settle

export const fadeRise: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

export const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};

/** A single element that fades + rises into view once. */
export function Reveal({
  children,
  delay = 0,
  className,
  ...props
}: { children: ReactNode; delay?: number } & Omit<HTMLMotionProps<'div'>, 'ref'>) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={{
        hidden: { opacity: 0, y: 12 },
        show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE, delay } },
      }}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  );
}

/** Wrap a group; children using `RevealItem` (or variants={fadeRise}) cascade in. */
export function Stagger({
  children,
  className,
  ...props
}: { children: ReactNode } & Omit<HTMLMotionProps<'div'>, 'ref'>) {
  return (
    <motion.div
      initial="hidden"
      animate="show"
      variants={staggerContainer}
      className={className}
      {...props}
    >
      {children}
    </motion.div>
  );
}

/** A staggered child — place inside <Stagger>. */
export function RevealItem({
  children,
  className,
  ...props
}: { children: ReactNode } & Omit<HTMLMotionProps<'div'>, 'ref'>) {
  return (
    <motion.div variants={fadeRise} className={className} {...props}>
      {children}
    </motion.div>
  );
}

/** Card that enters with the stagger and lifts subtly on hover. */
export function MotionCard({
  children,
  interactive = true,
  ...cardProps
}: { children: ReactNode; interactive?: boolean } & CardProps) {
  return (
    <motion.div
      variants={fadeRise}
      whileHover={interactive ? { y: -3 } : undefined}
      transition={{ type: 'spring', stiffness: 320, damping: 26 }}
      className="h-full"
    >
      <Card {...cardProps} className={cardProps.className}>
        {children}
      </Card>
    </motion.div>
  );
}
