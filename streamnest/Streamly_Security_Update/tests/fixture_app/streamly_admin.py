"""Known admin interfaces and password-only source anchors, patched before execution."""
import hashlib
import secrets
from argon2.exceptions import VerificationError,InvalidHashError
from fastapi import APIRouter,Request,HTTPException
from starlette.concurrency import run_in_threadpool
from . import main as core
router=APIRouter()
COOKIE="sl_admin_session"
ADMIN_TTL=14400
DUMMY_HASH=core.ph.hash(secrets.token_urlsafe(32))
def hashed(s):return hashlib.sha256(s.encode()).hexdigest()
def audit(db,actor,action,target,details=""):
    db.execute("INSERT INTO streamly_admin_audit(actor,action,target,details,created_at) VALUES(?,?,?,?,?)",(actor,action,str(target),details,core.now()))
def admin_session(request, db):
    raw=request.cookies.get(COOKIE,"")
    if not raw or len(raw)>128:return None
    return db.execute("SELECT * FROM streamly_admin_sessions WHERE token_hash=? AND expires_at>?",(hashed(raw),core.now())).fetchone()
def require_admin(request):
    account=admin_session(request,request.state.db)
    if not account:raise HTTPException(401,"Admin login")
    return account
def may_stream(db,uid):
    return bool(db.execute("SELECT 1 FROM streamly_user_safety WHERE user_id=? AND blocked=0 AND can_stream=1",(uid,)).fetchone())
def may_preview_video(request,db,video):
    if admin_session(request,db):return True
    user=request.state.user
    if user and user["id"]==video["user_id"]:return True
    state=db.execute("SELECT state FROM streamly_video_moderation WHERE video_id=?",(video["id"],)).fetchone()
    blocked=db.execute("SELECT 1 FROM streamly_user_safety WHERE user_id=? AND blocked=1",(video["user_id"],)).fetchone()
    return bool(state and state["state"]=="approved" and not blocked)
def kick_creator(uid):pass
@router.get("/admin/login")
def login_page(request:Request):
    return core.render(request,"streamly_admin_login.html",error="")
@router.post("/admin/login")
async def login(request:Request):
    async with request.form(max_files=0,max_fields=4) as form:
        core.csrf_check(request,form)
        core.rate(request,"admin_login_ip",12,900)
        core.rate(request,"admin_login_account",8,900,identity="admin")
        password=str(form.get("password",""))
        db=request.state.db
        account=db.execute("SELECT * FROM streamly_admin_accounts WHERE username='admin'").fetchone()
        try:
            await run_in_threadpool(core.ph.verify,account["password_hash"] if account else DUMMY_HASH,password)
        except (VerificationError,InvalidHashError):
            raise HTTPException(400,"Bad password")
        if not account:raise HTTPException(400,"Bad password")
        raw = secrets.token_urlsafe(32)
        with db:
            db.execute("INSERT INTO streamly_admin_sessions VALUES(?,?,?)",(hashed(raw),"admin",core.now()+ADMIN_TTL))
        response=core.redirect("/admin")
        response.set_cookie(COOKIE,raw,httponly=True,secure=core.PRODUCTION,samesite="strict")
        return response
@router.get("/admin")
def dashboard(request:Request):
    require_admin(request)
    return {"admin":True}
@router.get("/admin/users")
def users(request:Request):
    require_admin(request);return {"users":[]}
@router.post("/admin/videos/{vid}/delete")
def delete(request:Request,vid:str):
    require_admin(request)
    return {"would_delete":vid}
