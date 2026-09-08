'use client';

import { useCallback, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { uploadDocument } from '@/lib/api';
import styles from './page.module.css';

const SUPPORTED_TYPES = ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'];
const SUPPORTED_EXTENSIONS = ['.pdf', '.docx'];
const MAX_SIZE_MB = 100;
const MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024;

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const validateFile = useCallback((file: File): string | null => {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!SUPPORTED_EXTENSIONS.includes(ext)) {
      return `Unsupported file type. Please upload a ${SUPPORTED_EXTENSIONS.join(' or ')} file.`;
    }
    if (file.size > MAX_SIZE_BYTES) {
      return `File too large. Maximum size is ${MAX_SIZE_MB} MB.`;
    }
    if (file.size === 0) {
      return 'File is empty.';
    }
    return null;
  }, []);

  const handleFile = useCallback((file: File) => {
    setError(null);
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setSelectedFile(file);
  }, [validateFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragActive(false);
  }, []);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    setUploading(true);
    setProgress(0);
    setError(null);

    try {
      const result = await uploadDocument(selectedFile, setProgress);
      // Redirect to document detail page
      router.push(`/documents/${result.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setUploading(false);
    }
  }, [selectedFile, router]);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <main className="section">
      <div className="container">
        <div className={styles.wrapper}>
          <div className={styles.header}>
            <h1 className="heading-2">
              Upload a <span className="text-gradient">Book</span>
            </h1>
            <p className="text-muted">
              Drop your PDF or DOCX file below. We&apos;ll summarize it and make it searchable.
            </p>
          </div>

          {/* Drop Zone */}
          <div
            className={`glass-card ${styles.dropzone} ${dragActive ? styles.dropzoneActive : ''} ${selectedFile ? styles.dropzoneHasFile : ''}`}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onClick={() => !selectedFile && fileInputRef.current?.click()}
            id="upload-dropzone"
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx"
              onChange={handleInputChange}
              className={styles.fileInput}
              id="file-input"
            />

            {!selectedFile ? (
              <div className={styles.dropContent}>
                <div className={styles.dropIcon}>
                  <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </div>
                <p className={styles.dropText}>
                  <strong>Click to browse</strong> or drag and drop
                </p>
                <p className={styles.dropHint}>
                  PDF or DOCX • Max {MAX_SIZE_MB} MB
                </p>
              </div>
            ) : (
              <div className={styles.filePreview}>
                <div className={styles.fileIcon}>
                  {selectedFile.name.endsWith('.pdf') ? '📕' : '📘'}
                </div>
                <div className={styles.fileInfo}>
                  <p className={styles.fileName}>{selectedFile.name}</p>
                  <p className={styles.fileSize}>{formatSize(selectedFile.size)}</p>
                </div>
                <button
                  className={`btn btn-ghost btn-sm ${styles.removeBtn}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedFile(null);
                    setError(null);
                    setProgress(0);
                    if (fileInputRef.current) fileInputRef.current.value = '';
                  }}
                  id="remove-file-btn"
                >
                  ✕
                </button>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className={styles.errorBox} id="upload-error">
              <span className={styles.errorIcon}>⚠️</span>
              {error}
            </div>
          )}

          {/* Progress */}
          {uploading && (
            <div className={styles.progressContainer}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className={styles.progressText}>{progress}%</span>
            </div>
          )}

          {/* Upload Button */}
          <button
            className={`btn btn-primary btn-lg ${styles.uploadBtn}`}
            onClick={handleUpload}
            disabled={!selectedFile || uploading}
            id="upload-submit-btn"
          >
            {uploading ? (
              <>
                <span className="spinner" />
                Uploading…
              </>
            ) : (
              <>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                Upload & Summarize
              </>
            )}
          </button>
        </div>
      </div>
    </main>
  );
}
