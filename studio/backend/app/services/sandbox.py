"""
Mark II Studio — E2B Sandbox Manager
Manages cloud sandbox lifecycle for build, test, preview, and hardening.
"""
from __future__ import annotations

import logging
import asyncio
import re
import httpx
from typing import Any
from dataclasses import dataclass

from app.settings import settings

logger = logging.getLogger(__name__)

_PORT_PATTERNS = (
    re.compile(r"(?:^|\s)--port(?:=|\s+)(\d+)(?:\s|$)"),
    re.compile(r"(?:^|\s)-p(?:=|\s+)(\d+)(?:\s|$)"),
    re.compile(r"(?:^|\s)PORT=(\d+)(?:\s|$)"),
)


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class TestResult:
    passed: bool
    detail: str
    metrics: dict[str, Any]


class SandboxManager:
    """
    E2B sandbox lifecycle manager.
    Each candidate gets its own isolated sandbox for building, testing, and previewing.
    """

    def __init__(self) -> None:
        self._sandboxes: dict[str, Any] = {}  # sandbox_id → E2B Sandbox instance

    @staticmethod
    def infer_service_port(
        startup_cmd: str | None,
        *,
        health_path: str = "/health",
        files: dict[str, str] | None = None,
    ) -> int:
        """Best-effort public port inference for sandboxed services."""
        command = (startup_cmd or "").strip()
        for pattern in _PORT_PATTERNS:
            match = pattern.search(command)
            if match:
                return int(match.group(1))

        lowered = command.lower()
        if "vite" in lowered:
            return 5173
        if any(marker in lowered for marker in ("next ", "nextjs", "npm run dev", "pnpm dev", "yarn dev", "npm start")):
            return 3000
        if any(marker in lowered for marker in ("uvicorn", "gunicorn", "hypercorn", "fastapi")):
            return 8000

        file_names = set((files or {}).keys())
        if any(name in file_names for name in ("next.config.js", "next.config.mjs", "next.config.ts")):
            return 3000
        if "vite.config.ts" in file_names or "vite.config.js" in file_names:
            return 5173
        if any(name.startswith("app/") and name.endswith((".tsx", ".jsx")) for name in file_names):
            return 3000
        return 8000

    async def get_service_url_for_command(
        self,
        sandbox_id: str,
        startup_cmd: str | None,
        *,
        health_path: str = "/health",
        files: dict[str, str] | None = None,
    ) -> str:
        port = self.infer_service_port(startup_cmd, health_path=health_path, files=files)
        return await self.get_service_url(sandbox_id, port=port)

    @staticmethod
    def _escape_single_quotes(value: str) -> str:
        return value.replace("'", "'\"'\"'")

    def _build_launch_command(self, startup_cmd: str) -> str:
        escaped_startup_cmd = self._escape_single_quotes(startup_cmd)
        # Use non-login shell (-c not -lc) to avoid login profile scripts (e.g. nohup wrappers
        # in /etc/profile.d/) writing to service.log before the service starts.
        # Explicitly prepend common bin paths so npm/uvicorn/python are found without login env.
        return (
            "bash -c 'export PATH=/usr/local/bin:/usr/bin:/bin:/home/user/.local/bin:$PATH; "
            f"exec {escaped_startup_cmd} > service.log 2>&1'"
        )

    async def is_service_available(self, base_url: str, health_path: str = "/health") -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base_url}{health_path}", timeout=3.0)
                return resp.status_code < 500
        except Exception:
            return False

    async def is_sandbox_alive(self, sandbox_id: str) -> bool:
        """Check if a sandbox is still active and reachable."""
        if not sandbox_id:
            return False
        if sandbox_id.startswith("mock-"):
            return True
        try:
            from e2b import AsyncSandbox
            await AsyncSandbox.connect(sandbox_id)
            return True
        except Exception:
            return False

    async def _ensure_sandbox(self, sandbox_id: str) -> Any:
        """Internal helper to get a sandbox instance, reconnecting if necessary."""
        if sandbox_id in self._sandboxes:
            return self._sandboxes[sandbox_id]
        
        if sandbox_id.startswith("mock-"):
            # Recreate mock metadata if lost
            mock_sb = {"mock": True, "files": {}}
            self._sandboxes[sandbox_id] = mock_sb
            return mock_sb

        try:
            from e2b import AsyncSandbox
            logger.info("Reconnecting to E2B sandbox %s...", sandbox_id)
            sandbox = await AsyncSandbox.connect(sandbox_id)
            self._sandboxes[sandbox_id] = sandbox
            return sandbox
        except Exception as e:
            logger.error("Failed to reconnect to sandbox %s: %s", sandbox_id, e)
            raise ValueError(f"Sandbox {sandbox_id} could not be recovered")

    async def create_sandbox(self, profile: str, session_id: str) -> str:
        """
        Create a new E2B sandbox from a profile template.
        Returns the sandbox ID.
        """
        try:
            from e2b import AsyncSandbox

            sandbox = await AsyncSandbox.create(
                api_key=settings.e2b_api_key,
                timeout=settings.e2b_sandbox_timeout_s,
            )
            sandbox_id = sandbox.sandbox_id
            self._sandboxes[sandbox_id] = sandbox
            logger.info("Created sandbox %s for session %s (profile=%s)", sandbox_id, session_id, profile)
            return sandbox_id

        except ImportError:
            # E2B not installed — use mock sandbox for development
            import uuid
            sandbox_id = f"mock-{uuid.uuid4().hex[:12]}"
            self._sandboxes[sandbox_id] = {"mock": True, "files": {}}
            logger.warning("E2B not installed — using mock sandbox %s", sandbox_id)
            return sandbox_id

        except Exception as e:
            logger.error("Failed to create sandbox: %s", e)
            raise

    async def upload_files(self, sandbox_id: str, files: dict[str, str]) -> None:
        """Upload files to a sandbox workspace."""
        sandbox = await self._ensure_sandbox(sandbox_id)

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            sandbox["files"].update(files)
            logger.info("Mock upload: %d files to %s", len(files), sandbox_id)
            return

        for path, content in files.items():
            await sandbox.files.write(f"/home/user/{path}", content)
        logger.info("Uploaded %d files to sandbox %s", len(files), sandbox_id)

    async def run_command(self, sandbox_id: str, cmd: str) -> CommandResult:
        """Execute a command in a sandbox."""
        sandbox = await self._ensure_sandbox(sandbox_id)

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            logger.info("Mock command in %s: %s", sandbox_id, cmd)
            return CommandResult(exit_code=0, stdout="mock output", stderr="")

        result = await sandbox.commands.run(cmd)
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    async def install_deps(self, sandbox_id: str, profile_install_cmd: str) -> CommandResult:
        """Install project dependencies in a sandbox."""
        sandbox = await self._ensure_sandbox(sandbox_id)

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            logger.info("Mock dependency install in %s: %s", sandbox_id, profile_install_cmd)
            return CommandResult(exit_code=0, stdout="mock install", stderr="")

        result = await sandbox.commands.run(
            profile_install_cmd,
            cwd="/home/user",
            timeout=max(int(getattr(settings, "max_build_timeout_s", 300) or 300), 300),
            request_timeout=0,
        )
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    async def ensure_preview_dependencies(
        self,
        sandbox_id: str,
        *,
        install_cmd: str | None,
        startup_cmd: str | None,
        files: dict[str, str] | None = None,
    ) -> None:
        """Install preview dependencies only when the sandbox is clearly missing them."""
        install_cmd = (install_cmd or "").strip()
        if not install_cmd:
            return

        sandbox = await self._ensure_sandbox(sandbox_id)
        if isinstance(sandbox, dict) and sandbox.get("mock"):
            return

        files = files or {}
        combined = f"{install_cmd} {startup_cmd or ''}".lower()
        if "package.json" not in files and not any(token in combined for token in ("npm", "pnpm", "yarn", "next")):
            return

        package_json = files.get("package.json", "")
        probe_cmd = "test -d /home/user/node_modules"
        if "\"next\"" in package_json or "'next'" in package_json or "next" in combined:
            probe_cmd = "test -x /home/user/node_modules/.bin/next"

        probe = await sandbox.commands.run(
            f"bash -lc 'if {probe_cmd}; then echo READY; else echo MISSING; fi'",
            cwd="/home/user",
            timeout=10,
        )
        if "READY" in (probe.stdout or ""):
            return

        logger.info("Preview dependencies missing in sandbox %s — running %s", sandbox_id, install_cmd)
        install_result = await self.install_deps(sandbox_id, install_cmd)
        if install_result.exit_code != 0:
            stderr = (install_result.stderr or install_result.stdout or "").strip()
            raise RuntimeError(f"Dependency install failed: {stderr[:400]}")

    async def start_preview(self, sandbox_id: str, startup_cmd: str, health_path: str = "/health") -> str:
        """
        Starts the app in background, waits for health, and returns the preview URL.
        Redirects all output to /home/user/service.log for forensic analysis.
        """
        sandbox = await self._ensure_sandbox(sandbox_id)

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            preview_url = f"https://mock-preview-{sandbox_id[:8]}.e2b.dev"
            logger.info("Mock preview: %s", preview_url)
            return preview_url

        service_port = self.infer_service_port(startup_cmd, health_path=health_path)
        launch_cmd = self._build_launch_command(startup_cmd)

        # Kill any stale preview process already bound to the target port.
        # Preview self-heal can be triggered multiple times while the UI polls.
        try:
            await sandbox.commands.run(f"fuser -k {service_port}/tcp 2>/dev/null || true", timeout=5)
            await asyncio.sleep(1)
        except Exception:
            pass

        logger.info("Starting preview in sandbox %s: %s", sandbox_id, startup_cmd)
        await sandbox.commands.run(
            launch_cmd,
            cwd="/home/user",
            background=True,
            timeout=0,
            request_timeout=0,
        )

        base_url = f"https://{sandbox.get_host(service_port)}"
        
        # Wait for healthy (30s timeout)
        logger.info("Waiting for preview at %s...", base_url)
        for i in range(15):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{base_url}{health_path}", timeout=2.0)
                    if resp.status_code < 500:
                        logger.info("Preview is healthy at %s", base_url)
                        return base_url
                    if health_path != "/":
                        root_resp = await client.get(f"{base_url}/", timeout=2.0)
                        if root_resp.status_code < 500:
                            logger.info("Preview is healthy at %s via root fallback", base_url)
                            return base_url
            except Exception:
                pass
            await asyncio.sleep(2)

            if i == 4:
                try:
                    log_content = await sandbox.files.read("/home/user/service.log")
                    logger.warning("Preview not up yet. service.log:\n%s", (log_content or "")[-800:])
                except Exception:
                    pass
        
        logger.warning("Preview failed to be healthy at %s after 30s", base_url)
        return base_url

    async def run_service(self, sandbox_id: str, startup_cmd: str, health_path: str = "/health") -> str:
        """
        Starts the target service in the sandbox and waits for it to be healthy.
        Returns the base URL of the running service.
        """
        sandbox = await self._ensure_sandbox(sandbox_id)

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            logger.info("Mock service start: %s", startup_cmd)
            return f"http://localhost:mock-{sandbox_id[:8]}"

        service_port = self.infer_service_port(startup_cmd, health_path=health_path)

        # Kill any previous process on the target port first (left over from prior mark)
        try:
            await sandbox.commands.run(f"fuser -k {service_port}/tcp 2>/dev/null || true", timeout=5)
            await asyncio.sleep(1)
        except Exception:
            pass

        launch_cmd = self._build_launch_command(startup_cmd)
        logger.info("Starting service in sandbox %s: %s", sandbox_id, startup_cmd)
        await sandbox.commands.run(
            launch_cmd,
            cwd="/home/user",
            background=True,
            timeout=0,
            request_timeout=0,
        )

        base_url = f"https://{sandbox.get_host(service_port)}"

        # Health check — accept 200 OR any non-connection-refused response
        # (some services return 404 on / but are still running)
        logger.info("Waiting for service at %s%s …", base_url, health_path)
        last_error = ""
        for i in range(20):  # 20 × 2s = 40s timeout
            await asyncio.sleep(2)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{base_url}{health_path}", timeout=3.0)
                    if resp.status_code < 500:
                        logger.info("Service healthy at %s (status %s)", base_url, resp.status_code)
                        return base_url
                    last_error = f"HTTP {resp.status_code}"
            except httpx.ConnectError:
                last_error = "connection refused"
            except Exception as e:
                last_error = str(e)

            # After 10s, dump the log to help debug
            if i == 4:
                try:
                    log_content = await sandbox.files.read("/home/user/service.log")
                    logger.warning("Service not up yet. service.log:\n%s", (log_content or "")[-800:])
                except Exception:
                    pass

        # Final: dump full log before raising
        try:
            log_content = await sandbox.files.read("/home/user/service.log")
            logger.error("Service failed to start. service.log:\n%s", (log_content or "")[-1500:])
        except Exception:
            pass

        raise RuntimeError(
            f"Service at {base_url}{health_path} not healthy after 40s. Last error: {last_error}"
        )

    async def get_service_url(self, sandbox_id: str, port: int = 8000) -> str:
        """Returns the public URL for a port in the sandbox."""
        sandbox = await self._ensure_sandbox(sandbox_id)
            
        if isinstance(sandbox, dict) and sandbox.get("mock"):
            return f"http://localhost:mock-{sandbox_id[:8]}"
            
        return f"https://{sandbox.get_host(port)}"

    async def download_artifacts(self, sandbox_id: str, paths: list[str]) -> dict[str, bytes]:
        """Download files from a sandbox."""
        sandbox = await self._ensure_sandbox(sandbox_id)

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            return {p: b"mock content" for p in paths}

        artifacts = {}
        for path in paths:
            content = await sandbox.files.read(f"/home/user/{path}")
            artifacts[path] = content if isinstance(content, bytes) else content.encode()
        return artifacts

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        """Shut down and destroy a sandbox."""
        sandbox = self._sandboxes.pop(sandbox_id, None)
        if sandbox is None:
            return

        if isinstance(sandbox, dict) and sandbox.get("mock"):
            logger.info("Mock sandbox %s destroyed", sandbox_id)
            return

        try:
            await sandbox.kill()
            logger.info("Sandbox %s destroyed", sandbox_id)
        except Exception as e:
            logger.error("Error destroying sandbox %s: %s", sandbox_id, e)


# Singleton
sandbox_manager = SandboxManager()
