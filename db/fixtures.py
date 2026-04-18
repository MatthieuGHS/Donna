"""Development fixtures — seed data for testing.

REFUSES to run in production. Idempotent by default.
Use --reset flag to wipe and re-seed.
"""

import argparse
import sys

from supabase import create_client

from config import settings


def seed(reset: bool = False) -> None:
    """Insert test data into Supabase dev database."""

    if settings.is_prod:
        print("REFUSING to run fixtures in production environment.")
        sys.exit(1)

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    if reset:
        print("Resetting all data...")
        client.table("pending_actions").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        client.table("audit_logs").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        client.table("todos").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        client.table("rules").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        print("All data cleared.")

    # Check if data already exists (idempotent)
    existing_todos = client.table("todos").select("id").limit(1).execute()
    if existing_todos.data and not reset:
        print("Data already exists. Use --reset to wipe and re-seed.")
        return

    # Seed todos
    todos = [
        {"title": "Rendre le rapport de stage", "deadline": "2026-04-25", "priority": "high"},
        {"title": "Acheter des courses", "priority": "medium"},
        {"title": "Appeler le dentiste", "deadline": "2026-04-22", "priority": "low"},
    ]
    for todo in todos:
        client.table("todos").insert(todo).execute()
    print(f"Inserted {len(todos)} todos.")

    # Seed rules
    rules = [
        {
            "type": "availability",
            "rule_text": "Pas de rendez-vous avant 9h",
            "structured": {"type": "no_events_before", "hour": 9},
        },
        {
            "type": "availability",
            "rule_text": "Pas de rendez-vous après 20h",
            "structured": {"type": "no_events_after", "hour": 20},
        },
        {
            "type": "recap",
            "rule_text": "Rappeler les deadlines à J-2",
            "structured": {"type": "deadline_reminder", "days_before": 2},
        },
    ]
    for rule in rules:
        client.table("rules").insert(rule).execute()
    print(f"Inserted {len(rules)} rules.")

    print("Fixtures loaded successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load dev fixtures")
    parser.add_argument("--reset", action="store_true", help="Wipe all data before seeding")
    args = parser.parse_args()
    seed(reset=args.reset)
