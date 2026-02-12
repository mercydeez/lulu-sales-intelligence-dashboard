'use client';

import { Sparkles } from 'lucide-react';

interface AIToggleButtonProps {
  isOpen: boolean;
  onClick: () => void;
}

export default function AIToggleButton({ isOpen, onClick }: AIToggleButtonProps) {
  if (isOpen) return null;
  
  return (
    <button
      onClick={onClick}
      className="fixed bottom-6 right-6 z-50 group"
      title="Open AI Assistant"
    >
      <div className="relative">
        {/* Glow effect */}
        <div className="absolute inset-0 bg-gradient-to-r from-violet-600 to-purple-600 rounded-full blur-lg opacity-50 group-hover:opacity-75 transition-opacity" />
        
        {/* Button */}
        <div className="relative flex items-center gap-2 px-5 py-3 bg-gradient-to-r from-violet-600 to-purple-600 rounded-full shadow-lg hover:shadow-xl transition-all duration-300 hover:scale-105">
          <Sparkles className="w-5 h-5 text-white" />
          <span className="text-white font-medium">Ask Lulu AI</span>
        </div>
        
        {/* Ping indicator */}
        <span className="absolute -top-1 -right-1 flex h-4 w-4">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-4 w-4 bg-cyan-500"></span>
        </span>
      </div>
    </button>
  );
}
