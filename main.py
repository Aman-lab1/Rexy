import sys
import requests
import json

if len(sys.argv) < 2:
    print("Usage: python main.py \"what time is it\"")
    sys.exit(1)

command = sys.argv[1]
try:
    response = requests.post("http://localhost:8000/process", 
                           json={"command": command})
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"❌ Rexy server error: {e}")
 
