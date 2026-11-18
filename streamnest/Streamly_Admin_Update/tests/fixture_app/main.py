"""Minimal reconstruction of the original core interfaces for integration tests."""
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path
from contextlib import asynccontextmanager

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,HTMLResponse,FileResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

BASE=Path(__file__).resolve().parent
DATA=Path(os.environ["DATA_DIR"])
MEDIA=DATA/"media"
MAX_VIDEO_BYTES=2*1024**3
MAX_USER_BYTES=20*1024**3
PRODUCTION=False
PUBLIC_URL="http://testserver"
COOKIE="sn_session"
CATEGORIES=["Gaming","Technologie","Musik","Kreativ","Wissen","Lifestyle"]
ph=PasswordHasher(time_cost=2,memory_cost=19456,parallelism=1)
DUMMY_HASH=ph.hash(secrets.token_urlsafe(24))
templates=Jinja2Templates(directory=str(BASE/"templates"))
templates.env.filters["ago"]=lambda value:"vor kurzem"
templates.env.filters["compact"]=lambda value:str(value)
templates.env.filters["duration"]=lambda value:"0:01"
def now():return int(time.time())
def token_hash(value):return hashlib.sha256(value.encode()).hexdigest()
def connect():
    DATA.mkdir(exist_ok=True,parents=True)
    db=sqlite3.connect(DATA/"test.sqlite3",timeout=30,check_same_thread=False)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db
def init_db():
    MEDIA.mkdir(exist_ok=True,parents=True)
    db=connect()
    try:
        db.executescript((BASE/"schema.sql").read_text())
    finally:db.close()
@asynccontextmanager
async def lifespan(app):
    init_db()
    yield
app=FastAPI(lifespan=lifespan)
def rotate_session(request,user_id=None):
    raw=secrets.token_urlsafe(32)
    session={"token_hash":token_hash(raw),"csrf":secrets.token_urlsafe(32),"user_id":user_id,"expires_at":now()+86400}
    db=request.state.db
    with db:
        if request.state.session:
            db.execute("DELETE FROM sessions WHERE token_hash=?",(request.state.session["token_hash"],))
        db.execute("INSERT INTO sessions VALUES(:token_hash,:csrf,:user_id,:expires_at)",session)
    request.state.session=session
    request.state.cookie=raw
@app.middleware("http")
async def sessions(request,call_next):
    db=connect();request.state.db=db;request.state.cookie=None
    raw=request.cookies.get(COOKIE,"")
    row=db.execute("SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",(token_hash(raw),now())).fetchone() if raw else None
    request.state.session=dict(row) if row else None
    if not row:rotate_session(request)
    request.state.user=db.execute("SELECT * FROM users WHERE id=?",(row["user_id"],)).fetchone() if row and row["user_id"] else None
    try:
        response=await call_next(request)
        if request.state.cookie:
            response.set_cookie(COOKIE,request.state.cookie,httponly=True,samesite="lax")
        return response
    finally:db.close()
def require_user(request):
    if not request.state.user:
        raise HTTPException(401,"Bitte anmelden.")
    return request.state.user
def csrf_check(request,form=None):
    supplied=str(form.get("csrf","")) if form is not None else request.headers.get("x-csrf-token","")
    if not secrets.compare_digest(supplied.encode(),request.state.session["csrf"].encode()):
        raise HTTPException(403,"CSRF")
    if request.headers.get("origin") and request.headers["origin"] != PUBLIC_URL:
        raise HTTPException(403,"Origin")
def rate(request,action,maximum,window=900,identity=None):
    key=token_hash(f"{action}:{identity or request.client.host}:{now()//window}")
    db=request.state.db
    with db:
        db.execute("INSERT INTO rate_limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",(key,now()+window))
        count=db.execute("SELECT count FROM rate_limits WHERE key=?",(key,)).fetchone()[0]
    if count>maximum:raise HTTPException(429,"Rate limit")
def field(form,name,low,high):
    value=str(form.get(name,"")).strip()
    if not low<=len(value)<=high:raise HTTPException(400,"Feld ungueltig")
    return value
def redirect(path):return RedirectResponse(path,status_code=303)
def render(request,name,**context):
    return templates.TemplateResponse(request=request,name=name,context={"user":request.state.user,"csrf":request.state.session["csrf"],"categories":CATEGORIES,"q":"","path":request.url.path,**context})
def process_video(source,suffix,target,poster):
    target.write_bytes(Path(source).read_bytes());poster.write_bytes(b"jpeg")
    return 1.0
VIDEO_QUERY="SELECT v.*,u.username,u.display_name FROM videos v JOIN users u ON u.id=v.user_id "
def get_videos(db,where="",args=(),order="v.created_at DESC",page=1,size=12):
    rows=db.execute(VIDEO_QUERY+where+f" ORDER BY {order} LIMIT ? OFFSET ?",(*args,size+1,(page-1)*size)).fetchall()
    return rows[:size],len(rows)>size
@app.get("/")
def home(request:Request,q:str="",category:str=""):
    conditions=[];args=[]
    if q:conditions.append("v.title LIKE ?");args.append("%"+q+"%")
    if category:conditions.append("v.category=?");args.append(category)
    videos,more=get_videos(request.state.db,"WHERE "+" AND ".join(conditions) if conditions else "",args)
    creators=request.state.db.execute(
        "SELECT u.id,u.username,u.display_name "
        "FROM users u WHERE u.username LIKE ? OR u.display_name LIKE ? LIMIT 8",
        (f"%{q}%",f"%{q}%")).fetchall() if q else []
    return {"videos":[dict(v) for v in videos],"creators":[dict(c) for c in creators]}
def video_or_404(db,vid):
    row=db.execute(VIDEO_QUERY+"WHERE v.id=?",(vid,)).fetchone()
    if not row:raise HTTPException(404,"Not found")
    return row
@app.get("/watch/{vid}")
def watch(request:Request,vid:str):
    db=request.state.db
    video=video_or_404(db,vid)
    recommended=db.execute(VIDEO_QUERY + "WHERE v.id!=? ORDER BY (v.category=?) DESC,v.views DESC LIMIT 6",(vid,video["category"])).fetchall()
    return {"video":dict(video),"recommended":[dict(v) for v in recommended]}
@app.get("/channel/{username}")
def channel(request:Request,username:str):
    creator=request.state.db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
    if not creator:raise HTTPException(404)
    videos,_=get_videos(request.state.db,"WHERE v.user_id=?",(creator["id"],))
    return {"videos":[dict(v) for v in videos]}
@app.get("/media/{vid}")
def media(request:Request,vid:str):
    video=video_or_404(request.state.db,vid)
    return FileResponse(MEDIA/video["filename"])
@app.get("/poster/{vid}")
def poster(request:Request,vid:str):
    video=video_or_404(request.state.db,vid)
    return FileResponse(MEDIA/video["poster"])
@app.post("/api/videos/{vid}/view")
def view(request:Request,vid:str):
    csrf_check(request)
    video_or_404(request.state.db,vid)
    return {"counted":True}
@app.get("/studio")
def studio(request:Request):
    user=require_user(request)
    rows=request.state.db.execute(VIDEO_QUERY+"WHERE v.user_id=?",(user["id"],)).fetchall()
    return {"videos":[dict(v) for v in rows]}
@app.post("/studio/{vid}/edit")
async def edit_video(request:Request,vid:str):
    user=require_user(request)
    async with request.form() as form:
        csrf_check(request,form)
        video=video_or_404(request.state.db,vid)
        if video["user_id"]!=user["id"]:raise HTTPException(403)
        with request.state.db:
            request.state.db.execute("UPDATE videos SET title=? WHERE id=?",(str(form["title"]),vid))
    return redirect("/studio")
@app.post("/login")
async def login(request:Request):
    async with request.form() as form:
        csrf_check(request,form)
        user=request.state.db.execute("SELECT * FROM users WHERE username=?",(str(form.get("username","")),)).fetchone()
        try:await run_in_threadpool(ph.verify,user["password_hash"] if user else DUMMY_HASH,str(form.get("password","")))
        except VerificationError:raise HTTPException(400,"Bad login")
        if not user:raise HTTPException(400,"Bad login")
        rotate_session(request, user["id"])
    return redirect("/")
from .streamly_extension import router as extension_router
app.include_router(extension_router)
