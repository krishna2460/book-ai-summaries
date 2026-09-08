'use client';

/**
 * Auth context — manages JWT state and user profile across the app.
 *
 * Provides:
 *  • user — the current UserOut or null
 *  • isLoading — true while checking auth on mount
 *  • isAuthenticated — convenience boolean
 *  • loginUser(token) — store JWT and fetch profile
 *  • logoutUser() — clear JWT and state
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { getMe, migrateSession, type UserOut } from '@/lib/api';

interface AuthContextType {
  user: UserOut | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  loginUser: (token: string) => Promise<void>;
  logoutUser: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  isAuthenticated: false,
  loginUser: async () => {},
  logoutUser: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Fetch profile with stored token
  const fetchUser = useCallback(async () => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }
    try {
      const me = await getMe();
      setUser(me);
    } catch {
      // Token expired or invalid
      localStorage.removeItem('access_token');
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const loginUser = useCallback(async (token: string) => {
    localStorage.setItem('access_token', token);
    try {
      const me = await getMe();
      setUser(me);
      // Migrate anonymous session documents to the new user
      await migrateSession().catch(() => {});
    } catch {
      localStorage.removeItem('access_token');
      setUser(null);
    }
  }, []);

  const logoutUser = useCallback(() => {
    localStorage.removeItem('access_token');
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        loginUser,
        logoutUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
