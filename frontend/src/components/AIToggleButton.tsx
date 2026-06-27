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
        {/* Glow effect */}
        <div className="absolute inset-0 bg-gradient-to-r from-violet-600 to-purple-600 rounded-full blur-lg opacity-50 group-hover:opacity-80 transition-opacity" />

        {/* Button */}
        <div className="relative flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-violet-600 to-purple-600 rounded-full shadow-lg transition-shadow duration-300 group-hover:shadow-xl">
          <Sparkles className="w-5 h-5 text-white" />
          <span className="text-white font-medium">Ask {CHATBOT_NAME}</span>
        </div>

        {/* Ping indicator */}
        <span className="absolute -top-1 -end-1 flex h-4 w-4">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-4 w-4 bg-teal-500"></span>
        </span>
      </div>
    </motion.button>
  );
}
