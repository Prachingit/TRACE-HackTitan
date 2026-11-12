import re
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    r = c.get("/")
    print("/", r.status_code, 'id="root"' in r.text)
    print("/projects/abc", c.get("/projects/abc").status_code)
    print("api me unauth", c.get("/api/auth/me").status_code)
    a = re.search(r"/assets/[^\"]+\.js", r.text).group(0)
    print(a, c.get(a).status_code)
    s = c.post("/api/auth/signup", json={"name": "S", "email": "s@example.com", "password": "securepass123", "confirm_password": "securepass123"})
    print("signup", s.status_code, s.headers.get("set-cookie", "")[:110])
    w = c.post("/api/workspaces", json={"name": "W"}).json()
    p = c.post("/api/projects", json={"workspace_id": w["id"], "name": "P"}).json()
    print("sample", c.post(f"/api/projects/{p['id']}/sample").json())
    for x in c.get(f"/api/projects/{p['id']}/sources").json():
        print(x["id"], x["filename"], x["status"], x["chunk_count"], x["error_message"])
