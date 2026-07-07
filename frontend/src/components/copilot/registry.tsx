'use client';

/**
 * Open homepage widget registry (Sage Copilot).
 *
 * Replaces the closed, inline `ZONE_REGISTRY` that lived in `/today`. Surfaces
 * register their widgets here by string type; the homepage resolves each zone in
 * the server experience config against this registry.
 *
 * Design contract:
 * - EXTENSIBLE: any surface (this phase's `/today`, later the Copilot feed
 *   widgets) can `registerWidget(type, Component)` without editing a central
 *   switch.
 * - FORWARD-COMPATIBLE: an unknown type resolves to `null` and is skipped, so a
 *   backend config may name a widget a given frontend build doesn't ship yet
 *   (e.g. `business_health`, `risks`, `growth` arriving with the feed) without
 *   breaking the page. Old frontends tolerate new configs; new frontends tolerate
 *   old configs.
 *
 * A widget is a pure presentational component handed the resolved experience
 * config and its own zone spec — it fetches only existing endpoints.
 */
import type { ExperienceConfig, ZoneSpec } from '@/contexts/ExperienceContext';

export interface WidgetProps {
  config: ExperienceConfig;
  spec: ZoneSpec;
}

export type WidgetComponent = (props: WidgetProps) => JSX.Element | null;

const registry: Record<string, WidgetComponent> = {};

/** Register (or override) a single homepage widget by type. */
export function registerWidget(type: string, component: WidgetComponent): void {
  registry[type] = component;
}

/** Register several widgets at once (convenience for a surface's own set). */
export function registerWidgets(entries: Record<string, WidgetComponent>): void {
  Object.assign(registry, entries);
}

/** The widget for a type, or `null` when none is registered (skip gracefully). */
export function resolveWidget(type: string): WidgetComponent | null {
  return registry[type] ?? null;
}

/** Types currently registered — handy for tests/diagnostics. */
export function registeredWidgetTypes(): string[] {
  return Object.keys(registry);
}
