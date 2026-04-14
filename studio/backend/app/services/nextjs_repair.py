"""
Mark II Studio — Next.js Repair Helpers
Deterministic fixes for common generated Next.js project omissions.
"""
from __future__ import annotations

import json

from app.services.profiles import detect_profile


_POSTCSS_CONFIG_JS = """module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
"""


def repair_nextjs_project_files(files: dict[str, str] | None) -> tuple[dict[str, str], bool]:
    normalized_files = dict(files or {})
    if not normalized_files:
        return normalized_files, False
    if detect_profile(normalized_files).name != "nextjs_webapp":
        return normalized_files, False

    files_changed = False
    uses_alias_imports = any(
        isinstance(content, str) and "@/" in content
        for content in normalized_files.values()
    )
    has_typescript_sources = any(
        path.endswith((".ts", ".tsx"))
        for path in normalized_files
    )
    globals_css = str(normalized_files.get("app/globals.css", ""))
    uses_tailwind = "@tailwind" in globals_css or any(
        name.startswith("tailwind.config.")
        for name in normalized_files
    )

    if has_typescript_sources and "tsconfig.json" not in normalized_files:
        normalized_files["tsconfig.json"] = json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2017",
                    "lib": ["dom", "dom.iterable", "esnext"],
                    "allowJs": True,
                    "skipLibCheck": True,
                    "strict": False,
                    "noEmit": True,
                    "esModuleInterop": True,
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "jsx": "preserve",
                    "incremental": True,
                    "plugins": [{"name": "next"}],
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["./*"],
                    },
                },
                "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
                "exclude": ["node_modules"],
            },
            indent=2,
        ) + "\n"
        files_changed = True

    if has_typescript_sources and "next-env.d.ts" not in normalized_files:
        normalized_files["next-env.d.ts"] = (
            "/// <reference types=\"next\" />\n"
            "/// <reference types=\"next/image-types/global\" />\n"
            "\n"
        )
        files_changed = True

    if uses_alias_imports and not has_typescript_sources and "jsconfig.json" not in normalized_files:
        normalized_files["jsconfig.json"] = json.dumps(
            {
                "compilerOptions": {
                    "baseUrl": ".",
                    "paths": {
                        "@/*": ["./*"],
                    },
                },
            },
            indent=2,
        ) + "\n"
        files_changed = True

    if uses_tailwind and "postcss.config.js" not in normalized_files and "postcss.config.mjs" not in normalized_files:
        normalized_files["postcss.config.js"] = _POSTCSS_CONFIG_JS
        files_changed = True

    return normalized_files, files_changed
