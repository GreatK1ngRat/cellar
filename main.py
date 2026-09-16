import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import db, identify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "")

if not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD must be set -- see .env.example")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set -- see .env.example")

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Cellar")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")


@app.on_event("startup")
def on_startup():
    db.init_db()


def require_auth(request: Request):
    if not request.session.get("authed"):
        raise HTTPException(status_code=401, detail="Not authenticated")


# ---- auth ----------------------------------------------------------------

@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    if body.get("password") == APP_PASSWORD:
        request.session["authed"] = True
        return {"ok": True}
    raise HTTPException(status_code=401, detail="Wrong password")


@app.post("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


# ---- wines -----------------------------------------------------------------

@app.get("/api/wines", dependencies=[Depends(require_auth)])
def api_list_wines(q: str | None = None, type: str | None = None):
    return db.list_wines(q=q, wine_type=type)


@app.get("/api/wines/{wine_id}", dependencies=[Depends(require_auth)])
def api_get_wine(wine_id: int):
    wine = db.get_wine(wine_id)
    if not wine:
        raise HTTPException(status_code=404, detail="Not found")
    return wine


@app.post("/api/wines", dependencies=[Depends(require_auth)])
async def api_create_wine(request: Request):
    data = await request.json()
    if not data.get("name") or not data.get("type"):
        raise HTTPException(status_code=400, detail="name and type are required")
    return db.create_wine(data)


@app.put("/api/wines/{wine_id}", dependencies=[Depends(require_auth)])
async def api_update_wine(wine_id: int, request: Request):
    data = await request.json()
    wine = db.update_wine(wine_id, data)
    if not wine:
        raise HTTPException(status_code=404, detail="Not found")
    return wine


@app.delete("/api/wines/{wine_id}", dependencies=[Depends(require_auth)])
def api_delete_wine(wine_id: int):
    if not db.delete_wine(wine_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---- identification ---------------------------------------------------------

@app.post("/api/identify/barcode", dependencies=[Depends(require_auth)])
async def api_identify_barcode(request: Request):
    body = await request.json()
    result = await identify.lookup_barcode(body.get("barcode", ""))
    if not result:
        return JSONResponse({"matched": False}, status_code=200)
    return {"matched": True, **result}


@app.post("/api/identify/photo", dependencies=[Depends(require_auth)])
async def api_identify_photo(file: UploadFile = File(...)):
    image_bytes = await file.read()
    result = await identify.identify_photo(image_bytes, file.content_type or "image/jpeg")
    if result.get("image_url"):
        ok = await identify.verify_image_url(result["image_url"])
        if not ok:
            result["image_url"] = None
            result["image_source"] = None
    return result


@app.post("/api/verify-image", dependencies=[Depends(require_auth)])
async def api_verify_image(request: Request):
    body = await request.json()
    ok = await identify.verify_image_url(body.get("url", ""))
    return {"valid": ok}


# ---- frontend ----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    if not request.session.get("authed"):
        return HTMLResponse(LOGIN_PAGE)
    return HTMLResponse((STATIC_DIR / "index.html").read_text())


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

LOGIN_PAGE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cellar</title>
<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
<style>
  body{background:#12171a;color:#e9e5dc;font-family:system-ui,sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
  form{display:flex;flex-direction:column;gap:12px;width:260px}
  input{font:inherit;padding:10px 12px;border-radius:4px;border:1px solid #2c363d;
        background:#1a2126;color:#e9e5dc}
  button{font:inherit;padding:10px;border-radius:4px;border:0;background:#e9e5dc;
         color:#12171a;cursor:pointer;font-weight:500}
  p{color:#e0968d;font-size:13px;margin:0}
  h1{font-family:Georgia,serif;margin:0 0 8px}
</style></head><body>
<form id="f">
  <h1>Cellar.</h1>
  <input type="password" id="pw" placeholder="Password" autofocus>
  <button type="submit">Enter</button>
  <p id="err" style="display:none">Wrong password.</p>
</form>
<script>
document.getElementById('f').addEventListener('submit', async e => {
  e.preventDefault();
  const res = await fetch('/api/login', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: document.getElementById('pw').value})
  });
  if (res.ok) location.reload();
  else document.getElementById('err').style.display = 'block';
});
</script>
</body></html>"""
