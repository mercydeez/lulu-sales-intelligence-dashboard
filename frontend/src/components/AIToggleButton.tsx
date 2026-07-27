'use client';

import { motion } from 'framer-motion';
import { Bot } from 'lucide-react';
import { CHATBOT_NAME } from '@/lib/brand';

interface AIToggleButtonProps {
  isOpen: boolean;
  onClick: () => void;
}

export default function AIToggleButton({ isOpen, onClick }: AIToggleButtonProps) {
  if (isOpen) return null;

  return (
    <motion.button
      onClick={onClick}
      className="fixed bottom-6 end-6 z-50 group"
      title={`Open ${CHATBOT_NAME}`}
      aria-label={`Open ${CHATBOT_NAME}`}
      initial={{ opacity: 0, scale: 0.8, y: 12 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 22, delay: 0.4 }}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.96 }}
    >
      <div className="relative">
        {/* A recognisable assistant avatar is more discoverable than a generic
            sparkle and avoids relying on a third-party mascot asset. */}
        <div className="relative flex h-12 items-center gap-2 rounded-full bg-[var(--ai-600)] py-1.5 ps-1.5 pe-4 shadow-soft transition-shadow duration-300 group-hover:shadow-elevated">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 ring-1 ring-white/25">
            <Bot className="h-5 w-5 text-white" aria-hidden />
          </span>
          <span className="hidden text-sm font-semibold text-white sm:inline">{CHATBOT_NAME}</span>
        </div>
      </div>
    </motion.button>
  );
}
