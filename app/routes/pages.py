# / , /profile, /gpt-image, /nanobanana-pro, /veo31...etc
# app/routes/pages.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..core.paths import templates
from ..web_shared import packs_list

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

# ========================
# VIDEO tools
# ========================
@router.get("/gpt-image", response_class=HTMLResponse)
async def gpt_image_page(request: Request):
    return templates.TemplateResponse("gpt-image.html", {"request": request})

@router.get("/veo31", response_class=HTMLResponse)
async def veo31_page(request: Request):
    return templates.TemplateResponse("veo31.html", {"request": request})

@router.get("/veo3fast", response_class=HTMLResponse)
async def veo3fast_page(request: Request):
    return templates.TemplateResponse("veo3fast.html", {"request": request})

@router.get("/sora2pro", response_class=HTMLResponse)
async def sora2pro_page(request: Request):
    return templates.TemplateResponse("sora2pro.html", {"request": request})

@router.get("/sora2", response_class=HTMLResponse)
async def sora2_page(request: Request):
    return templates.TemplateResponse("sora2.html", {"request": request})

@router.get("/kling26", response_class=HTMLResponse)
async def kling26_page(request: Request):
    return templates.TemplateResponse("kling26.html", {"request": request})

@router.get("/kling-o1", response_class=HTMLResponse)
async def kling_o1_page(request: Request):
    return templates.TemplateResponse("kling-o1.html", {"request": request})

@router.get("/kling21", response_class=HTMLResponse)
async def kling21_page(request: Request):
    return templates.TemplateResponse("kling21.html", {"request": request})

@router.get("/kling25turbo", response_class=HTMLResponse)
async def kling25turbo_page(request: Request):
    return templates.TemplateResponse("kling25turbo.html", {"request": request})

@router.get("/kling26motion", response_class=HTMLResponse)
async def kling26motion_page(request: Request):
    return templates.TemplateResponse("kling26motion.html", {"request": request})

@router.get("/kling26motion2", response_class=HTMLResponse)
async def kling26motion2_page(request: Request):
    return templates.TemplateResponse("kling26motion2.html", {"request": request})

@router.get("/kling30", response_class=HTMLResponse)
async def kling30_page(request: Request):
    return templates.TemplateResponse("kling30.html", {"request": request})

@router.get("/kling30-2", response_class=HTMLResponse)
async def kling30_2_page(request: Request):
    return templates.TemplateResponse("kling30-2.html", {"request": request})

@router.get("/klingv1avatar", response_class=HTMLResponse)
async def klingv1avatar_page(request: Request):
    return templates.TemplateResponse("klingv1avatar.html", {"request": request})

@router.get("/runway", response_class=HTMLResponse)
async def runway_page(request: Request):
    return templates.TemplateResponse("runway.html", {"request": request})

@router.get("/runway-aleph", response_class=HTMLResponse)
async def runway_aleph_page(request: Request):
    return templates.TemplateResponse("runway-aleph.html", {"request": request})

@router.get("/seedance", response_class=HTMLResponse)
async def seedance_page(request: Request):
    return templates.TemplateResponse("seedance.html", {"request": request})

@router.get("/hailuo02", response_class=HTMLResponse)
async def hailuo02_page(request: Request):
    return templates.TemplateResponse("hailuo02.html", {"request": request})

@router.get("/topaz-upscale", response_class=HTMLResponse)
async def topaz_upscale_page(request: Request):
    return templates.TemplateResponse("topaz-upscale.html", {"request": request})

@router.get("/wan25", response_class=HTMLResponse)
async def wan25_page(request: Request):
    return templates.TemplateResponse("wan25.html", {"request": request})

@router.get("/wan26", response_class=HTMLResponse)
async def wan26_page(request: Request):
    return templates.TemplateResponse("wan26.html", {"request": request})

@router.get("/modjourney-video", response_class=HTMLResponse)
async def modjourney_video_page(request: Request):
    return templates.TemplateResponse("modjourney-video.html", {"request": request})

# ========================
# IMAGE tools
# ========================
@router.get("/nanobanana-pro", response_class=HTMLResponse)
async def nanobanana_pro_page(request: Request):
    return templates.TemplateResponse("nanobananapro.html", {"request": request})

@router.get("/nanobanana", response_class=HTMLResponse)
async def nanobanana_page(request: Request):
    return templates.TemplateResponse("nanobanana.html", {"request": request})

@router.get("/grok", response_class=HTMLResponse)
async def grok_page(request: Request):
    return templates.TemplateResponse("grok.html", {"request": request})

@router.get("/midjourney", response_class=HTMLResponse)
async def midjourney_page(request: Request):
    return templates.TemplateResponse("midjourney.html", {"request": request})

@router.get("/seedream", response_class=HTMLResponse)
async def seedream_page(request: Request):
    return templates.TemplateResponse("seedream.html", {"request": request})

@router.get("/seedream45", response_class=HTMLResponse)
async def seedream45_page(request: Request):
    return templates.TemplateResponse("seedream45.html", {"request": request})

# ========================
# AUDIO tools
# ========================
@router.get("/sunov5", response_class=HTMLResponse)
async def sunov5_page(request: Request):
    return templates.TemplateResponse("sunov5.html", {"request": request})

@router.get("/elevenlabs", response_class=HTMLResponse)
async def elevenlabs_page(request: Request):
    return templates.TemplateResponse("elevenlabs.html", {"request": request})
