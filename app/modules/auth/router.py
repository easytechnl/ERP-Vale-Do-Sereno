from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.templating import templates
from app.core.deps import get_db
from app.modules.auth.service import authenticate
from app.modules.auth.utils import require_login, current_user

router = APIRouter()

@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.post("/login")
def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        user = authenticate(db, email=email.strip().lower(), password=password)
    except HTTPException as exc:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": exc.detail, "email": email},
            status_code=exc.status_code,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)

@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

@router.get("/me")
def me(request: Request, user=Depends(require_login), db: Session = Depends(get_db)):
    u = current_user(request, db)
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role}
