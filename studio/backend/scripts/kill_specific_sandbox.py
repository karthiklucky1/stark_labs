import asyncio
from e2b import AsyncSandbox
from app.settings import settings

async def main(sandbox_id):
    try:
        print(f"Killing sandbox {sandbox_id}...")
        sb = await AsyncSandbox.connect(sandbox_id, api_key=settings.e2b_api_key)
        await sb.kill()
        print("Success.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main("iwbt981r7djwcl19kitod"))
