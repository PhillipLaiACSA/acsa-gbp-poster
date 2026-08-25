#!/usr/bin/env python3
"""One-time: exchange an OAuth authorization code for a permanent refresh token.
Runs on a GitHub Actions runner (which can reach googleapis).
Prints the refresh_token so you can paste it into the GOOGLE_REFRESH_TOKEN secret,
then DELETE this workflow run.
"""
import os, sys, requests

code = os.environ["AUTH_CODE"].strip()
data = {
    "code": code,
    "client_id": os.environ["GOOGLE_CLIENT_ID"].strip(),
    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"].strip(),
    "redirect_uri": os.environ.get("REDIRECT_URI", "http://localhost").strip(),
    "grant_type": "authorization_code",
}
r = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=60)
j = r.json()
if "refresh_token" not in j:
    print("ERROR: no refresh_token in response:", j)
    sys.exit(1)
print("\n================  COPY THIS  ================")
print("GOOGLE_REFRESH_TOKEN =", j["refresh_token"])
print("============================================\n")
print("Now: save it as the GOOGLE_REFRESH_TOKEN repo secret, then delete this run.")
