"use client";

import React, { useEffect, useState, useRef } from 'react';
import { useParams } from 'next/navigation';
import { AutoPlayer } from '@/components/AutoPlayer';

interface ShowcaseData {
  id: string;
  title: string;
  marketing_pitch: string;
  demo_script_json: any[];
  telemetry_highlights_json: any;
  view_count: number;
}

interface SessionPreview {
  preview_url: string;
  status: string;
}

export default function SharePage() {
  const { id } = useParams();
  const [showcase, setShowcase] = useState<ShowcaseData | null>(null);
  const [preview, setPreview] = useState<SessionPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [isDemoActive, setIsDemoActive] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

  useEffect(() => {
    fetchData();
  }, [id]);

  const fetchData = async () => {
    try {
      const [showcaseRes, previewRes] = await Promise.all([
        fetch(`${API}/sessions/${id}/showcase`),
        fetch(`${API}/sessions/${id}/preview`)
      ]);

      if (showcaseRes.ok) setShowcase(await showcaseRes.json());
      if (previewRes.ok) {
        const previewData = await previewRes.json();
        setPreview(previewData);
        
        if (previewData.status === 'restoring') {
          setTimeout(fetchData, 5000);
        }
      }
    } catch (error) {
      console.error("Failed to fetch showcase:", error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-stark-dark flex flex-col items-center justify-center gap-4">
        <div className="w-12 h-1 bg-white/10 relative overflow-hidden">
          <div className="absolute inset-0 bg-white/40" />
        </div>
        <div className="text-[10px] font-bold tracking-[0.3em] text-stark-white/60 uppercase">SYSTEM_READY // INITIALIZING_REGISTRY...</div>
      </div>
    );
  }

  if (!showcase) {
    return (
      <div className="min-h-screen bg-stark-dark flex flex-col items-center justify-center p-4 text-center">
        <div className="stark-grid absolute inset-0 opacity-20" />
        <h1 className="text-5xl font-black text-white mb-4 italic tracking-tighter uppercase">ACCESS_DENIED</h1>
        <p className="text-slate-500 max-w-md font-mono text-[10px] uppercase leading-relaxed tracking-widest">
          The requested project record is restricted or has been purged from the Stark Labs archive.
        </p>
        <a href="/" className="mt-8 btn-stark">
          RETURN_TO_STUDIO
        </a>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-stark-dark text-white selection:bg-white/10 selection:text-white overflow-x-hidden">
      <div className="stark-grid opacity-10 fixed inset-0 pointer-events-none" />
      
      {/* Refined Nav */}
      <nav className="fixed top-0 left-0 right-0 z-50 px-8 py-6 flex justify-between items-center bg-gradient-to-b from-stark-dark to-transparent">
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 rounded-sm bg-stark-white flex items-center justify-center">
            <span className="font-bold text-[10px] text-bg-primary">ST</span>
          </div>
          <div className="flex flex-col">
            <span className="font-bold tracking-[0.2em] text-[10px] uppercase text-white">STARK SYSTEMS</span>
            <span className="text-[7px] font-mono text-stark-white/40 tracking-[0.4em] uppercase -mt-0.5">Industrial Registry // Stable</span>
          </div>
        </div>
        
        <div className="px-5 py-2 glass-card border-none rounded-sm">
           <div className="text-[8px] font-mono text-stark-white/60 tracking-widest uppercase flex items-center gap-2">
             <span className="w-1.5 h-1.5 rounded-full bg-stark-white/40" />
             NODE_STABLE :: {showcase.id.slice(0,8).toUpperCase()}
           </div>
        </div>
      </nav>

      <main className="relative pt-40 pb-24 px-8 max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-16 items-center">
        {/* Cinematic Backdrop */}
        <div className="absolute top-1/4 -left-20 w-96 h-96 bg-stark-cyan/10 blur-[120px] rounded-full pointer-events-none" />
        <div className="absolute bottom-1/4 -right-20 w-80 h-80 bg-[#7000ff]/5 blur-[100px] rounded-full pointer-events-none" />

        {/* Left: Narrative HUD */}
        <div className="lg:col-span-5 relative">
          <div className="inline-flex items-center gap-3 px-3 py-1 bg-white/5 border border-white/10 rounded-full text-stark-white/60 text-[9px] font-bold tracking-widest uppercase mb-8">
            <span className="w-1 h-1 bg-stark-white/40 rounded-full" />
            Industrial Registry // Release Manifest
          </div>
          
          <h1 className="text-7xl font-bold tracking-tighter mb-10 leading-[0.85] text-white uppercase">
            {showcase.title.replace(' ', '_')}
          </h1>
          
          <div className="space-y-8 text-slate-400 font-medium leading-relaxed text-lg mb-14 border-l border-white/10 pl-8 relative">
            <div className="absolute top-0 left-[-1px] w-[3px] h-12 bg-stark-white" />
            {showcase.marketing_pitch.split('\n\n').map((para, i) => (
              <p key={i} className="animate-in fade-in slide-in-from-left-4 duration-700">{para}</p>
            ))}
          </div>

          <div className="flex flex-wrap gap-5">
            <button 
              onClick={() => setIsDemoActive(true)}
              className="px-10 py-5 bg-stark-white text-bg-primary font-bold uppercase tracking-widest text-[10px] transition-all hover:bg-white/90 rounded-sm group relative"
            >
              <span className="flex items-center gap-3">
                <svg className="w-4 h-4 text-bg-primary group-hover:scale-110 transition-transform" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z"/>
                </svg>
                RUN_SYSTEM_DEMO
              </span>
            </button>
            <button className="px-8 py-5 bg-white/5 border border-white/10 text-slate-500 font-black uppercase tracking-widest text-[10px] italic hover:text-white hover:border-white/20 transition-all rounded-sm">
              VIEW_SOURCE_BLUEPRINT
            </button>
          </div>

          {/* Technical Metadata */}
          <div className="mt-20 pt-10 border-t border-white/10 grid grid-cols-2 gap-12">
            <div>
              <p className="text-[8px] font-bold tracking-widest text-slate-500 uppercase mb-3">SYSTEM_INTEGRITY</p>
              <div className="flex items-baseline gap-2">
                 <p className="text-3xl font-bold text-white tracking-tighter">LVL_07</p>
                 <span className="text-[10px] font-mono text-stark-white/60 uppercase">Stable</span>
              </div>
            </div>
            <div>
              <p className="text-[8px] font-bold tracking-widest text-slate-500 uppercase mb-3">ADVERSARY_RESILIENCE</p>
              <p className="text-3xl font-bold text-stark-white tracking-tighter">98.4%</p>
            </div>
          </div>
        </div>

        {/* Right: Technical Viewport */}
        <div className="lg:col-span-7 relative">
          <div className="glass-card border-white/10 aspect-[4/3] rounded-sm overflow-hidden shadow-2xl relative group">
            <div className="absolute inset-0 bg-gradient-to-tr from-stark-dark to-transparent z-10 pointer-events-none opacity-20" />
            
            {/* Live Environment */}
            {preview?.status === 'active' ? (
              <div className="w-full h-full relative">
                <iframe 
                  ref={iframeRef}
                  src={preview.preview_url} 
                  className="w-full h-full bg-white border-0"
                  title="Mark III.5 Live Stream"
                />
                <AutoPlayer 
                  iframeRef={iframeRef}
                  script={showcase.demo_script_json}
                  isActive={isDemoActive}
                  onComplete={() => setIsDemoActive(false)}
                />
              </div>
            ) : preview?.status === 'restoring' ? (
              <div className="w-full h-full flex flex-col items-center justify-center bg-black/80 space-y-4">
                <div className="w-24 h-1 bg-white/10 relative overflow-hidden text-center justify-center items-center">
                    <div className="absolute inset-0 bg-white/40" />
                </div>
                <div className="text-stark-white font-bold text-[11px] uppercase tracking-[0.2em]">RESTORING_ENVIRONMENT...</div>
                <div className="text-slate-600 font-mono text-[7px] uppercase tracking-[0.4em]">STARK_CORE_NODE_SYNC_IN_PROGRESS</div>
              </div>
            ) : (
              <div className="w-full h-full flex flex-col items-center justify-center bg-black/90 text-center p-12">
                <div className="text-slate-500 font-black italic text-sm uppercase tracking-[0.3em] mb-4">ENVIRONMENT_DECOMMISSIONED</div>
                <p className="text-slate-700 font-mono text-[9px] uppercase max-w-xs leading-relaxed tracking-widest">
                  The mission instance has been purged. Data integrity verified but execution capability suspended.
                </p>
              </div>
            )}

            {/* Viewport HUD Overlays */}
            <div className="absolute top-6 left-6 z-40 flex items-center gap-3">
              <div className="w-2 h-2 rounded-full bg-red-600 animate-pulse" />
              <div className="flex flex-col">
                <div className="text-[9px] font-bold uppercase tracking-widest text-white/60">LIVE_SYSTEM_FEED</div>
                <div className="text-[6px] font-mono text-stark-white/40 uppercase tracking-tighter -mt-1">SECURE_LINK_STABLE</div>
              </div>
            </div>
            
            <div className="absolute bottom-6 right-6 z-40">
              <div className="px-4 py-2 glass-card border-none rounded-sm text-[9px] font-mono text-stark-white/40 uppercase tracking-widest">
                FPS: 60.0 // LATENCY: 14ms // {preview?.status?.toUpperCase()}
              </div>
            </div>
          </div>

          <div className="mt-8 flex justify-between items-center px-4">
            <div className="flex gap-4">
               {[1,2,3,4].map(i => (
                 <div key={i} className={`w-1 h-3 bg-white/10 ${i === 1 ? 'bg-stark-white' : ''}`} />
               ))}
            </div>
            <div className="flex flex-col items-end">
                 <div className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">REGISTRY_METRICS</div>
                 <div className="text-[7px] font-mono text-slate-600 uppercase">View_Count: {showcase.view_count.toString().padStart(5, '0')}</div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer Branding */}
      <footer className="py-20 px-8 flex flex-col items-center border-t border-white/5 bg-stark-dark relative">
        <div className="text-stark-white/20 text-[10px] font-bold tracking-[0.4em] uppercase mb-4">STARK SYSTEMS // INDUSTRIAL STUDIO MARK III.5</div>
        <p className="text-slate-700 text-[10px] font-mono uppercase tracking-[0.2em]">The industrial standard for autonomous engineering.</p>
        
        <div className="mt-10 flex gap-12 opacity-30">
            <div className="text-[8px] font-mono uppercase">©2026_STARK_LABS</div>
            <div className="text-[8px] font-mono uppercase">RESTRICTED_ACCESS</div>
            <div className="text-[8px] font-mono uppercase">ENCRYPTION_AES_256</div>
        </div>
      </footer>
    </div>
  );
}
