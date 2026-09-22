"""Host-only interactive OAuth bootstrap; never print credentials or callback URLs."""

import argparse
import json
import os
from pathlib import Path
import tempfile

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def local_path(value):
    path = Path(value).expanduser().resolve()
    if "Mobile Documents" in path.parts or "CloudStorage" in path.parts:
        raise ValueError("OAuth credentials must be outside synchronized directories")
    return path


def save_credentials(credentials, path):
    path = local_path(path)
    if not credentials.refresh_token:
        raise ValueError(
            "No offline refresh token received; authorize again with consent"
        )
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".oauth-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(credentials.to_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_credentials(path):
    from google.oauth2.credentials import Credentials

    path = local_path(path)
    if path.stat().st_mode & 0o077:
        raise ValueError("OAuth token file must be private: chmod 600")
    credentials = Credentials.from_authorized_user_file(str(path))
    if not credentials.refresh_token or not credentials.has_scopes(DRIVE_SCOPES):
        raise ValueError(
            "Drive offline authorization is missing; run OAuth login again"
        )
    return credentials


def authorize(client_secrets, token_file):
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_secrets, token_file = local_path(client_secrets), local_path(token_file)
    if client_secrets == token_file:
        raise ValueError(
            "Token output must not overwrite the OAuth client configuration"
        )
    config = json.loads(client_secrets.read_text())
    if "installed" not in config:
        raise ValueError("A Desktop app OAuth client is required")
    # Fixed Google endpoints; the attached JSON is configuration, not executable input.
    client = config["installed"]
    if (
        client.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth"
        or client.get("token_uri") != "https://oauth2.googleapis.com/token"
    ):
        raise ValueError("Unexpected OAuth endpoint")
    flow = InstalledAppFlow.from_client_config(
        config, DRIVE_SCOPES, autogenerate_code_verifier=True
    )
    print(
        "Opening Google sign-in. Complete authorization in your browser (10-minute timeout).",
        flush=True,
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        timeout_seconds=600,
        authorization_prompt_message="",
        success_message="ASR authorization received. You may close this tab.",
        prompt="consent",
        access_type="offline",
    )
    if not credentials.has_scopes(DRIVE_SCOPES):
        raise ValueError("Required Drive permission was not granted")
    save_credentials(credentials, token_file)
    print("OAuth authorization saved privately. No token is shown.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Authorize native ASR Drive access")
    parser.add_argument("--client-secrets", required=True)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    try:
        authorize(args.client_secrets, args.token_file)
    except Exception as exc:
        # OAuth exception payloads can contain authorization codes or tokens.
        raise SystemExit(
            "OAuth authorization did not complete ("
            + type(exc).__name__
            + "). Retry sign-in; check consent-screen test users and Drive permissions."
        ) from None


if __name__ == "__main__":
    main()
