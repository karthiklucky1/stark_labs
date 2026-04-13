import sqlite3
import json
import asyncio
import os
from e2b import AsyncSandbox

def load_env():
    try:
        with open('../../.env', 'r') as f:
            for line in f:
                if line.startswith('E2B_API_KEY='):
                    os.environ['E2B_API_KEY'] = line.split('=')[1].strip().strip('\"').strip('\'')
    except:
        pass

async def sync():
    load_env()
    conn = sqlite3.connect('markii_studio.db')
    c = conn.cursor()
    cid = '7b7db0eae3f2426ba19aaebf148bfff3'
    sid = 'dfb9721d-c336-4dc3-949c-48dda5da64b3'
    sandbox_id = 'imagxeqlgqtrfrzpfknps'
    
    c.execute('SELECT files_json FROM build_candidates WHERE id = ?', (cid,))
    row = c.fetchone()
    if not row:
        print("Candidate not found")
        return
        
    files = json.loads(row[0])
    print(f"Syncing {len(files)} files to sandbox {sandbox_id}...")
    
    # E2B sync
    sb = await AsyncSandbox.connect(sandbox_id)
    # Upload one by one to ensure workspace paths
    for path, content in files.items():
        print(f"  Uploading {path}...")
        # E2B files are usually in /home/user
        sb_path = f"/home/user/{path}"
        await sb.files.write(sb_path, content)
    
    await sb.close()
    print("SUCCESS: SpaceX Deep Sync complete.")

if __name__ == "__main__":
    asyncio.run(sync())
