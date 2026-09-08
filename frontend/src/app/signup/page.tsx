'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { signup } from '@/lib/api';
import { useAuth } from '@/lib/auth-context';
import styles from './page.module.css';

export default function SignupPage() {
  const router = useRouter();
  const { loginUser } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const result = await signup(email, password, displayName || undefined);
      await loginUser(result.access_token);
      router.push('/documents');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Signup failed');
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
              <h1 className="heading-2">Create an account</h1>
              <p className="text-muted">Start summarizing books with AI</p>
            </div>

            <form onSubmit={handleSubmit} className={styles.form} id="signup-form">
              <div className={styles.field}>
                <label htmlFor="signup-name" className="input-label">
                  Display Name <span className="text-muted">(optional)</span>
                </label>
                <input
                  id="signup-name"
                  type="text"
                  className="input"
                  placeholder="Jane Doe"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  autoFocus
                />
              </div>

              <div className={styles.field}>
                <label htmlFor="signup-email" className="input-label">
                  Email
                </label>
                <input
                  id="signup-email"
                  type="email"
                  className={`input ${error ? 'input-error' : ''}`}
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              <div className={styles.field}>
                <label htmlFor="signup-password" className="input-label">
                  Password
                </label>
                <input
                  id="signup-password"
                  type="password"
                  className={`input ${error ? 'input-error' : ''}`}
                  placeholder="Minimum 8 characters"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                />
              </div>

              {error && (
                <p className="error-text" id="signup-error">{error}</p>
              )}

              <button
                type="submit"
                className={`btn btn-primary btn-lg ${styles.submitBtn}`}
                disabled={loading}
                id="signup-submit"
              >
                {loading ? (
                  <>
                    <span className="spinner" />
                    Creating account…
                  </>
                ) : (
                  'Create Account'
                )}
              </button>
            </form>

            <p className={styles.footer}>
              Already have an account?{' '}
              <Link href="/login">Sign in</Link>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
