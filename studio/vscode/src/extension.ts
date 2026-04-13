/**
 * Mark II Studio — VS Code Extension Entry Point
 *
 * Registers all commands, views, and event handlers.
 * This is a thin client — all business logic lives in the backend API.
 */
import * as vscode from 'vscode';
import { getHealth, createSession, getSession, startBuild, startHardening, Session } from './apiClient';
import { EventStream, SSEEvent } from './eventStream';
import { SessionTreeProvider } from './sessionProvider';
import { handleSendComment } from './commentInput';
import { PreviewPanel } from './previewPanel';

let activeSession: Session | null = null;
let outputChannel: vscode.OutputChannel;
let statusBarItem: vscode.StatusBarItem;
let eventStream: EventStream;
let sessionProvider: SessionTreeProvider;
let previewPanel: PreviewPanel;

export function activate(context: vscode.ExtensionContext) {
  // ── Output Channel ──────────────────────────────────
  outputChannel = vscode.window.createOutputChannel('Mark II Studio', { log: true });
  outputChannel.appendLine('⚡ Mark II Studio extension activated');

  // ── Status Bar ──────────────────────────────────────
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBarItem.text = '$(zap) Mark II';
  statusBarItem.tooltip = 'Mark II Studio — Click to connect';
  statusBarItem.command = 'markii.connect';
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // ── Session Tree ────────────────────────────────────
  sessionProvider = new SessionTreeProvider();
  const treeView = vscode.window.createTreeView('markii-sessions', {
    treeDataProvider: sessionProvider,
    showCollapseAll: true,
  });
  context.subscriptions.push(treeView);

  // ── Event Stream ────────────────────────────────────
  eventStream = new EventStream();
  const eventSub = eventStream.onEvent((event) => {
    _handleEvent(event);
  });
  context.subscriptions.push(eventSub);
  context.subscriptions.push({ dispose: () => eventStream.dispose() });

  // ── Preview Panel ───────────────────────────────────
  previewPanel = new PreviewPanel();
  context.subscriptions.push({ dispose: () => previewPanel.dispose() });

  // ── Commands ────────────────────────────────────────

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.connect', async () => {
      try {
        const health = await getHealth();
        vscode.window.showInformationMessage(
          `✅ Connected to ${health.product} (${health.status})`
        );
        statusBarItem.text = '$(zap) Mark II — Connected';
        statusBarItem.color = '#10b981';
        outputChannel.appendLine(`✅ Connected to ${health.product}`);
        sessionProvider.refresh();
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Mark II: Cannot connect — ${message}`);
        statusBarItem.text = '$(zap) Mark II — Offline';
        statusBarItem.color = '#ef4444';
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.newSession', async () => {
      const intakeMode = await vscode.window.showQuickPick(
        [
          { label: '💡 Describe It', description: 'Prompt mode', value: 'prompt' },
          { label: '📋 Paste Code', description: 'Send workspace files', value: 'paste' },
        ],
        { placeHolder: 'How do you want to start?' }
      );

      if (!intakeMode) { return; }

      let prompt: string | undefined;
      if (intakeMode.value === 'prompt') {
        prompt = await vscode.window.showInputBox({
          prompt: 'Describe what you want to build',
          placeHolder: 'A FastAPI service that...',
          ignoreFocusOut: true,
        });
        if (!prompt) { return; }
      }

      try {
        const session = await createSession({
          intake_mode: intakeMode.value,
          prompt,
        });
        activeSession = session;
        sessionProvider.addSession(session);
        _updateStatusBar(session);
        outputChannel.appendLine(`🆕 Session created: ${session.id}`);

        // Auto-connect to event stream
        if (vscode.workspace.getConfiguration('markii').get<boolean>('autoStream')) {
          eventStream.connect(session.id);
          outputChannel.appendLine(`📡 Event stream connected for ${session.id.slice(0, 8)}`);
        }

        vscode.window.showInformationMessage(
          `Mark II: Session ${session.id.slice(0, 8)} created (${intakeMode.value})`,
          'Open Web UI'
        ).then((action) => {
          if (action === 'Open Web UI') {
            const frontendUrl = vscode.workspace.getConfiguration('markii').get<string>('apiUrl')?.replace(':8000', ':3000') || 'http://localhost:3000';
            vscode.env.openExternal(vscode.Uri.parse(`${frontendUrl}/session/${session.id}`));
          }
        });
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Mark II: Failed to create session — ${message}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.selectSession', (session: Session) => {
      activeSession = session;
      _updateStatusBar(session);
      outputChannel.appendLine(`👉 Selected session: ${session.id.slice(0, 8)} (${session.status})`);

      if (vscode.workspace.getConfiguration('markii').get<boolean>('autoStream')) {
        eventStream.connect(session.id);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.sendComment', () => {
      handleSendComment(activeSession);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.refreshSessions', () => {
      sessionProvider.refresh();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.openPreview', () => {
      if (!activeSession) {
        vscode.window.showWarningMessage('Mark II: No active session');
        return;
      }
      previewPanel.show(activeSession, context.extensionUri);
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.downloadArtifacts', async () => {
      if (!activeSession) {
        vscode.window.showWarningMessage('Mark II: No active session');
        return;
      }
      if (activeSession.status !== 'complete') {
        vscode.window.showWarningMessage('Mark II: Session is not complete yet');
        return;
      }
      // Open the web UI artifacts page
      const frontendUrl = vscode.workspace.getConfiguration('markii').get<string>('apiUrl')?.replace(':8000', ':3000') || 'http://localhost:3000';
      vscode.env.openExternal(vscode.Uri.parse(`${frontendUrl}/session/${activeSession.id}`));
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('markii.setApiUrl', async () => {
      const current = vscode.workspace.getConfiguration('markii').get<string>('apiUrl') || 'http://localhost:8000';
      const url = await vscode.window.showInputBox({
        prompt: 'Mark II Studio API URL',
        value: current,
        placeHolder: 'http://localhost:8000',
      });
      if (url) {
        await vscode.workspace.getConfiguration('markii').update('apiUrl', url, vscode.ConfigurationTarget.Global);
        vscode.window.showInformationMessage(`Mark II: API URL set to ${url}`);
      }
    })
  );

  // Auto-connect on startup
  vscode.commands.executeCommand('markii.connect');
}

function _handleEvent(event: SSEEvent): void {
  const icon = _eventIcon(event.event_type);
  const timestamp = new Date(event.timestamp).toLocaleTimeString();

  outputChannel.appendLine(`${icon} [${timestamp}] ${event.event_type}`);

  if (event.data && Object.keys(event.data).length > 0) {
    outputChannel.appendLine(`   ${JSON.stringify(event.data)}`);
  }

  // Update session status if we get a status event
  if (event.event_type === 'session_status' && activeSession) {
    const newStatus = event.data.status as string;
    if (newStatus) {
      activeSession = { ...activeSession, status: newStatus };
      sessionProvider.updateSession(activeSession);
      _updateStatusBar(activeSession);
    }
  }

  // Show notifications for important events
  switch (event.event_type) {
    case 'judge_result':
      vscode.window.showInformationMessage(
        `Mark II: Judge selected ${event.data.winner || 'winner'} — ${String(event.data.reasoning || '').slice(0, 100)}`
      );
      break;
    case 'mark_result':
      if (event.data.passed) {
        vscode.window.showInformationMessage(`Mark II: Mark ${event.data.mark_name} — ARMOR HOLDS ✅`);
      } else {
        vscode.window.showWarningMessage(`Mark II: Mark ${event.data.mark_name} — DESTROYED 💥 (${event.data.failure_type})`);
      }
      break;
    case 'delivery_ready':
      vscode.window.showInformationMessage('Mark II: Build complete! 🎉 Artifacts ready.', 'Download').then((action) => {
        if (action === 'Download') {
          vscode.commands.executeCommand('markii.downloadArtifacts');
        }
      });
      break;
    case 'error':
      vscode.window.showErrorMessage(`Mark II: ${event.data.error || 'Unknown error'}`);
      break;
  }
}

function _updateStatusBar(session: Session): void {
  const icons: Record<string, string> = {
    created: '🔵', interviewing: '💬', spec_review: '📋',
    building: '⚙️', judging: '⚖️', hardening: '🛡️',
    complete: '✅', failed: '❌',
  };
  const icon = icons[session.status] || '⚪';
  statusBarItem.text = `$(zap) Mark II ${icon} ${session.id.slice(0, 8)}`;
  statusBarItem.tooltip = `${session.profile_type || session.intake_mode} — ${session.status}`;
}

function _eventIcon(eventType: string): string {
  const icons: Record<string, string> = {
    interview_message: '💬',
    build_progress: '🔨',
    candidate_ready: '📦',
    judge_result: '⚖️',
    mark_started: '🛡️',
    mark_result: '⚔️',
    preview_update: '🖥️',
    change_request: '📝',
    delivery_ready: '🎉',
    session_status: '📡',
    error: '❌',
  };
  return icons[eventType] || '📌';
}

export function deactivate() {
  outputChannel?.dispose();
  eventStream?.dispose();
  previewPanel?.dispose();
}
