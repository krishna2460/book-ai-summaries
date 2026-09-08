'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  getDocument,
  queryDocument,
  listQueries,
  type DocumentOut,
  type QueryOut,
  type ChunkCitation,
} from '@/lib/api';
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
    hour: '2-digit',
    minute: '2-digit',
  });
}

function CitationCard({ citation }: { citation: ChunkCitation }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <button
      className={styles.citation}
      onClick={() => setExpanded(!expanded)}
      type="button"
    >
      <div className={styles.citationHeader}>
        <span className={styles.citationTag}>
          Chunk {citation.chunk_index}
        </span>
        {citation.page_start && (
          <span className={styles.citationPages}>
            Pages {citation.page_start}–{citation.page_end}
          </span>
        )}
        <span className={styles.citationToggle}>
          {expanded ? '▾' : '▸'}
        </span>
      </div>
      {expanded && (
        <p className={styles.citationPreview}>{citation.content_preview}</p>
      )}
    </button>
  );
}

export default function DocumentDetailPage() {
  const params = useParams();
  const documentId = params.id as string;

  const [doc, setDoc] = useState<DocumentOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Chat state
  const [queries, setQueries] = useState<QueryOut[]>([]);
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Load document
  const loadDocument = useCallback(async () => {
    try {
      const d = await getDocument(documentId);
      setDoc(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load document');
    } finally {
      setLoading(false);
    }
  }, [documentId]);

  // Poll for processing status
  useEffect(() => {
    loadDocument();
  }, [loadDocument]);

  useEffect(() => {
    if (!doc) return;
    if (doc.status === 'uploaded' || doc.status === 'processing') {
      const interval = setInterval(async () => {
        try {
          const updated = await getDocument(documentId);
          setDoc(updated);
          if (updated.status === 'completed' || updated.status === 'failed') {
            clearInterval(interval);
          }
        } catch {
          // ignore poll errors
        }
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [doc?.status, documentId]);

  // Load existing queries when document is completed
  useEffect(() => {
    if (doc?.status === 'completed') {
      listQueries(documentId).then(setQueries).catch(() => {});
    }
  }, [doc?.status, documentId]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [queries]);

  const handleAsk = useCallback(async () => {
    if (!question.trim() || asking) return;

    setAsking(true);
    const q = question.trim();
    setQuestion('');

    try {
      const result = await queryDocument(documentId, q);
      setQueries((prev) => [result, ...prev]);
    } catch (err) {
      // Show error as a failed query entry
      setQueries((prev) => [
        {
          id: crypto.randomUUID(),
          document_id: documentId,
          question: q,
          answer: null,
          citations: [],
          status: 'failed' as const,
          error_message: err instanceof Error ? err.message : 'Query failed',
          created_at: new Date().toISOString(),
        },
        ...prev,
      ]);
    } finally {
      setAsking(false);
    }
  }, [question, asking, documentId]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleAsk();
      }
    },
    [handleAsk],
  );

  // Loading
  if (loading) {
    return (
      <main className="section">
        <div className="container">
          <div className={styles.loadingState}>
            <div className="spinner" style={{ width: 32, height: 32 }} />
            <p className="text-muted">Loading document…</p>
          </div>
        </div>
      </main>
    );
  }

  // Error
  if (error || !doc) {
    return (
      <main className="section">
        <div className="container">
          <div className={styles.errorState}>
            <p>⚠️ {error || 'Document not found'}</p>
            <Link href="/documents" className="btn btn-secondary">
              Back to Library
            </Link>
          </div>
        </div>
      </main>
    );
  }

  const isReady = doc.status === 'completed';
  const isProcessing = doc.status === 'uploaded' || doc.status === 'processing';

  return (
    <main className="section">
      <div className="container">
        <div className={styles.layout}>
          {/* ── Left Panel: Document Info ─────────────────── */}
          <div className={styles.infoPanel}>
            <Link href="/documents" className={styles.backLink}>
              ← Back to Library
            </Link>

            <div className={`glass-card ${styles.docCard} animate-fade-in`}>
              <div className={styles.docHeader}>
                <span className={styles.docIcon}>
                  {doc.file_type === 'pdf' ? '📕' : '📘'}
                </span>
                <div>
                  <h1 className={styles.docTitle}>{doc.filename}</h1>
                  <div className={styles.docMeta}>
                    <StatusBadge status={doc.status} />
                    <span className="text-sm text-muted">
                      {formatDate(doc.created_at)}
                    </span>
                  </div>
                </div>
              </div>

              <div className={styles.docStats}>
                {doc.file_size_bytes && (
                  <div className={styles.stat}>
                    <span className={styles.statLabel}>Size</span>
                    <span className={styles.statValue}>
                      {(doc.file_size_bytes / (1024 * 1024)).toFixed(1)} MB
                    </span>
                  </div>
                )}
                {doc.page_count && (
                  <div className={styles.stat}>
                    <span className={styles.statLabel}>Pages</span>
                    <span className={styles.statValue}>{doc.page_count}</span>
                  </div>
                )}
                {doc.chunk_count > 0 && (
                  <div className={styles.stat}>
                    <span className={styles.statLabel}>Chunks</span>
                    <span className={styles.statValue}>{doc.chunk_count}</span>
                  </div>
                )}
              </div>

              {/* Processing state */}
              {isProcessing && (
                <div className={styles.processingBanner}>
                  <div className={styles.processingIcon}>
                    <span className="spinner" />
                  </div>
                  <div>
                    <p className={styles.processingTitle}>Processing your book…</p>
                    <p className={styles.processingHint}>
                      Parsing, chunking, embedding, and summarizing. This may take a few minutes.
                    </p>
                  </div>
                </div>
              )}

              {/* Failed state */}
              {doc.status === 'failed' && (
                <div className={styles.failedBanner}>
                  <p>❌ Processing failed</p>
                  {doc.error_message && (
                    <p className="text-sm">{doc.error_message}</p>
                  )}
                </div>
              )}

              {/* Summary */}
              {doc.summary && (
                <div className={styles.summarySection}>
                  <h2 className={styles.summaryTitle}>
                    <span className={styles.summaryIcon}>✨</span>
                    AI Summary
                  </h2>
                  <p className={styles.summaryText}>{doc.summary}</p>
                </div>
              )}
            </div>
          </div>

          {/* ── Right Panel: Q&A Chat ────────────────────── */}
          <div className={styles.chatPanel}>
            <div className={`glass-card ${styles.chatCard} animate-fade-in`}>
              <div className={styles.chatHeader}>
                <h2 className="heading-3">
                  💬 Ask Questions
                </h2>
                {!isReady && (
                  <span className="text-sm text-muted">
                    Available after processing
                  </span>
                )}
              </div>

              {/* Chat Messages */}
              <div className={styles.chatMessages} id="chat-messages">
                {queries.length === 0 && isReady && (
                  <div className={styles.chatEmpty}>
                    <p className="text-muted">
                      Ask a question about this book and get answers with citations.
                    </p>
                    <div className={styles.suggestions}>
                      {[
                        'What is the main argument?',
                        'Summarize chapter 1',
                        'What are the key takeaways?',
                      ].map((s) => (
                        <button
                          key={s}
                          className={styles.suggestion}
                          onClick={() => setQuestion(s)}
                          type="button"
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {[...queries].reverse().map((q) => (
                  <div key={q.id} className={styles.chatExchange}>
                    {/* User Question */}
                    <div className={styles.messageBubbleUser}>
                      <p>{q.question}</p>
                    </div>

                    {/* AI Answer */}
                    <div className={styles.messageBubbleAI}>
                      {q.status === 'completed' && q.answer ? (
                        <>
                          <p className={styles.answerText}>{q.answer}</p>
                          {q.citations.length > 0 && (
                            <div className={styles.citations}>
                              <p className={styles.citationsLabel}>
                                📎 Sources ({q.citations.length})
                              </p>
                              {q.citations.map((c, i) => (
                                <CitationCard key={i} citation={c} />
                              ))}
                            </div>
                          )}
                        </>
                      ) : q.status === 'failed' ? (
                        <p className={styles.errorText}>
                          ⚠️ {q.error_message || 'Query failed'}
                        </p>
                      ) : (
                        <div className={styles.thinkingDots}>
                          <span /><span /><span />
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {asking && (
                  <div className={styles.chatExchange}>
                    <div className={styles.messageBubbleAI}>
                      <div className={styles.thinkingDots}>
                        <span /><span /><span />
                      </div>
                    </div>
                  </div>
                )}

                <div ref={chatEndRef} />
              </div>

              {/* Chat Input */}
              <div className={styles.chatInputContainer}>
                <textarea
                  className={`input ${styles.chatInput}`}
                  placeholder={isReady ? 'Ask a question about this book…' : 'Processing…'}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={!isReady || asking}
                  rows={1}
                  id="chat-input"
                />
                <button
                  className={`btn btn-primary ${styles.sendBtn}`}
                  onClick={handleAsk}
                  disabled={!isReady || !question.trim() || asking}
                  id="send-query-btn"
                >
                  {asking ? (
                    <span className="spinner" />
                  ) : (
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="22" y1="2" x2="11" y2="13" />
                      <polygon points="22 2 15 22 11 13 2 9 22 2" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
