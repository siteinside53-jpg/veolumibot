# app/core/paths.py
from pathlib import Path
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent          # /app/app
TEMPLATES_DIR = BASE_DIR / "web_templates"
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
VIDEOS_DIR = STATIC_DIR / "videos"

def ensure_dir(path: Path):
    if path.exists() and path.is_file():
        path.unlink()
    path.mkdir(parents=True, exist_ok=True)

ensure_dir(STATIC_DIR)
ensure_dir(IMAGES_DIR)
ensure_dir(VIDEOS_DIR)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
