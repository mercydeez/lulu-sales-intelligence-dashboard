'use client';

import { useTheme, ThemePref } from '@/contexts/ThemeContext';
import { Sun, Moon, Monitor, LucideIcon } from 'lucide-react';

/**
 * Segmented light/dark/system control (E4-2). Mirrors the language toggle's
 * visual language in the Topbar; `showLabels` renders the wider variant used
 * on the settings page. Keyboard operable (native buttons) with aria-pressed.
 */
const OPTIONS: { value: ThemePref; label: string; icon: LucideIcon }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

export interface ThemeToggleProps {
  /** Render text labels next to the icons (settings page variant). */
  showLabels?: boolean;
  className?: string;
}

export function ThemeToggle({ showLabels = false, className = '' }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="group"
      aria-label="Appearance"
      className={`flex items-center rounded-lg border border-line overflow-hidden ${className}`}
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = theme === value;
        return (
          <button
            key={value}
            type="button"
            onClick={() => setTheme(value)}
            aria-pressed={active}
            aria-label={`${label} appearance`}
            title={`${label} appearance`}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold transition-colors ${
              active ? 'bg-teal-600 text-white' : 'text-ink-muted hover:bg-surface-2'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {showLabels && label}
          </button>
        );
      })}
    </div>
  );
}
