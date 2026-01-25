#/ , /profile, /gpt-image, /nanobanana-pro, /veo31...etc
# app/routes/pages.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..core.paths import templates
from ..web_shared import packs_list  # ή βάλε packs_list σε core module (δες παρακάτω)

router = APIRouter()

@router.get("/")
async def root():
    return RedirectResponse(url="/profile")

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "credits": "—", "packs": packs_list()},
    )

@router.get("/gpt-image", response_class=HTMLResponse)
async def gpt_image_page(request: Request):
    return templates.TemplateResponse("gpt-image.html", {"request": request})

@router.get("/nanobanana-pro", response_class=HTMLResponse)
async def nanobanana_pro_page(request: Request):
    return templates.TemplateResponse("nanobananapro.html", {"request": request})

@router.get("/veo31", response_class=HTMLResponse)
async def veo31_page(request: Request):
    return templates.TemplateResponse("veo31.html", {"request": request})

@router.get("/sora2pro", response_class=HTMLResponse)
async def sora2pro_page(request: Request):
    return templates.TemplateResponse("sora2pro.html", {"request": request})

@router.get("/grok", response_class=HTMLResponse)
async def grok_page(request: Request):
    return templates.TemplateResponse("grok.html", {"request": request})

@router.get("/nanobanana", response_class=HTMLResponse)
async def nanobanana_page(request: Request):
    return templates.TemplateResponse("nanobanana.html", {"request": request})
    
