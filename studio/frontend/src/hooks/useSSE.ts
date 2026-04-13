'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { getSSEUrl } from '@/lib/api';
import type { SSEEvent } from '@/lib/types';

/**
 * Hook for consuming Server-Sent Events from a session.
 * Auto-reconnects with exponential backoff.
 */
export function useSSE(sessionId: string | null) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const retryRef = useRef(0);

  const connect = useCallback(() => {
    if (!sessionId) return;

    const url = getSSEUrl(sessionId);
    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => {
      setConnected(true);
      retryRef.current = 0;
    };

    source.onmessage = (event) => {
      try {
        const parsed: SSEEvent = JSON.parse(event.data);
        setEvents((prev) => [...prev, parsed]);
        setLastEvent(parsed);
      } catch {
        // Ignore parse errors
      }
    };

    // Listen for specific event types
    const eventTypes = [
      'interview_message', 'build_progress', 'candidate_ready',
      'judge_result', 'mark_started', 'mark_result',
      'preview_update', 'change_request', 'delivery_ready',
      'session_status', 'error',
    ];

    for (const type of eventTypes) {
      source.addEventListener(type, (event) => {
        try {
          const parsed: SSEEvent = JSON.parse((event as MessageEvent).data);
          setEvents((prev) => [...prev, parsed]);
          setLastEvent(parsed);
        } catch {
          // Ignore
        }
      });
    }

    source.onerror = () => {
      setConnected(false);
      source.close();
      // Exponential backoff
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000);
      retryRef.current++;
      setTimeout(connect, delay);
    };
  }, [sessionId]);

  useEffect(() => {
    connect();
    return () => {
      sourceRef.current?.close();
    };
  }, [connect]);

  const clearEvents = useCallback(() => {
    setEvents([]);
    setLastEvent(null);
  }, []);

  return { events, lastEvent, connected, clearEvents };
}
