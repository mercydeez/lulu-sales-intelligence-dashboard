import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import AcceptInvitePage from './page';

// next/navigation hooks are not available outside the Next runtime — mock them.
// No token in the URL exercises the error/empty state.
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(''),
  useRouter: () => ({ push: vi.fn() }),
}));

describe('AcceptInvitePage', () => {
  it('renders an invalid-link state when no token is present', () => {
    render(<AcceptInvitePage />);
    expect(screen.queryByText(/invalid invite link/i)).not.toBeNull();
  });
});
