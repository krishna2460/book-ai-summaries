'use client';

import { AuthProvider } from '@/lib/auth-context';
import Navbar from '@/components/Navbar';

/**
 * Client-side providers wrapper.
 *
 * Wraps the app with AuthProvider (context) and renders the Navbar.
 * This is a client component because AuthProvider uses hooks.
 */
export function ClientProviders({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <Navbar />
      <div className="page-wrapper">{children}</div>
    </AuthProvider>
  );
}
