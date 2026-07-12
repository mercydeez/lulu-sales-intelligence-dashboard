'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import { useAuth } from '@/contexts/AuthContext';
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
  const { isAuthenticated, isLoading } = useAuth();

  // Sage's shell is controlled by session state only. Role/experience config
  // may shape its persona and capabilities, but must never hide the launcher.
  const isSageVisible = isAuthenticated && !isLoading;

  // A logout must also clear UI state so a later login never reopens a panel
  // that belonged to the previous session.
  useEffect(() => {
    if (!isAuthenticated) {
      setIsChatOpen(false);
      setPendingPrompt(undefined);
    }
  }, [isAuthenticated]);

  const openChat = (initialPrompt?: string) => {
    // AI is an authenticated, tenant-scoped surface. Keeping this guard here
    // prevents public pages from opening a client panel during auth redirects.
    if (!isAuthenticated || isLoading) return;
    setPendingPrompt(initialPrompt);
    setIsChatOpen(true);
  };
  const closeChat = () => {
    setIsChatOpen(false);
    setPendingPrompt(undefined); // never resend on a later reopen
  };

  return (
    <AIContext.Provider value={{ isChatOpen: isSageVisible && isChatOpen, openChat, closeChat }}>
      {/* Main content with adjusted width when chat is open */}
      <div className={`transition-all duration-300 ${isSageVisible && isChatOpen ? 'lg:me-[400px]' : ''}`}>
        {children}
      </div>

      {/* Authenticated users always keep the global Sage entry point. */}
      {isSageVisible && (
        <AIToggleButton
          isOpen={isChatOpen}
          onClick={() => openChat()}
        />
      )}

      {/* ChatBot Panel — AnimatePresence drives the slide in/out */}
      <AnimatePresence>
        {isSageVisible && isChatOpen && (
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
