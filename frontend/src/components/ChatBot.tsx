'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { 
  MessageSquare, 
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
  Lock
} from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { PRODUCT_NAME, CHATBOT_NAME } from '@/lib/brand';

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

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
}

interface ChatBotProps {
  isOpen: boolean;
  onToggle: () => void;
}

export default function ChatBot({ isOpen, onToggle }: ChatBotProps) {
  const { user, hasPermission, hasRole, authFetch } = useAuth();
  
  // Permission checks - super_admin and regional_manager get full access
  // store_manager gets chat only, analyst gets restricted access
  const canUseChat = hasRole(['super_admin', 'regional_manager', 'store_manager']) || 
                     hasPermission('can_use_ai_chat');
  const canUseVoice = hasRole(['super_admin', 'regional_manager']) || 
                      hasPermission('can_use_voice_chat');
  
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content: `👋 Hi, I'm **${CHATBOT_NAME}**, your ${PRODUCT_NAME} analytics assistant. Ask me anything about your sales data — I'll query it directly and answer with real numbers:\n\n• "What was revenue last week?"\n• "Top 5 stores by revenue"\n• "Which items had the most returns this month?"\n• "Units sold per category"\n\n🎤 **Voice Input**: Click the mic button and speak. Your words will appear in real-time!\n\nWhat would you like to know?`,
      timestamp: new Date()
    }
  ]);
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
                }
              } catch (e) {
                // Skip invalid JSON
              }
            }
          }
        }
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
      setMessages(prev => prev.map(m => 
        m.id === assistantId 
          ? { ...m, content: 'Sorry, I encountered an error. Please try again.', isStreaming: false }
          : m
      ));
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, isLoading, autoSpeak, authFetch]);

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
      content: "👋 Chat cleared! How can I help you?",
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
      addSystemMessage('❌ **Speech recognition not supported.** Please use Chrome, Edge, or Safari browser.');
      return;
    }
    
    recognitionRef.current = recognition;
    let finalTranscript = '';
    
    // Show recording started message
    const recordingMsgId = addSystemMessage('🎤 **Listening...** Speak now! Your words will appear below in real-time.');
    
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
        updateSystemMessage(recordingMsgId, `🎤 **Hearing:** "${currentText}"`);
      }
    };
    
    recognition.onerror = (event: Event & { error: string }) => {
      console.error('Speech recognition error:', event.error);
      
      if (event.error === 'no-speech') {
        updateSystemMessage(recordingMsgId, '⚠️ **No speech detected.** Please speak louder or check your microphone.');
      } else if (event.error === 'audio-capture') {
        updateSystemMessage(recordingMsgId, '❌ **Microphone not found.** Please connect a microphone and try again.');
      } else if (event.error === 'not-allowed') {
        updateSystemMessage(recordingMsgId, '❌ **Microphone access denied.** Please allow microphone access in your browser settings.');
      } else {
        updateSystemMessage(recordingMsgId, `❌ **Error:** ${event.error}`);
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
        updateSystemMessage(recordingMsgId, `✅ **Captured:** "${finalText}"`);
        setInput(finalText);
        
        // Auto-send after a short delay
        setTimeout(() => {
          sendMessage(finalText);
        }, 300);
      } else {
        updateSystemMessage(recordingMsgId, '⚠️ **No speech captured.** Click mic and try again.');
      }
      
      setInterimTranscript('');
    };
    
    try {
      recognition.start();
    } catch (e) {
      console.error('Failed to start recognition:', e);
      addSystemMessage('❌ **Failed to start speech recognition.** Please try again.');
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
      .replace(/`(.*?)`/g, '<code class="bg-[#f3e7e0] px-1 rounded">$1</code>')
      .replace(/\n/g, '<br/>');
  };

  if (!isOpen) return null;

  // If user doesn't have chat permission, show restricted message
  if (!canUseChat) {
    return (
      <div className={`fixed right-0 top-0 h-full bg-surface border-l border-line shadow-2xl flex flex-col z-50 w-[400px]`}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-violet-600 to-purple-600 border-b border-line">
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
            <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-[#f3e7e0]/50 flex items-center justify-center">
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
      </div>
    );
  }

  return (
    <div className={`fixed right-0 top-0 h-full bg-surface border-l border-line shadow-2xl flex flex-col z-50 transition-all duration-300 ${
      isMinimized ? 'w-16' : 'w-[400px]'
    }`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-violet-600 to-purple-600 border-b border-line">
        {!isMinimized && (
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-surface/20 flex items-center justify-center">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-white font-semibold">{CHATBOT_NAME}</h2>
              <p className="text-white/70 text-xs">Sales Assistant</p>
            </div>
          </div>
        )}
        
        <div className="flex items-center gap-1">
          <button
            onClick={() => setIsMinimized(!isMinimized)}
            className="p-2 hover:bg-surface/10 rounded-lg transition-colors"
            title={isMinimized ? "Expand" : "Minimize"}
          >
            {isMinimized ? <Maximize2 className="w-4 h-4 text-white" /> : <Minimize2 className="w-4 h-4 text-white" />}
          </button>
          <button
            onClick={onToggle}
            className="p-2 hover:bg-surface/10 rounded-lg transition-colors"
            title="Close"
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
                  autoSpeak ? 'bg-violet-500/20 text-violet-400' : 'hover:bg-[#f3e7e0] text-ink-muted'
                }`}
                title={autoSpeak ? "Disable auto-speak" : "Enable auto-speak"}
              >
                {autoSpeak ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
              </button>
              <span className="text-xs text-ink-muted">
                {autoSpeak ? 'Voice replies on' : 'Voice replies off'}
              </span>
            </div>
            <button
              onClick={clearChat}
              className="p-2 hover:bg-[#f3e7e0] rounded-lg transition-colors text-ink-muted"
              title="Clear chat"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
                
                <div className={`flex-1 ${message.role === 'user' ? 'text-right' : ''} ${message.role === 'system' ? 'text-center' : ''}`}>
                  <div
                    className={`inline-block max-w-[85%] p-3 rounded-2xl ${
                      message.role === 'user'
                        ? 'bg-teal-50 text-ink rounded-tr-sm'
                        : message.role === 'system'
                        ? 'bg-amber-500/10 text-amber-200 border border-amber-500/30 text-xs'
                        : 'bg-surface-2 text-ink rounded-tl-sm'
                    }`}
                  >
                    <div 
                      className="text-sm leading-relaxed"
                      dangerouslySetInnerHTML={{ __html: formatMessage(message.content) }}
                    />
                    {message.isStreaming && (
                      <span className="inline-block w-2 h-4 bg-violet-400 animate-pulse ml-1" />
                    )}
                  </div>
                  
                  {message.role !== 'system' && (
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-ink-muted">
                        {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      {message.role === 'assistant' && !message.isStreaming && message.content && (
                        <button
                          onClick={() => speakText(message.content)}
                          disabled={isSpeaking}
                          className="p-1 hover:bg-[#f3e7e0] rounded transition-colors"
                          title="Speak"
                        >
                          <Volume2 className={`w-3 h-3 ${isSpeaking ? 'text-violet-400 animate-pulse' : 'text-ink-muted'}`} />
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            
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
                      ? 'bg-rose-500 text-white scale-110 shadow-lg shadow-rose-500/50 animate-pulse' 
                      : isProcessingVoice
                      ? 'bg-amber-500 text-white'
                      : 'bg-[#f3e7e0] hover:bg-[#ecdcd3] text-ink hover:scale-105'
                  }`}
                  title={isRecording ? "Click to stop recording" : "Click to start recording"}
                >
                  {isProcessingVoice ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : isRecording ? (
                    <MicOff className="w-5 h-5" />
                  ) : (
                    <Mic className="w-5 h-5" />
                  )}
                  {isRecording && (
                    <span className="absolute -top-1 -right-1 flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-rose-500"></span>
                    </span>
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  disabled
                  className="relative p-3 rounded-xl bg-[#f3e7e0]/50 text-ink-muted cursor-not-allowed"
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
                placeholder={isRecording ? "🎤 Recording... Click mic to stop" : "Ask about sales, trends, insights..."}
                className="flex-1 bg-surface border border-line rounded-xl px-4 py-3 text-ink placeholder-ink-muted focus:outline-none focus:border-violet-500 transition-colors"
                disabled={isLoading || isRecording}
              />
              
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="p-3 bg-gradient-to-r from-violet-600 to-purple-600 rounded-xl text-white disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
              >
                {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
              </button>
            </div>
            
            {isRecording && (
              <div className="mt-2 flex items-center justify-between bg-rose-500/20 rounded-lg px-3 py-2">
                <div className="flex items-center gap-2 text-rose-400 text-sm">
                  <span className="w-3 h-3 bg-rose-500 rounded-full animate-pulse" />
                  <span className="font-medium">🎤 Recording... Speak now!</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-rose-300 text-sm font-mono">{recordingDuration.toFixed(1)}s</span>
                  <button 
                    type="button"
                    onClick={stopRecording}
                    className="text-rose-400 text-xs bg-rose-500/30 px-2 py-1 rounded hover:bg-rose-500/50"
                  >
                    Click mic to stop
                  </button>
                </div>
              </div>
            )}
            
            {isProcessingVoice && (
              <div className="mt-2 flex items-center gap-2 bg-amber-500/20 rounded-lg px-3 py-2">
                <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />
                <span className="text-amber-400 text-sm">Processing your voice...</span>
              </div>
            )}
          </form>
        </>
      )}
    </div>
  );
}
