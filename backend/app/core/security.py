import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Request, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import sqlite3
from .config import SECRET_KEY, ALGORITHM, TOKEN_EXPIRE_HOURS, DB_PATH

security = HTTPBearer(auto_error=False)

def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

def _create_token(username: str, role: str, admin_id: int) -> str:
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": username, "role": role, "admin_id": admin_id, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # EventSource can't set headers — accept token as query param for SSE
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    data = _decode_token(token)
    # Ensure admin_id is present and respect the master_admin (0)
    admin_id = data.get("admin_id")
    if admin_id is None:
        admin_id = 0 if data.get("role") == "super_admin" else 1
    
    try:
        admin_id = int(admin_id)
    except:
        admin_id = 1
        
    return {"username": data["sub"], "role": data["role"], "admin_id": admin_id}

def require_admin(user=Depends(get_current_user)):
    role = user.get("role")
    if role not in ("admin", "super_admin"):
        print(f"[AUTH] Access Denied: User {user.get('username')} has role '{role}', but admin/super_admin required.")
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def require_super_admin(user=Depends(get_current_user)):
    role = user.get("role")
    if role != "super_admin":
        print(f"[AUTH] Access Denied: User {user.get('username')} has role '{role}', but super_admin required.")
        raise HTTPException(status_code=403, detail="Super Admin access only")
    return user
