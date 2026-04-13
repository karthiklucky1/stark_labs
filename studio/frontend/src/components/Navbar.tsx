"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Navbar() {
  const pathname = usePathname();

  if (pathname?.startsWith('/share')) return null;

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50"
      style={{
        background: 'rgba(3, 7, 18, 0.75)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderBottom: '1px solid rgba(255,255,255,0.05)',
      }}
    >
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-3 group">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: 'var(--gradient-primary)', boxShadow: '0 0 16px rgba(0,212,255,0.3)' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#030712" strokeWidth="3">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-bold tracking-tight text-white leading-none">
              Stark Studio
            </span>
            <span className="text-[9px] font-mono tracking-widest uppercase leading-none mt-0.5"
              style={{ color: 'var(--text-muted)' }}>
              Mark II Core
            </span>
          </div>
        </Link>

        {/* Status */}
        <div className="flex items-center gap-2">
          <div className="status-dot" style={{ background: 'var(--accent-green)' }} />
          <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
            Operational
          </span>
        </div>
      </div>
    </nav>
  );
}
