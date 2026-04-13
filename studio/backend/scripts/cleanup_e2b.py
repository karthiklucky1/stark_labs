import asyncio
import os
from e2b import AsyncSandbox
from app.settings import settings

async def cleanup():
    print(f"Purging E2B sandboxes for API key: {settings.e2b_api_key[:8]}...")
    try:
        sandboxes = await AsyncSandbox.list(api_key=settings.e2b_api_key)
        print(f"Found {len(sandboxes)} active sandboxes.")
        for sb in sandboxes:
            print(f"Killing sandbox: {sb.sandbox_id}")
            # We connect and kill
            try:
                s = await AsyncSandbox.connect(sb.sandbox_id, api_key=settings.e2b_api_key)
                await s.kill()
            except Exception as e:
                print(f"Failed to kill {sb.sandbox_id}: {e}")
        print("Cleanup complete.")
    except Exception as e:
        print(f"Error during listing: {e}")

if __name__ == "__main__":
    asyncio.run(cleanup())
