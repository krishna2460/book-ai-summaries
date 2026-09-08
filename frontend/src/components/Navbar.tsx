'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/lib/auth-context';
import styles from './Navbar.module.css';

export default function Navbar() {
  const pathname = usePathname();
  const { user, isAuthenticated, logoutUser } = useAuth();

  return (
    <nav className={styles.navbar} id="main-navbar">
      <div className={styles.inner}>
        {/* Logo */}
        <Link href="/" className={styles.logo}>
          <span className={styles.logoIcon}>📚</span>
          <span className={styles.logoText}>
            Book<span className={styles.logoAccent}>AI</span>
          </span>
        </Link>

        {/* Nav Links */}
        <div className={styles.links}>
          <Link
            href="/upload"
            className={`${styles.link} ${pathname === '/upload' ? styles.active : ''}`}
          >
            Upload
          </Link>
          <Link
            href="/documents"
            className={`${styles.link} ${pathname === '/documents' ? styles.active : ''}`}
          >
            Library
          </Link>
        </div>

        {/* Auth */}
        <div className={styles.auth}>
          {isAuthenticated ? (
            <div className={styles.userMenu}>
              <span className={styles.userName}>
                {user?.display_name || user?.email?.split('@')[0]}
              </span>
              <button
                onClick={logoutUser}
                className={`btn btn-ghost btn-sm ${styles.logoutBtn}`}
                id="logout-button"
              >
                Log out
              </button>
            </div>
          ) : (
            <div className={styles.authLinks}>
              <Link href="/login" className="btn btn-ghost btn-sm">
                Log in
              </Link>
              <Link href="/signup" className="btn btn-primary btn-sm">
                Sign up
              </Link>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
}
