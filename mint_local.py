#!/usr/bin/env python3
"""Alternative one-time minter: run on any machine that can reach Google,
with credentials.json (OAuth Desktop client) in the same folder.
Opens a browser, you approve once, and it prints a permanent refresh token.
    pip install google-auth-oauthlib
    python mint_local.py
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/business.manage",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]
flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nGOOGLE_REFRESH_TOKEN =", creds.refresh_token)
print("GOOGLE_CLIENT_ID     =", flow.client_config["client_id"])
print("GOOGLE_CLIENT_SECRET =", flow.client_config["client_secret"])
