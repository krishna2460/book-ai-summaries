/**
 * API client — typed fetch wrapper for the FastAPI backend.
 *
 * Features:
 *  • Auto-injects JWT from localStorage
 *  • Typed response generics
 *  • Centralised error handling
 *  • Base URL from env or default
 */

function getApiBase(): string {
  if (typeof window !== 'undefined') {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
}

// ── Types ────────────────────────────────────────────────────

export interface DocumentOut {
  id: string;
  filename: string;
  file_type: string;
  file_size_bytes: number | null;
  page_count: number | null;
  status: 'uploaded' | 'processing' | 'completed' | 'failed';
  error_message: string | null;
  summary: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface DocumentUploadResponse {
  id: string;
  status: string;
  message: string;
}

export interface QueryRequest {
  question: string;
}

export interface ChunkCitation {
  chunk_id: string;
  chunk_index: number;
  page_start: number | null;
  page_end: number | null;
  content_preview: string;
}

export interface QueryOut {
  id: string;
  document_id: string;
  question: string;
  answer: string | null;
  citations: ChunkCitation[];
  status: 'pending' | 'completed' | 'failed';
  error_message: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserOut {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
}

export interface ApiError {
  detail: string;
}

// ── Helper ───────────────────────────────────────────────────

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token');
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };

  // Don't set Content-Type for FormData (browser sets multipart boundary)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(`${getApiBase()}${path}`, {
    ...options,
    headers,
    credentials: 'include',  // send session cookie
  });

  if (!res.ok) {
    let detail = `Request failed with status ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore JSON parse error
    }
    throw new Error(detail);
  }

  return res.json() as Promise<T>;
}

// ── Auth ─────────────────────────────────────────────────────

export async function signup(
  email: string,
  password: string,
  displayName?: string,
): Promise<TokenResponse> {
  return apiFetch<TokenResponse>('/auth/signup', {
    method: 'POST',
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
}

export async function login(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return apiFetch<TokenResponse>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function getMe(): Promise<UserOut> {
  return apiFetch<UserOut>('/auth/me');
}

export async function migrateSession(): Promise<{ migrated: number }> {
  return apiFetch('/auth/migrate-session', { method: 'POST' });
}

// ── Documents ────────────────────────────────────────────────

export async function uploadDocument(
  file: File,
  onProgress?: (pct: number) => void,
): Promise<DocumentUploadResponse> {
  const token = getToken();

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${getApiBase()}/documents/upload`);

    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }
    xhr.withCredentials = true;

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          reject(new Error(body.detail || `Upload failed: ${xhr.status}`));
        } catch {
          reject(new Error(`Upload failed: ${xhr.status}`));
        }
      }
    });

    xhr.addEventListener('error', () => reject(new Error('Network error during upload')));

    const formData = new FormData();
    formData.append('file', file);
    xhr.send(formData);
  });
}

export async function getDocument(id: string): Promise<DocumentOut> {
  return apiFetch<DocumentOut>(`/documents/${id}`);
}

export async function getDocumentStatus(
  id: string,
): Promise<{ document_id: string; status: string; error_message: string | null }> {
  return apiFetch(`/documents/${id}/status`);
}

export async function listDocuments(): Promise<DocumentOut[]> {
  return apiFetch<DocumentOut[]>('/documents');
}

// ── Queries ──────────────────────────────────────────────────

export async function queryDocument(
  documentId: string,
  question: string,
): Promise<QueryOut> {
  return apiFetch<QueryOut>(`/documents/${documentId}/query`, {
    method: 'POST',
    body: JSON.stringify({ question }),
  });
}

export async function listQueries(documentId: string): Promise<QueryOut[]> {
  return apiFetch<QueryOut[]>(`/documents/${documentId}/queries`);
}
