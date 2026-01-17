# app/web.py
import stripe
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import STRIPE_SECRET_KEY
from .core.paths import STATIC_DIR
from .routes.health import router as health_router
from .routes.pages import router as pages_router
from .routes.tools import router as tools_router
from .routes.me import router as me_router
from .routes.referrals import router as referrals_router
from .routes.billing import router as billing_router
from .routes.gpt_image import router as gpt_image_router
from .routes.nanobanana_pro import router as nanobanana_pro_router
from .routes.veo31 import router as veo31_router
from .routes.sora2pro import router as sora2pro_router

stripe.api_key = STRIPE_SECRET_KEY

app = FastAPI()
api = app  # για συμβατότητα με uvicorn app.web:api αν το χρησιμοποιείς κάπου

# Static
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Root redirect
@app.get("/")
async def root():
    return RedirectResponse(url="/profile")

# Routers
app.include_router(health_router)
app.include_router(pages_router)
app.include_router(tools_router)
app.include_router(me_router)
app.include_router(referrals_router)
app.include_router(billing_router)
app.include_router(gpt_image_router)
app.include_router(nanobanana_pro_router)
app.include_router(veo31_router)
app.include_router(sora2pro_router)

