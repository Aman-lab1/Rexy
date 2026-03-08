from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from modules.permissions import permissions_db

app = FastAPI(title="🔐 Rexy Permissions Dashboard")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    # FIX 1: Initialize rows_html FIRST
    rows_html = ""
    
    try:
        perms = permissions_db.list_all()
    except:
        perms = []
    
    # FIX 2: Safe row unpacking
    for row in perms:
        try:
            user_id = row[0] if len(row) > 0 else "user1"
            capability = row[1] if len(row) > 1 else "unknown"
            mode = row[2] if len(row) > 2 else "confirm"
            timestamp = row[3] if len(row) > 3 else "now"
        except:
            user_id, capability, mode, timestamp = "user1", "calc", "allow", "now"
        
        rows_html += f"""
        <tr>
            <td>{user_id}</td>
            <td>{capability}</td>
            <td>{mode}</td>
            <td>{timestamp[:19]}</td>
            <td>
                <button onclick="setPerm('{capability}', 'allow')">✅ Allow</button>
                <button onclick="setPerm('{capability}', 'deny')">❌ Deny</button>
                <button onclick="setPerm('{capability}', 'never')">🚫 Never</button>
            </td>
        </tr>"""
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>🔐 Rexy Permissions Dashboard</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; 
               background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; min-height: 100vh; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .card {{ background: rgba(255,255,255,0.15); backdrop-filter: blur(20px); border-radius: 24px; 
                padding: 30px; margin: 20px 0; box-shadow: 0 20px 40px rgba(0,0,0,0.3); 
                border: 1px solid rgba(255,255,255,0.2); }}
        h1 {{ font-size: 2.5em; margin: 0; text-shadow: 0 4px 8px rgba(0,0,0,0.3); }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1); }}
        th {{ background: rgba(255,255,255,0.2); }}
        button {{ padding: 8px 16px; margin: 2px; border: none; border-radius: 20px; cursor: pointer; 
                 font-weight: bold; transition: all 0.3s; }}
        button:hover {{ transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,0,0,0.3); }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔐 Rexy Permissions Dashboard</h1>
        <p>Live controls for calculator, files, and safety permissions</p>
    </div>
    <div class="card">
        <h2>Current Permissions</h2>
        <table>
            <tr><th>User</th><th>Capability</th><th>Mode</th><th>Time</th><th>Actions</th></tr>
            {rows_html}
        </table>
    </div>
    <script>
        async function setPerm(action, mode) {{
            try {{
                await fetch(`/api/set/${{action}}/${{mode}}`);
                location.reload();
            }} catch(e) {{
                alert('Update failed');
            }}
        }}
        setInterval(() => location.reload(), 10000);
    </script>
</body>
</html>"""
    return HTMLResponse(html)

@app.get("/api/set/{action}/{mode}")
async def set_permission(action: str, mode: str):
    permissions_db.set_permission("user1", action, mode)
    return {"status": "updated"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
