# app/routes/nanobanana.py
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.paths import WEB_TEMPLATES_DIR

router = APIRouter()

@router.get("/nanobanana", response_class=HTMLResponse)
def nanobanana_page():
    """
    Serves the NanoBanana webapp UI.
    Template file: app/web-templates/nanobanana.html
    """
    html_path = WEB_TEMPLATES_DIR / "nanobanana.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
