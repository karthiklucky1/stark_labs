'use client';

import { useCallback, useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import PreviewSystem from '@/components/PreviewSystem';
import { ArtifactsViewer } from '@/components/ArtifactsViewer';
import { useParams, useSearchParams } from 'next/navigation';
import { useSSE } from '@/hooks/useSSE';
import type { InterviewMessage, SSEEvent } from '@/lib/types';

type Tab = 'interview' | 'build' | 'harden' | 'delivery';

const TAB_CONFIG: { key: Tab; label: string; icon: string }[] = [
  { key: 'interview', label: 'Interview', icon: '💬' },
  { key: 'build',     label: 'Build',     icon: '⚙️' },
  { key: 'harden',    label: 'Harden',    icon: '🛡️' },
  { key: 'delivery',  label: 'Delivery',  icon: '📦' },
];

const STATUS_COLORS: Record<string, string> = {
  created:     'var(--text-muted)',
  interviewing:'var(--accent-cyan)',
  spec_review: 'var(--accent-violet)',
  building:    'var(--accent-blue)',
  judging:     'var(--accent-orange)',
  hardening:   'var(--accent-red)',
  complete:    'var(--accent-green)',
  failed:      'var(--accent-red)',
};

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const { lastEvent } = useSSE(id);
  const requestedTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<Tab>(
    (requestedTab as Tab) || 'interview'
  );
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [status, setStatus] = useState('created');
  const [statusDetail, setStatusDetail] = useState('');
  const [buildEvents, setBuildEvents] = useState<SSEEvent[]>([]);
  const [markEvents, setMarkEvents] = useState<SSEEvent[]>([]);
  const [specReady, setSpecReady] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [generatingShowcase, setGeneratingShowcase] = useState(false);
  const [showcase, setShowcase] = useState<any>(null);
  const [builderStates, setBuilderStates] = useState<Record<string, { status: string; detail: string; progress: number }>>({});
  const [sessionData, setSessionData] = useState<any>(null);
  const [judgeResult, setJudgeResult] = useState<{ winner: string; reasoning: string; scores: any } | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);

  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const loadSession = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sessions/${id}`);
      if (!res.ok) return;
      const data = await res.json();
      setSessionData(data);
      setStatus(data.status);
      if (data.detail) setStatusDetail(data.detail);
      if (!requestedTab) {
        if (['building', 'judging'].includes(data.status)) setActiveTab('build');
        if (data.status === 'hardening') setActiveTab('harden');
        if (data.status === 'complete') setActiveTab('delivery');
      }
      if (data.status === 'spec_review') setSpecReady(true);

      // One-time seed of build log and card states from existing candidates.
      // Only runs once on mount. SSE events append to this during live builds.
      if (['building', 'judging', 'hardening', 'complete'].includes(data.status)) {
        try {
          const cr = await fetch(`${API}/sessions/${id}/candidates`);
          if (cr.ok) {
            const candidates = await cr.json();
            if (candidates.length) {
              setBuildEvents(candidates.map((c: any) => ({
                event_type: 'candidate_ready',
                session_id: id,
                timestamp: '',
                data: { candidate_id: c.candidate_id, provider: c.provider, status: c.status === 'built' ? 'built' : c.status, model: c.model, is_baseline: c.is_baseline },
              })));
              const states: Record<string, any> = {};
              candidates.forEach((c: any) => {
                const isFinished = c.status === 'complete' || c.status === 'built';
                states[c.provider] = {
                  status: c.status,
                  detail: isFinished ? `${c.provider}: Ready` : c.status === 'running' ? `${c.provider}: In Progress` : c.status === 'failed' ? `${c.provider}: Failed` : `${c.provider}: Waiting…`,
                  progress: isFinished ? 100 : c.status === 'running' ? 45 : c.status === 'failed' ? 100 : 0,
                };
              });
              setBuilderStates(prev => ({ ...prev, ...states }));
            }
          }
        } catch {}

        try {
          const jr = await fetch(`${API}/sessions/${id}/judge`);
          if (jr.ok) {
            const jd = await jr.json();
            if (jd?.winner) setJudgeResult({ winner: jd.winner, reasoning: jd.reasoning, scores: jd.scores });
          }
        } catch {}
      }
    } catch {}
  }, [API, id, requestedTab]);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const res = await fetch(`${API}/sessions/${id}/interview`);
        if (res.ok) {
          const history = await res.json();
          if (history?.length) {
            setMessages(history.map((m: any) => ({ role: m.role, content: m.content })));
            if (history[history.length - 1]?.spec_ready) setSpecReady(true);
          }
        }
      } catch {}
    };

    loadSession();
    fetchHistory();
  }, [loadSession, id, API]);

  useEffect(() => {
    if (!['hardening', 'complete'].includes(status)) return;

    const fetchMarks = () => {
      fetch(`${API}/sessions/${id}/marks`)
        .then(r => r.ok ? r.json() : [])
        .then(runs => {
          if (!runs.length) return;
          const events: SSEEvent[] = [];
          runs.forEach((r: any) => {
            events.push({ event_type: 'mark_started', session_id: id, timestamp: '', data: { mark_number: r.mark_number, mark_name: r.mark_name } });
            events.push({ event_type: 'mark_result',  session_id: id, timestamp: '', data: { mark_number: r.mark_number, mark_name: r.mark_name, passed: r.passed, failure_type: r.failure_type, patch_summary: r.patch_summary } });
          });
          setMarkEvents(events);
        })
        .catch(() => {});
    };

    fetchMarks();
    // Keep polling every 3s until complete so marks appear as they finish
    const interval = setInterval(() => {
      if (['hardening', 'complete'].includes(status)) fetchMarks();
    }, 3_000);
    return () => clearInterval(interval);
  }, [status, id, API]);

  // Re-fetch marks immediately when user switches to harden tab
  useEffect(() => {
    if (activeTab !== 'harden') return;
    if (!['hardening', 'complete'].includes(status)) return;
    fetch(`${API}/sessions/${id}/marks`)
      .then(r => r.ok ? r.json() : [])
      .then(runs => {
        if (!runs.length) return;
        const events: SSEEvent[] = [];
        runs.forEach((r: any) => {
          events.push({ event_type: 'mark_started', session_id: id, timestamp: '', data: { mark_number: r.mark_number, mark_name: r.mark_name } });
          events.push({ event_type: 'mark_result',  session_id: id, timestamp: '', data: { mark_number: r.mark_number, mark_name: r.mark_name, passed: r.passed, failure_type: r.failure_type, patch_summary: r.patch_summary } });
        });
        setMarkEvents(events);
      })
      .catch(() => {});
  }, [activeTab, status, id, API]);

  useEffect(() => {
    if (status !== 'complete') return;
    fetch(`${API}/sessions/${id}/showcase`)
      .then(r => r.ok ? r.json() : null)
      .then(data => data && setShowcase(data))
      .catch(() => {});
  }, [status, id, API]);

  useEffect(() => {
    if (!['building', 'judging', 'hardening', 'complete'].includes(status)) return;
    const poll = async () => {
      try {
        const res = await fetch(`${API}/sessions/${id}/preview`);
        if (res.ok) {
          const d = await res.json();
          if (d.preview_url && d.preview_url !== previewUrl) setPreviewUrl(d.preview_url);
        }
      } catch {}
    };
    poll();
    const interval = setInterval(poll, 10_000);
    return () => clearInterval(interval);
  }, [status, id, API, previewUrl]);

  useEffect(() => {
    if (!lastEvent) return;
    const { event_type, data } = lastEvent;
    if (event_type === 'interview_message') {
      setMessages(prev => [...prev, { role: data.role as 'user' | 'assistant', content: data.content as string }]);
      if (data.spec_ready) setSpecReady(true);
    } else if (event_type === 'session_status') {
      setStatus(data.status as string);
      setStatusDetail(data.detail as string || '');
      if (['building', 'judging'].includes(data.status as string)) setActiveTab('build');
      if (data.status === 'hardening') setActiveTab('harden');
      if (data.status === 'complete') setActiveTab('delivery');
      if (data.status === 'spec_review') setSpecReady(true);
      loadSession();
    } else if (['build_progress', 'candidate_ready', 'judge_result'].includes(event_type)) {
      setBuildEvents(prev => {
        // Deduplicate candidate_ready by provider — HTTP pre-seed + backend re-emit would cause doubles
        if (event_type === 'candidate_ready') {
          const provider = data.provider as string;
          if (prev.some(e => e.event_type === 'candidate_ready' && (e.data.provider as string) === provider)) {
            return prev; // already have this provider's result
          }
        }
        return [...prev, lastEvent];
      });
      if (event_type === 'build_progress') {
        const provider = data.provider as string;
        const ps = data.status as string;
        const detail = data.detail as string;
        setBuilderStates(prev => {
          const s = { ...prev };
          let progress = 20;
          if (detail.includes("Thinking")) progress = 45;
          if (detail.includes("Finalizing")) progress = 85;
          if (ps === "complete") progress = 100;
          s[provider] = { status: ps, detail, progress: Math.max(progress, prev[provider]?.progress || 0) };
          return s;
        });
      } else if (event_type === 'candidate_ready') {
        // Mark the provider card as complete/failed based on candidate status
        const provider = data.provider as string;
        const cStatus  = data.status as string; // 'built' | 'failed'
        const cardStatus = cStatus === 'built' ? 'complete' : 'failed';
        setBuilderStates(prev => ({
          ...prev,
          [provider]: { status: cardStatus, detail: cardStatus === 'complete' ? `${provider}: Build complete` : `${provider}: Build failed`, progress: 100 },
        }));
      }
      if (event_type === 'judge_result' && data.winner) {
        setJudgeResult({
          winner: data.winner as string,
          reasoning: data.reasoning as string,
          scores: data.scores,
        });
      }
    } else if (['mark_started', 'mark_result'].includes(event_type)) {
      setMarkEvents(prev => [...prev, lastEvent]);
    } else if (event_type === 'preview_update' && data.preview_url) {
      setPreviewUrl(data.preview_url as string);
    }
  }, [lastEvent, loadSession]);

  useEffect(() => {
    if (chatRef.current && activeTab === 'interview') {
      chatRef.current.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [messages, activeTab]);

  const sendMessage = async () => {
    if (!inputValue.trim()) return;
    const msg = inputValue.trim();
    setInputValue('');
    setMessages(prev => [...prev, { role: 'user', content: msg }]);
    await fetch(`${API}/sessions/${id}/interview/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
  };

  const confirmRequirements = async () => {
    setConfirming(true);
    try {
      await fetch(`${API}/sessions/${id}/requirements/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirmed: true }),
      });
      setSpecReady(false);
      setActiveTab('build');
    } finally { setConfirming(false); }
  };

  const generateShowcase = async () => {
    setGeneratingShowcase(true);
    try {
      const res = await fetch(`${API}/sessions/${id}/showcase/generate`, { method: 'POST' });
      if (res.ok) setShowcase(await res.json());
    } finally { setGeneratingShowcase(false); }
  };

  return (
    <div className="h-[calc(100vh-56px)] flex mt-14 overflow-hidden">

      {/* ── Main Content ─────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Tab Bar */}
        <div className="flex items-center justify-between px-5 h-12 shrink-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(3,7,18,0.6)', backdropFilter: 'blur(12px)' }}>

          <div className="flex gap-1">
            {TAB_CONFIG.map(tab => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className="relative px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                style={{
                  background: activeTab === tab.key ? 'rgba(0,212,255,0.08)' : 'transparent',
                  color: activeTab === tab.key ? 'var(--stark-cyan)' : 'var(--text-muted)',
                }}
              >
                {tab.icon} {tab.label}
                {activeTab === tab.key && (
                  <div className="absolute bottom-0 left-3 right-3 h-px"
                    style={{ background: 'var(--stark-cyan)', boxShadow: '0 0 8px var(--stark-cyan)' }} />
                )}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-4">
            {specReady && activeTab === 'interview' && (
              <button className="btn-primary py-1.5 px-4 text-xs" onClick={confirmRequirements} disabled={confirming}>
                {confirming ? 'Confirming…' : '✅ Confirm & Build'}
              </button>
            )}
            <div className="flex flex-col items-end gap-0.5">
              <div className="flex items-center gap-2">
                <div className="status-dot" style={{ background: STATUS_COLORS[status] || 'var(--text-muted)' }} />
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-primary)' }}>
                  {status.replace('_', ' ')}
                </span>
              </div>
              {statusDetail && (
                <span className="text-[10px] font-medium transition-all" style={{ color: 'var(--text-muted)' }}>
                  {statusDetail}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-hidden">

          {/* ── Interview Tab ─── */}
          {activeTab === 'interview' && (
            <div className="h-full flex flex-col">
              <div ref={chatRef} className="flex-1 overflow-y-auto p-6 space-y-4">
                {messages.length === 0 && (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center" style={{ color: 'var(--text-muted)' }}>
                      <div className="text-4xl mb-3">💬</div>
                      <p className="text-sm">Claude will start the interview shortly…</p>
                    </div>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className="max-w-[72%] px-4 py-3 rounded-2xl text-sm leading-relaxed"
                      style={{
                        background: msg.role === 'user' ? 'rgba(0,212,255,0.12)' : 'rgba(255,255,255,0.04)',
                        border: `1px solid ${msg.role === 'user' ? 'rgba(0,212,255,0.2)' : 'rgba(255,255,255,0.06)'}`,
                        color: msg.role === 'user' ? 'var(--stark-cyan)' : 'var(--text-primary)',
                        borderBottomRightRadius: msg.role === 'user' ? '4px' : undefined,
                        borderBottomLeftRadius: msg.role === 'assistant' ? '4px' : undefined,
                      }}
                    >
                      <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
                    </div>
                  </div>
                ))}
              </div>

              <div className="px-6 py-4 flex gap-3 shrink-0"
                style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                <input
                  className="input-field flex-1"
                  placeholder="Type your answer…"
                  value={inputValue}
                  onChange={e => setInputValue(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && sendMessage()}
                />
                <button className="btn-primary px-5" onClick={sendMessage}>Send</button>
              </div>
            </div>
          )}

          {/* ── Build Tab ─── */}
          {activeTab === 'build' && (
            <div className="h-full flex flex-col gap-0 overflow-hidden">

              {/* Provider cards row */}
              <div className="grid grid-cols-4 gap-px shrink-0"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(255,255,255,0.03)' }}>
                {[
                  { id: 'openai',   label: 'OpenAI',   abbr: 'OA', color: '#10b981' },
                  { id: 'deepseek', label: 'DeepSeek', abbr: 'DS', color: '#3b82f6' },
                  { id: 'zhipu',    label: 'Zhipu',    abbr: 'ZH', color: '#8b5cf6' },
                  { id: 'ollama',   label: 'Ollama',   abbr: 'OL', color: '#f97316' },
                ].map(({ id: p, label, abbr, color }) => {
                  const s = builderStates[p] || { status: 'idle', detail: 'Waiting for signal…', progress: 0 };
                  const isDone    = s.status === 'complete' || s.status === 'built';
                  const isRunning = s.status === 'running' || s.status === 'started';
                  const isFailed  = s.status === 'failed';

                  const statusColor = isDone ? 'var(--accent-green)'
                    : isFailed  ? 'var(--accent-red)'
                    : isRunning ? 'var(--stark-cyan)'
                    : 'var(--text-muted)';

                  const statusLabel = isDone ? 'Complete'
                    : isFailed  ? 'Failed'
                    : isRunning ? 'Building…'
                    : s.status === 'started' ? 'Initiating…'
                    : 'Idle';

                  return (
                    <div key={p} className="flex flex-col gap-3 p-5 relative"
                      style={{
                        background: isRunning
                          ? 'rgba(0,212,255,0.03)'
                          : isDone
                          ? 'rgba(16,185,129,0.02)'
                          : 'rgba(3,7,18,0.6)',
                        borderRight: '1px solid rgba(255,255,255,0.04)',
                        transition: 'background 0.4s ease',
                      }}>

                      {/* Glow on active */}
                      {isRunning && (
                        <div className="absolute inset-x-0 top-0 h-px"
                          style={{ background: 'linear-gradient(90deg, transparent, var(--stark-cyan), transparent)' }} />
                      )}
                      {isDone && (
                        <div className="absolute inset-x-0 top-0 h-px"
                          style={{ background: 'linear-gradient(90deg, transparent, var(--accent-green), transparent)' }} />
                      )}

                      {/* Header */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-[11px] font-bold"
                            style={{ background: `${color}18`, color, border: `1px solid ${color}30` }}>
                            {abbr}
                          </div>
                          <span className="text-sm font-semibold text-white">{label}</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <div className="w-1.5 h-1.5 rounded-full"
                            style={{
                              background: statusColor,
                              boxShadow: isRunning ? `0 0 6px var(--stark-cyan)` : isDone ? `0 0 6px var(--accent-green)` : 'none',
                              animation: isRunning ? 'pulse-glow 1.5s ease-in-out infinite' : 'none',
                            }} />
                          <span className="text-[10px] font-medium" style={{ color: statusColor }}>
                            {statusLabel}
                          </span>
                        </div>
                      </div>

                      {/* Detail */}
                      <p className="text-xs leading-snug h-8 line-clamp-2" style={{ color: 'var(--text-muted)' }}>
                        {s.detail}
                      </p>

                      {/* Progress bar */}
                      <div className="h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)' }}>
                        <div className="h-full rounded-full transition-all duration-700 ease-out"
                          style={{
                            width: `${s.progress}%`,
                            background: isDone
                              ? 'var(--accent-green)'
                              : isFailed
                              ? 'var(--accent-red)'
                              : 'linear-gradient(90deg, var(--stark-cyan), #3b82f6)',
                            boxShadow: isRunning ? '0 0 8px rgba(0,212,255,0.4)' : 'none',
                          }} />
                      </div>

                      {/* Progress % */}
                      <div className="flex justify-between items-center">
                        <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                          {p.toUpperCase()}
                        </span>
                        <span className="text-[10px] font-mono font-bold" style={{ color: statusColor }}>
                          {s.progress}%
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Judge result banner */}
              {judgeResult && (
                <div className="shrink-0 px-5 py-3 flex items-center gap-4"
                  style={{ borderBottom: '1px solid rgba(16,185,129,0.15)', background: 'rgba(16,185,129,0.04)' }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-xs font-bold"
                    style={{ background: 'rgba(16,185,129,0.15)', color: 'var(--accent-green)' }}>
                    ⚖
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-0.5">
                      <span className="text-xs font-bold" style={{ color: 'var(--accent-green)' }}>
                        Claude Judge — Winner: {judgeResult.winner.toUpperCase()}
                      </span>
                      <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                        style={{ background: 'rgba(16,185,129,0.12)', color: 'var(--accent-green)' }}>
                        Selected for hardening
                      </span>
                    </div>
                    <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>
                      {judgeResult.reasoning}
                    </p>
                  </div>
                </div>
              )}

              {/* Terminal build log */}
              <div className="flex-1 flex flex-col overflow-hidden" style={{ background: 'rgba(0,0,0,0.5)' }}>
                {/* Terminal header */}
                <div className="flex items-center justify-between px-5 py-2.5 shrink-0"
                  style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: 'rgba(0,0,0,0.3)' }}>
                  <div className="flex items-center gap-3">
                    <span className="text-[10px] font-mono font-semibold" style={{ color: 'rgba(255,255,255,0.25)' }}>
                      build.log
                    </span>
                    <span className="text-[10px] font-mono" style={{ color: 'rgba(255,255,255,0.1)' }}>—</span>
                    <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                      stark_studio
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="status-dot" style={{
                      background: buildEvents.length > 0 ? 'var(--accent-green)' : 'var(--text-muted)',
                    }} />
                    <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                      {buildEvents.length} events
                    </span>
                  </div>
                </div>

                {/* Log lines */}
                <div className="flex-1 overflow-y-auto px-5 py-4 space-y-1 font-mono text-xs">
                  {buildEvents.length === 0 ? (
                    <div className="flex items-center gap-2 py-8 justify-center">
                      <span style={{ color: 'var(--text-muted)' }}>Waiting for build events…</span>
                    </div>
                  ) : (
                    buildEvents.map((e, i) => {
                      const d = e.data;
                      const provider  = d.provider as string | undefined;
                      const evtStatus = d.status  as string | undefined;
                      const detail    = d.detail  as string | undefined;

                      // Human-readable message per event type
                      let message: string;
                      let badge: string | undefined;
                      let badgeColor: string;

                      if (e.event_type === 'candidate_ready') {
                        const cStatus = d.status as string;
                        const isOk = cStatus === 'built';
                        message = isOk
                          ? `${(provider || '').toUpperCase()} — build complete`
                          : `${(provider || '').toUpperCase()} — build failed`;
                        badge = isOk ? 'built' : 'failed';
                        badgeColor = isOk ? 'var(--accent-green)' : 'var(--accent-red)';
                      } else if (e.event_type === 'judge_result') {
                        const winner = d.winner as string | undefined;
                        const reasoning = d.reasoning as string | undefined;
                        message = winner
                          ? `Winner: ${winner.toUpperCase()} — ${reasoning ? reasoning.slice(0, 80) + (reasoning.length > 80 ? '…' : '') : ''}`
                          : 'Judging complete';
                        badge = winner ? `winner: ${winner}` : 'judged';
                        badgeColor = '#f97316';
                      } else {
                        message = detail || '';
                        badge = evtStatus;
                        badgeColor = evtStatus === 'complete' ? 'var(--accent-green)'
                          : evtStatus === 'failed'  ? 'var(--accent-red)'
                          : 'var(--stark-cyan)';
                      }

                      const lineColor =
                        e.event_type === 'candidate_ready' ? (evtStatus === 'failed' ? 'var(--accent-red)' : 'var(--accent-green)')
                        : e.event_type === 'judge_result'  ? '#f97316'
                        : evtStatus === 'failed'            ? 'var(--accent-red)'
                        : evtStatus === 'running'           ? 'var(--stark-cyan)'
                        : 'var(--text-muted)';

                      const prefix =
                        e.event_type === 'build_progress'   ? '▸'
                        : e.event_type === 'candidate_ready' ? '✓'
                        : e.event_type === 'judge_result'    ? '⚖'
                        : '·';

                      return (
                        <div key={i} className="flex gap-3 items-baseline group hover:bg-white/[0.02] px-2 py-0.5 rounded transition-colors -mx-2">
                          <span className="shrink-0 w-5 text-center text-[10px]" style={{ color: lineColor }}>
                            {prefix}
                          </span>
                          <span className="shrink-0 text-[10px]" style={{ color: 'rgba(255,255,255,0.15)' }}>
                            {String(i + 1).padStart(3, '0')}
                          </span>
                          <span className="shrink-0 font-semibold" style={{ color: lineColor, minWidth: '80px' }}>
                            {provider ? provider.toUpperCase() : e.event_type === 'judge_result' ? 'JUDGE' : e.event_type.replace(/_/g, ' ').toUpperCase()}
                          </span>
                          <span style={{ color: 'rgba(255,255,255,0.55)' }} className="truncate">
                            {message}
                          </span>
                          {badge && (
                            <span className="ml-auto shrink-0 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded"
                              style={{
                                background: `${badgeColor}18`,
                                color: badgeColor,
                              }}>
                              {badge}
                            </span>
                          )}
                        </div>
                      );
                    })
                  )}
                  {/* blinking cursor */}
                  {buildEvents.length > 0 && (
                    <div className="flex gap-3 items-baseline px-2 py-0.5">
                      <span className="w-5" />
                      <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.15)' }}>
                        {String(buildEvents.length + 1).padStart(3, '0')}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--stark-cyan)', animation: 'pulse-glow 1s ease-in-out infinite' }}>
                        █
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Harden Tab ─── */}
          {activeTab === 'harden' && (
            <div className="h-full flex flex-col overflow-hidden">
              {/* Status header */}
              <div className="px-6 py-3 shrink-0 flex items-center justify-between"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: 'rgba(0,0,0,0.2)' }}>
                <div className="flex items-center gap-2">
                  <div className="status-dot" style={{
                    background: status === 'hardening' ? 'var(--accent-red)' : 'var(--accent-green)',
                    animation: status === 'hardening' ? 'pulse-glow 1s ease-in-out infinite' : 'none',
                  }} />
                  <span className="text-xs font-semibold" style={{ color: status === 'hardening' ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                    {status === 'hardening' ? 'Hardening in progress…' : 'Hardening complete'}
                  </span>
                </div>
                <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>
                  {markEvents.filter(e => e.event_type === 'mark_result').length} marks completed
                </span>
              </div>

              {/* Mark I–VII stage tracker */}
              {(() => {
                const completedMarks = markEvents.filter(e => e.event_type === 'mark_result');
                const completedNums  = new Set(completedMarks.map(e => e.data.mark_number as number));
                const MARKS = [
                  { num: 1, name: 'Mark I' },
                  { num: 2, name: 'Mark II' },
                  { num: 3, name: 'Mark III' },
                  { num: 4, name: 'Mark IV' },
                  { num: 5, name: 'Mark V' },
                  { num: 6, name: 'Mark VI' },
                  { num: 7, name: 'Mark VII' },
                ];
                const nextNum = completedMarks.length + 1;
                return (
                  <div className="px-6 py-3 shrink-0 flex items-center gap-2 flex-wrap"
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: 'rgba(0,0,0,0.15)' }}>
                    {MARKS.map((m, idx) => {
                      const done    = completedNums.has(m.num);
                      const running = !done && m.num === nextNum && status === 'hardening';
                      const pending = !done && !running;
                      const result  = completedMarks.find(e => (e.data.mark_number as number) === m.num);
                      const passed  = result?.data.passed as boolean | undefined;
                      return (
                        <div key={m.num} className="flex items-center gap-1.5">
                          {idx > 0 && (
                            <div className="w-4 h-px" style={{ background: done ? 'rgba(16,185,129,0.4)' : 'rgba(255,255,255,0.08)' }} />
                          )}
                          <div className="flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold transition-all"
                            style={{
                              background: done
                                ? (passed ? 'rgba(16,185,129,0.12)' : 'rgba(255,71,87,0.12)')
                                : running
                                ? 'rgba(255,71,87,0.08)'
                                : 'rgba(255,255,255,0.03)',
                              border: `1px solid ${done ? (passed ? 'rgba(16,185,129,0.25)' : 'rgba(255,71,87,0.25)') : running ? 'rgba(255,71,87,0.2)' : 'rgba(255,255,255,0.06)'}`,
                              color: done
                                ? (passed ? 'var(--accent-green)' : 'var(--accent-red)')
                                : running
                                ? 'var(--accent-red)'
                                : 'var(--text-muted)',
                            }}>
                            {done
                              ? <span>{passed ? '✓' : '✗'}</span>
                              : running
                              ? <span style={{ animation: 'pulse-glow 1s ease-in-out infinite', display: 'inline-block' }}>●</span>
                              : <span>○</span>
                            }
                            <span>{m.name}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })()}

              <div className="flex-1 overflow-y-auto p-6 space-y-3">
                {/* Live running indicator */}
                {status === 'hardening' && markEvents.filter(e => e.event_type === 'mark_result').length === 0 && (
                  <div className="glass-card p-5 flex items-center gap-4"
                    style={{ borderColor: 'rgba(255,71,87,0.15)', background: 'rgba(255,71,87,0.03)' }}>
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                      style={{ background: 'rgba(255,71,87,0.1)' }}>
                      <span style={{ animation: 'pulse-glow 1s ease-in-out infinite', display: 'inline-block' }}>🛡️</span>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white">Mark II adversarial loop running</p>
                      <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                        Deploying swarm attacks — results will appear here as each mark completes
                      </p>
                    </div>
                  </div>
                )}

                {markEvents.map((e, i) => {
                  const markName = e.data.mark_name as string;

                  if (e.event_type === 'mark_started') {
                    return (
                      <div key={i} className="flex items-center gap-3 px-2 py-3" style={{ color: 'var(--text-muted)' }}>
                        <div className="status-dot" style={{ background: 'var(--accent-red)', animation: 'pulse-glow 1s ease-in-out infinite' }} />
                        <span className="text-xs">Mark {markName} starting...</span>
                      </div>
                    );
                  }

                  const passed      = e.data.passed      as boolean;
                  const failureType = e.data.failure_type as string | null;
                  const patchSummary= e.data.patch_summary as string | null;
                  const markNumber  = e.data.mark_number  as number;

                  return (
                    <div key={i} className="glass-card p-5 flex items-start gap-4"
                      style={{
                        borderColor: passed ? 'rgba(16,185,129,0.2)' : 'rgba(255,71,87,0.2)',
                        background: passed ? 'rgba(16,185,129,0.02)' : 'rgba(255,71,87,0.02)',
                      }}>
                      {/* Mark number badge */}
                      <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 font-bold text-sm"
                        style={{
                          background: passed ? 'rgba(16,185,129,0.12)' : 'rgba(255,71,87,0.12)',
                          color: passed ? 'var(--accent-green)' : 'var(--accent-red)',
                        }}>
                        {markNumber}
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-semibold text-white">Mark {markName}</span>
                          <span className="text-xs font-bold px-2 py-0.5 rounded-full"
                            style={{
                              background: passed ? 'rgba(16,185,129,0.12)' : 'rgba(255,71,87,0.12)',
                              color: passed ? 'var(--accent-green)' : 'var(--accent-red)',
                            }}>
                            {passed ? '✓ Armor holds' : '✗ Breach detected'}
                          </span>
                        </div>

                        {failureType && (
                          <p className="text-xs mb-1.5 font-mono" style={{ color: 'var(--accent-red)' }}>
                            Vulnerability: {failureType}
                          </p>
                        )}
                        {patchSummary && (
                          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                            🔧 {patchSummary}
                          </p>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Still hardening — waiting for more marks */}
                {status === 'hardening' && markEvents.filter(e => e.event_type === 'mark_result').length > 0 && (
                  <div className="flex items-center gap-3 px-2 py-3" style={{ color: 'var(--text-muted)' }}>
                    <div className="status-dot" style={{ background: 'var(--accent-red)', animation: 'pulse-glow 1s ease-in-out infinite' }} />
                    <span className="text-xs">Next mark running…</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Delivery Tab ─── */}
          {activeTab === 'delivery' && (
            <div className="h-full flex flex-col overflow-hidden">

              {/* Header bar */}
              <div className="shrink-0 px-6 py-3 flex items-center justify-between"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(0,0,0,0.2)' }}>
                <div className="flex items-center gap-3">
                  <div className="status-dot" style={{ background: 'var(--accent-green)' }} />
                  <span className="text-xs font-semibold" style={{ color: 'var(--accent-green)' }}>
                    Build complete — your code is ready
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  {previewUrl && (
                    <a href={previewUrl} target="_blank" rel="noreferrer"
                      className="text-xs px-3 py-1.5 rounded-lg font-semibold transition-all"
                      style={{ background: 'rgba(0,212,255,0.1)', border: '1px solid rgba(0,212,255,0.2)', color: 'var(--stark-cyan)' }}>
                      Open live ↗
                    </a>
                  )}
                  {!showcase ? (
                    <button className="btn-primary py-1.5 px-4 text-xs" onClick={generateShowcase} disabled={generatingShowcase}>
                      {generatingShowcase ? 'Generating…' : 'Generate Showcase'}
                    </button>
                  ) : (
                    <Link href={`/share/${id}`} target="_blank"
                      className="text-xs px-3 py-1.5 rounded-lg font-semibold"
                      style={{ background: 'rgba(0,212,255,0.1)', border: '1px solid rgba(0,212,255,0.2)', color: 'var(--stark-cyan)' }}>
                      View Showroom ↗
                    </Link>
                  )}
                </div>
              </div>

              {/* Main — code viewer fills height, no outer scroll needed since ArtifactsViewer scrolls internally */}
              <div className="flex-1 min-h-0 p-6 flex flex-col">
                <ArtifactsViewer sessionId={id} />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Preview Sidebar ───────────────────────────── */}
      <div className="w-[380px] shrink-0 flex flex-col"
        style={{ borderLeft: '1px solid rgba(255,255,255,0.05)' }}>
        <PreviewSystem
          sessionId={id}
          previewUrl={previewUrl}
          profileType={sessionData?.profile_type || null}
          previewMode={sessionData?.preview_mode || null}
        />
      </div>
    </div>
  );
}
