#!/usr/bin/env python3
"""
Export YouTube channel subscriptions from one Google account and import
them into another account owned by the same person.

Usage:
    python subscriptions_tool.py export
        Log in as the SOURCE account and save all subscriptions
        to subscriptions.json.

    python subscriptions_tool.py import
        Log in as the DESTINATION account and subscribe to every
        channel in subscriptions.json that isn't already subscribed.

    python subscriptions_tool.py list --account source|dest
        Print the subscriptions of the saved credentials (no login
        prompt if tokens are still valid).

The same client_secret.json is used for both accounts; the OAuth flow
always shows the account chooser so you can pick which account to use.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Read/write subscriptions requires this scope.
SCOPES = ["https://www.googleapis.com/auth/youtube"]
CLIENT_SECRETS_FILE = "client_secret.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
TOKEN_FILES = {
    "source": "token_source.json",
    "dest": "token_dest.json",
}
ITEMS_PER_PAGE = 50


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_credentials(account: str) -> Credentials:
    """Run the OAuth flow (or refresh) and return credentials for `account`.

    `prompt="select_account"` forces the Google account chooser so you can
    log in as the correct account each time.
    """
    token_path = Path(TOKEN_FILES[account])
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                print(f"Token refresh failed ({exc}); re-authenticating...")
                creds = None

    if not creds or not creds.valid:
        if not Path(CLIENT_SECRETS_FILE).exists():
            sys.exit(
                f"Error: {CLIENT_SECRETS_FILE} not found.\n"
                "Download the OAuth client secret JSON from Google Cloud Console\n"
                "(APIs & Services -> Credentials -> OAuth client ID, type\n"
                "'Desktop app') and save it next to this script."
            )
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(
            port=0,
            prompt="select_account",  # always show the account chooser
        )

    token_path.write_text(creds.to_json())
    return creds


def get_service(account: str):
    """Build an authenticated YouTube Data API v3 client."""
    creds = get_credentials(account)
    return build("youtube", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def list_all_subscriptions(youtube) -> list[dict]:
    """Page through subscriptions().list(mine=True) and return
    [{channelId, title}, ...]."""
    results = []
    request = youtube.subscriptions().list(
        part="snippet",
        mine=True,
        maxResults=ITEMS_PER_PAGE,
    )
    while request is not None:
        response = request.execute()
        for item in response.get("items", []):
            snippet = item["snippet"]
            results.append(
                {
                    "channelId": snippet["resourceId"]["channelId"],
                    "title": snippet["title"],
                }
            )
        request = youtube.subscriptions().list_next(request, response)
    return results


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_export() -> None:
    print("Starting OAuth flow for the SOURCE account "
          "(the one you want to copy subscriptions FROM)...")
    youtube = get_service("source")
    print("Fetching all subscriptions...")
    subs = list_all_subscriptions(youtube)

    data = {"exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "subscriptions": subs}
    Path(SUBSCRIPTIONS_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Exported {len(subs)} subscriptions to {SUBSCRIPTIONS_FILE}")


def cmd_import(delay: float) -> None:
    if not Path(SUBSCRIPTIONS_FILE).exists():
        sys.exit(f"Error: {SUBSCRIPTIONS_FILE} not found. Run `export` first.")

    data = json.loads(Path(SUBSCRIPTIONS_FILE).read_text())
    wanted = data["subscriptions"]

    print("Starting OAuth flow for the DESTINATION account "
          "(the one you want to subscribe WITH)...")
    youtube = get_service("dest")

    print(f"Fetching existing subscriptions of the destination account "
          f"to skip duplicates...")
    existing = {s["channelId"] for s in list_all_subscriptions(youtube)}

    todo = [s for s in wanted if s["channelId"] not in existing]
    skipped = len(wanted) - len(todo)
    print(f"{len(wanted)} channels in file, {skipped} already subscribed, "
          f"{len(todo)} to subscribe.")

    if not todo:
        print("Nothing to do — destination account already has all of them.")
        return

    failed = []
    done = 0
    for i, sub in enumerate(todo, start=1):
        channel_id = sub["channelId"]
        title = sub.get("title", channel_id)
        try:
            youtube.subscriptions().insert(
                part="snippet",
                body={"snippet": {"resourceId": {"channelId": channel_id}}},
            ).execute()
            done += 1
            print(f"[{i}/{len(todo)}] Subscribed: {title}")
        except HttpError as exc:
            reason = _error_reason(exc)
            if exc.resp.status == 403 and "quota" in reason:
                print(f"\nDaily quota exceeded after {done} imports "
                      f"({reason}).\n"
                      "Wait for the quota reset (midnight PT) and simply run\n"
                      "this command again — already-imported channels are\n"
                      "skipped automatically.")
                break
            failed.append({"channelId": channel_id, "title": title, "error": reason})
            print(f"[{i}/{len(todo)}] FAILED: {title} ({reason})")
        time.sleep(delay)

    print(f"\nDone: subscribed to {done} channels.")
    if failed:
        fail_path = Path("failed_imports.json")
        fail_path.write_text(json.dumps(failed, indent=2, ensure_ascii=False))
        print(f"{len(failed)} channels failed — see {fail_path}")


def cmd_list(account: str) -> None:
    youtube = get_service(account)
    subs = list_all_subscriptions(youtube)
    print(f"{len(subs)} subscriptions in account '{account}':")
    for i, sub in enumerate(subs, start=1):
        print(f"{i:4d}. {sub['title']}  [{sub['channelId']}]")


def _error_reason(exc: HttpError) -> str:
    try:
        content = json.loads(exc.content.decode("utf-8"))
        return content.get("error", {}).get("message", str(exc))
    except Exception:
        return str(exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy YouTube subscriptions between your own accounts."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("export", help="Export subscriptions from the source account.")
    p_import = sub.add_parser(
        "import", help="Import subscriptions into the destination account."
    )
    p_import.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between subscribe calls (default: 0.5).",
    )
    p_list = sub.add_parser(
        "list", help="List subscriptions of an already-authorized account."
    )
    p_list.add_argument(
        "--account", choices=list(TOKEN_FILES), default="source",
        help="Which saved credentials to use.",
    )

    args = parser.parse_args()
    if args.command == "export":
        cmd_export()
    elif args.command == "import":
        cmd_import(args.delay)
    elif args.command == "list":
        cmd_list(args.account)


if __name__ == "__main__":
    main()
