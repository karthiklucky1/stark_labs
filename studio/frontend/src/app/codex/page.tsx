'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface Pattern {
  id: string;
  vulnerability: string;
  summary: string;
  timestamp: string;
}

interface CodexStats {
  total_patterns: number;
  recent: Pattern[];
}

export default function CodexPage() {
  const [stats, setStats] = useState<CodexStats | null>(null);
  const [loading, setLoading] = useState(true);
  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch(`${API}/codex`);
        if (res.ok) {
          const data = await res.json();
          setStats(data);
        }
      } catch (err) {
        console.error('Failed to fetch codex stats:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, [API]);

  const handleExport = () => {
    window.open(`${API}/codex/export`);
  };

  return (
    <div className="pt-24 pb-20 px-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold mb-2">Project Neural-Arc</h1>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Distilling high-quality coding insights from the Mark II Hardening loop.
          </p>
        </div>
        <button 
          onClick={handleExport}
          className="btn-primary flex items-center gap-2"
        >
          <span>📦</span> Export for Training
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
        <div className="glass-card p-8 text-center">
          <div className="text-4xl font-mono mb-2 gradient-text">
            {stats?.total_patterns || 0}
          </div>
          <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
            Harvested Patterns
          </div>
        </div>
        <div className="glass-card p-8 text-center">
          <div className="text-4xl font-mono mb-2" style={{ color: 'var(--accent-green)' }}>
            100%
          </div>
          <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
            Data Integrity
          </div>
        </div>
        <div className="glass-card p-8 text-center">
          <div className="text-4xl font-mono mb-2" style={{ color: 'var(--accent-cyan)' }}>
            Local
          </div>
          <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
            Storage Architecture
          </div>
        </div>
      </div>

      <div className="glass-card overflow-hidden">
        <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
          <h2 className="font-semibold">Recent Knowledge Distillations</h2>
          <span className="text-xs font-mono" style={{ color: 'var(--text-muted)' }}>stark_codex_v1.0</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-white/5 text-xs uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                <th className="px-6 py-3 font-semibold">Vulnerability</th>
                <th className="px-6 py-3 font-semibold">Distilled Insight</th>
                <th className="px-6 py-3 font-semibold text-right">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10">
              {stats?.recent.map((p) => (
                <tr key={p.id} className="hover:bg-white/5 transition-colors">
                  <td className="px-6 py-4">
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono border" style={{ color: 'var(--accent-red)', borderColor: 'rgba(239, 68, 68, 0.2)', backgroundColor: 'rgba(239, 68, 68, 0.1)' }}>
                      {p.vulnerability}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm font-medium">{p.summary}</td>
                  <td className="px-6 py-4 text-xs tabular-nums text-right" style={{ color: 'var(--text-muted)' }}>
                    {new Date(p.timestamp).toLocaleString()}
                  </td>
                </tr>
              ))}
              {stats?.recent.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-6 py-20 text-center" style={{ color: 'var(--text-muted)' }}>
                    <div className="text-3xl mb-4">💤</div>
                    <p>No coding patterns harvested yet. Run a hardening loop to start learning.</p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-8 p-6 glass-card bg-white/5 border-white/10">
        <h3 className="font-semibold mb-2 flex items-center gap-2">
          <span>🧠</span> Out-of-the-Box: How this makes you better
        </h3>
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          Standard coders are trained on generic internet code. <strong>The Codex</strong> is different—it learns specifically from the 
          <strong> Stark Labs Break-Heal Loop</strong>. It captures the rare moments where an LLM is pushed to its limits and forced 
          to fix a critical security flaw. By feeding this data back into a personal model, you create a "Shadow Coder" 
          that specializes in precisely the patterns your architecture uses.
        </p>
      </div>

      <div className="mt-6 flex justify-center">
        <Link href="/" className="text-sm hover:underline" style={{ color: 'var(--text-muted)' }}>
          ← Back to Command Center
        </Link>
      </div>
    </div>
  );
}
