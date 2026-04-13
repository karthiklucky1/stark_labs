import json
import sqlite3

def run():
    conn = sqlite3.connect('markii_studio.db')
    cursor = conn.cursor()
    candidate_id = '19a0e73ecc2642b6acdca21d839ab6b5'
    
    cursor.execute("SELECT files_json FROM build_candidates WHERE id = ?", (candidate_id,))
    row = cursor.fetchone()
    if not row:
        print("Candidate not found")
        return
        
    files = json.loads(row[0])
    if 'main.py' in files:
        code = files['main.py']
        if '@app.get("/")' not in code:
            print("Patching main.py with root route...")
            # Insert before the first @app.get
            root_route = """
@app.get("/", response_class=HTMLResponse)
async def root():
    return \"\"\"
    <html>
        <head>
            <title>Stark Drone Command</title>
            <style>
                body { background: #020617; color: #00f2ff; font-family: monospace; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
                .hud { border: 1px solid #00f2ff33; padding: 40px; border-radius: 20px; background: #00f2ff05; box-shadow: 0 0 50px #00f2ff11; text-align: center; }
                h1 { font-style: italic; letter-spacing: -2px; font-size: 3em; margin: 0; }
                p { color: #94a3b8; margin-top: 10px; }
                .status { margin-top: 30px; font-weight: bold; font-size: 0.8em; opacity: 0.6; }
            </style>
        </head>
        <body>
            <div class="hud">
                <h1>DRONE_TACTICAL_COMMAND</h1>
                <p>Telemetry stream active. Neural sync established.</p>
                <div class="status">SYSTEM_STATUS: INNOVATION_STABLE // PORT_8000_OPEN</div>
            </div>
        </body>
    </html>
    \"\"\"
"""
            # We need to import HTMLResponse
            if "from fastapi.responses import" in code:
                code = code.replace("from fastapi.responses import", "from fastapi.responses import HTMLResponse,")
            else:
                code = "from fastapi.responses import HTMLResponse\n" + code
                
            code = code.replace('@app.get("/health"', root_route + '\n@app.get("/health"')
            files['main.py'] = code
            
            cursor.execute("UPDATE build_candidates SET files_json = ? WHERE id = ?", (json.dumps(files), candidate_id))
            conn.commit()
            print("Successfully patched.")
    conn.close()

if __name__ == "__main__":
    run()
