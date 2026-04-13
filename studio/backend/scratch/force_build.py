
import asyncio
import uuid
import json
from datetime import datetime
from app.database import async_session_factory
from app.models.session import ProjectSession
from app.models.requirement import RequirementSpec
from app.services.orchestrator import orchestrator

SESSION_ID = uuid.UUID("9b98c9d1-6589-4cd1-a310-18a732186f0f")

BLUEPRINT = {
    "tech_stack": {
        "frontend": "Next.js 14 + Tailwind CSS",
        "backend": "Python FastAPI",
        "database": "SQLite (Local Dev)"
    },
    "file_tree": [
        "frontend/src/app/page.tsx",
        "frontend/src/app/layout.tsx",
        "frontend/src/components/Menu.tsx",
        "frontend/src/components/ReservationForm.tsx",
        "backend/main.py",
        "backend/requirements.txt"
    ],
    "install_commands": [
        "cd frontend && npm install",
        "cd backend && pip install fastapi uvicorn"
    ],
    "startup_commands": [
        "cd frontend && npm run dev",
        "cd backend && uvicorn main:app --host 0.0.0.0 --port 8000"
    ]
}

REQUIREMENTS = {
    "functional": [
        "Dark premium restaurant landing page",
        "Multi-course menu with Appetizers, Mains, and Desserts",
        "Reservation form (Name, Date, Time, Guests)",
        "Mobile-responsive design"
    ],
    "technical": [
        "Next.js frontend for SEO and performance",
        "FastAPI backend for reservation processing",
        "TypeScript for type safety"
    ]
}

async def force_transition():
    async with async_session_factory() as db:
        # 1. Update Session Status
        from sqlalchemy import update
        await db.execute(
            update(ProjectSession)
            .where(ProjectSession.id == SESSION_ID)
            .values(status="spec_review", profile_type="nextjs_webapp")
        )
        
        # 2. Update/Create Requirement Spec
        # Find existing spec
        from sqlalchemy import select
        res = await db.execute(select(RequirementSpec).where(RequirementSpec.session_id == SESSION_ID))
        spec = res.scalars().first()
        
        if spec:
            spec.summary = "Traditional yet modern premium restaurant experience."
            spec.requirements_json = REQUIREMENTS
            spec.blueprint_json = BLUEPRINT
            spec.detected_profile = "nextjs_webapp"
            spec.confirmed = True
        
        await db.commit()
        print(f"Session {SESSION_ID} transitioned to spec_review and spec confirmed.")

    # 3. Trigger Build
    print("Triggering orchestrator build...")
    await orchestrator.start_build(SESSION_ID)
    print("Build initiated in background.")

if __name__ == "__main__":
    asyncio.run(force_transition())
