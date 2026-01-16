# app/routes/tools.py
from fastapi import APIRouter

router = APIRouter()

TOOLS_CATALOG = { ... }  # κάνε paste από το web.py

@router.get("/api/tools")
async def tools_catalog():
    return {"ok": True, "tools": TOOLS_CATALOG}
