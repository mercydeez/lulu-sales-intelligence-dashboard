'use client';

import { useState } from 'react';
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
      
      {/* ChatBot Panel */}
      <ChatBot 
        isOpen={isChatOpen} 
        onToggle={() => setIsChatOpen(false)} 
      />
    </>
  );
}
