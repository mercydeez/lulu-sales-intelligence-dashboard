'use client';

import { createContext, useContext, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import { useExperience } from '@/contexts/ExperienceContext';
import ChatBot from './ChatBot';
import AIToggleButton from './AIToggleButton';

interface AIProviderProps {
  children: React.ReactNode;
}

/**
 * Programmatic access to the Sage panel (A1 — Sage-guided onboarding).
 * Exposed so surfaces like the first-run nudge can open the chat; safe
 * no-op fallback outside the provider (same pattern as Language/Theme).
 */
interface AIContextValue {
  isChatOpen: boolean;
  openChat: () => void;
  closeChat: () => void;
}

const AIContext = createContext<AIContextValue | undefined>(undefined);

export function useAI(): AIContextValue {
  const ctx = useContext(AIContext);
  if (!ctx) return { isChatOpen: false, openChat: () => {}, closeChat: () => {} };
  return ctx;
}

export default function AIProvider({ children }: AIProviderProps) {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const { config } = useExperience();

  // Experience-driven assistant shell. `hidden` removes the Sage affordance
  // entirely for the role; `panel` and `copilot` both render the current panel
  // this phase (the dedicated copilot surface arrives later) — the switch is
  // wired now so it becomes config-only. Absent config → default panel behavior.
  const assistantMode = config?.assistant_mode ?? 'panel';
  if (assistantMode === 'hidden') {
    return <>{children}</>;
  }

  return (
    <AIContext.Provider
      value={{
        isChatOpen,
        openChat: () => setIsChatOpen(true),
        closeChat: () => setIsChatOpen(false),
      }}
    >
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
    </AIContext.Provider>
  );
}
