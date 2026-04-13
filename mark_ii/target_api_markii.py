import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio

import re
import time
from pydantic import field_validator
app = FastAPI()
lock = asyncio.Lock()
rate_limiters = {}
RATE_LIMIT = 5  # requests per second


# In-memory "database"
database = {
    "user_1": {"balance": 100.0}
}

class Transaction(BaseModel):
    @field_validator('user_id')
    def validate_user_id(cls, v):
        if not re.match(r'^[A-Za-z0-9_]+$', v):
            raise ValueError('Invalid user_id')
        return v

    @field_validator('amount')
    def validate_amount(cls, v):
        if v <= 0 or v > 1_000_000:
            raise ValueError('Invalid amount')
        return v

    user_id: str
    amount: float

@app.post("/transfer")
async def transfer_funds(transaction: Transaction):
    user = database.get(transaction.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Rate limiting
    current_time = time.time()
    user_rate_limit = rate_limiters.get(transaction.user_id, (0, 0))
    if current_time - user_rate_limit[0] < 1:
        if user_rate_limit[1] >= RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Too Many Requests")
        rate_limiters[transaction.user_id] = (user_rate_limit[0], user_rate_limit[1] + 1)
    else:
        rate_limiters[transaction.user_id] = (current_time, 1)

    async with lock:
        current_balance = user["balance"]
        if current_balance < transaction.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds")
        user["balance"] = current_balance - transaction.amount

    return {"status": "success", "remaining_balance": user["balance"]}

@app.get("/balance/{user_id}")
async def get_balance(user_id: str):
    return {"balance": database.get(user_id, {}).get("balance", 0.0)}

@app.post("/reset")
async def reset():
    database["user_1"]["balance"] = 100.0
    return {"status": "reset"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8111)
