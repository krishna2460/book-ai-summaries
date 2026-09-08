'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { listDocuments, type DocumentOut } from '@/lib/api';
import styles from './page.module.css';

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge badge-${status}`}>
      <span className="badge-dot" />
      {status}
    </span>
  );
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function formatSize(bytes: number | null) {
  if (!bytes) return '—';
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDocuments();
  }, []);

  async function loadDocuments() {
    setLoading(true);
    try {
      const docs = await listDocuments();
      setDocuments(docs);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="section">
      <div className="container">
        <div className={styles.header}>
          <div>
            <h1 className="heading-2">
              Your <span className="text-gradient">Library</span>
            </h1>
            <p className="text-muted text-sm">
              {documents.length} document{documents.length !== 1 ? 's' : ''}
            </p>
          </div>
          <Link href="/upload" className="btn btn-primary" id="library-upload-btn">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Upload
          </Link>
        </div>

        {/* Loading Skeleton */}
        {loading && (
          <div className={styles.grid}>
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className={`glass-card ${styles.card}`}>
                <div className={`skeleton ${styles.skeletonIcon}`} />
                <div className={`skeleton ${styles.skeletonTitle}`} />
                <div className={`skeleton ${styles.skeletonMeta}`} />
                <div className={`skeleton ${styles.skeletonBadge}`} />
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className={styles.errorBox}>
            <p>⚠️ {error}</p>
            <button className="btn btn-secondary btn-sm" onClick={loadDocuments}>
              Retry
            </button>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && documents.length === 0 && (
          <div className={styles.empty}>
            <div className={styles.emptyIcon}>📚</div>
            <h3 className="heading-3">No documents yet</h3>
            <p className="text-muted">
              Upload your first book to get started.
            </p>
            <Link href="/upload" className="btn btn-primary">
              Upload a Book
            </Link>
          </div>
        )}

        {/* Document Grid */}
        {!loading && !error && documents.length > 0 && (
          <div className={`${styles.grid} stagger`}>
            {documents.map((doc) => (
              <Link
                key={doc.id}
                href={`/documents/${doc.id}`}
                className={`glass-card ${styles.card} animate-fade-in`}
                id={`doc-card-${doc.id}`}
              >
                <div className={styles.cardIcon}>
                  {doc.file_type === 'pdf' ? '📕' : '📘'}
                </div>

                <div className={styles.cardBody}>
                  <h3 className={styles.cardTitle}>{doc.filename}</h3>
                  <div className={styles.cardMeta}>
                    <span>{formatSize(doc.file_size_bytes)}</span>
                    <span>•</span>
                    <span>{formatDate(doc.created_at)}</span>
                    {doc.chunk_count > 0 && (
                      <>
                        <span>•</span>
                        <span>{doc.chunk_count} chunks</span>
                      </>
                    )}
                  </div>
                </div>

                <StatusBadge status={doc.status} />

                {doc.summary && (
                  <p className={styles.cardSummary}>
                    {doc.summary.slice(0, 120)}…
                  </p>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
