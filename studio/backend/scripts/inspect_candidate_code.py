import json
import sqlite3

def run():
    conn = sqlite3.connect('markii_studio.db')
    cursor = conn.cursor()
    cursor.execute("SELECT files_json FROM build_candidates WHERE id = '19a0e73ecc2642b6acdca21d839ab6b5'")
    row = cursor.fetchone()
    if row:
        files = json.loads(row[0])
        print("--- FILES DETECTED ---")
        print(list(files.keys()))
        if 'main.py' in files:
            print("\n--- main.py CONTENT ---")
            print(files['main.py'])
    conn.close()

if __name__ == "__main__":
    run()
