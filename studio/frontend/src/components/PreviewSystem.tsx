'use client';

import { useState, useEffect } from 'react';

interface PreviewSystemProps {
  sessionId: string;
  previewUrl: string | null;
  profileType: string | null;
  previewMode?: 'iframe' | 'api_playground' | 'none' | null;
  previewStatus?: string | null;
  previewDetail?: string | null;
}

interface ApiEndpoint {
  path: string;
  method: string;
}

type UrlState = 'checking' | 'alive' | 'dead' | 'none';

export default function PreviewSystem({
  sessionId,
  previewUrl,
  profileType,
  previewMode,
  previewStatus,
  previewDetail,
}: PreviewSystemProps) {
  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const [viewport, setViewport] = useState<'mobile' | 'tablet' | 'desktop'>('desktop');
  const [endpoints, setEndpoints] = useState<ApiEndpoint[]>([]);
  const [activeEndpointKey, setActiveEndpointKey] = useState<string>('GET /');
  const [response, setResponse] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const previewIsReady = previewStatus === 'active';
  const urlState: UrlState =
    !previewUrl
      ? 'none'
      : previewIsReady
      ? 'alive'
      : previewStatus === 'restoring'
      ? 'checking'
      : previewStatus === 'paused'
      ? 'checking'
      : 'checking';

  const isApiPreview = previewMode
    ? previewMode === 'api_playground'
    : profileType === 'fastapi_service';
  const endpointOptions = endpoints.length > 0 ? endpoints : [{ method: 'GET', path: '/' }];
  const activeEndpoint =
    endpointOptions.find(endpoint => `${endpoint.method} ${endpoint.path}` === activeEndpointKey)
    || endpointOptions[0];

  useEffect(() => {
    setEndpoints([]);
    setActiveEndpointKey('GET /');
    setResponse(null);
  }, [sessionId, isApiPreview]);

  // Auto-discover endpoints for APIs when sandbox is alive
  useEffect(() => {
    if (isApiPreview && previewUrl && previewIsReady) {
      fetch(`${API}/sessions/${sessionId}/preview/openapi`)
        .then(r => r.ok ? r.json() : null)
        .then(spec => {
          if (!spec) return;
          const discovered: ApiEndpoint[] = [];
          Object.entries(spec.paths).forEach(([path, methods]: [string, any]) => {
            Object.keys(methods).forEach(method => {
              discovered.push({ path, method: method.toUpperCase() });
            });
          });
          setEndpoints(discovered);
          if (discovered.length > 0) setActiveEndpointKey(`${discovered[0].method} ${discovered[0].path}`);
        })
        .catch(() => {});
    }
  }, [API, isApiPreview, previewIsReady, previewUrl, sessionId]);

  const triggerRequest = async () => {
    if (!previewUrl || !activeEndpoint) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/sessions/${sessionId}/preview/request`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: activeEndpoint.path, method: activeEndpoint.method }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        setResponse({ error: 'Request failed', detail: data?.detail || `HTTP ${res.status}` });
        return;
      }
      setResponse(data);
    } catch (err) {
      setResponse({ error: 'Request failed', detail: String(err) });
    } finally {
      setLoading(false);
    }
  };

  // No URL at all
  if (!previewUrl || urlState === 'none') {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.4)' }}>
        <div className="text-center p-8 max-w-[260px]">
          <div className="text-3xl mb-4">📡</div>
          <p className="text-xs font-semibold mb-1" style={{ color: 'var(--text-secondary)' }}>Live Preview</p>
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            Preview will appear here once the service starts in the sandbox
          </p>
        </div>
      </div>
    );
  }

  if (!previewIsReady) {
    const title = previewStatus === 'paused' ? 'Preview Paused' : 'Restoring Preview';
    const detail =
      previewDetail
      || (previewStatus === 'paused'
        ? 'Hardening is using the sandbox right now. Preview will come back after it finishes.'
        : 'The sandbox service is starting up. Preview will appear here once it is ready.');
    return (
      <div className="flex-1 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.4)' }}>
        <div className="text-center p-8 max-w-[280px]">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center mx-auto mb-4"
            style={{ background: 'rgba(0,212,255,0.1)', border: '1px solid rgba(0,212,255,0.18)' }}>
            <span className="text-sm" style={{ color: 'var(--stark-cyan)' }}>⟳</span>
          </div>
          <p className="text-xs font-semibold mb-1 text-white">{title}</p>
          <p className="text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {detail}
          </p>
        </div>
      </div>
    );
  }

  // Checking
  if (urlState === 'checking') {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.4)' }}>
        <div className="text-center p-8">
          <div className="status-dot mx-auto mb-3" style={{ background: 'var(--stark-cyan)', animation: 'pulse-glow 1s ease-in-out infinite' }} />
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Connecting to sandbox…</p>
        </div>
      </div>
    );
  }

  const viewportFrameClass =
    viewport === 'mobile'
      ? 'w-[375px] h-[667px] rounded-[30px]'
      : viewport === 'tablet'
      ? 'w-[768px] h-[1024px] scale-[0.55] origin-top rounded-[32px]'
      : 'w-full h-full rounded-[24px]';

  // API PLAYGROUND MODE (alive + API)
  if (isApiPreview) {
    return (
      <div className="flex-1 flex flex-col h-full overflow-hidden" style={{ background: 'rgba(0,0,0,0.6)' }}>
        {/* Header */}
        <div className="px-4 py-3 flex items-center justify-between shrink-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(0,0,0,0.3)' }}>
          <div>
            <p className="text-xs font-semibold text-white">API Playground</p>
            <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Live sandbox</p>
          </div>
          <a href={`${previewUrl}/docs`} target="_blank" rel="noreferrer"
            className="text-[10px] font-semibold transition-colors"
            style={{ color: 'var(--stark-cyan)' }}>
            Docs ↗
          </a>
        </div>

        {/* Endpoint selector */}
        <div className="px-4 py-3 shrink-0" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          <p className="text-[10px] font-semibold mb-2" style={{ color: 'var(--text-muted)' }}>Endpoint</p>
          <div className="flex gap-2">
            <select
              value={`${activeEndpoint.method} ${activeEndpoint.path}`}
              onChange={e => setActiveEndpointKey(e.target.value)}
              className="flex-1 text-xs rounded-lg px-3 py-2 outline-none"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text-primary)' }}>
              {endpointOptions.map(e => (
                    <option key={`${e.method}-${e.path}`} value={`${e.method} ${e.path}`} style={{ background: '#050608' }}>
                      {e.method} {e.path}
                    </option>
                  ))}
            </select>
            <button onClick={triggerRequest} disabled={loading} className="btn-primary px-4 text-xs">
              {loading ? '…' : 'Send'}
            </button>
          </div>
        </div>

        {/* Response */}
        <div className="flex-1 overflow-auto px-4 py-3">
          <p className="text-[10px] font-semibold mb-2" style={{ color: 'var(--text-muted)' }}>Response</p>
          {response ? (
            <pre className="text-[11px] font-mono leading-relaxed rounded-lg p-3 overflow-x-auto"
              style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.06)', color: 'var(--text-primary)' }}>
              {JSON.stringify(response, null, 2)}
            </pre>
          ) : (
            <div className="flex items-center justify-center h-32 rounded-lg text-xs"
              style={{ border: '1px dashed rgba(255,255,255,0.08)', color: 'var(--text-muted)' }}>
              Hit Send to see the response
            </div>
          )}
        </div>
      </div>
    );
  }

  // WEB APP IFRAME MODE (alive + web)
  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden"
      style={{ background: 'linear-gradient(180deg, rgba(2,6,23,0.98) 0%, rgba(8,15,31,0.96) 100%)' }}>
      <div className="px-4 py-3 shrink-0"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: 'rgba(0,0,0,0.24)' }}>
        <div className="flex items-center justify-between gap-3 mb-3">
          <div>
            <p className="text-xs font-semibold text-white">Live Preview</p>
            <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Responsive canvas</p>
          </div>
          <a href={previewUrl} target="_blank" rel="noreferrer"
            className="text-[10px] font-semibold px-3 py-1.5 rounded-full transition-all"
            style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-secondary)' }}>
            Open ↗
          </a>
        </div>
        <div className="text-[10px] font-mono truncate px-3 py-2 rounded-xl text-center"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.06)', color: 'var(--text-secondary)' }}>
          {previewUrl}
        </div>
      </div>

      {/* Viewport toggles */}
      <div className="px-4 py-3 shrink-0"
        style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: 'rgba(255,255,255,0.02)' }}>
        <div className="flex justify-center">
          <div className="inline-flex items-center gap-1 p-1 rounded-full"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
            {(['mobile', 'tablet', 'desktop'] as const).map(v => (
              <button key={v} onClick={() => setViewport(v)}
                className="text-[10px] font-semibold capitalize transition-all px-3 py-1.5 rounded-full"
                style={{
                  background: viewport === v ? 'rgba(0,212,255,0.14)' : 'transparent',
                  color: viewport === v ? 'var(--stark-cyan)' : 'var(--text-secondary)',
                  boxShadow: viewport === v ? 'inset 0 0 0 1px rgba(0,212,255,0.18)' : 'none',
                }}>
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Iframe */}
      <div className="flex-1 flex items-center justify-center p-4 overflow-auto"
        style={{
          background: 'radial-gradient(circle at top, rgba(0,212,255,0.12) 0%, transparent 32%), linear-gradient(180deg, rgba(15,23,42,0.9) 0%, rgba(2,6,23,0.96) 100%)',
        }}>
        <div className="w-full h-full rounded-[28px] p-3"
          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
          <div className={`${viewportFrameClass} border overflow-hidden transition-all duration-500 mx-auto`}
            style={{
              borderColor: 'rgba(255,255,255,0.12)',
              background: '#ffffff',
              boxShadow: '0 28px 80px rgba(0,0,0,0.38)',
            }}>
            <div className="h-8 px-3 flex items-center gap-1.5"
              style={{ background: 'linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%)', borderBottom: '1px solid rgba(15,23,42,0.08)' }}>
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#f87171' }} />
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#fbbf24' }} />
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#34d399' }} />
              <div className="ml-2 flex-1 text-[10px] font-mono truncate"
                style={{ color: '#64748b' }}>
                {viewport}
              </div>
            </div>
            <iframe
              src={previewUrl}
              className="w-full border-0 bg-white"
              style={{ height: 'calc(100% - 32px)' }}
              title="Live Preview"
              sandbox="allow-scripts allow-same-origin allow-forms"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
