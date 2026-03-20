"""Research plan persistence (file-based for MVP)."""
import json
from datetime import datetime
from typing import List, Optional

from app.core.settings import settings


STORE_PATH = settings.DATA_DIR / "plans.json"


def _load_store() -> dict:
    if not STORE_PATH.exists():
        return {"plans": {}}
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_store(data: dict):
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_plan(plan: dict) -> None:
    """Persist plan to file."""
    data = _load_store()
    plan_copy = plan.copy()
    plan_copy["updated_at"] = datetime.now().isoformat()
    data["plans"][plan["plan_id"]] = plan_copy
    _save_store(data)


def list_plans() -> List[dict]:
    """List all saved plans (for dropdown)."""
    data = _load_store()
    plans = list(data["plans"].values())
    plans.sort(key=lambda p: p.get("updated_at", ""), reverse=True)
    return plans


def get_plan_from_store(plan_id: str) -> Optional[dict]:
    """Get plan by ID from file."""
    data = _load_store()
    return data["plans"].get(plan_id)


def load_all_plans() -> dict:
    """Load all plans from file (for in-memory cache)."""
    data = _load_store()
    return data.get("plans", {})
