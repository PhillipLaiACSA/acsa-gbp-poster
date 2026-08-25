# ACSA GBP Auto-Poster — how it works + one-time setup

**What it does:** twice a week (Mon + Thu), a free GitHub robot picks the next
post from your Google Sheet, grabs a never-used photo from Drive, hosts it on
your website, and posts it to your Google Business Profile. No Mac, no login,
no approval. It writes "Posted" back to the Sheet and logs the photo so it
never repeats. If anything breaks, GitHub emails you.

**You already have (built for you):**
- Schedule Sheet: `ACSA GBP Schedule (Sep-Dec 2026)` (35 posts, all "Ready")
- Photo folder in Drive: `ACSA GBP Photos` with 8 theme subfolders
- All the code in this repo (compliance guardrail included, fail-closed)

---

## Day to day: nothing

Just keep photos in the Drive folders. To change any post, edit the Sheet.
That's it.

---

## One-time setup (~15 min, done once)

### 1. Make the Google login permanent
- Google Cloud Console → project **My Maps Project** → **APIs & Services → OAuth consent screen**.
- If it says "Testing", click **Publish app → Confirm** (this is what stops the 7-day expiry).

### 2. Get your API keys
- APIs & Services → **Credentials** → your OAuth **Desktop** client → note the
  **Client ID** and **Client secret** (or open your existing `credentials.json`).

### 3. Create the GitHub repo
- New **private** repo named `acsa-gbp-poster`.
- Upload every file in this folder (keep the `.github/workflows` folder).

### 4. Add the 5 secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `GOOGLE_CLIENT_ID` | from step 2 |
| `GOOGLE_CLIENT_SECRET` | from step 2 |
| `GOOGLE_REFRESH_TOKEN` | from step 6 |
| `WP_USER` | your WordPress admin username |
| `WP_APP_PASSWORD` | from step 5 |

### 5. WordPress application password
- WordPress admin → **Users → Profile → Application Passwords**.
- Name it `gbp-poster`, click **Add**, copy the password → that's `WP_APP_PASSWORD`.

### 6. Mint the permanent refresh token
- Open the consent link (built for you) in a browser signed in as
  **philliplai@gmail.com**, click **Allow**.
- The page will fail to load — copy the `code=...` value out of the address bar.
- In GitHub: **Actions → "(one-time) Mint Google refresh token" → Run workflow**,
  paste the code, run it. The log prints `GOOGLE_REFRESH_TOKEN = ...`.
- Save that as the `GOOGLE_REFRESH_TOKEN` secret (step 4), then delete the run.

### 7. Upload photos
Drop photos into the Drive subfolders by theme. Rough targets to cover Sep–Dec:
`beginner ~15, community ~8, womens ~6, kids ~6, boxing ~5, coaches ~4, teens ~3`.
Any format is fine — the robot converts them. Never-repeated, so more is better.

### 8. Test it
- **Actions → "Post to Google Business Profile" → Run workflow.**
- Check the log says "POSTED ok", the Sheet row flips to "Posted", and the post
  appears on your Google Business Profile.

Done. From here it runs itself.

---

## Good to know
- **Compliance guardrail** (`compliance.py`) blocks any post with a price, a
  phone number, a URL in the text, urgency words, a non-acsamelbourne.com.au
  button, or a bad image — fail-closed, so a bad row is skipped, never posted.
- **Photos run low?** The log warns when few unused photos remain, and the run
  fails (emails you) if a due post has no unused photo left. Top up the folder.
- **Change cadence?** Edit the `cron` line in `.github/workflows/post.yml`.
