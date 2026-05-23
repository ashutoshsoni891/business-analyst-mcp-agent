#!/usr/bin/env python3
"""
Run this once to exchange your Google credentials.json for an OAuth token.
The token is printed at the end — paste it into .env as GOOGLE_DRIVE_OAUTH_TOKEN.

Usage:
    python get_google_token.py path/to/credentials.json
"""

import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]


def main():
    if len(sys.argv) < 2:
        print("Usage: python get_google_token.py path/to/credentials.json")
        sys.exit(1)

    creds_file = sys.argv[1]
    flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)

    # Opens a browser tab for you to approve access
    # Port must match an Authorized Redirect URI in Google Cloud Console
    creds = flow.run_local_server(port=8080, open_browser=True)

    print("\n--- Copy the values below into your .env ---\n")
    print(f"GOOGLE_DRIVE_OAUTH_TOKEN={creds.token}")
    print(f"\n# Refresh token (optional, for long-lived access):")
    print(f"# GOOGLE_DRIVE_REFRESH_TOKEN={creds.refresh_token}")
    print(f"\n# Token expiry: {creds.expiry}")


if __name__ == "__main__":
    main()
