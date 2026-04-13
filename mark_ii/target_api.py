import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio

app = FastAPI()

# In-memory "database"
database = {
    "user_1": {"balance": 100.0}
}

class Transaction(BaseModel):
    user_id: str
    amount: float

@app.post("/transfer")
async def transfer_funds(transaction: Transaction):
    """
    VULNERABILITY: Race condition.
    It reads the balance, yields to event loop (asyncio.sleep), and then updates.
    A swarm of requests will read the same $100 before any update is written,
    allowing one user to spend the $100 balance thousands of times.
    """
    user = database.get(transaction.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    current_balance = user["balance"]
    
    if current_balance < transaction.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")
        
    # Simulate database latency
    await asyncio.sleep(0.1)
    
    # Process transfer
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
