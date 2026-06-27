'use client';

import { useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import ChatBot from './ChatBot';
import AIToggleButton from './AIToggleButton';

interface AIProviderProps {
  children: React.ReactNode;
}

export default function AIProvider({ children }: AIProviderProps) {
  const [isChatOpen, setIsChatOpen] = useState(false);

  return (
    <>
      {/* Main content with adjusted width when chat is open */}
      <div className={`transition-all duration-300 ${isChatOpen ? 'mr-[400px]' : ''}`}>
        {children}
      </div>
      
      {/* AI Toggle Button */}
      <AIToggleButton 
        isOpen={isChatOpen} 
        onClick={() => setIsChatOpen(true)} 
      />
      
      {/* ChatBot Panel — AnimatePresence drives the slide in/out */}
      <AnimatePresence>
        {isChatOpen && (
          <ChatBot
            key="sage-chat"
            isOpen={isChatOpen}
            onToggle={() => setIsChatOpen(false)}
          />
        )}
      </AnimatePresence>
    </>
  );
}
