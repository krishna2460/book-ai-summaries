'use client';

import Link from 'next/link';
import styles from './page.module.css';

export default function Home() {
  return (
    <main>
      {/* Hero Section */}
      <section className={styles.hero}>
        <div className="container">
          <div className={styles.heroContent}>
            <div className={styles.heroBadge}>
              <span className={styles.heroBadgeDot} />
              AI-Powered Book Intelligence
            </div>

            <h1 className={`heading-1 ${styles.heroTitle}`}>
              Understand Any Book in{' '}
              <span className="text-gradient">Minutes</span>
            </h1>

            <p className={styles.heroDescription}>
              Upload your PDF or DOCX books and get instant AI-generated summaries.
              Ask questions and receive precise, cited answers — all powered by
              advanced RAG technology.
            </p>

            <div className={styles.heroCTA}>
              <Link href="/upload" className="btn btn-primary btn-lg" id="hero-upload-btn">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                Upload a Book
              </Link>
              <Link href="/documents" className="btn btn-secondary btn-lg" id="hero-library-btn">
                Browse Library
              </Link>
            </div>
          </div>

          {/* Floating Feature Cards */}
          <div className={`${styles.features} stagger`}>
            <div className={`glass-card ${styles.featureCard} animate-fade-in-up`}>
              <div className={styles.featureIcon}>⚡</div>
              <h3 className="heading-3">Instant Summaries</h3>
              <p className="text-muted text-sm">
                Multi-pass map-reduce AI distils entire books into concise 100-word summaries.
              </p>
            </div>

            <div className={`glass-card ${styles.featureCard} animate-fade-in-up`}>
              <div className={styles.featureIcon}>💬</div>
              <h3 className="heading-3">Ask Questions</h3>
              <p className="text-muted text-sm">
                Chat with your books. Get precise answers with page-level citations from the source.
              </p>
            </div>

            <div className={`glass-card ${styles.featureCard} animate-fade-in-up`}>
              <div className={styles.featureIcon}>🔒</div>
              <h3 className="heading-3">Secure & Private</h3>
              <p className="text-muted text-sm">
                Your documents are scoped to your account. No cross-user visibility, ever.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className={`section ${styles.howItWorks}`}>
        <div className="container">
          <h2 className={`heading-2 ${styles.sectionTitle}`}>
            How It <span className="text-gradient">Works</span>
          </h2>

          <div className={styles.steps}>
            <div className={styles.step}>
              <div className={styles.stepNumber}>01</div>
              <h3 className="heading-3">Upload</h3>
              <p className="text-muted text-sm">
                Drag and drop your PDF or DOCX file. We support books up to 100 MB.
              </p>
            </div>

            <div className={styles.stepArrow}>→</div>

            <div className={styles.step}>
              <div className={styles.stepNumber}>02</div>
              <h3 className="heading-3">Process</h3>
              <p className="text-muted text-sm">
                AI chunks, embeds, and summarizes your book using multi-stage pipelines.
              </p>
            </div>

            <div className={styles.stepArrow}>→</div>

            <div className={styles.step}>
              <div className={styles.stepNumber}>03</div>
              <h3 className="heading-3">Explore</h3>
              <p className="text-muted text-sm">
                Read the summary, ask questions, and dive deep into any topic from the book.
              </p>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
