# app/web.py
import stripe
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import STRIPE_SECRET_KEY
from .core.paths import STATIC_DIR

# --- Existing routers ---
from .routes.health import router as health_router
from .routes.pages import router as pages_router
from .routes.tools import router as tools_router
from .routes.me import router as me_router
from .routes.referrals import router as referrals_router
from .routes.billing import router as billing_router
from .routes.jobs import router as jobs_router

# --- Image tools ---
from .routes.gpt_image import router as gpt_image_router
from .routes.nanobanana_pro import router as nanobanana_pro_router
from .routes.nanobanana import router as nanobanana_router
from .routes.grok import router as grok_router
from .routes.midjourney import router as midjourney_router
from .routes.seedream import router as seedream_router
from .routes.seedream45 import router as seedream45_router

# --- Video tools ---
from .routes.veo31 import router as veo31_router
from .routes.veo3fast import router as veo3fast_router
from .routes.sora2pro import router as sora2pro_router
from .routes.sora2 import router as sora2_router
from .routes.kling26 import router as kling26_router
from .routes.kling_o1 import router as kling_o1_router
from .routes.kling21 import router as kling21_router
from .routes.kling25turbo import router as kling25turbo_router
from .routes.kling26motion import router as kling26motion_router
from .routes.kling26motion2 import router as kling26motion2_router
from .routes.kling30 import router as kling30_router
from .routes.kling30_2 import router as kling30_2_router
from .routes.klingv1avatar import router as klingv1avatar_router
from .routes.runway import router as runway_router
from .routes.runway_aleph import router as runway_aleph_router
from .routes.seedance import router as seedance_router
from .routes.hailuo02 import router as hailuo02_router
from .routes.topaz_upscale import router as topaz_upscale_router
from .routes.wan25 import router as wan25_router
from .routes.wan26 import router as wan26_router
from .routes.modjourney_video import router as modjourney_video_router

# --- Audio tools ---
from .routes.suno_v5 import router as suno_v5_router
from .routes.elevenlabs import router as elevenlabs_router


stripe.api_key = STRIPE_SECRET_KEY

app = FastAPI()
api = app  # για συμβατότητα με uvicorn app.web:api αν το χρησιμοποιείς κάπου

# Static
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Routers — core
app.include_router(health_router)
app.include_router(pages_router)
app.include_router(tools_router)
app.include_router(me_router)
app.include_router(referrals_router)
app.include_router(billing_router)
app.include_router(jobs_router)

# Routers — image tools
app.include_router(gpt_image_router)
app.include_router(nanobanana_pro_router)
app.include_router(nanobanana_router)
app.include_router(grok_router)
app.include_router(midjourney_router)
app.include_router(seedream_router)
app.include_router(seedream45_router)

# Routers — video tools
app.include_router(veo31_router)
app.include_router(veo3fast_router)
app.include_router(sora2pro_router)
app.include_router(sora2_router)
app.include_router(kling26_router)
app.include_router(kling_o1_router)
app.include_router(kling21_router)
app.include_router(kling25turbo_router)
app.include_router(kling26motion_router)
app.include_router(kling26motion2_router)
app.include_router(kling30_router)
app.include_router(kling30_2_router)
app.include_router(klingv1avatar_router)
app.include_router(runway_router)
app.include_router(runway_aleph_router)
app.include_router(seedance_router)
app.include_router(hailuo02_router)
app.include_router(topaz_upscale_router)
app.include_router(wan25_router)
app.include_router(wan26_router)
app.include_router(modjourney_video_router)

# Routers — audio tools
app.include_router(suno_v5_router)
app.include_router(elevenlabs_router)
