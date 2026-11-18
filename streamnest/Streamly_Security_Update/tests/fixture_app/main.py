"""Executable adapter for the known core interfaces; not the user's full original application."""
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path
from contextlib import asynccontextmanager
from argon2 import PasswordHasher
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

BASE=Path(__file__).resolve().parent
DATA=Path(os.environ["DATA_DIR"]);MEDIA=DATA/"media"
PRODUCTION=False
COOKIE="sn_session"
CATEGORIES=["Gaming","Technologie","Musik","Kreativ","Wissen","Lifestyle"]
ph=PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)
templates=Jinja2Templates(directory=str(BASE/"templates"))
templates.env.filters["ago"]=lambda t:"vor kurzem"
templates.env.filters["compact"]=str
def now():return int(time.time())
def token_hash(raw):return hashlib.sha256(raw.encode()).hexdigest()
def connect():
    DATA.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(DATA/"test.sqlite3",timeout=30,check_same_thread=False)
    db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON")
    return db
def init_db():
    MEDIA.mkdir(exist_ok=True,parents=True)
    db=connect()
    try:db.executescript((BASE/"schema.sql").read_text())
    finally:db.close()
@asynccontextmanager
async def lifespan(app):
    init_db();yield
app=FastAPI(lifespan=lifespan)
@app.middleware("http")
async def sessions(request,call_next):
    db=connect();request.state.db=db
    raw=request.cookies.get(COOKIE,"")
    row=db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",(token_hash(raw),now())).fetchone() if raw else None
    fresh=not row
    if fresh:
        raw=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
        with db:db.execute("INSERT INTO sessions VALUES(?,?,NULL,?)",(token_hash(raw),csrf,now()+86400))
        row=db.execute("SELECT * FROM sessions WHERE token_hash=?",(token_hash(raw),)).fetchone()
    request.state.session=dict(row)
    request.state.user=db.execute("SELECT * FROM users WHERE id=?",(row["user_id"],)).fetchone() if row["user_id"] else None
    try:
        response=await call_next(request)
        if fresh:response.set_cookie(COOKIE,raw,httponly=True,samesite="lax")
        response.headers["Cache-Control"]="no-store"
        return response
    finally:db.close()
def require_user(request):
    u=request.state.user
    if not u:raise HTTPException(401,"Anmelden")
    if request.state.db.execute("SELECT 1 FROM streamly_user_safety WHERE user_id=? AND blocked=1",(u["id"],)).fetchone():raise HTTPException(403,"Blocked")
    return u
def csrf_check(request,form=None):
    token=str(form.get("csrf","")) if form is not None else request.headers.get("x-csrf-token","")
    if not secrets.compare_digest(token.encode(),request.state.session["csrf"].encode()):raise HTTPException(403,"CSRF")
    if request.headers.get("origin") and request.headers["origin"]!="http://testserver":raise HTTPException(403,"Origin")
def rate(request,action,maximum,window=900,identity=None):
    key=token_hash(f"{action}:{identity or request.client.host}:{now()//window}")
    db=request.state.db
    with db:
        db.execute("INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",(key,now()+window))
        count=db.execute("SELECT count FROM rate_limits WHERE key=?",(key,)).fetchone()[0]
    if count>maximum:raise HTTPException(429,"Rate")
def field(form,name,low,high):
    value=str(form.get(name,"")).strip()
    if not low<=len(value)<=high:raise HTTPException(400,"Field")
    return value
def redirect(path):return RedirectResponse(path,status_code=303)
def render(request,name,**context):
    return templates.TemplateResponse(request=request,name=name,context={"user":request.state.user,"csrf":request.state.session["csrf"],"categories":CATEGORIES,**context})
@app.get("/")
def home():return {"site":"Streamly"}
# STREAMLY_ADMIN_UPDATE_V1
from .streamly_admin import router as admin_router
app.include_router(admin_router)
