/**
 * Mark II Studio — Comment Input Handler
 * Command palette action for sending mid-build comments/special instructions.
 */
import * as vscode from 'vscode';
import { submitComment, answerInterview, Session } from './apiClient';

/**
 * Prompt the user for a comment and send it to the active session.
 */
export async function handleSendComment(session: Session | null): Promise<void> {
  if (!session) {
    vscode.window.showWarningMessage('Mark II: No active session. Create or select a session first.');
    return;
  }

  const isInterviewing = session.status === 'interviewing';
  const placeholder = isInterviewing
    ? 'Answer the interview question...'
    : 'Add a feature, change something, or give feedback...';
  const prompt = isInterviewing
    ? 'Mark II Interview — Answer'
    : 'Mark II — Special Instruction';

  const input = await vscode.window.showInputBox({
    prompt,
    placeHolder: placeholder,
    ignoreFocusOut: true,
  });

  if (!input || !input.trim()) { return; }

  try {
    if (isInterviewing) {
      await answerInterview(session.id, input.trim());
      vscode.window.showInformationMessage('Mark II: Interview answer sent');
    } else {
      const result = await submitComment(session.id, input.trim());
      vscode.window.showInformationMessage(
        `Mark II: Comment received — classified as "${result.classification}"`
      );
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Mark II: Failed to send — ${message}`);
  }
}

/**
 * Show a multi-line text input for longer comments (e.g. paste code snippets).
 */
export async function handleSendDetailedComment(session: Session | null): Promise<void> {
  if (!session) {
    vscode.window.showWarningMessage('Mark II: No active session.');
    return;
  }

  // Open a temporary untitled document for the user to type in
  const doc = await vscode.workspace.openTextDocument({
    content: '',
    language: 'markdown',
  });
  const editor = await vscode.window.showTextDocument(doc);

  // Show a message about submitting
  vscode.window.showInformationMessage(
    'Mark II: Type your detailed instruction, then run "Mark II: Send Comment" again to submit.',
    'Got it'
  );
}
