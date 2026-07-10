'use client';

import { motion } from 'framer-motion';
import { Sparkles } from 'lucide-react';
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
      initial={{ opacity: 0, scale: 0.8, y: 12 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 22, delay: 0.4 }}
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.96 }}
    >
      <div className="relative">
        {/* Button — tokenized AI accent (violet = AI provenance), neutral elevation */}
        <div className="relative flex items-center gap-2 px-5 py-3 bg-[var(--ai-600)] rounded-full shadow-soft transition-shadow duration-300 group-hover:shadow-elevated">
          <Sparkles className="w-5 h-5 text-white" />
          <span className="text-white font-medium">Ask {CHATBOT_NAME}</span>
        </div>
      </div>
    </motion.button>
  );
}
