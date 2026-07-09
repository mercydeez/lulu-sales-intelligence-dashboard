/**
 * Nav permissions — the client-side RBAC filter for built-in nav items.
 *
 * IMPORTANT: this does NOT decide authorization. The backend does, via the
 * experience manifest and role scoping. This only mirrors the same rules for the
 * built-in fallback nav (when no server manifest is present), exactly as the old
 * sidebar did. Pure predicate — no React.
 */
import type { UserRole } from '@/types/auth';

/** Auth capabilities a caller passes in (from `useAuth`). */
export interface NavAccessCtx {
  hasRole: (roles: UserRole[]) => boolean;
  hasPermission: (permission: string) => boolean;
}

/** The access constraints a nav item may declare. */
export interface NavAccessRule {
  roles?: UserRole[];
  permission?: string;
}

/** True when the caller may see a built-in nav item under the current RBAC. */
export function canAccessNavItem(rule: NavAccessRule, ctx: NavAccessCtx): boolean {
  if (rule.roles && !ctx.hasRole(rule.roles)) return false;
  if (rule.permission && !ctx.hasPermission(rule.permission)) return false;
  return true;
}
