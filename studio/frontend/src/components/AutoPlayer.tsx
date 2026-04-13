"use client";

import React, { useEffect, useState, useRef } from 'react';

/**
 * AutoPlayer component
 * Executes a sequence of UI interactions against a target iframe.
 */
interface DemoStep {
  action: 'click' | 'type' | 'wait' | 'api_call';
  target: string;
  value?: string;
  caption: string;
  delay: number;
}

interface AutoPlayerProps {
  iframeRef: React.RefObject<HTMLIFrameElement>;
  script: DemoStep[];
  isActive: boolean;
  onComplete?: () => void;
}

export const AutoPlayer: React.FC<AutoPlayerProps> = ({ iframeRef, script, isActive, onComplete }) => {
  const [currentStep, setCurrentStep] = useState(-1);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (isActive && !isPlaying && script.length > 0) {
      startDemo();
    }
  }, [isActive]);

  const startDemo = async () => {
    setIsPlaying(true);
    setCurrentStep(0);

    for (let i = 0; i < script.length; i++) {
      setCurrentStep(i);
      const step = script[i];
      
      await executeStep(step);
      
      if (i < script.length - 1) {
        await new Promise(resolve => setTimeout(resolve, step.delay));
      }
    }

    setIsPlaying(false);
    if (onComplete) onComplete();
  };

  const executeStep = async (step: DemoStep) => {
    const iframe = iframeRef.current;
    if (!iframe || !iframe.contentWindow) return;

    // Cross-origin limitation: We can only simulate if the sandbox allows it.
    // However, since we control the sandbox build, we could inject a small 
    // "Remote Control" script during build.
    // For now, we simulate "Visual Highlighting" on the parent and 
    // attempt to postMessage for interaction.
    
    console.log(`[AutoPlayer] Executing: ${step.caption}`, step);

    // 1. Send command to iframe
    iframe.contentWindow.postMessage({
      type: 'STARK_DEMO_ACTION',
      payload: step
    }, '*');

    // 2. Local visual effect if needed
  };

  if (!isActive || currentStep === -1) return null;

  return (
    <div className="absolute bottom-12 left-1/2 -translate-x-1/2 z-50 w-full max-w-md pointer-events-none">
      <div className="bg-black/80 backdrop-blur-md border border-[#00f2ff]/30 p-4 rounded-xl shadow-[0_0_30px_rgba(0,242,255,0.1)] transition-all animate-in fade-in slide-in-from-bottom-4">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-[#00f2ff] animate-pulse" />
          <p className="text-[#00f2ff] font-mono text-sm uppercase tracking-wider">
            {script[currentStep]?.caption}
          </p>
        </div>
        <div className="mt-2 h-1 bg-white/10 rounded-full overflow-hidden">
          <div 
            className="h-full bg-[#00f2ff] transition-all duration-500"
            style={{ width: `${((currentStep + 1) / script.length) * 100}%` }}
          />
        </div>
      </div>
    </div>
  );
};
