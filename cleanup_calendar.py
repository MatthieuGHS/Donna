"""Cleanup script to remove imported ICS events from Google Calendar.

Uses the same Service Account credentials as Donna.
The Service Account must have scope: https://www.googleapis.com/auth/calendar
(not just readonly — Donna already uses this scope, so it should be fine).

Usage:
    python cleanup_calendar.py --dry-run          # Preview what would be deleted
    python cleanup_calendar.py                    # Delete after confirmation
    python cleanup_calendar.py --ics other.ics    # Use a different ICS file
"""

import argparse
import json
import re
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def unfold_ics(text: str) -> str:
    """RFC 5545: unfold lines that start with space or tab."""
    return re.sub(r"\r?\n[ \t]", "", text)


def extract_uids(ics_path: str) -> list[str]:
    """Extract all UIDs from an ICS file."""
    with open(ics_path, "r", encoding="utf-8") as f:
        content = f.read()

    content = unfold_ics(content)
    uids = []
    for line in content.splitlines():
        if line.startswith("UID:"):
            uids.append(line[4:].strip())

    return uids


def get_calendar_service():
    sa_info = json.loads(settings.google_service_account_json)
    credentials = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build("calendar", "v3", credentials=credentials)


def main():
    parser = argparse.ArgumentParser(description="Remove imported ICS events from Google Calendar")
    parser.add_argument("--ics", default="Cours.ics", help="Path to ICS file (default: Cours.ics)")
    parser.add_argument("--dry-run", action="store_true", help="List events without deleting")
    args = parser.parse_args()

    # Extract UIDs
    print(f"Parsing {args.ics}...")
    uids = extract_uids(args.ics)
    print(f"Found {len(uids)} UIDs in ICS file.\n")

    if not uids:
        print("No UIDs found. Exiting.")
        return

    service = get_calendar_service()
    calendar_id = settings.google_calendar_id

    found = 0
    not_found = 0
    deleted = 0
    errors = 0

    # First pass: find all events
    events_to_delete = []

    for i, uid in enumerate(uids, 1):
        try:
            result = service.events().list(
                calendarId=calendar_id,
                iCalUID=uid,
                singleEvents=False,
            ).execute()

            items = result.get("items", [])
            if items:
                for event in items:
                    event_id = event["id"]
                    summary = event.get("summary", "(sans titre)")
                    start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", "?"))
                    events_to_delete.append((event_id, summary, start, uid))
                    found += 1
                    print(f"  [{i}/{len(uids)}] Found: {summary} | {start}")
            else:
                not_found += 1
                print(f"  [{i}/{len(uids)}] Not found: {uid}")

        except HttpError as e:
            errors += 1
            print(f"  [{i}/{len(uids)}] Error for {uid}: {e.resp.status} {e._get_reason()}")

    # Summary
    print(f"\n{'='*50}")
    print(f"Total UIDs:  {len(uids)}")
    print(f"Found:       {found}")
    print(f"Not found:   {not_found}")
    print(f"Errors:      {errors}")
    print(f"{'='*50}\n")

    if not events_to_delete:
        print("Nothing to delete.")
        return

    if args.dry_run:
        print("DRY RUN — no events were deleted.")
        return

    # Confirmation
    confirm = input(f"Delete {len(events_to_delete)} events? Type 'oui' to confirm: ")
    if confirm.strip().lower() != "oui":
        print("Cancelled.")
        return

    # Delete
    print()
    for i, (event_id, summary, start, uid) in enumerate(events_to_delete, 1):
        try:
            service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            deleted += 1
            print(f"  [{i}/{len(events_to_delete)}] Deleted: {summary} | {start}")
        except HttpError as e:
            print(f"  [{i}/{len(events_to_delete)}] Failed to delete {summary}: {e.resp.status}")

    print(f"\nDone. Deleted {deleted}/{len(events_to_delete)} events.")


if __name__ == "__main__":
    main()
