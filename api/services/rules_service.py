"""Rules CRUD operations via Supabase."""

from uuid import UUID

import structlog
from supabase import create_client

from config import settings
from db.models import RuleType

logger = structlog.get_logger(__name__)


def _get_client():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def list_rules(rule_type: str = "all") -> list[dict]:
    """List rules, optionally filtered by type."""
    client = _get_client()
    query = client.table("rules").select("*").eq("active", True).order("created_at", desc=True)

    if rule_type != "all":
        query = query.eq("type", rule_type)

    result = query.execute()
    logger.info("rules_list", type=rule_type, count=len(result.data))
    return result.data


def create_rule(rule_type: RuleType, rule_text: str, structured: dict) -> dict:
    """Create a new rule."""
    client = _get_client()
    data = {
        "type": rule_type.value,
        "rule_text": rule_text,
        "structured": structured,
    }

    result = client.table("rules").insert(data).execute()
    rule = result.data[0]
    logger.info("rules_create", rule_id=rule["id"], type=rule_type)
    return rule


def delete_rule(rule_id: UUID) -> dict:
    """Soft-delete a rule by deactivating it."""
    client = _get_client()
    result = client.table("rules").update({"active": False}).eq("id", str(rule_id)).execute()

    if not result.data:
        raise ValueError(f"Rule {rule_id} not found")

    logger.info("rules_delete", rule_id=str(rule_id))
    return {"deleted": str(rule_id)}
