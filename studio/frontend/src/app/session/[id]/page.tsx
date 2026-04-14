'use client';

import { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import PreviewSystem from '@/components/PreviewSystem';
import { ArtifactsViewer } from '@/components/ArtifactsViewer';
import { useParams, useSearchParams } from 'next/navigation';
import { useSSE } from '@/hooks/useSSE';
import type { InterviewMessage, SSEEvent } from '@/lib/types';

type Tab = 'interview' | 'build' | 'harden' | 'delivery';

const TAB_CONFIG: { key: Tab; label: string; icon: string }[] = [
  { key: 'interview', label: 'Interview', icon: '💬' },
  { key: 'build', label: 'Build', icon: '⚙️' },
  { key: 'harden', label: 'Harden', icon: '🛡️' },
  { key: 'delivery', label: 'Delivery', icon: '📦' },
];

const STATUS_COLORS: Record<string, string> = {
  created: 'var(--text-muted)',
  interviewing: 'var(--accent-cyan)',
  spec_review: 'var(--accent-violet)',
  building: 'var(--accent-blue)',
  judging: 'var(--accent-orange)',
  hardening: 'var(--accent-red)',
  complete: 'var(--accent-green)',
  failed: 'var(--accent-red)',
};

const BUILDER_META = [
  { id: 'openai', label: 'OpenAI', abbr: 'OA', color: '#10b981' },
  { id: 'deepseek', label: 'DeepSeek', abbr: 'DS', color: '#3b82f6' },
  { id: 'zhipu', label: 'Zhipu', abbr: 'ZH', color: '#8b5cf6' },
  { id: 'ollama', label: 'Ollama', abbr: 'OL', color: '#f97316' },
];

function formatDuration(durationMs?: number | null): string | null {
  if (durationMs == null) return null;
  if (durationMs >= 60000) {
    return `${Math.floor(durationMs / 60000)}m ${Math.round((durationMs % 60000) / 1000)}s`;
  }
  if (durationMs >= 1000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }
  return `${Math.round(durationMs)}ms`;
}

function formatBuildMode(mode?: string | null): string {
  if (!mode) return 'Balanced';
  if (mode === 'max_quality') return 'Max Quality';
  return mode.charAt(0).toUpperCase() + mode.slice(1);
}

function describeBuildMode(mode?: string | null): string {
  if (mode === 'fast') return 'Single architect-builder pass with synthesis kept minimal for speed.';
  if (mode === 'max_quality') return 'Expanded multi-model assembly with deeper review, scoring, and synthesis.';
  return 'Deterministic multi-model module plan with balanced speed and review depth.';
}

function formatProviderLabel(provider?: string | null): string {
  if (!provider) return 'Unknown';
  const meta = BUILDER_META.find(item => item.id === provider);
  if (meta) return meta.label;
  return provider.charAt(0).toUpperCase() + provider.slice(1);
}

function humanizeMetric(metric: string): string {
  return metric.replace(/_/g, ' ');
}

function buildScoreSummary(rawScore: any): { judgeScore: string; strongest: string; weakest: string } {
  if (!rawScore || typeof rawScore !== 'object') {
    return { judgeScore: '--', strongest: 'Not scored yet', weakest: 'Not scored yet' };
  }

  const total = rawScore.total_weighted;
  const scoredEntries = Object.entries(rawScore).filter(([key, value]) => key !== 'total_weighted' && typeof value === 'number');
  if (!scoredEntries.length) {
    return {
      judgeScore: typeof total === 'number' ? String(Math.round(total)) : '--',
      strongest: 'Not scored yet',
      weakest: 'Not scored yet',
    };
  }

  const strongest = [...scoredEntries].sort((a, b) => Number(b[1]) - Number(a[1]))[0];
  const weakest = [...scoredEntries].sort((a, b) => Number(a[1]) - Number(b[1]))[0];

  return {
    judgeScore: typeof total === 'number' ? String(Math.round(total)) : '--',
    strongest: `${humanizeMetric(strongest[0])} ${strongest[1]}/10`,
    weakest: `${humanizeMetric(weakest[0])} ${weakest[1]}/10`,
  };
}

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const { connected, lastEvent } = useSSE(id);
  const [activeTab, setActiveTab] = useState<Tab>(
    (searchParams.get('tab') as Tab) || 'interview'
  );
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [status, setStatus] = useState('created');
  const [statusDetail, setStatusDetail] = useState('');
  const [buildEvents, setBuildEvents] = useState<SSEEvent[]>([]);
  const [markEvents, setMarkEvents] = useState<SSEEvent[]>([]);
  const [specReady, setSpecReady] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const [previewStatus, setPreviewStatus] = useState<string | null>(null);
  const [previewDetail, setPreviewDetail] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [generatingShowcase, setGeneratingShowcase] = useState(false);
  const [showcase, setShowcase] = useState<any>(null);
  const [builderStates, setBuilderStates] = useState<Record<string, { status: string; detail: string; progress: number }>>({});
  const [sessionData, setSessionData] = useState<any>(null);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [judgeResult, setJudgeResult] = useState<{ winner: string; reasoning: string; scores: any } | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);

  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  const refreshCandidates = async () => {
    try {
      const res = await fetch(`${API}/sessions/${id}/candidates`);
      if (!res.ok) return;
      const list = await res.json();
      setCandidates(list);

      if (!list.length) return;

      setBuildEvents(prev => {
        const retained = prev.filter(event => event.event_type !== 'candidate_ready');
        const seeded = list.map((candidate: any) => ({
          event_type: 'candidate_ready',
          session_id: id,
          timestamp: '',
          data: {
            candidate_id: candidate.candidate_id,
            provider: candidate.provider,
            status: candidate.status === 'built' ? 'built' : candidate.status,
            model: candidate.model,
            is_baseline: candidate.is_baseline,
            duration_ms: candidate.build_duration_ms,
            score: candidate.score,
            module_scope_json: candidate.module_scope_json,
            review_notes_json: candidate.review_notes_json,
            patch_summary: candidate.patch_summary,
          },
        }));
        return [...retained, ...seeded];
      });

      const nextStates: Record<string, { status: string; detail: string; progress: number }> = {};
      list.forEach((candidate: any) => {
        const status = candidate.status;
        const isFinished = status === 'complete' || status === 'built';
        nextStates[candidate.provider] = {
          status,
          detail: isFinished
            ? `${candidate.provider}: Ready`
            : status === 'running'
            ? `${candidate.provider}: In Progress`
            : status === 'failed'
            ? `${candidate.provider}: Failed`
            : `${candidate.provider}: Waiting…`,
          progress: isFinished ? 100 : status === 'running' ? 45 : status === 'failed' ? 100 : 0,
        };
      });
      setBuilderStates(prev => ({ ...prev, ...nextStates }));
    } catch { }
  };

  const refreshJudgeDecision = async () => {
    try {
      const res = await fetch(`${API}/sessions/${id}/judge`);
      if (!res.ok) return;
      const decision = await res.json();
      if (decision?.winner || decision?.reasoning || (decision?.scores && Object.keys(decision.scores).length > 0)) {
        setJudgeResult({ winner: decision.winner, reasoning: decision.reasoning, scores: decision.scores });
      } else {
        setJudgeResult(null);
      }
    } catch { }
  };

  const plannedBuilders = Array.isArray(sessionData?.planned_builders) ? sessionData.planned_builders : [];
  const baselineCandidate = candidates.find(candidate => candidate.is_baseline) || candidates.find(candidate => candidate.status === 'built') || null;
  const architecture = sessionData?.architecture_json || {};
  const masterBlueprint = architecture?.master_blueprint || {};
  const architectureStage = typeof architecture?.stage === 'string' ? architecture.stage : 'council';
  const sharedContracts = Array.isArray(masterBlueprint?.shared_contracts) ? masterBlueprint.shared_contracts : [];
  const providerModules = masterBlueprint?.provider_modules || {};
  const visibleBuilders = (plannedBuilders.length > 0 ? plannedBuilders : BUILDER_META.map(item => item.id)).filter((provider: string) => provider !== 'synthesis');
  const contributorCandidates = candidates.filter((candidate: any) => candidate.provider !== 'synthesis' && visibleBuilders.includes(candidate.provider));

  useEffect(() => {
    const fetchSession = async () => {
      try {
        const res = await fetch(`${API}/sessions/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        setSessionData(data);
        setStatus(data.status);
        if (data.detail) setStatusDetail(data.detail);
        if (!searchParams.get('tab')) {
          if (['building', 'judging'].includes(data.status)) setActiveTab('build');
          if (data.status === 'hardening') setActiveTab('harden');
          if (data.status === 'complete') setActiveTab('delivery');
        }
        if (data.status === 'spec_review') setSpecReady(true);

        // One-time seed of build log and card states from existing candidates.
        // Only runs once on mount. SSE events append to this during live builds.
        if (['building', 'judging', 'hardening', 'complete'].includes(data.status)) {
          await refreshCandidates();
          await refreshJudgeDecision();
        }
      } catch { }
    };

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
      } catch { }
    };

    fetchSession();
    fetchHistory();
  }, [id, API, searchParams]); // ← id/API only — NOT status, so this never re-runs on status changes

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
            events.push({ event_type: 'mark_result', session_id: id, timestamp: '', data: { mark_number: r.mark_number, mark_name: r.mark_name, passed: r.passed, failure_type: r.failure_type, patch_summary: r.patch_summary } });
          });
          setMarkEvents(events);
        })
        .catch(() => { });
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
          events.push({ event_type: 'mark_result', session_id: id, timestamp: '', data: { mark_number: r.mark_number, mark_name: r.mark_name, passed: r.passed, failure_type: r.failure_type, patch_summary: r.patch_summary } });
        });
        setMarkEvents(events);
      })
      .catch(() => { });
  }, [activeTab, status, id, API]);

  useEffect(() => {
    if (status !== 'complete') return;
    fetch(`${API}/sessions/${id}/showcase`)
      .then(r => r.ok ? r.json() : null)
      .then(data => data && setShowcase(data))
      .catch(() => { });
  }, [status, id, API]);

  useEffect(() => {
    if (!['building', 'judging', 'complete'].includes(status)) {
      if (status === 'hardening') {
        setPreviewStatus('paused');
        setPreviewDetail('Preview is temporarily paused while hardening reuses the sandbox');
      }
      return;
    }
    const poll = async () => {
      try {
        const res = await fetch(`${API}/sessions/${id}/preview`);
        if (res.ok) {
          const d = await res.json();
          setPreviewStatus(d.status || null);
          setPreviewDetail(d.detail || null);
          if (d.preview_url && d.preview_url !== previewUrlRef.current) {
            previewUrlRef.current = d.preview_url;
            setPreviewUrl(d.preview_url);
          }
        }
      } catch { }
    };
    poll();
    const interval = setInterval(poll, 10_000);
    return () => clearInterval(interval);
  }, [status, id, API]);

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
      if (['building', 'judging', 'hardening', 'complete'].includes(data.status as string)) {
        void refreshCandidates();
      }
      if (['judging', 'hardening', 'complete'].includes(data.status as string)) {
        void refreshJudgeDecision();
      }
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
        const cStatus = data.status as string; // 'built' | 'failed'
        const cardStatus = cStatus === 'built' ? 'complete' : 'failed';
        setBuilderStates(prev => ({
          ...prev,
          [provider]: { status: cardStatus, detail: cardStatus === 'complete' ? `${provider}: Build complete` : `${provider}: Build failed`, progress: 100 },
        }));
        void refreshCandidates();
      } else if (event_type === 'judge_result') {
        void refreshJudgeDecision();
      }
    } else if (['mark_started', 'mark_result'].includes(event_type)) {
      setMarkEvents(prev => [...prev, lastEvent]);
    } else if (event_type === 'preview_update' && data.preview_url) {
      previewUrlRef.current = data.preview_url as string;
      setPreviewUrl(data.preview_url as string);
      setPreviewStatus((data.status as string) || 'active');
      setPreviewDetail(null);
    }
  }, [lastEvent]);

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
            <div className="h-full min-h-0 flex flex-col gap-0 overflow-y-auto">
              <div className="px-6 py-5 shrink-0 space-y-5"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(3,7,18,0.42)' }}>
                <div className="flex items-start justify-between gap-6 flex-wrap">
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                        Build Mode
                      </span>
                      <span className="text-xs px-2.5 py-1 rounded-full font-semibold"
                        style={{ background: 'rgba(0,212,255,0.08)', color: 'var(--stark-cyan)', border: '1px solid rgba(0,212,255,0.18)' }}>
                        {formatBuildMode(sessionData?.build_mode)}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      {describeBuildMode(sessionData?.build_mode)}
                    </p>
                  </div>

                  {visibleBuilders[0] && (
                    <div className="flex justify-end min-w-[120px]">
                      <span className="text-[10px] px-2.5 py-1 rounded-full font-semibold"
                        style={{ background: 'rgba(16,185,129,0.12)', color: 'var(--accent-green)', border: '1px solid rgba(16,185,129,0.18)' }}>
                        {formatProviderLabel(visibleBuilders[0])}
                      </span>
                    </div>
                  )}
                </div>

                <div className="flex items-start justify-between gap-4 flex-wrap">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                      Assembly Protocol
                    </p>
                    <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      Deterministic multi-model module plan.
                    </p>
                  </div>
                  <span className="text-[10px] px-3 py-1 rounded-full font-semibold"
                    style={{ background: 'rgba(59,130,246,0.12)', color: '#8fb6ff', border: '1px solid rgba(59,130,246,0.18)' }}>
                    {architecture?.protocol || 'assembly_v1'}
                  </span>
                </div>

                {(() => {
                  const steps = [
                    { id: 'council', label: 'Council' },
                    { id: 'blueprint', label: 'Blueprint' },
                    { id: 'assembly', label: 'Assembly' },
                    { id: 'synthesis', label: 'Synthesis' },
                  ];
                  const stageIndex =
                    architectureStage === 'council' ? 0
                    : architectureStage === 'blueprint_complete' ? 1
                    : architectureStage === 'assembly_complete' ? 2
                    : architectureStage === 'synthesized' ? 3
                    : 0;

                  return (
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                      {steps.map((step, index) => {
                        const isDone = index < stageIndex || (index === stageIndex && ['hardening', 'complete'].includes(status) && architectureStage === 'synthesized');
                        const isActive = !isDone && index === stageIndex;
                        return (
                          <div key={step.id} className="glass-card p-4"
                            style={{
                              background: isActive ? 'rgba(0,212,255,0.06)' : 'rgba(255,255,255,0.02)',
                              borderColor: isActive ? 'rgba(0,212,255,0.18)' : 'rgba(255,255,255,0.06)',
                            }}>
                            <div className="flex items-center justify-between">
                              <span className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: isActive ? 'var(--stark-cyan)' : 'var(--text-muted)' }}>
                                Step {index + 1}
                              </span>
                              <span className="text-[10px]" style={{ color: isDone ? 'var(--accent-green)' : isActive ? 'var(--stark-cyan)' : 'rgba(255,255,255,0.2)' }}>
                                {isDone ? '●' : isActive ? '●' : '○'}
                              </span>
                            </div>
                            <p className="mt-2 text-base font-semibold" style={{ color: isDone || isActive ? 'var(--text-primary)' : 'rgba(255,255,255,0.35)' }}>
                              {step.label}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  );
                })()}

                <div className="glass-card p-5">
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                    Shared Contracts
                  </p>
                  <div className="mt-4 space-y-3">
                    {(sharedContracts.length > 0 ? sharedContracts.slice(0, 3) : [
                      'Preserve agreed file ownership; avoid overwriting another model\'s owned files.',
                      'Keep top-level dependencies and runtime commands consistent with the master blueprint.',
                      'Honor shared data contracts across UI, API, and validation layers.',
                    ]).map((contract: string, index: number) => (
                      <p key={index} className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                        {contract}
                      </p>
                    ))}
                  </div>
                </div>
              </div>

              <div className={`grid ${visibleBuilders.length > 1 ? 'grid-cols-1 xl:grid-cols-2' : 'grid-cols-1'} gap-3 px-6 py-4 shrink-0`}
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(255,255,255,0.02)' }}>
                {visibleBuilders.map((p: string) => {
                  const meta = BUILDER_META.find(item => item.id === p);
                  const label = meta?.label || formatProviderLabel(p);
                  const abbr = meta?.abbr || p.slice(0, 2).toUpperCase();
                  const color = meta?.color || '#10b981';
                  const s = builderStates[p] || { status: 'idle', detail: 'Waiting for signal…', progress: 0 };
                  const candidate = candidates.find(item => item.provider === p)
                    || buildEvents.find(e => e.event_type === 'candidate_ready' && (e.data.provider as string) === p)?.data;
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

                  // model name from candidate data
                  const modelName = candidate?.model as string | undefined;
                  // duration from candidate data
                  const durationLabel = formatDuration(candidate?.build_duration_ms ?? candidate?.duration_ms);

                  return (
                    <div key={p} className="glass-card flex flex-col gap-3 p-5 relative"
                      style={{
                        background: isRunning ? 'rgba(0,212,255,0.03)' : isDone ? 'rgba(16,185,129,0.02)' : 'rgba(3,7,18,0.6)',
                        borderColor: 'rgba(255,255,255,0.06)',
                        transition: 'background 0.4s ease',
                      }}>
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
                          <span className="text-[10px] font-medium" style={{ color: statusColor }}>{statusLabel}</span>
                        </div>
                      </div>

                      {/* Model + time row */}
                      <div className="flex items-center gap-2 flex-wrap">
                        {modelName && (
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded"
                            style={{ background: `${color}12`, color, border: `1px solid ${color}22` }}>
                            {modelName}
                          </span>
                        )}
                        {durationLabel && (
                          <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                            ⏱ {durationLabel}
                          </span>
                        )}
                        {!modelName && !durationLabel && (
                          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>—</span>
                        )}
                      </div>

                      {/* Summary */}
                      <p className="text-xs leading-snug line-clamp-2" style={{ color: 'var(--text-muted)', minHeight: '2rem' }}>
                        {s.detail}
                      </p>

                      {/* Progress bar */}
                      <div className="h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)' }}>
                        <div className="h-full rounded-full transition-all duration-700 ease-out"
                          style={{
                            width: `${s.progress}%`,
                            background: isDone ? 'var(--accent-green)' : isFailed ? 'var(--accent-red)' : 'linear-gradient(90deg, var(--stark-cyan), #3b82f6)',
                            boxShadow: isRunning ? '0 0 8px rgba(0,212,255,0.4)' : 'none',
                          }} />
                      </div>

                      <div className="flex justify-between items-center">
                        <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>{p.toUpperCase()}</span>
                        <span className="text-[10px] font-mono font-bold" style={{ color: statusColor }}>{s.progress}%</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="px-6 py-4 shrink-0 space-y-3"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(3,7,18,0.28)' }}>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                      Module Contributors
                    </p>
                    <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      Inspect module ownership, advisory scores, and peer review feedback before synthesis.
                    </p>
                  </div>
                  <span className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                    {visibleBuilders.length} contributors
                  </span>
                </div>

                <div className="space-y-2">
                  {visibleBuilders.map((provider: string) => {
                    const candidate = contributorCandidates.find((item: any) => item.provider === provider) || null;
                    const scope = (candidate?.module_scope_json || providerModules?.[provider] || {}) as Record<string, any>;
                    const ownedFiles = Array.isArray(scope?.owned_files) ? scope.owned_files : [];
                    const reviews = Array.isArray(candidate?.review_notes_json)
                      ? candidate.review_notes_json
                      : Array.isArray(architecture?.peer_reviews)
                      ? architecture.peer_reviews.filter((review: any) => review?.target === provider)
                      : [];
                    const scorePayload = judgeResult?.scores?.[provider] || null;
                    const scoreSummary = buildScoreSummary(scorePayload);
                    const statusValue = candidate?.status || builderStates[provider]?.status || 'queued';
                    const durationValue = formatDuration(candidate?.build_duration_ms) || 'n/a';
                    const outcomeValue =
                      candidate?.is_baseline
                        ? 'Selected'
                        : statusValue === 'built' || statusValue === 'complete'
                        ? 'Ready'
                        : statusValue === 'failed'
                        ? 'Failed'
                        : 'Waiting';
                    const noteText =
                      candidate?.build_log
                        ? String(candidate.build_log).slice(0, 180)
                        : 'No candidate output yet.';
                    const moduleName = scope?.module_name || `${formatProviderLabel(provider)} module`;

                    return (
                      <div key={provider} className="glass-card p-4"
                        style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex items-start gap-2.5">
                            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold"
                              style={{ background: 'rgba(16,185,129,0.12)', color: 'var(--accent-green)', border: '1px solid rgba(16,185,129,0.16)' }}>
                              {(BUILDER_META.find(item => item.id === provider)?.abbr || provider.slice(0, 2)).toUpperCase()}
                            </div>
                            <div>
                              <p className="text-base font-semibold text-white">{formatProviderLabel(provider)}</p>
                              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{moduleName}</p>
                            </div>
                          </div>
                          <div className="text-right">
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                              Judge Score
                            </p>
                            <p className="mt-1.5 text-xl font-semibold text-white">{scoreSummary.judgeScore}</p>
                          </div>
                        </div>

                        <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
                          {[
                            { label: 'Status', value: statusValue },
                            { label: 'Duration', value: durationValue },
                            { label: 'Outcome', value: outcomeValue },
                          ].map((item) => (
                            <div key={item.label} className="rounded-2xl px-3 py-2.5"
                              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                              <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                                {item.label}
                              </p>
                              <p className="mt-1.5 text-sm font-semibold text-white">{item.value}</p>
                            </div>
                          ))}
                        </div>

                        <div className="mt-2 space-y-2">
                          <div className="rounded-2xl px-3 py-2.5"
                            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                              Owned Files
                            </p>
                            <p className="mt-1.5 text-sm font-semibold text-white">{ownedFiles.length}</p>
                          </div>

                          <div className="rounded-2xl px-3 py-2.5"
                            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                              Strongest
                            </p>
                            <p className="mt-1.5 text-sm font-semibold text-white">{scoreSummary.strongest}</p>
                          </div>

                          <div className="rounded-2xl px-3 py-2.5"
                            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                              Weakest
                            </p>
                            <p className="mt-1.5 text-sm font-semibold text-white">{scoreSummary.weakest}</p>
                          </div>

                          <div className="rounded-2xl px-3 py-2.5"
                            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                              Peer Review
                            </p>
                            <p className="mt-1.5 text-sm font-medium leading-relaxed text-white">
                              {reviews.length > 0
                                ? (reviews[0]?.review?.summary || reviews[0]?.summary || 'Review available')
                                : 'Peer review pending'}
                            </p>
                          </div>

                          <div className="rounded-2xl px-3 py-2.5"
                            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.04)' }}>
                            <p className="text-[10px] font-semibold uppercase tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>
                              Contributor Notes
                            </p>
                            <p className="mt-1.5 text-sm font-medium leading-relaxed text-white">{noteText}</p>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Terminal build log */}
              <div className="mx-6 mt-4 mb-6 flex-none min-h-[280px] max-h-[420px] flex flex-col overflow-hidden rounded-[24px] border"
                style={{ background: 'rgba(0,0,0,0.5)', borderColor: 'rgba(255,255,255,0.05)' }}>
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
                      const provider = d.provider as string | undefined;
                      const evtStatus = d.status as string | undefined;
                      const detail = d.detail as string | undefined;

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
                          : evtStatus === 'failed' ? 'var(--accent-red)'
                            : 'var(--stark-cyan)';
                      }

                      const lineColor =
                        e.event_type === 'candidate_ready' ? (evtStatus === 'failed' ? 'var(--accent-red)' : 'var(--accent-green)')
                          : e.event_type === 'judge_result' ? '#f97316'
                            : evtStatus === 'failed' ? 'var(--accent-red)'
                              : evtStatus === 'running' ? 'var(--stark-cyan)'
                                : 'var(--text-muted)';

                      const prefix =
                        e.event_type === 'build_progress' ? '▸'
                          : e.event_type === 'candidate_ready' ? '✓'
                            : e.event_type === 'judge_result' ? '⚖'
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
                  {buildEvents.length > 0 && (
                    status === 'building' ? (
                      <div className="flex gap-3 items-baseline px-2 py-0.5">
                        <span className="w-5" />
                        <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.15)' }}>
                          {String(buildEvents.length + 1).padStart(3, '0')}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--stark-cyan)', animation: 'pulse-glow 1s ease-in-out infinite' }}>
                          █
                        </span>
                      </div>
                    ) : (
                      <div className="flex gap-3 items-baseline group px-2 py-0.5 rounded -mx-2">
                        <span className="shrink-0 w-5 text-center text-[10px]" style={{ color: 'var(--accent-green)' }}>
                          ✓
                        </span>
                        <span className="shrink-0 text-[10px]" style={{ color: 'rgba(255,255,255,0.15)' }}>
                          {String(buildEvents.length + 1).padStart(3, '0')}
                        </span>
                        <span className="shrink-0 font-semibold" style={{ color: 'var(--accent-green)', minWidth: '80px' }}>
                          SYSTEM
                        </span>
                        <span style={{ color: 'rgba(255,255,255,0.55)' }}>
                          Build stage finished
                        </span>
                        <span className="ml-auto shrink-0 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded"
                          style={{
                            background: 'rgba(16,185,129,0.18)',
                            color: 'var(--accent-green)',
                          }}>
                          done
                        </span>
                      </div>
                    )
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
                const completedNums = new Set(completedMarks.map(e => e.data.mark_number as number));
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
                      const done = completedNums.has(m.num);
                      const running = !done && m.num === nextNum && status === 'hardening';
                      const pending = !done && !running;
                      const result = completedMarks.find(e => (e.data.mark_number as number) === m.num);
                      const passed = result?.data.passed as boolean | undefined;
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
                  if (e.event_type === 'mark_started') {
                    return (
                      <div key={i} className="flex items-center gap-3 px-2 py-3" style={{ color: 'var(--text-muted)' }}>
                        <div className="status-dot" style={{ background: 'var(--accent-red)', animation: 'pulse-glow 1s ease-in-out infinite' }} />
                        <span className="text-xs">Mark {e.data.mark_name as string} starting...</span>
                      </div>
                    );
                  }

                  const passed = e.data.passed as boolean;
                  const markName = e.data.mark_name as string;
                  const failureType = e.data.failure_type as string | null;
                  const patchSummary = e.data.patch_summary as string | null;
                  const markNumber = e.data.mark_number as number;

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

              <div className="shrink-0 px-6 py-3 flex items-center justify-between gap-3"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(0,0,0,0.2)' }}>
                <div className="flex items-center gap-3">
                  <div className="status-dot" style={{ background: 'var(--accent-green)' }} />
                  <div>
                    <p className="text-xs font-semibold" style={{ color: 'var(--accent-green)' }}>
                      Build complete — your code is ready
                    </p>
                    <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                      {baselineCandidate
                        ? `${baselineCandidate.provider.toUpperCase()} is the current delivery baseline`
                        : 'Artifacts are ready to inspect and export.'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {previewUrl && previewStatus === 'active' && (
                    <a href={previewUrl} target="_blank" rel="noreferrer"
                      className="text-xs px-3 py-1.5 rounded-lg font-semibold transition-all"
                      style={{ background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.18)', color: 'var(--stark-cyan)' }}>
                      Open Live ↗
                    </a>
                  )}
                  {/* Showcase */}
                  {!showcase ? (
                    <button className="text-xs px-3 py-1.5 rounded-lg font-semibold transition-all"
                      style={{ background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.18)', color: 'var(--stark-cyan)' }}
                      onClick={generateShowcase} disabled={generatingShowcase}>
                      {generatingShowcase ? 'Generating…' : 'Generate Showcase'}
                    </button>
                  ) : (
                    <Link href={`/share/${id}`} target="_blank"
                      className="text-xs px-3 py-1.5 rounded-lg font-semibold"
                      style={{ background: 'rgba(0,212,255,0.08)', border: '1px solid rgba(0,212,255,0.18)', color: 'var(--stark-cyan)' }}>
                      View Showroom ↗
                    </Link>
                  )}
                </div>
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto p-6 pt-5">
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
          previewStatus={previewStatus}
          previewDetail={previewDetail}
        />
      </div>
    </div>
  );
}
