/**
 * Mark II Studio — API Client
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }
  return res.json();
}

// ── Sessions ─────────────────────────────────────
export const api = {
  createSession: (data: { intake_mode: string; prompt?: string; github_url?: string }) =>
    request('/sessions', { method: 'POST', body: JSON.stringify(data) }),

  getSession: (id: string) =>
    request(`/sessions/${id}`),

  submitIntake: (id: string, data: { files?: Record<string, string>; github_url?: string }) =>
    request(`/sessions/${id}/intake`, { method: 'POST', body: JSON.stringify(data) }),

  answerInterview: (id: string, message: string) =>
    request(`/sessions/${id}/interview/answer`, { method: 'POST', body: JSON.stringify({ message }) }),

  confirmRequirements: (id: string) =>
    request(`/sessions/${id}/requirements/confirm`, { method: 'POST', body: JSON.stringify({ confirmed: true }) }),

  startBuild: (id: string) =>
    request(`/sessions/${id}/build/start`, { method: 'POST' }),

  submitComment: (id: string, comment: string) =>
    request(`/sessions/${id}/comments`, { method: 'POST', body: JSON.stringify({ comment }) }),

  startHardening: (id: string) =>
    request(`/sessions/${id}/hardening/start`, { method: 'POST' }),

  getPreview: (id: string) =>
    request(`/sessions/${id}/preview`),

  getArtifacts: (id: string) =>
    request(`/sessions/${id}/artifacts`),

  getHealth: () =>
    request('/health'),
};

// ── SSE Stream URL ───────────────────────────────
export function getSSEUrl(sessionId: string): string {
  return `${API_URL}/sessions/${sessionId}/events`;
}
