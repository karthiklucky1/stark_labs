"""
Mark II Studio — Harvester Service
Autonomous knowledge distillation from hardening repairs.
"""
from __future__ import annotations

import logging
import uuid
import json
import os
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.codex import CodexPattern
from app.models.mark_run import MarkRun
from app.models.candidate import BuildCandidate
from app.settings import settings

logger = logging.getLogger(__name__)

class HarvesterService:
    """
    Distills 'Knowledge' from unsuccessful Mark runs that were successfully repaired.
    Captures: Broken Code + Attack -> Solution Code.
    """

    async def harvest_repair(
        self, 
        db: AsyncSession, 
        mark_run: MarkRun, 
        broken_candidate: BuildCandidate, 
        fixed_candidate: BuildCandidate
    ) -> CodexPattern | None:
        """
        Extract an evolution pattern from a repair event.
        """
        try:
            logger.info("Harvesting knowledge from Mark %s repair...", mark_run.mark_name)
            
            # Extract the specific attack payload from the swarm report if available
            # We take the first critical failure detail as the attack payload represention
            attack_payload = mark_run.rejection_reason or "Unknown attack payload"
            
            pattern = CodexPattern(
                session_id=mark_run.session_id,
                mark_run_id=mark_run.id,
                vulnerability_type=mark_run.failure_type or "Unknown",
                attack_payload=attack_payload,
                broken_code_json=broken_candidate.files_json,
                fixed_code_json=fixed_candidate.files_json,
                language="python",
                framework=fixed_candidate.session.profile_type if fixed_candidate.session else None,
                summary=mark_run.patch_summary or f"Fixed {mark_run.failure_type}"
            )
            
            db.add(pattern)
            await db.flush()
            
            # LOCAL SYNC: Append to MLX-ready training buffer
            await self._sync_to_mlx_buffer(pattern)
            
            logger.info("✅ Harvested new evolution pattern: %s", pattern.id)
            return pattern
            
        except Exception as e:
            logger.error("Failed to harvest knowledge: %s", e)
            return None

    async def _sync_to_mlx_buffer(self, pattern: CodexPattern) -> None:
        """
        Appends the pattern to a local JSONL file in MLX Chat format.
        """
        buffer_dir = settings.project_root / ".neural_arc" / "training"
        os.makedirs(buffer_dir, exist_ok=True)
        
        train_file = buffer_dir / "train.jsonl"
        
        # MLX Chat Format
        entry = {
            "messages": [
                {
                    "role": "system", 
                    "content": "You are a senior security engineer. Fix the vulnerability in the provided source code."
                },
                {
                    "role": "user", 
                    "content": f"Vulnerability: {pattern.vulnerability_type}\nAttack: {pattern.attack_payload}\n\nSource Code:\n{json.dumps(pattern.broken_code_json, indent=2)}"
                },
                {
                    "role": "assistant", 
                    "content": json.dumps(pattern.fixed_code_json)
                }
            ]
        }
        
        with open(train_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

harvester_service = HarvesterService()
