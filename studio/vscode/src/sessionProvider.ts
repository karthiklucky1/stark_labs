/**
 * Mark II Studio — Session Tree View Provider
 * TreeView showing active sessions and their status in the activity bar sidebar.
 */
import * as vscode from 'vscode';
import { getApiUrl, getSession, Session } from './apiClient';

export class SessionTreeProvider implements vscode.TreeDataProvider<SessionItem> {
  private _onDidChange = new vscode.EventEmitter<SessionItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChange.event;

  private sessions: Session[] = [];

  refresh(): void {
    this._fetchSessions().then(() => {
      this._onDidChange.fire(undefined);
    });
  }

  getTreeItem(element: SessionItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: SessionItem): Thenable<SessionItem[]> {
    if (element) {
      // Children of a session: show metadata
      return Promise.resolve(this._getSessionDetails(element.session));
    }
    // Top level: session list
    return this._fetchSessions().then(() =>
      this.sessions.map((s) => new SessionItem(s))
    );
  }

  private _getSessionDetails(session: Session): SessionItem[] {
    const items: SessionItem[] = [];
    items.push(
      new SessionItem(
        session,
        `Profile: ${session.profile_type || 'detecting...'}`,
        vscode.TreeItemCollapsibleState.None
      )
    );
    items.push(
      new SessionItem(
        session,
        `Intake: ${session.intake_mode}`,
        vscode.TreeItemCollapsibleState.None
      )
    );
    if (session.original_prompt) {
      items.push(
        new SessionItem(
          session,
          `Prompt: ${session.original_prompt.slice(0, 60)}...`,
          vscode.TreeItemCollapsibleState.None
        )
      );
    }
    items.push(
      new SessionItem(
        session,
        `Created: ${new Date(session.created_at).toLocaleString()}`,
        vscode.TreeItemCollapsibleState.None
      )
    );
    return items;
  }

  private async _fetchSessions(): Promise<void> {
    // Note: backend doesn't have a GET /sessions (list) endpoint yet.
    // For now, return any sessions we've tracked locally.
    // In production, this would hit GET /sessions?user_id=...
  }

  addSession(session: Session): void {
    // Remove existing if present
    this.sessions = this.sessions.filter((s) => s.id !== session.id);
    this.sessions.unshift(session);
    this._onDidChange.fire(undefined);
  }

  updateSession(session: Session): void {
    const idx = this.sessions.findIndex((s) => s.id === session.id);
    if (idx >= 0) {
      this.sessions[idx] = session;
    } else {
      this.sessions.unshift(session);
    }
    this._onDidChange.fire(undefined);
  }
}

const STATUS_ICONS: Record<string, string> = {
  created: '🔵',
  interviewing: '💬',
  spec_review: '📋',
  building: '⚙️',
  judging: '⚖️',
  hardening: '🛡️',
  complete: '✅',
  failed: '❌',
};

export class SessionItem extends vscode.TreeItem {
  constructor(
    public readonly session: Session,
    label?: string,
    collapsibleState?: vscode.TreeItemCollapsibleState
  ) {
    const displayLabel = label || `${STATUS_ICONS[session.status] || '⚪'} ${session.id.slice(0, 8)} — ${session.status.toUpperCase()}`;
    super(displayLabel, collapsibleState ?? vscode.TreeItemCollapsibleState.Collapsed);

    if (!label) {
      // Top-level session item
      this.tooltip = `${session.intake_mode} session | ${session.profile_type || 'unknown'} | ${session.status}`;
      this.description = session.profile_type || session.intake_mode;
      this.contextValue = 'session';
      this.command = {
        command: 'markii.selectSession',
        title: 'Select Session',
        arguments: [session],
      };
    } else {
      // Detail item
      this.contextValue = 'sessionDetail';
    }
  }
}
