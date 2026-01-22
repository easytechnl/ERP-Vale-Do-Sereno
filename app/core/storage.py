import os
from pathlib import Path
from app.core.config import settings

def storage_root() -> Path:
    root = Path(settings.STORAGE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root

def competence_dir(competence: str) -> Path:
    # competence: YYYY-MM
    safe = competence.replace("/", "-").replace("..", "")
    d = storage_root() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d

def write_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path

def write_text(path: Path, data: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    return path
