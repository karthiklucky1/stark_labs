'use client';

import React from 'react';

interface GlassCardProps {
  children: React.ReactNode;
  title?: string;
  icon?: string;
  className?: string;
  headerAction?: React.ReactNode;
  subtitle?: string;
}

const GlassCard: React.FC<GlassCardProps> = ({
  children,
  title,
  icon,
  className = '',
  headerAction,
  subtitle,
}) => {
  return (
    <div className={`glass-card flex flex-col h-full min-h-0 ${className}`}>
      {(title || icon) && (
        <div className="px-5 py-3.5 flex items-center justify-between shrink-0"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <div className="flex items-center gap-2.5">
            {icon && <span className="text-base opacity-70">{icon}</span>}
            <div className="flex flex-col gap-0.5">
              {title && (
                <h3 className="text-xs font-semibold tracking-wide text-white/70">
                  {title}
                </h3>
              )}
              {subtitle && (
                <span className="text-[9px] font-mono uppercase tracking-widest"
                  style={{ color: 'var(--text-muted)' }}>
                  {subtitle}
                </span>
              )}
            </div>
          </div>
          {headerAction && <div className="flex items-center">{headerAction}</div>}
        </div>
      )}

      <div className="flex-1 min-h-0 relative flex flex-col">
        {children}
      </div>
    </div>
  );
};

export default GlassCard;
