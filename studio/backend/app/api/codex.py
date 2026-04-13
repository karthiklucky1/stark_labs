"""
Mark II Studio — Codex API
Endpoints for managing harvested knowledge and training datasets.
"""
from __future__ import annotations

import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import io

from app.database import get_session
from app.models.codex import CodexPattern

router = APIRouter(prefix="/codex", tags=["codex"])

@router.get("")
async def get_codex_stats(db: AsyncSession = Depends(get_session)):
    """Get overview of harvested knowledge patterns."""
    count_result = await db.execute(select(func.count(CodexPattern.id)))
    total_patterns = count_result.scalar()
    
    recent_patterns = await db.execute(
        select(CodexPattern)
        .order_by(CodexPattern.created_at.desc())
        .limit(10)
    )
    
    return {
        "total_patterns": total_patterns,
        "recent": [
            {
                "id": str(p.id),
                "vulnerability": p.vulnerability_type,
                "summary": p.summary,
                "timestamp": p.created_at.isoformat()
            }
            for p in recent_patterns.scalars().all()
        ]
    }

@router.get("/patterns")
async def get_all_patterns(db: AsyncSession = Depends(get_session)):
    """Get all harvested patterns."""
    result = await db.execute(select(CodexPattern).order_by(CodexPattern.created_at.desc()))
    return [
        {
            "id": str(p.id),
            "vulnerability": p.vulnerability_type,
            "attack_payload": p.attack_payload,
            "broken_code": p.broken_code_json,
            "fixed_code": p.fixed_code_json,
            "summary": p.summary,
            "timestamp": p.created_at.isoformat()
        }
        for p in result.scalars().all()
    ]

@router.get("/export")
async def export_dataset(db: AsyncSession = Depends(get_session)):
    """Export the codex as a JSONL dataset for fine-tuning."""
    result = await db.execute(select(CodexPattern))
    patterns = result.scalars().all()
    
    output = io.StringIO()
    for p in patterns:
        # Standard instruction-tuning format
        item = {
            "instruction": f"Fix the security vulnerability in this code. Vulnerability: {p.vulnerability_type}. Attack payload triggering failure: {p.attack_payload}",
            "input": json.dumps(p.broken_code_json),
            "output": json.dumps(p.fixed_code_json),
            "metadata": {
                "id": str(p.id),
                "framework": p.framework,
                "summary": p.summary
            }
        }
        output.write(json.dumps(item) + "\n")
    
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=stark_codex_dataset.jsonl"}
    )
