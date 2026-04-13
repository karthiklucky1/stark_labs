/**
 * Mark II Studio — VS Code API Client
 * Thin HTTP client wrapping the backend REST API.
 */
import * as vscode from 'vscode';
import * as https from 'https';
import * as http from 'http';

export interface Session {
  id: string;
  intake_mode: string;
  profile_type: string | null;
  status: string;
  github_repo_url: string | null;
  original_prompt: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChangeRequest {
  id: string;
  user_comment: string;
  classification: string;
  status: string;
}

export interface PreviewInfo {
  session_id: string;
  preview_url: string | null;
  status: string;
}

export function getApiUrl(): string {
  return vscode.workspace.getConfiguration('markii').get<string>('apiUrl') || 'http://localhost:8000';
}

async function request<T>(path: string, options?: { method?: string; body?: string }): Promise<T> {
  const url = `${getApiUrl()}${path}`;
  return new Promise((resolve, reject) => {
    const parsedUrl = new URL(url);
    const client = parsedUrl.protocol === 'https:' ? https : http;

    const req = client.request(
      {
        hostname: parsedUrl.hostname,
        port: parsedUrl.port,
        path: parsedUrl.pathname + parsedUrl.search,
        method: options?.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => {
          try {
            resolve(JSON.parse(data) as T);
          } catch {
            reject(new Error(`Invalid JSON: ${data.slice(0, 200)}`));
          }
        });
      }
    );
    req.on('error', reject);
    if (options?.body) {
      req.write(options.body);
    }
    req.end();
  });
}

export async function getHealth(): Promise<{ status: string; product: string }> {
  return request('/health');
}

export async function createSession(data: {
  intake_mode: string;
  prompt?: string;
}): Promise<Session> {
  return request('/sessions', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getSession(id: string): Promise<Session> {
  return request(`/sessions/${id}`);
}

export async function submitComment(sessionId: string, comment: string): Promise<ChangeRequest> {
  return request(`/sessions/${sessionId}/comments`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  });
}

export async function getPreview(sessionId: string): Promise<PreviewInfo> {
  return request(`/sessions/${sessionId}/preview`);
}

export async function startBuild(sessionId: string): Promise<{ status: string }> {
  return request(`/sessions/${sessionId}/build/start`, { method: 'POST' });
}

export async function startHardening(sessionId: string): Promise<{ status: string }> {
  return request(`/sessions/${sessionId}/hardening/start`, { method: 'POST' });
}

export async function answerInterview(sessionId: string, message: string): Promise<{ status: string }> {
  return request(`/sessions/${sessionId}/interview/answer`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}
