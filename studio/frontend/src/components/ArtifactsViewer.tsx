'use client';

import React, { useState, useEffect } from 'react';

interface ArtifactsData {
  artifacts: Record<string, string>;
  status: string;
  provider?: string;
}

export function ArtifactsViewer({ sessionId }: { sessionId: string }) {
  const [data, setData] = useState<ArtifactsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  useEffect(() => {
    const fetchArtifacts = async () => {
      try {
        const res = await fetch(`${API}/sessions/${sessionId}/artifacts`);
        if (res.ok) {
          const json = await res.json();
          setData(json);
          const filenames = Object.keys(json.artifacts);
          if (filenames.length > 0) setSelectedFile(filenames[0]);
        }
      } catch (err) {
        console.error("Failed to fetch artifacts:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchArtifacts();
  }, [sessionId, API]);

  if (loading) return (
    <div className="text-center py-20 flex flex-col items-center gap-4">
      <div className="w-12 h-1 bg-white/5 relative overflow-hidden">
        <div className="absolute inset-0 bg-white/20 animate-shimmer" />
      </div>
      <div className="text-[10px] font-bold tracking-[0.3em] text-slate-500 uppercase">SYNCHRONIZING_REGISTRY...</div>
    </div>
  );

  if (!data || !data.artifacts || Object.keys(data.artifacts).length === 0) return (
    <div className="text-center py-20 border border-dashed border-white/5 rounded-sm">
      <div className="text-sm font-bold text-slate-600 uppercase tracking-widest">ZERO_ARTIFACTS_DETECTED</div>
      <div className="text-[8px] font-mono text-slate-700 mt-2 uppercase">NO_SHIPMENT_TRACES_FOUND_IN_REGISTRY</div>
    </div>
  );

  const filenames = Object.keys(data.artifacts);

  return (
    <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-[500px] relative" style={{ height: '100%' }}>
      {/* File List HUD */}
      <div className="w-full lg:w-72 flex flex-col gap-2 overflow-y-auto pr-2 custom-scrollbar">
        <div className="text-[8px] font-bold text-slate-500 uppercase tracking-[0.2em] mb-2 pl-2">REGISTRY_NODES</div>
        {filenames.map(name => (
          <button
            key={name}
            onClick={() => setSelectedFile(name)}
            className={`text-left px-4 py-3 rounded-xl transition-all relative group ${
              selectedFile === name
                ? 'bg-white/5 border-white/10 text-white shadow-[0_0_0_1px_rgba(255,255,255,0.04),0_0_18px_rgba(255,255,255,0.06)]'
                : 'bg-black/20 border-white/5 text-slate-500 hover:border-white/10 hover:text-slate-300'
            } border`}
          >
            {selectedFile === name && <div className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-white" />}
            <span className="text-[10px] font-mono truncate block lowercase">{name}</span>
          </button>
        ))}
      </div>

      {/* Code Viewer Matrix */}
      <div className="flex-1 glass-card overflow-hidden flex flex-col !p-0">
        <div className="px-5 py-3 border-b border-white/10 bg-black/40 flex justify-between items-center">
          <div className="flex flex-col">
             <span className="text-[10px] font-bold text-white uppercase tracking-widest">{selectedFile}</span>
             <span className="text-[7px] font-mono text-slate-500 tracking-tighter -mt-0.5 uppercase">VERIFIED_BLUEPRINT</span>
          </div>
          <button 
            onClick={() => {
              if (selectedFile) {
                navigator.clipboard.writeText(data.artifacts[selectedFile]);
              }
            }}
            className="text-[9px] font-bold text-slate-400 uppercase tracking-widest hover:text-white transition-colors"
          >
            Copy_Source
          </button>
        </div>
        
        <div className="flex-1 relative overflow-hidden bg-black/60">
           <pre className="h-full p-8 overflow-auto text-[11px] font-mono text-slate-300 leading-relaxed selection:bg-white/10 selection:text-white custom-scrollbar">
            <code>{selectedFile ? data.artifacts[selectedFile] : ''}</code>
           </pre>
        </div>
        
        <div className="px-5 py-2 border-t border-white/5 bg-white/[0.01] flex justify-between items-center">
           <div className="text-[7px] font-mono text-slate-600 uppercase tracking-widest">
              Security: Mark_III.5_Verified
           </div>
           <div className="text-[7px] font-mono text-slate-400 uppercase">
              LOC: {selectedFile ? data.artifacts[selectedFile].split('\n').length : 0}
           </div>
        </div>
      </div>
    </div>
  );
}
