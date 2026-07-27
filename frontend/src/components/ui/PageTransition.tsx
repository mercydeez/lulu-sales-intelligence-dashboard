'use client';

/**
 * Route-change transition. Wraps the routed `{children}` in AppShell so every
 * navigation rises into place instead of hard-cutting. Keyed on the pathname, so
 * React swaps the tree on navigation. Honors prefers-reduced-motion via the
 * global `MotionConfig reducedMotion="user"`.
 *
 * WHY THERE IS NO AnimatePresence / exit / fade HERE.
 *
 * This was <AnimatePresence mode="wait"> with an exit animation and an
 * `initial: { opacity: 0 }` enter. Both halves of that are load-bearing for
 * content, which is exactly what they must never be:
 *
 *   * `mode="wait"` does not MOUNT the incoming route until the outgoing one's
 *     exit animation reports completion. framer-motion drives animations with
 *     requestAnimationFrame, and rAF is suspended whenever the document is
 *     hidden — background tab, embedded webview, headless/automation. The exit
 *     then never completes and the new route never mounts. Measured in an
 *     embedded preview: visibilityState 'hidden', 0 rAF frames in 500ms, and a
 *     keyed panel that never swapped (the identical bug in the Flywheel campaign
 *     studio, fixed alongside this).
 *
 *   * Dropping only `mode="wait"` is not enough — AnimatePresence would keep the
 *     OUTGOING route mounted until its exit finished, stacking two pages.
 *
 *   * An opacity fade starting at 0 fails the same way: with no rAF the page
 *     mounts and stays invisible. That is the "cards invisible (opacity 0)" bug
 *     this repo has already fixed once.
 *
 * So: transform-only, enter-only, no presence choreography. Worst case — zero
 * animation frames ever run — the page sits 4px off-target and is completely
 * readable. See components/flywheel/motion.tsx: motion is never load-bearing
 * for meaning.
 *
 * DURATION IS DELIBERATELY SHORT. The settle was 320ms over 8px, which read as
 * lag on every single tab switch — the transition never gates content (see
 * above), but a third of a second of drift on each navigation is felt as the app
 * being slow. 160ms over 4px still registers as "rose into place" without
 * putting perceptible latency in front of every route change.
 */
import { ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { motion, useReducedMotion } from 'framer-motion';
import { EASE } from './motion';

export function PageTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const reduce = useReducedMotion();
  return (
    <motion.div
      key={pathname}
      initial={reduce ? false : { y: 4 }}
      animate={{ y: 0 }}
      transition={{ duration: reduce ? 0 : 0.16, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}
