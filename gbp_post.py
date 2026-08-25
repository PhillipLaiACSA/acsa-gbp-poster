#!/usr/bin/env python3
"""
ACSA Google Business Profile — fully automated poster.

Runs headless on GitHub Actions. Each run:
  1. Auth with a permanent refresh token (no login, no Mac).
  2. Read the Google Sheet schedule; find the earliest DUE 'Ready' row.
  3. Pick the oldest NEVER-USED photo for that row's theme (Google Drive).
  4. Convert it to a clean 1600px JPEG and upload to the WordPress media
     library -> public https URL on acsamelbourne.com.au (Google rejects webp).
  5. Run the compliance guardrail (fail-closed).
  6. Post to the Google Business Profile.
  7. Write 'Posted' + date back to the Sheet and log the used photo so it
     never repeats.

Any real failure exits non-zero so GitHub emails Phill automatically.
Config (non-secret) lives in config.json; secrets come from env vars.
"""
import io
import os
import sys
import json
import time
import base64
import datetime

import requests
from PIL import Image
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    # Google libs are installed on the GitHub runner (requirements.txt).
    # Guarded so pure-logic unit tests can import this module without them.
    Credentials = AuthorizedSession = build = MediaIoBaseDownload = None

try:
    from zoneinfo import ZoneInfo
    _MELB = ZoneInfo("Australia/Melbourne")
except Exception:
    _MELB = None

import compliance

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))

SCOPES = [
    "https://www.googleapis.com/auth/business.manage",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

TODAY = (datetime.datetime.now(_MELB).date() if _MELB else datetime.date.today())


def env(name, required=True):
    val = os.environ.get(name, "").strip()
    if required and not val:
        die(f"missing required secret/env var: {name}")
    return val


def log(msg):
    print(f"[gbp] {msg}", flush=True)


def die(msg, code=1):
    print(f"::error::[gbp] {msg}", flush=True)
    sys.exit(code)


def creds():
    return Credentials(
        None,
        refresh_token=env("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=env("GOOGLE_CLIENT_ID"),
        client_secret=env("GOOGLE_CLIENT_SECRET"),
        scopes=SCOPES,
    )


# ---------- Google Sheet ----------
# The schedule always lives on the FIRST tab, so schedule ranges omit the tab
# name (Sheets defaults to the first visible sheet). The photo log lives on a
# dedicated tab that we auto-create if it is missing.
PHOTOLOG = None  # resolved tab title, set by ensure_photolog()


def ensure_photolog(sheets, sheet_id):
    global PHOTOLOG
    want = CFG["sheet_tab_photolog"]
    meta = sheets.spreadsheets().get(spreadsheetId=sheet_id,
                                     fields="sheets.properties.title").execute()
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if want not in titles:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": want}}}]},
        ).execute()
        sheets.spreadsheets().values().update(
            spreadsheetId=sheet_id, range=f"{want}!A1:E1",
            valueInputOption="RAW",
            body={"values": [["Date Posted", "Theme", "Filename", "Drive File ID", "Public URL"]]},
        ).execute()
    PHOTOLOG = want


def read_schedule(sheets, sheet_id):
    resp = sheets.spreadsheets().values().get(
        spreadsheetId=sheet_id, range="A2:I").execute()
    return resp.get("values", [])


def pick_due_row(rows, today):
    """Earliest Ready row whose date is on/before today. Returns
    (sheet_row_number, padded_row) or None. Self-heals: a missed post is
    picked up on the next run because older due rows sort first."""
    for i, r in enumerate(rows):
        r = (r + [""] * 9)[:9]
        date_s, status = r[0].strip(), r[1].strip().lower()
        if status != "ready":
            continue
        try:
            d = datetime.date.fromisoformat(date_s)
        except ValueError:
            continue
        if d <= today:
            return (i + 2, r)  # +2: row 1 is the header, data starts at row 2
    return None


def read_used_file_ids(sheets, sheet_id):
    try:
        resp = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{PHOTOLOG}!A2:E").execute()
    except Exception:
        return set()
    used = set()
    for r in resp.get("values", []):
        if len(r) >= 4 and r[3].strip():  # cols: date, theme, filename, file_id, url
            used.add(r[3].strip())
    return used


def mark_posted(sheets, sheet_id, row_number):
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"B{row_number}",
        valueInputOption="RAW", body={"values": [["Posted"]]}).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id, range=f"I{row_number}",
        valueInputOption="RAW", body={"values": [[TODAY.isoformat()]]}).execute()


def log_photo(sheets, sheet_id, theme, filename, file_id, wp_url):
    sheets.spreadsheets().values().append(
        spreadsheetId=sheet_id, range=f"{PHOTOLOG}!A:E",
        valueInputOption="RAW", insertDataOption="INSERT_ROWS",
        body={"values": [[TODAY.isoformat(), theme, filename, file_id, wp_url]]},
    ).execute()


# ---------- Google Drive photos ----------
def find_subfolder_id(drive, root_id, name):
    q = (f"'{root_id}' in parents and name = '{name}' "
         f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    res = drive.files().list(q=q, fields="files(id,name)", pageSize=5).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def list_images(drive, folder_id):
    q = (f"'{folder_id}' in parents and mimeType contains 'image/' "
         f"and trashed = false")
    out, page = [], None
    while True:
        res = drive.files().list(
            q=q, orderBy="createdTime",
            fields="nextPageToken, files(id,name,mimeType,createdTime)",
            pageSize=200, pageToken=page).execute()
        out.extend(res.get("files", []))
        page = res.get("nextPageToken")
        if not page:
            break
    return out


def pick_photo(drive, root_id, theme, used_ids):
    """Oldest unused image in the theme folder; fall back to 'general'.
    Returns (file_meta, resolved_theme, remaining_unused_total)."""
    order = [theme] if theme else []
    if CFG["fallback_theme"] not in order:
        order.append(CFG["fallback_theme"])

    remaining_total = 0
    chosen = None
    chosen_theme = None
    # count unused across ALL theme folders for the low-pool signal
    for t in CFG["theme_subfolders"]:
        fid = find_subfolder_id(drive, root_id, t)
        if not fid:
            continue
        imgs = [f for f in list_images(drive, fid) if f["id"] not in used_ids]
        remaining_total += len(imgs)
        if chosen is None and t in order:
            if imgs:
                chosen = imgs[0]
                chosen_theme = t
    return chosen, chosen_theme, remaining_total


def download_bytes(drive, file_id):
    buf = io.BytesIO()
    req = drive.files().get_media(fileId=file_id)
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf.seek(0)
    return buf.read()


# ---------- image -> clean JPEG ----------
def to_clean_jpeg(raw, max_w=1600, quality=75):
    im = Image.open(io.BytesIO(raw))
    if im.mode != "RGB":
        im = im.convert("RGB")
    if im.width > max_w:
        h = int(im.height * max_w / im.width)
        im = im.resize((max_w, h), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=quality, optimize=True)  # strips metadata
    out.seek(0)
    return out.read()


# ---------- image hosting: commit to this repo, serve via public raw URL ----------
# The repo is public, so raw.githubusercontent.com serves the committed JPEG at a
# public https URL that Google can fetch. No WordPress, no extra credentials — the
# workflow's built-in GITHUB_TOKEN (contents: write) does the commit.
def upload_to_github(jpeg, filename):
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")           # e.g. "PhillipLaiACSA/acsa-gbp-poster"
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    path = f"images/{filename}"
    body = {
        "message": f"gbp image: {filename}",
        "content": base64.b64encode(jpeg).decode(),
        "branch": branch,
    }
    r = requests.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        json=body, timeout=90,
    )
    if r.status_code not in (200, 201):
        die(f"GitHub image upload failed ({r.status_code}): {r.text[:300]}")
    raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    time.sleep(3)  # let the CDN pick up the new file before Google fetches it
    return raw_url


# ---------- Google Business Profile ----------
def post_to_gbp(session, copy, action_type, url, image_url):
    acct = CFG["account_id"]
    loc = CFG["location_id"]
    endpoint = (f"https://mybusiness.googleapis.com/v4/accounts/{acct}"
                f"/locations/{loc}/localPosts")
    body = {
        "languageCode": "en-AU",
        "summary": copy,
        "callToAction": {"actionType": action_type, "url": url},
        "media": [{"mediaFormat": "PHOTO", "sourceUrl": image_url}],
        "topicType": "STANDARD",
    }
    r = session.post(endpoint, json=body, timeout=90)
    if r.status_code not in (200, 201):
        die(f"GBP post failed ({r.status_code}): {r.text[:500]}")
    return r.json()


def main():
    sheet_id = os.environ.get("SHEET_ID", "").strip() or CFG.get("sheet_id", "")
    root_photos = os.environ.get("DRIVE_PHOTOS_FOLDER_ID", "").strip() or CFG.get("drive_photos_folder_id", "")
    if not sheet_id:
        die("no SHEET_ID (env or config.json)")
    if not root_photos:
        die("no DRIVE_PHOTOS_FOLDER_ID (env or config.json)")
    c = creds()
    sheets = build("sheets", "v4", credentials=c, cache_discovery=False)
    drive = build("drive", "v3", credentials=c, cache_discovery=False)
    session = AuthorizedSession(c)
    ensure_photolog(sheets, sheet_id)

    rows = read_schedule(sheets, sheet_id)
    if not rows:
        log("schedule empty — nothing to do")
        return

    target = pick_due_row(rows, TODAY)

    if target is None:
        log("no Ready row is due today — nothing to post (this is normal)")
        return

    row_num, r = target
    date_s, status, theme_name, ptype, copy, btn, link, image_theme, _ = r
    image_theme = (image_theme or "").strip().lower()
    log(f"due row {row_num}: {date_s} | {theme_name} | theme-photo='{image_theme}'")

    # compliance FIRST — never post something non-compliant
    violations = compliance.check(copy, btn, link, ptype or "Update")
    if violations:
        die("compliance guardrail BLOCKED this post:\n  - " + "\n  - ".join(violations))
    action_type = compliance._label_to_action(btn)

    # pick an unused photo
    used = read_used_file_ids(sheets, sheet_id)
    photo, resolved_theme, remaining = pick_photo(drive, root_photos, image_theme, used)
    if photo is None:
        die(f"NO UNUSED PHOTO available for theme '{image_theme}' (or fallback). "
            f"Upload photos to the Drive folder and re-run.")
    log(f"photo: {photo['name']} (theme '{resolved_theme}', {remaining} unused left overall)")

    raw = download_bytes(drive, photo["id"])
    jpeg = to_clean_jpeg(raw)
    # unique filename (theme + date + short photo id) so re-runs never collide
    fname = f"acsa-{resolved_theme}-{date_s}-{photo['id'][:8]}.jpg"
    img_url = upload_to_github(jpeg, fname)
    log(f"hosted: {img_url}")

    result = post_to_gbp(session, copy, action_type, link, img_url)
    log(f"POSTED ok: {result.get('name','(no name)')}")

    # write back + log photo
    mark_posted(sheets, sheet_id, row_num)
    log_photo(sheets, sheet_id, resolved_theme, photo["name"], photo["id"], img_url)
    log(f"sheet updated (row {row_num} -> Posted) and photo logged")

    if remaining - 1 <= CFG["low_pool_threshold"]:
        # non-fatal: post still succeeded, but warn loudly in the log
        print(f"::warning::[gbp] photo pool LOW — only {remaining-1} unused photos "
              f"left. Upload more to the Drive folder soon.", flush=True)


if __name__ == "__main__":
    main()
