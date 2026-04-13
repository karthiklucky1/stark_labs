'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

type IntakeMode = 'prompt' | 'github' | 'paste';

const INTAKE_OPTIONS: { mode: IntakeMode; icon: string; title: string; desc: string }[] = [
  { mode: 'prompt',  icon: '💡', title: 'Describe It',  desc: 'Tell us what to build — Claude will interview you for the full spec' },
  { mode: 'github',  icon: '🔗', title: 'GitHub Repo',  desc: 'Import an existing repo — analyze, strengthen, and harden it' },
  { mode: 'paste',   icon: '📋', title: 'Paste Code',   desc: 'Paste files directly — we detect the stack and get to work' },
];

const STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  complete:    { bg: 'rgba(16,185,129,0.1)',  color: '#10b981' },
  hardening:   { bg: 'rgba(255,71,87,0.1)',   color: '#ff4757' },
  building:    { bg: 'rgba(59,130,246,0.1)',  color: '#3b82f6' },
  judging:     { bg: 'rgba(249,115,22,0.1)',  color: '#f97316' },
  interviewing:{ bg: 'rgba(0,212,255,0.1)',   color: '#00d4ff' },
  spec_review: { bg: 'rgba(139,92,246,0.1)',  color: '#8b5cf6' },
};

function uniqueFilePath(path: string, used: Set<string>): string {
  if (!used.has(path)) {
    used.add(path);
    return path;
  }

  const extensionIndex = path.lastIndexOf('.');
  const base = extensionIndex > 0 ? path.slice(0, extensionIndex) : path;
  const extension = extensionIndex > 0 ? path.slice(extensionIndex) : '';

  let suffix = 2;
  let candidate = `${base}-${suffix}${extension}`;
  while (used.has(candidate)) {
    suffix += 1;
    candidate = `${base}-${suffix}${extension}`;
  }
  used.add(candidate);
  return candidate;
}

function extractPathFromFenceInfo(info: string): string | null {
  const trimmed = info.trim();
  if (!trimmed) return null;

  const keyMatch = trimmed.match(/(?:file|path)\s*[:=]\s*["']?([^"'\s]+)["']?/i);
  if (keyMatch?.[1]) return keyMatch[1];

  const titleMatch = trimmed.match(/title\s*=\s*["']([^"']+)["']/i);
  if (titleMatch?.[1]) return titleMatch[1];

  const tokens = trimmed
    .split(/\s+/)
    .map(token => token.replace(/^["']|["']$/g, ''))
    .filter(Boolean);

  return tokens.find(token => token.includes('/') || /\.[a-z0-9]+$/i.test(token)) || null;
}

function inferFilename(content: string, hint?: string | null, index = 0): string {
  const trimmed = content.trim();
  const lower = trimmed.toLowerCase();
  const normalizedHint = (hint || '').trim().toLowerCase();

  if (normalizedHint === 'json' || (trimmed.startsWith('{') && /"dependencies"\s*:/.test(trimmed))) {
    return 'package.json';
  }
  if (/from\s+fastapi\b|import\s+fastapi\b|fastapi\(/i.test(trimmed)) {
    return 'main.py';
  }
  if (normalizedHint === 'md' || normalizedHint === 'markdown' || lower.startsWith('# ')) {
    return 'README.md';
  }
  if (normalizedHint === 'css' || /@tailwind\b|:root\s*\{|body\s*\{/i.test(trimmed)) {
    return 'app/globals.css';
  }
  if (
    normalizedHint === 'tsx'
    || normalizedHint === 'jsx'
    || /\buse client\b/.test(lower)
    || /from\s+['"]next\//i.test(trimmed)
    || /export\s+default\s+function/i.test(trimmed)
    || /className=/.test(trimmed)
  ) {
    return normalizedHint === 'jsx' ? 'app/page.jsx' : 'app/page.tsx';
  }
  if (normalizedHint === 'ts' || normalizedHint === 'typescript') {
    return `main${index > 0 ? `-${index + 1}` : ''}.ts`;
  }
  if (normalizedHint === 'js' || normalizedHint === 'javascript') {
    return `main${index > 0 ? `-${index + 1}` : ''}.js`;
  }
  if (normalizedHint === 'py' || normalizedHint === 'python') {
    return `main${index > 0 ? `-${index + 1}` : ''}.py`;
  }
  if (normalizedHint === 'html' || /<!doctype html>|<html/i.test(trimmed)) {
    return 'index.html';
  }

  return `main${index > 0 ? `-${index + 1}` : ''}.txt`;
}

function parsePastedFiles(input: string): Record<string, string> {
  const trimmed = input.trim();
  if (!trimmed) return {};

  const files: Record<string, string> = {};
  const usedPaths = new Set<string>();
  const blockPattern = /(?:^|\n)(?:(?:File|Path):\s*([^\n`]+)|([A-Za-z0-9_./@-]+\.[A-Za-z0-9]+))?\s*\n```([^\n`]*)\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  let blockIndex = 0;

  while ((match = blockPattern.exec(trimmed)) !== null) {
    const explicitPath = (match[1] || match[2] || '').trim();
    const fenceInfo = (match[3] || '').trim();
    const content = match[4].replace(/\n$/, '');
    const inferredPath = explicitPath || extractPathFromFenceInfo(fenceInfo) || inferFilename(content, fenceInfo, blockIndex);
    files[uniqueFilePath(inferredPath, usedPaths)] = content;
    blockIndex += 1;
  }

  if (Object.keys(files).length > 0) {
    return files;
  }

  return { [inferFilename(trimmed)]: trimmed };
}

export default function Home() {
  const [mode, setMode] = useState<IntakeMode>('prompt');
  const [prompt, setPrompt] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [pastedCode, setPastedCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessions, setSessions] = useState<any[]>([]);
  const router = useRouter();

  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetch(`${API}/sessions?limit=6`)
      .then(r => r.ok ? r.json() : [])
      .then(setSessions)
      .catch(() => {});
  }, [API]);

  const handleStart = async () => {
    setLoading(true);
    try {
      const body: Record<string, string> = { intake_mode: mode };
      if (mode === 'prompt') body.prompt = prompt;
      if (mode === 'github') body.github_url = githubUrl;

      const res = await fetch(`${API}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const session = await res.json();

      if (mode === 'paste' && pastedCode) {
        await fetch(`${API}/sessions/${session.id}/intake`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ files: parsePastedFiles(pastedCode) }),
        });
      }

      router.push(`/session/${session.id}`);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center px-6 pt-28 pb-20 stark-grid-fine">

      {/* ── Hero ─────────────────────────────────────────── */}
      <div className="text-center mb-14 max-w-3xl relative">
        {/* ambient glow behind heading */}
        <div className="absolute -top-16 left-1/2 -translate-x-1/2 w-[600px] h-[300px] pointer-events-none"
          style={{ background: 'radial-gradient(ellipse, rgba(0,212,255,0.07) 0%, transparent 70%)' }} />

        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full mb-6"
          style={{ border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.03)' }}>
          <div className="status-dot" style={{ background: 'var(--accent-green)' }} />
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
            Stark Studio — Mark II Core
          </span>
        </div>

        <h1 className="text-6xl font-black mb-5 leading-tight tracking-tight">
          <span className="gradient-text">Build.</span>{' '}
          <span style={{ color: 'rgba(255,255,255,0.25)' }}>Break.</span>{' '}
          <span className="text-white">Heal.</span>
        </h1>

        <p className="text-base leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          AI models build your app in parallel. Claude judges. Mark II hardens it for production.
        </p>
      </div>

      {/* ── Intake ───────────────────────────────────────── */}
      <div className="w-full max-w-2xl mb-16">
        {/* Mode selector */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          {INTAKE_OPTIONS.map((opt) => (
            <button
              key={opt.mode}
              onClick={() => setMode(opt.mode)}
              className="glass-card p-4 text-left transition-all"
              style={{
                borderColor: mode === opt.mode ? 'rgba(0,212,255,0.35)' : undefined,
                background: mode === opt.mode ? 'rgba(0,212,255,0.05)' : undefined,
                boxShadow: mode === opt.mode ? '0 0 20px rgba(0,212,255,0.08)' : undefined,
              }}
            >
              <div className="text-xl mb-2">{opt.icon}</div>
              <div className="text-sm font-semibold text-white mb-1">{opt.title}</div>
              <div className="text-xs leading-snug" style={{ color: 'var(--text-muted)' }}>{opt.desc}</div>
            </button>
          ))}
        </div>

        {/* Input card */}
        <div className="glass-card p-6">
          {mode === 'prompt' && (
            <textarea
              className="input-field min-h-[130px] resize-none text-sm"
              placeholder="Describe what you want to build… e.g. 'A FastAPI service for user subscriptions with Stripe and rate limiting'"
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
            />
          )}
          {mode === 'github' && (
            <input
              className="input-field text-sm"
              placeholder="https://github.com/username/repo"
              value={githubUrl}
              onChange={e => setGithubUrl(e.target.value)}
            />
          )}
          {mode === 'paste' && (
            <>
              <textarea
                className="input-field min-h-[180px] resize-none terminal-text text-xs"
                placeholder={'// Paste a file, or multiple fenced blocks\n// Example:\n// File: app/page.tsx\n// ```tsx\n// ...\n// ```'}
                value={pastedCode}
                onChange={e => setPastedCode(e.target.value)}
              />
              <p className="mt-3 text-[11px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                Paste a single file directly, or use blocks like <code>File: app/page.tsx</code> followed by fenced code for multi-file intake.
              </p>
            </>
          )}

          <button
            className="btn-primary w-full mt-4 py-3 text-sm"
            onClick={handleStart}
            disabled={loading}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3"
                    fill="none" strokeDasharray="31.4" strokeDashoffset="10" />
                </svg>
                Starting session…
              </span>
            ) : '🚀 Start Building'}
          </button>
        </div>
      </div>

      {/* ── Feature Cards ────────────────────────────────── */}
      <div className="w-full max-w-4xl grid grid-cols-3 gap-5 mb-24">
        {[
          { icon: '🤖', title: 'Reverse Interview',   desc: 'Claude captures full requirements through intelligent Q&A' },
          { icon: '⚔️', title: 'Dual Builder Race',   desc: 'Multiple AI providers build in parallel — Claude picks the winner' },
          { icon: '🛡️', title: 'Mark II Hardening',  desc: 'Adversarial swarm attacks harden your code for production' },
        ].map(f => (
          <div key={f.title} className="glass-card p-6 text-center">
            <div className="text-3xl mb-4">{f.icon}</div>
            <div className="text-sm font-semibold text-white mb-2">{f.title}</div>
            <div className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>{f.desc}</div>
          </div>
        ))}
      </div>

      {/* ── Sessions Portal ───────────────────────────────── */}
      {sessions.length > 0 && (
        <div className="w-full max-w-6xl">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-bold text-white">Recent Projects</h2>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {sessions.length} sessions
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {sessions.map(s => {
              const st = STATUS_STYLE[s.status] || { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' };
              return (
                <div key={s.id}
                  className="glass-card p-5 flex flex-col gap-4 hover:-translate-y-0.5 transition-transform">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="text-sm font-semibold text-white leading-snug line-clamp-1">
                      {s.showcase?.title || `Project ${s.id.slice(0, 8).toUpperCase()}`}
                    </h3>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full shrink-0 capitalize"
                      style={{ background: st.bg, color: st.color }}>
                      {s.status.replace('_', ' ')}
                    </span>
                  </div>

                  <p className="text-xs leading-relaxed line-clamp-2" style={{ color: 'var(--text-muted)' }}>
                    {s.original_prompt || 'No description'}
                  </p>

                  <div className="flex gap-2 mt-auto">
                    <Link href={`/session/${s.id}`}
                      className="flex-1 py-2 rounded-lg text-xs font-semibold text-center transition-all"
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-secondary)' }}>
                      Open
                    </Link>
                    {s.status === 'complete' && (
                      <Link href={`/share/${s.id}`}
                        className="flex-1 py-2 rounded-lg text-xs font-semibold text-center transition-all"
                        style={{ background: 'rgba(0,212,255,0.1)', border: '1px solid rgba(0,212,255,0.2)', color: 'var(--stark-cyan)' }}>
                        Showroom
                      </Link>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Footer ────────────────────────────────────────── */}
      <div className="w-full max-w-6xl mt-20 pt-8 flex justify-between items-center"
        style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
        <Link href="/codex"
          className="flex items-center gap-2 text-xs transition-colors hover:text-white"
          style={{ color: 'var(--text-muted)' }}>
          <span>🧠</span>
          <span>Knowledge Codex</span>
        </Link>
        <span className="text-xs font-mono" style={{ color: 'rgba(255,255,255,0.1)' }}>
          Stark Studio v2.2
        </span>
      </div>
    </div>
  );
}
