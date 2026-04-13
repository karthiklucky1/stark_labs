/**
 * Mark II Studio — Live Preview Panel
 * WebviewPanel that displays the sandbox preview URL or build status.
 */
import * as vscode from 'vscode';
import { getPreview, Session } from './apiClient';

export class PreviewPanel {
  private panel: vscode.WebviewPanel | null = null;
  private currentSessionId: string | null = null;
  private refreshTimer: NodeJS.Timeout | null = null;

  /**
   * Open or update the preview panel for a session.
   */
  async show(session: Session, extensionUri: vscode.Uri): Promise<void> {
    this.currentSessionId = session.id;

    if (!this.panel) {
      this.panel = vscode.window.createWebviewPanel(
        'markiiPreview',
        `Mark II — Preview`,
        vscode.ViewColumn.Beside,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
        }
      );

      this.panel.onDidDispose(() => {
        this.panel = null;
        this.currentSessionId = null;
        if (this.refreshTimer) {
          clearInterval(this.refreshTimer);
          this.refreshTimer = null;
        }
      });
    }

    this.panel.title = `Mark II — Preview (${session.id.slice(0, 8)})`;
    await this._updateContent(session);

    // Poll for preview URL updates
    this.refreshTimer = setInterval(() => this._pollPreview(), 5000);
  }

  /**
   * Close the preview panel.
   */
  close(): void {
    this.panel?.dispose();
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
    }
  }

  private async _pollPreview(): Promise<void> {
    if (!this.currentSessionId || !this.panel) { return; }

    try {
      const preview = await getPreview(this.currentSessionId);
      if (preview.preview_url && preview.status === 'active') {
        this.panel.webview.html = this._getIframeHtml(preview.preview_url);
        // Stop polling once we have a preview
        if (this.refreshTimer) {
          clearInterval(this.refreshTimer);
          this.refreshTimer = null;
        }
      }
    } catch {
      // Ignore poll errors
    }
  }

  private async _updateContent(session: Session): Promise<void> {
    if (!this.panel) { return; }

    try {
      const preview = await getPreview(session.id);
      if (preview.preview_url && preview.status === 'active') {
        this.panel.webview.html = this._getIframeHtml(preview.preview_url);
      } else {
        this.panel.webview.html = this._getStatusHtml(session);
      }
    } catch {
      this.panel.webview.html = this._getStatusHtml(session);
    }
  }

  private _getIframeHtml(url: string): string {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { margin: 0; padding: 0; overflow: hidden; background: #0a0e1a; }
    iframe { width: 100%; height: 100vh; border: none; }
    .toolbar {
      position: fixed; top: 0; left: 0; right: 0; height: 32px;
      background: rgba(15, 23, 42, 0.95); backdrop-filter: blur(8px);
      display: flex; align-items: center; padding: 0 12px;
      font-family: 'Segoe UI', sans-serif; font-size: 12px;
      color: #94a3b8; border-bottom: 1px solid rgba(148,163,184,0.1);
      z-index: 100;
    }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; margin-right: 8px; }
    .url { color: #64748b; margin-left: 8px; }
    iframe { margin-top: 32px; height: calc(100vh - 32px); }
  </style>
</head>
<body>
  <div class="toolbar">
    <div class="dot"></div>
    <span>Live Preview</span>
    <span class="url">${url}</span>
  </div>
  <iframe src="${url}" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
</body>
</html>`;
  }

  private _getStatusHtml(session: Session): string {
    const statusMessages: Record<string, string> = {
      created: '🔵 Session created — waiting for input',
      interviewing: '💬 Interview in progress — Claude is gathering requirements',
      spec_review: '📋 Requirements ready — waiting for confirmation',
      building: '⚙️ Building... OpenAI and DeepSeek are generating code',
      judging: '⚖️ Judging... Claude is evaluating candidates',
      hardening: '🛡️ Hardening... Mark II adversarial loop is running',
      complete: '✅ Build complete! Artifacts ready for download.',
      failed: '❌ Build failed. Check the event stream for details.',
    };

    const message = statusMessages[session.status] || `Status: ${session.status}`;

    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body {
      margin: 0; padding: 40px; background: #0a0e1a;
      font-family: 'Segoe UI', sans-serif; color: #f1f5f9;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      min-height: calc(100vh - 80px);
    }
    .card {
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(148, 163, 184, 0.1);
      border-radius: 16px; padding: 40px; text-align: center;
      max-width: 400px; width: 100%;
      backdrop-filter: blur(16px);
    }
    .status { font-size: 18px; margin-bottom: 12px; }
    .session-id { font-size: 12px; color: #64748b; font-family: monospace; }
    .profile { font-size: 13px; color: #94a3b8; margin-top: 8px; }
    @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
    .loading { animation: pulse 2s ease-in-out infinite; }
  </style>
</head>
<body>
  <div class="card">
    <div class="status ${['building', 'hardening', 'judging'].includes(session.status) ? 'loading' : ''}">${message}</div>
    <div class="profile">${session.profile_type || session.intake_mode}</div>
    <div class="session-id">${session.id}</div>
  </div>
</body>
</html>`;
  }

  dispose(): void {
    this.close();
  }
}
