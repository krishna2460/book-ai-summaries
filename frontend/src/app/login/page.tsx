'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { login } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

export default function LoginPage() {
  const router = useRouter();
  const { loginUser } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = await login(email, password);
      await loginUser(result.access_token);
      router.push('/documents');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="section">
      <div className="container">
        <div className={styles.wrapper}>
          <div className={`glass-card ${styles.card} animate-scale-in`}>
            <div className={styles.header}>
              <h1 className="heading-2">Welcome back</h1>
              <p className="text-muted">Sign in to your BookAI account</p>
            </div>

            <form onSubmit={handleSubmit} className={styles.form} id="login-form">
              <div className={styles.field}>
                <label htmlFor="login-email" className="input-label">
                  Email
                </label>
                <input
                  id="login-email"
                  type="email"
                  className={`input ${error ? 'input-error' : ''}`}
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                />
              </div>

              <div className={styles.field}>
                <label htmlFor="login-password" className="input-label">
                  Password
                </label>
                <input
                  id="login-password"
                  type="password"
                  className={`input ${error ? 'input-error' : ''}`}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>

              {error && (
                <p className="error-text" id="login-error">{error}</p>
              )}

              <button
                type="submit"
                className={`btn btn-primary btn-lg ${styles.submitBtn}`}
                disabled={loading}
                id="login-submit"
              >
                {loading ? (
                  <>
                    <span className="spinner" />
                    Signing in…
                  </>
                ) : (
                  'Sign In'
                )}
              </button>
            </form>

            <p className={styles.footer}>
              Don&apos;t have an account?{' '}
              <Link href="/signup">Create one</Link>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
