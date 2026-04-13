/**
 * Mark II Studio — SSE Event Stream
 * Connects to the backend SSE endpoint and dispatches events to the Output channel.
 */
import * as vscode from 'vscode';
import * as http from 'http';
import * as https from 'https';
import { getApiUrl } from './apiClient';

export interface SSEEvent {
  event_type: string;
  session_id: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export type EventCallback = (event: SSEEvent) => void;

/**
 * Manages an SSE connection to a session's event stream.
 * Parses SSE format and dispatches typed events to subscribers.
 */
export class EventStream {
  private request: http.ClientRequest | null = null;
  private listeners: EventCallback[] = [];
  private reconnectTimer: NodeJS.Timeout | null = null;
  private retryCount = 0;
  private _connected = false;
  private _sessionId: string | null = null;

  get connected(): boolean {
    return this._connected;
  }

  get sessionId(): string | null {
    return this._sessionId;
  }

  /**
   * Subscribe to events.
   */
  onEvent(callback: EventCallback): vscode.Disposable {
    this.listeners.push(callback);
    return new vscode.Disposable(() => {
      this.listeners = this.listeners.filter((cb) => cb !== callback);
    });
  }

  /**
   * Connect to a session's event stream.
   */
  connect(sessionId: string): void {
    this.disconnect();
    this._sessionId = sessionId;
    this._connect();
  }

  /**
   * Disconnect from the event stream.
   */
  disconnect(): void {
    this._connected = false;
    this._sessionId = null;
    this.retryCount = 0;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.request) {
      this.request.destroy();
      this.request = null;
    }
  }

  private _connect(): void {
    if (!this._sessionId) { return; }

    const url = `${getApiUrl()}/sessions/${this._sessionId}/events`;
    const parsedUrl = new URL(url);
    const client = parsedUrl.protocol === 'https:' ? https : http;

    this.request = client.request(
      {
        hostname: parsedUrl.hostname,
        port: parsedUrl.port,
        path: parsedUrl.pathname,
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
      },
      (res) => {
        this._connected = true;
        this.retryCount = 0;

        let buffer = '';

        res.on('data', (chunk: Buffer) => {
          buffer += chunk.toString();
          const parts = buffer.split('\n\n');
          // Keep the last incomplete part in the buffer
          buffer = parts.pop() || '';

          for (const part of parts) {
            const event = this._parseSSE(part);
            if (event) {
              this._dispatch(event);
            }
          }
        });

        res.on('end', () => {
          this._connected = false;
          this._scheduleReconnect();
        });

        res.on('error', () => {
          this._connected = false;
          this._scheduleReconnect();
        });
      }
    );

    this.request.on('error', () => {
      this._connected = false;
      this._scheduleReconnect();
    });

    this.request.end();
  }

  /**
   * Parse an SSE message block into a typed event.
   */
  private _parseSSE(block: string): SSEEvent | null {
    let eventType = 'message';
    let data = '';

    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        data += line.slice(6);
      }
    }

    if (!data) { return null; }

    try {
      const parsed = JSON.parse(data);
      return {
        event_type: parsed.event_type || eventType,
        session_id: parsed.session_id || '',
        timestamp: parsed.timestamp || new Date().toISOString(),
        data: parsed.data || parsed,
      };
    } catch {
      return null;
    }
  }

  private _dispatch(event: SSEEvent): void {
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (e) {
        // Swallow listener errors
      }
    }
  }

  private _scheduleReconnect(): void {
    if (!this._sessionId) { return; }
    const delay = Math.min(1000 * Math.pow(2, this.retryCount), 30000);
    this.retryCount++;
    this.reconnectTimer = setTimeout(() => this._connect(), delay);
  }

  dispose(): void {
    this.disconnect();
    this.listeners = [];
  }
}
