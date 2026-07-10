'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Send,
  X, 
  Trash2, 
  Mic, 
  MicOff, 
  Volume2, 
  VolumeX,
  Loader2,
  Bot,
  User,
  Minimize2,
  Maximize2,
  Sparkles,
  Lock,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
  Brain,
  FileText,
  CheckCircle2,
  Database
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useExperience } from '@/contexts/ExperienceContext';
import { CHATBOT_NAME } from '@/lib/brand';

// Web Speech API types
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionResultList {
  length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  length: number;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
  isFinal: boolean;
}

interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: (event: SpeechRecognitionEvent) => void;
  onerror: (event: Event & { error: string }) => void;
  onend: () => void;
  onstart: () => void;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognition;
    webkitSpeechRecognition: new () => SpeechRecognition;
  }
}

// Sage v3 multi-agent metadata, delivered on the SSE 'done' event.
interface TraceEntry {
  node: string;
  summary: string;
  confidence?: number | null;
}
interface Evidence {
  kind: string;
  sql?: string;
  citation?: string;
  label?: string;
  source?: string;
  row_count?: number;
}
interface ChatMeta {
  engine?: string;
  route?: string;
  confidence?: number | null;
  grounded?: boolean;
  needs_clarification?: boolean;
  needs_readback?: boolean;
  readback_text?: string | null;
  clarification_question?: string | null;
  trace?: TraceEntry[];
  evidence?: Evidence[];
}

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  meta?: ChatMeta;
}

interface ChatBotProps {
  isOpen: boolean;
  onToggle: () => void;
  /** Submitted once on mount through the normal send path — the copilot
   *  surface's embedded input hands its question off here. */
  initialPrompt?: string;
}

// Human labels for the agent-trace "thinking" view.
const NODE_LABELS: Record<string, string> = {
  router: 'Routed the question',
  intent: 'Read intent + clarity',
  clarification: 'Asked to clarify',
  readback: 'Confirmed the plan',
  planner: 'Planned sub-questions',
  sql_agent: 'Queried the database',
  rag_agent: 'Searched documents',
  hybrid_executor: 'Answered each part',
  synthesiser: 'Composed the answer',
  critic: 'Critiqued the draft',
  cross_validator: 'Cross-checked figures',
  arbiter: 'Reconciled verdicts',
  completeness: 'Checked completeness',
  finaliser: 'Finalised',
};

/**
 * Sage's opening line — written in the caller's persona voice, not a generic
 * "chatbot" greeting. Only advertises voice when the role actually has it, so
 * we never point a user at a control they can't use. The example questions are
 * rendered as one-tap chips below the message (SUGGESTED_QUESTIONS).
 */
function buildWelcome(title: string, canVoice: boolean): string {
  const voiceLine = canVoice ? ' Prefer to talk it through? Tap the mic and ask.' : '';
  return `I'm **${CHATBOT_NAME}**, your ${title}. I read your live sales, inventory, and open findings directly — and I answer with the number, what it means, and the move I'd make next.${voiceLine}\n\nTap a question below, or ask your own.`;
}

// One-tap starters — each is a question the deterministic engine can ground.
const SUGGESTED_QUESTIONS = [
  'How did revenue move this week — and why?',
  'Which stores need my attention today?',
  "What's my biggest stock risk right now?",
  'Where am I losing money to dead stock?',
];

function confidenceStyle(c?: number | null) {
  if (c == null) return { label: '—', cls: 'bg-surface-3 text-ink-muted' };
  const pct = `${Math.round(c * 100)}%`;
  if (c >= 0.7) return { label: pct, cls: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' };
  if (c >= 0.5) return { label: pct, cls: 'bg-amber-500/15 text-amber-400 border border-amber-500/30' };
  return { label: pct, cls: 'bg-rose-500/15 text-rose-400 border border-rose-500/30' };
}

// Confidence badge + collapsible agent trace + citations + readback confirm.
function MessageMeta({ meta, onConfirm }: { meta: ChatMeta; onConfirm: () => void }) {
  const [showTrace, setShowTrace] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const conf = confidenceStyle(meta.confidence);
  const sqlEvidence = (meta.evidence || []).filter((e) => e.kind === 'sql' && e.sql);
  const docEvidence = (meta.evidence || []).filter((e) => e.kind === 'doc' && e.citation);
  const srcEvidence = (meta.evidence || []).filter((e) => e.kind === 'source');

  return (
    <div className="mt-2 space-y-1.5">
      {/* Badges row */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${conf.cls}`}>
          <ShieldCheck className="w-3 h-3" /> Confidence {conf.label}
        </span>
        {meta.grounded && (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-violet-500/15 text-violet-300 border border-violet-500/30">
            <Database className="w-3 h-3" /> Grounded
          </span>
        )}
        {meta.route && (
          <span className="px-2 py-0.5 rounded-full text-[11px] bg-surface-3 text-ink-muted capitalize">{meta.route}</span>
        )}
      </div>

      {/* Readback confirm */}
      {meta.needs_readback && (
        <button
          onClick={onConfirm}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-500 transition-colors"
        >
          <CheckCircle2 className="w-3.5 h-3.5" /> Confirm &amp; run
        </button>
      )}

      {/* Citations */}
      {(docEvidence.length > 0 || srcEvidence.length > 0) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {docEvidence.map((e, i) => (
            <span key={`d${i}`} className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-sky-500/15 text-sky-300 border border-sky-500/30">
              <FileText className="w-3 h-3" /> {e.citation}
            </span>
          ))}
          {srcEvidence.map((e, i) => (
            <span key={`s${i}`} className="px-2 py-0.5 rounded text-[11px] bg-sky-500/15 text-sky-300 border border-sky-500/30">
              {e.source || e.label}
            </span>
          ))}
        </div>
      )}

      {/* SQL (collapsible) */}
      {sqlEvidence.length > 0 && (
        <div>
          <button onClick={() => setShowSql((v) => !v)} className="inline-flex items-center gap-1 text-[11px] text-ink-muted hover:text-ink transition-colors">
            {showSql ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <Database className="w-3 h-3" /> {showSql ? 'Hide' : 'Show'} SQL ({sqlEvidence.length})
          </button>
          {showSql && (
            <div className="mt-1 space-y-1">
              {sqlEvidence.map((e, i) => (
                <pre key={i} className="text-[10px] bg-surface-3/70 text-ink-muted p-2 rounded overflow-x-auto whitespace-pre-wrap">{e.sql}</pre>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Agent trace (collapsible "thinking") */}
      {meta.trace && meta.trace.length > 0 && (
        <div>
          <button onClick={() => setShowTrace((v) => !v)} className="inline-flex items-center gap-1 text-[11px] text-ink-muted hover:text-ink transition-colors">
            {showTrace ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <Brain className="w-3 h-3" /> {showTrace ? 'Hide' : 'Show'} reasoning ({meta.trace.length} steps)
          </button>
          {showTrace && (
            <ol className="mt-1 space-y-1 border-s border-line ps-3">
              {meta.trace.map((t, i) => (
                <li key={i} className="text-[11px] text-ink-muted">
                  <span className="text-ink/80 font-medium">{NODE_LABELS[t.node] || t.node}</span>
                  <span className="text-ink-muted"> — {t.summary}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}

export default function ChatBot({ isOpen, onToggle, initialPrompt }: ChatBotProps) {
  const { user, hasPermission, hasRole, authFetch } = useAuth();
  const { config: experience } = useExperience();
  const personaTitle = experience?.persona?.title ?? 'Sales Assistant';

  // Authorization stays server-side (routes/ai.py require_ai_chat / require_voice_chat).
  // The client gate mirrors it via role/permission, and the experience config's
  // `capabilities` can only NARROW it further (never widen) — so a role that
  // isn't allowed chat can't gain it by config, and one that is can be turned off
  // per experience. Absent capabilities (v1 payload) → unchanged behavior.
  const caps = experience?.capabilities;
  const canUseChat = (hasRole(['super_admin', 'regional_manager', 'store_manager']) ||
                      hasPermission('can_use_ai_chat')) && (caps?.ai_chat ?? true);
  const canUseVoice = (hasRole(['super_admin', 'regional_manager']) ||
                      hasPermission('can_use_voice_chat')) && (caps?.voice ?? true);
  
  const [messages, setMessages] = useState<Message[]>(() => [
    {
      id: '0',
      role: 'assistant',
      content: buildWelcome(personaTitle, canUseVoice),
      timestamp: new Date()
    }
  ]);

  // The persona/voice access resolve asynchronously (experience config). Refresh
  // the opening line once they land — but only while the chat is still pristine,
  // so we never overwrite a real conversation.
  useEffect(() => {
    setMessages((prev) =>
      prev.length === 1 && prev[0].id === '0' && prev[0].role === 'assistant'
        ? [{ ...prev[0], content: buildWelcome(personaTitle, canUseVoice) }]
        : prev
    );
  }, [personaTitle, canUseVoice]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>('');
  const [isMinimized, setIsMinimized] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [autoSpeak, setAutoSpeak] = useState(false);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [isProcessingVoice, setIsProcessingVoice] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState('');
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const recordingTimerRef = useRef<NodeJS.Timeout | null>(null);

  const buildDataFallback = useCallback(async (question: string) => {
    const readJson = async (url: string) => {
      try {
        const res = await authFetch(url);
        return res.ok ? await res.json() : null;
      } catch {
        return null;
      }
    };

    const [kpis, inventory, alertSummary, activeAlerts, approvals] = await Promise.all([
      readJson('/api/kpis'),
      readJson('/api/inventory/summary'),
      readJson('/api/alerts/summary'),
      readJson('/api/alerts/list?status=active&limit=5'),
      readJson('/api/procurement/approvals'),
    ]);

    // Present a confident operational read — evidence, then the move I'd make —
    // rather than apologising for not having an LLM answer. Every figure below is
    // pulled live and kept honest (units vs AED never mixed).
    const lines = ["Here's where your operation stands right now — and where I'd start:", ''];

    const critical = alertSummary?.critical_alerts ?? 0;
    const outOfStock = inventory?.out_of_stock_count ?? 0;
    const lowStock = inventory?.low_stock_count ?? 0;
    const poWaiting = approvals?.count ?? 0;

    if (kpis) {
      lines.push('• **Today so far:** ' + new Intl.NumberFormat('en-AE').format(kpis.total_sales_today ?? 0) + ' units sold · AED ' + new Intl.NumberFormat('en-AE', { maximumFractionDigits: 0 }).format(kpis.total_revenue_today ?? 0) + ' revenue.');
    }
    if (alertSummary) {
      lines.push('• **Alerts:** ' + (alertSummary.total_active ?? 0) + ' active — ' + critical + ' critical, ' + (alertSummary.warning_alerts ?? 0) + ' warning.');
    }
    if (inventory) {
      lines.push('• **Stock:** ' + outOfStock + ' out of stock, ' + lowStock + ' running low, ' + (inventory.overstocked_count ?? 0) + ' overstocked.');
    }
    if (approvals) {
      lines.push('• **Approvals:** ' + poWaiting + ' purchase order' + (poWaiting === 1 ? '' : 's') + ' awaiting your decision.');
    }

    const alerts = activeAlerts?.alerts ?? [];
    if (alerts.length > 0) {
      lines.push('');
      lines.push('The alerts I\'d read first:');
      alerts.slice(0, 3).forEach((alert: any, index: number) => {
        lines.push((index + 1) + '. ' + alert.title + ' — ' + (alert.store_name || 'assigned store'));
      });
    }

    // Close like an operator: one clear next move, ranked by what costs the most.
    const loadedAnything = kpis || alertSummary || inventory || approvals;
    if (!loadedAnything) {
      return "I can't reach your live data at the moment. Give it a moment and refresh — then check Alerts, Inventory, and Approvals directly, and I'll pick it back up.";
    }
    lines.push('');
    if (critical > 0) {
      lines.push('**My recommendation:** start with the ' + critical + ' critical alert' + (critical === 1 ? '' : 's') + ' above — that\'s the fastest money on the table today.');
    } else if (outOfStock > 0) {
      lines.push('**My recommendation:** clear the ' + outOfStock + ' out-of-stock line' + (outOfStock === 1 ? '' : 's') + ' first — every hour off-shelf is revenue you can\'t recover.');
    } else if (poWaiting > 0) {
      lines.push('**My recommendation:** approve the ' + poWaiting + ' waiting purchase order' + (poWaiting === 1 ? '' : 's') + ' — that keeps your shelves full ahead of demand.');
    } else if (lowStock > 0) {
      lines.push('**My recommendation:** watch the ' + lowStock + ' low-stock line' + (lowStock === 1 ? '' : 's') + ' — reorder before they run out, not after.');
    } else {
      lines.push('**My read:** nothing urgent is flagging right now — you\'re clear to focus on the plan. Ask me anything specific and I\'ll dig in.');
    }

    return lines.join('\n');
  }, [authFetch]);

  // Generate session ID on mount
  useEffect(() => {
    setSessionId(`session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`);
  }, []);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen && !isMinimized) {
      inputRef.current?.focus();
    }
  }, [isOpen, isMinimized]);

  // Esc closes the panel (unless the mic is live — stopping a recording with
  // Esc mid-sentence would be surprising; stop the recording first).
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isRecording) onToggle();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, isRecording, onToggle]);

  const sendMessage = useCallback(async (messageText: string) => {
    if (!messageText.trim() || isLoading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageText,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    // Add placeholder for assistant response
    const assistantId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true
    }]);

    try {
      const response = await authFetch('/api/ai/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
          stream: true
        })
      });

      if (!response.ok) throw new Error('Failed to get response');

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let fullResponse = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const text = decoder.decode(value);
          const lines = text.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.content) {
                  fullResponse += data.content;
                  setMessages(prev => prev.map(m =>
                    m.id === assistantId
                      ? { ...m, content: fullResponse }
                      : m
                  ));
                } else if (data.engine === 'sage_v3') {
                  // Sage v3 'done' meta: confidence, agent trace, citations, dialogue flags.
                  const meta = data as ChatMeta;
                  setMessages(prev => prev.map(m =>
                    m.id === assistantId ? { ...m, meta } : m
                  ));
                }
              } catch (e) {
                // Skip invalid JSON
              }
            }
          }
        }
      }

      if (!fullResponse.trim()) {
        fullResponse = await buildDataFallback(messageText);
        setMessages(prev => prev.map(m =>
          m.id === assistantId
            ? { ...m, content: fullResponse }
            : m
        ));
      }

      // Mark as done streaming
      setMessages(prev => prev.map(m => 
        m.id === assistantId 
          ? { ...m, isStreaming: false }
          : m
      ));

      // Auto-speak response if enabled
      if (autoSpeak && fullResponse) {
        speakText(fullResponse);
      }

    } catch (error) {
      const fallback = await buildDataFallback(messageText);
      setMessages(prev => prev.map(m => 
        m.id === assistantId 
          ? { ...m, content: fallback, isStreaming: false }
          : m
      ));
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, isLoading, autoSpeak, authFetch, buildDataFallback]);

  // Copilot hand-off: a prompt passed in is submitted exactly once, through the
  // same send path as a typed message (server authorization unchanged).
  const initialPromptSent = useRef(false);
  useEffect(() => {
    if (initialPrompt && canUseChat && !initialPromptSent.current) {
      initialPromptSent.current = true;
      sendMessage(initialPrompt);
    }
  }, [initialPrompt, canUseChat, sendMessage]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const clearChat = async () => {
    try {
      await authFetch('/api/ai/chat/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      });
    } catch (e) {
      console.error('Failed to clear chat:', e);
    }

    setMessages([{
      id: '0',
      role: 'assistant',
      content: buildWelcome(personaTitle, canUseVoice),
      timestamp: new Date()
    }]);
  };

  // Helper to add system messages to chat
  const addSystemMessage = (content: string) => {
    const systemMsg: Message = {
      id: `system_${Date.now()}`,
      role: 'system',
      content,
      timestamp: new Date()
    };
    setMessages(prev => [...prev, systemMsg]);
    return systemMsg.id;
  };

  const updateSystemMessage = (id: string, content: string) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, content } : m));
  };

  // Initialize Web Speech API
  const initSpeechRecognition = useCallback(() => {
    if (typeof window === 'undefined') return null;
    
    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) {
      console.warn('Speech Recognition not supported');
      return null;
    }
    
    const recognition = new SpeechRecognitionAPI();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    
    return recognition;
  }, []);

  // Toggle voice recording - click to start, click to stop
  const toggleRecording = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  // Voice recording using FREE Web Speech API (no API key needed!)
  const startRecording = () => {
    if (isProcessingVoice || isLoading) return;
    
    const recognition = initSpeechRecognition();
    if (!recognition) {
      addSystemMessage('**Speech recognition not supported.** Please use Chrome, Edge, or Safari browser.');
      return;
    }
    
    recognitionRef.current = recognition;
    let finalTranscript = '';
    
    // Show recording started message
    const recordingMsgId = addSystemMessage('**Listening...** Speak now. Your words will appear below in real-time.');
    
    recognition.onstart = () => {
      setIsRecording(true);
      setRecordingDuration(0);
      setInterimTranscript('');
      
      // Start duration timer
      recordingTimerRef.current = setInterval(() => {
        setRecordingDuration(prev => prev + 0.1);
      }, 100);
    };
    
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalTranscript += result[0].transcript + ' ';
        } else {
          interim += result[0].transcript;
        }
      }
      
      // Show real-time transcription in the input box
      const currentText = (finalTranscript + interim).trim();
      setInterimTranscript(currentText);
      setInput(currentText);
      
      // Update the recording message to show what's being heard
      if (currentText) {
        updateSystemMessage(recordingMsgId, `**Hearing:** "${currentText}"`);
      }
    };
    
    recognition.onerror = (event: Event & { error: string }) => {
      console.error('Speech recognition error:', event.error);
      
      if (event.error === 'no-speech') {
        updateSystemMessage(recordingMsgId, '**No speech detected.** Please speak louder or check your microphone.');
      } else if (event.error === 'audio-capture') {
        updateSystemMessage(recordingMsgId, '**Microphone not found.** Please connect a microphone and try again.');
      } else if (event.error === 'not-allowed') {
        updateSystemMessage(recordingMsgId, '**Microphone access denied.** Please allow microphone access in your browser settings.');
      } else {
        updateSystemMessage(recordingMsgId, `**Error:** ${event.error}`);
      }
      
      stopRecording();
    };
    
    recognition.onend = () => {
      // Clean up timer
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
        recordingTimerRef.current = null;
      }
      
      setIsRecording(false);
      
      const finalText = finalTranscript.trim() || interimTranscript.trim();
      
      if (finalText) {
        updateSystemMessage(recordingMsgId, `**Captured:** "${finalText}"`);
        setInput(finalText);
        
        // Auto-send after a short delay
        setTimeout(() => {
          sendMessage(finalText);
        }, 300);
      } else {
        updateSystemMessage(recordingMsgId, '**No speech captured.** Click mic and try again.');
      }
      
      setInterimTranscript('');
    };
    
    try {
      recognition.start();
    } catch (e) {
      console.error('Failed to start recognition:', e);
      addSystemMessage('**Failed to start speech recognition.** Please try again.');
    }
  };

  const stopRecording = () => {
    // Clear the timer
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      setIsRecording(false);
    }
  };
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current);
      }
      if (recognitionRef.current) {
        recognitionRef.current.abort();
      }
    };
  }, []);

  // Text-to-speech using FREE browser API
  const speakText = (text: string) => {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      console.warn('Speech synthesis not supported');
      return;
    }
    
    // Cancel any ongoing speech
    window.speechSynthesis.cancel();
    
    setIsSpeaking(true);
    
    // Clean the text (remove markdown)
    const cleanText = text
      .replace(/\*\*(.*?)\*\*/g, '$1')
      .replace(/\*(.*?)\*/g, '$1')
      .replace(/`(.*?)`/g, '$1')
      .replace(/•/g, '')
      .replace(/\n/g, ' ');
    
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    
    // Try to use a good English voice
    const voices = window.speechSynthesis.getVoices();
    const englishVoice = voices.find(v => 
      v.lang.startsWith('en') && (v.name.includes('Google') || v.name.includes('Microsoft'))
    ) || voices.find(v => v.lang.startsWith('en'));
    
    if (englishVoice) {
      utterance.voice = englishVoice;
    }
    
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    
    window.speechSynthesis.speak(utterance);
  };

  const formatMessage = (content: string) => {
    // Simple markdown-like formatting
    return content
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code class="bg-surface-2 px-1 rounded">$1</code>')
      .replace(/\n/g, '<br/>');
  };

  const panelMotion = {
    initial: { x: '100%', opacity: 0 },
    animate: { x: 0, opacity: 1 },
    exit: { x: '100%', opacity: 0 },
    transition: { type: 'spring' as const, stiffness: 260, damping: 30 },
  };

  // If user doesn't have chat permission, show restricted message
  if (!canUseChat) {
    return (
      <motion.aside {...panelMotion} className="fixed end-0 top-0 h-full w-full max-w-[400px] bg-surface border-s border-line shadow-2xl flex flex-col z-50">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-[var(--ai-600)] border-b border-line">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-surface/20 flex items-center justify-center">
              <Lock className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-white font-semibold">{CHATBOT_NAME}</h2>
              <p className="text-white/70 text-xs">Restricted Access</p>
            </div>
          </div>
          <button
            onClick={onToggle}
            className="p-2 hover:bg-surface/10 rounded-lg transition-colors"
            title="Close"
          >
            <X className="w-4 h-4 text-white" />
          </button>
        </div>
        
        {/* Restricted Access Message */}
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center">
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-surface-2/60 flex items-center justify-center">
              <Lock className="w-8 h-8 text-ink-muted" />
            </div>
            <h3 className="text-lg font-semibold text-ink mb-2">Access Restricted</h3>
            <p className="text-ink-muted text-sm mb-4">
              You don't have permission to use the AI assistant.
            </p>
            <p className="text-ink-muted text-xs">
              Contact your administrator to request access.
            </p>
            <p className="text-ink-muted text-xs mt-2">
              Logged in as: {user?.email || 'Unknown'}
            </p>
          </div>
        </div>
      </motion.aside>
    );
  }

  return (
    <motion.aside {...panelMotion} className={`fixed end-0 top-0 h-full bg-surface border-s border-line shadow-2xl flex flex-col z-50 ${
      isMinimized ? 'w-16' : 'w-full max-w-[400px]'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[var(--ai-600)] border-b border-line">
        {!isMinimized && (
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-surface/20 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-white font-semibold">{CHATBOT_NAME}</h2>
              <p className="text-white/70 text-xs">{personaTitle}</p>
            </div>
          </div>
        )}
        
        <div className="flex items-center gap-1">
          <button
            onClick={() => setIsMinimized(!isMinimized)}
            className="p-2 hover:bg-surface/10 rounded-lg transition-colors"
            title={isMinimized ? "Expand" : "Minimize"}
            aria-label={isMinimized ? 'Expand chat panel' : 'Minimize chat panel'}
          >
            {isMinimized ? <Maximize2 className="w-4 h-4 text-white" /> : <Minimize2 className="w-4 h-4 text-white" />}
          </button>
          <button
            onClick={onToggle}
            className="p-2 hover:bg-surface/10 rounded-lg transition-colors"
            title="Close"
            aria-label="Close chat panel"
          >
            <X className="w-4 h-4 text-white" />
          </button>
        </div>
      </div>

      {!isMinimized && (
        <>
          {/* Voice Controls */}
          <div className="flex items-center justify-between px-4 py-2 bg-surface-2/50 border-b border-line/50">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setAutoSpeak(!autoSpeak)}
                className={`p-2 rounded-lg transition-colors ${
                  autoSpeak ? 'bg-violet-500/20 text-violet-400' : 'hover:bg-surface-2 text-ink-muted'
                }`}
                title={autoSpeak ? "Disable auto-speak" : "Enable auto-speak"}
                aria-label={autoSpeak ? 'Disable spoken replies' : 'Enable spoken replies'}
                aria-pressed={autoSpeak}
              >
                {autoSpeak ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
              </button>
              <span className="text-xs text-ink-muted">
                {autoSpeak ? 'Voice replies on' : 'Voice replies off'}
              </span>
            </div>
            <button
              onClick={clearChat}
              className="p-2 hover:bg-surface-2 rounded-lg transition-colors text-ink-muted"
              title="Clear chat"
              aria-label="Clear conversation"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4" role="log" aria-live="polite" aria-label="Conversation with Sage">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : ''} ${message.role === 'system' ? 'justify-center' : ''}`}
              >
                {message.role !== 'system' && (
                  <div className={`w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center ${
                    message.role === 'user' 
                      ? 'bg-teal-50' 
                      : 'bg-violet-500/20'
                  }`}>
                    {message.role === 'user' 
                      ? <User className="w-4 h-4 text-teal-600" />
                      : <Bot className="w-4 h-4 text-violet-400" />
                    }
                  </div>
                )}
                
                <div className={`flex-1 ${message.role === 'user' ? 'text-end' : ''} ${message.role === 'system' ? 'text-center' : ''}`}>
                  <div
                    className={`inline-block max-w-[85%] p-3 rounded-2xl ${
                      message.role === 'user'
                        ? 'bg-teal-50 text-ink rounded-tr-sm'
                        : message.role === 'system'
                        ? 'bg-amber-50 text-amber-800 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:border-amber-500/30 text-xs'
                        : 'bg-surface-2 text-ink rounded-tl-sm'
                    }`}
                  >
                    <div 
                      className="text-sm leading-relaxed"
                      dangerouslySetInnerHTML={{ __html: formatMessage(message.content) }}
                    />
                    {message.isStreaming && (
                      <span className="inline-block w-2 h-4 bg-violet-400 animate-pulse ms-1" />
                    )}
                  </div>

                  {/* Sage v3: confidence badge, agent trace, citations, readback confirm */}
                  {message.role === 'assistant' && !message.isStreaming && message.meta && (
                    <MessageMeta meta={message.meta} onConfirm={() => sendMessage('yes')} />
                  )}

                  {message.role !== 'system' && (
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-ink-muted">
                        {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      {message.role === 'assistant' && !message.isStreaming && message.content && (
                        <button
                          onClick={() => speakText(message.content)}
                          disabled={isSpeaking}
                          className="p-1 hover:bg-surface-2 rounded transition-colors"
                          title="Speak"
                          aria-label="Read this reply aloud"
                        >
                          <Volume2 className={`w-3 h-3 ${isSpeaking ? 'text-violet-400 animate-pulse' : 'text-ink-muted'}`} />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            
            {/* One-tap starters — shown only while the chat is pristine */}
            {messages.length === 1 && messages[0].id === '0' && !isLoading && (
              <div className="flex flex-wrap gap-2 ps-11">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => sendMessage(q)}
                    className="px-3 py-1.5 rounded-full text-xs text-start text-ink bg-surface-2 hover:bg-violet-500/10 border border-line hover:border-violet-300 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            {isLoading && messages[messages.length - 1]?.content === '' && (
              <div className="flex items-center gap-2 text-ink-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm">Thinking...</span>
              </div>
            )}
            
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <form onSubmit={handleSubmit} className="p-4 border-t border-line bg-surface-2/50">
            <div className="flex items-center gap-2">
              {/* Voice Button - only show if user has voice permission */}
              {canUseVoice ? (
                <button
                  type="button"
                  onClick={toggleRecording}
                  disabled={isProcessingVoice || isLoading}
                  className={`relative p-3 rounded-xl transition-all ${
                    isRecording 
                      ? 'bg-rose-500 text-white scale-110 animate-pulse'
                      : isProcessingVoice
                      ? 'bg-amber-500 text-white'
                      : 'bg-surface-2 hover:bg-surface-3 text-ink hover:scale-105'
                  }`}
                  title={isRecording ? "Click to stop recording" : "Click to start recording"}
                  aria-label={isRecording ? 'Stop voice recording' : 'Start voice recording'}
                  aria-pressed={isRecording}
                >
                  {isProcessingVoice ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : isRecording ? (
                    <MicOff className="w-5 h-5" />
                  ) : (
                    <Mic className="w-5 h-5" />
                  )}
                  {isRecording && (
                    <span className="absolute -top-1 -end-1 flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500"></span>
                    </span>
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  disabled
                  className="relative p-3 rounded-xl bg-surface-2/60 text-ink-muted cursor-not-allowed"
                  title="Voice chat not available for your role"
                >
                  <Lock className="w-5 h-5" />
                </button>
              )}
              
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={isRecording ? "Recording... Click mic to stop" : "Ask about sales, trends, insights..."}
                className="flex-1 bg-surface border border-line rounded-xl px-4 py-3 text-ink placeholder-ink-muted focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-500 transition-colors"
                disabled={isLoading || isRecording}
              />
              
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="p-3 bg-[var(--ai-600)] rounded-xl text-white disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
                aria-label="Send message"
              >
                {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
              </button>
            </div>
            
            {isRecording && (
              <div className="mt-2 flex items-center justify-between bg-rose-50 border border-rose-200 dark:bg-rose-500/15 dark:border-rose-500/30 rounded-lg px-3 py-2">
                <div className="flex items-center gap-2 text-rose-700 dark:text-rose-300 text-sm">
                  <span className="w-3 h-3 bg-rose-500 rounded-full animate-pulse" />
                  <span className="font-medium">Recording... Speak now.</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-rose-600 dark:text-rose-300 text-sm font-mono tabular-nums">{recordingDuration.toFixed(1)}s</span>
                  <button
                    type="button"
                    onClick={stopRecording}
                    className="text-rose-700 dark:text-rose-300 text-xs bg-rose-100 hover:bg-rose-200 dark:bg-rose-500/30 dark:hover:bg-rose-500/50 px-2 py-1 rounded-lg"
                  >
                    Click mic to stop
                  </button>
                </div>
              </div>
            )}

            {isProcessingVoice && (
              <div className="mt-2 flex items-center gap-2 bg-amber-50 border border-amber-200 dark:bg-amber-500/15 dark:border-amber-500/30 rounded-lg px-3 py-2">
                <Loader2 className="w-4 h-4 text-amber-700 dark:text-amber-300 animate-spin" />
                <span className="text-amber-700 dark:text-amber-300 text-sm">Processing your voice...</span>
              </div>
            )}
          </form>
        </>
      )}
    </motion.aside>
  );
}
