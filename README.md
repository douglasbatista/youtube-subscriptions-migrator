# YouTube Subscriptions Migrator

Copy your YouTube channel subscriptions from one Google account to another
account you own (e.g., when switching to a new primary Google account).

## How it works

1. `export` — OAuth login as the **source** account, pages through the
   YouTube Data API v3 `subscriptions.list` (mine=true), saves everything
   to `subscriptions.json`.
2. `import` — OAuth login as the **destination** account, fetches its
   existing subscriptions, then calls `subscriptions.insert` for every
   channel not already subscribed.

Both accounts use the same `client_secret.json`; separate token files
(`token_source.json` / `token_dest.json`) keep the two logins apart, and
the OAuth screen always shows the account chooser so you can't mix them up.

## Setup

### 1. Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a project (or reuse an existing one).
2. In **APIs & Services → Library**, enable **YouTube Data API v3**.
3. In **APIs & Services → OAuth consent screen**, choose **External**, add
   your email as a test user, and add the scope
   `.../auth/youtube` (the script requests it automatically, you just need
   your test accounts allowed).
4. In **APIs & Services → Credentials**, create an **OAuth client ID** of
   type **Desktop app**, download the JSON, and save it next to this script
   as `client_secret.json`.

> **Note:** While the project is in *testing* status, the consent screen
> may warn you about an unverified app. This is expected for personal-use
> apps — you can click through. Access tokens for test users expire after
> 7 days, after which you simply re-authenticate (a browser window opens
> again; nothing is lost).

### 2. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# 1. Copy subscriptions OUT of the old account
python subscriptions_tool.py export

# 2. Paste them INTO the new account
python subscriptions_tool.py import

# Optional: inspect either account afterwards
python subscriptions_tool.py list --account dest
```

## Quota (important!)

The default YouTube API quota is **10,000 units/day**:

- `subscriptions.list`: 1 unit per page (50 subs) — negligible.
- `subscriptions.insert`: **50 units each** → roughly **200 new
  subscriptions per day**.

If you have more than ~200 subscriptions, the import will stop when the
quota runs out. **Just run `import` again the next day** — the script
re-checks the destination account's existing subscriptions and resumes
exactly where it left off.

To avoid the limit entirely, request a quota increase in the Cloud Console
(IAM & Admin → Quotas → YouTube Data API v3).

## Notes

- Deleted/private channels may fail to import; failures are logged to
  `failed_imports.json`.
- Subscription *order* (newest first) and notification-bell settings are
  not preserved — the API doesn't expose them.
