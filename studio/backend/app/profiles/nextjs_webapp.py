"""
Mark II Studio — Next.js Web App Profile
Full autonomous build+harden support for Next.js projects.
"""
from __future__ import annotations

from typing import Any

from app.profiles.base import BaseProfile


class NextJSWebAppProfile(BaseProfile):
    """Profile for Next.js web application projects."""

    @property
    def name(self) -> str:
        return "nextjs_webapp"

    @property
    def display_name(self) -> str:
        return "Next.js Web App"

    @property
    def supported(self) -> bool:
        return True

    @property
    def startup_command(self) -> str:
        return "npm run dev -- --hostname 0.0.0.0 --port 3000"

    @property
    def install_command(self) -> str:
        return "npm install"

    @property
    def preview_mode(self) -> str:
        return "iframe"

    @property
    def hardening_suite(self) -> str:
        return "nextjs_webapp"

    def get_builder_instructions(self) -> str:
        return """
Next.js Web App Profile Requirements:
- Use Next.js 14+ with App Router (app/ directory)
- Use TypeScript for all files
- Include package.json with all dependencies
- Include proper next.config.js
- Use server components by default, client components only when needed
- Include proper error boundaries and loading states
- Add SEO metadata to layout.tsx
- Use CSS Modules or Tailwind CSS for styling
- Include a health/status API route at /api/health
- Structure: app/layout.tsx, app/page.tsx, app/api/ for API routes
- Include proper TypeScript types
- Add proper form validation and error handling
"""

    def get_smoke_test_config(self) -> dict[str, Any]:
        return {
            "health_endpoint": "/api/health",
            "page_endpoint": "/",
            "expected_status": 200,
            "timeout_s": 15.0,
        }

    def get_delivery_manifest(self) -> list[str]:
        return [
            "package.json",
            "next.config.js",
            "tsconfig.json",
            "app/",
            "public/",
            "README.md",
        ]

    @classmethod
    def detect(cls, files: dict[str, str]) -> bool:
        """Detect Next.js projects by looking for framework markers."""
        # Check package.json for next dependency
        pkg = files.get("package.json", "")
        if '"next"' in pkg:
            return True
        # Check for next.config
        if "next.config.js" in files or "next.config.mjs" in files or "next.config.ts" in files:
            return True
        # Check for app directory structure
        for path in files:
            if path.startswith("app/") and path.endswith((".tsx", ".jsx", ".ts")):
                return True
        return False
