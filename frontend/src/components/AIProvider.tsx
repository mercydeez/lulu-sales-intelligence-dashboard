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
  /** Open the panel; an optional prompt is submitted once through the normal
   *  send path (the copilot surface's embedded input hands off here). */
  openChat: (initialPrompt?: string) => void;
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
  const [pendingPrompt, setPendingPrompt] = useState<string | undefined>(undefined);
  const { config } = useExperience();

  // Experience-driven assistant shell. `hidden` removes the Sage affordance
  // entirely for the role; `copilot` keeps the panel machinery (openChat from
  // the /copilot surface and nudges still works) but retires the floating pill
  // — the dedicated surface is the entry point. `panel` is the default, and
  // absent config fails open to it.
  const assistantMode = config?.assistant_mode ?? 'panel';
  if (assistantMode === 'hidden') {
    return <>{children}</>;
  }

  const openChat = (initialPrompt?: string) => {
    setPendingPrompt(initialPrompt);
    setIsChatOpen(true);
  };
  const closeChat = () => {
    setIsChatOpen(false);
    setPendingPrompt(undefined); // never resend on a later reopen
  };

  return (
    <AIContext.Provider value={{ isChatOpen, openChat, closeChat }}>
      {/* Main content with adjusted width when chat is open */}
      <div className={`transition-all duration-300 ${isChatOpen ? 'lg:me-[400px]' : ''}`}>
        {children}
      </div>

      {/* AI Toggle Button — retired in copilot mode (§3.4) */}
      {assistantMode !== 'copilot' && (
        <AIToggleButton
          isOpen={isChatOpen}
          onClick={() => openChat()}
        />
      )}

      {/* ChatBot Panel — AnimatePresence drives the slide in/out */}
      <AnimatePresence>
        {isChatOpen && (
          <ChatBot
            key="sage-chat"
            isOpen={isChatOpen}
            onToggle={closeChat}
            initialPrompt={pendingPrompt}
          />
        )}
      </AnimatePresence>
    </AIContext.Provider>
  );
}
