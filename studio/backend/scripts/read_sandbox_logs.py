import asyncio
from e2b import AsyncSandbox
from app.settings import settings

async def main(sandbox_id):
    try:
        print(f"Connecting to sandbox {sandbox_id}...")
        sb = await AsyncSandbox.connect(sandbox_id, api_key=settings.e2b_api_key)
        logs = await sb.files.read("/home/user/service.log")
        print("--- SANDBOX LOGS START ---")
        print(logs)
        print("--- SANDBOX LOGS END ---")
    except Exception as e:
        print(f"Error reading logs: {e}")

if __name__ == "__main__":
    # We'll try common IDs found in the logs
    asyncio.run(main("iwbt981r7djwcl19kitod"))
