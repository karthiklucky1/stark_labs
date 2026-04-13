import asyncio
import re
import time
from typing import Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, field_validator

app = FastAPI()

SEED_USER_ID = "user_1"
SEED_BALANCE = 100.0
MAX_AMOUNT = 1_000_000
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

balances: Dict[str, float] = {SEED_USER_ID: SEED_BALANCE}
balance_lock = asyncio.Lock()

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 120
rate_limit_store: Dict[str, list[float]] = {}
rate_limit_lock = asyncio.Lock()


class TransferRequest(BaseModel):
    user_id: str
    amount: float

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        if not USER_ID_PATTERN.fullmatch(value):
            raise ValueError("user_id must match ^[A-Za-z0-9_]+$")
        return value

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value <= 0 or value > MAX_AMOUNT:
            raise ValueError(f"amount must be > 0 and <= {MAX_AMOUNT}")
        return value


async def check_rate_limit(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    now = time.time()
    async with rate_limit_lock:
        timestamps = rate_limit_store.get(client_host, [])
        timestamps = [ts for ts in timestamps if now - ts < RATE_LIMIT_WINDOW_SECONDS]
        if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
            rate_limit_store[client_host] = timestamps
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        timestamps.append(now)
        rate_limit_store[client_host] = timestamps


@app.post("/transfer")
async def transfer(payload: TransferRequest, request: Request):
    await check_rate_limit(request)
    async with balance_lock:
        if payload.user_id not in balances:
            raise HTTPException(status_code=404, detail="User not found")
        current_balance = balances[payload.user_id]
        if current_balance < payload.amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")
        balances[payload.user_id] = current_balance - payload.amount
        return {
            "status": "success",
            "user_id": payload.user_id,
            "amount": payload.amount,
            "balance": balances[payload.user_id],
        }


@app.get("/balance/{user_id}")
async def get_balance(user_id: str, request: Request):
    await check_rate_limit(request)
    if not USER_ID_PATTERN.fullmatch(user_id):
        raise HTTPException(status_code=422, detail="Invalid user_id")
    async with balance_lock:
        if user_id not in balances:
            raise HTTPException(status_code=404, detail="User not found")
        return {"user_id": user_id, "balance": balances[user_id]}


@app.post("/reset")
async def reset(request: Request):
    await check_rate_limit(request)
    async with balance_lock:
        balances.clear()
        balances[SEED_USER_ID] = SEED_BALANCE
    async with rate_limit_lock:
        rate_limit_store.clear()
    return {"status": "reset", "user_id": SEED_USER_ID, "balance": SEED_BALANCE}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8111)