import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from asr_service.drive import Drive, DriveError, FOLDER
from asr_service.oauth import (
    authorize,
    save_credentials,
    load_credentials,
    DRIVE_SCOPES,
)


class OAuthTest(unittest.TestCase):
    def credentials(self):
        return Credentials(
            token="test-access",
            refresh_token="test-refresh",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="test-client",
            client_secret="test-secret",
            scopes=DRIVE_SCOPES,
        )

    def test_private_roundtrip_and_no_refresh_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens/user.json"
            save_credentials(self.credentials(), path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_credentials(path).refresh_token, "test-refresh")
            original = path.read_bytes()
            bad = Mock(refresh_token=None)
            with self.assertRaises(ValueError):
                save_credentials(bad, path)
            self.assertEqual(path.read_bytes(), original)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                load_credentials(path)

    def test_oauth_my_drive_destination_but_not_readonly(self):
        source = {"mimeType": FOLDER, "capabilities": {"canListChildren": True}}
        destination = {"mimeType": FOLDER, "capabilities": {"canAddChildren": True}}
        d = Drive(session=Mock(), auth_mode="oauth")
        d.metadata = lambda id: source if id == "source" else destination
        d.preflight("source", "destination")
        d.auth_mode = "service_account"
        with self.assertRaises(DriveError):
            d.preflight("source", "destination")
        d.auth_mode = "oauth"
        destination["capabilities"]["canAddChildren"] = False
        with self.assertRaises(DriveError):
            d.preflight("source", "destination")

    def test_oauth_mode_never_falls_back_to_service_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user.json"
            save_credentials(self.credentials(), path)
            with (
                patch("google.auth.transport.requests.AuthorizedSession") as session,
                patch(
                    "google.oauth2.service_account.Credentials.from_service_account_file"
                ) as service,
            ):
                Drive(credentials_path=path, auth_mode="oauth")
                session.assert_called_once()
                service.assert_not_called()
            with self.assertRaises(FileNotFoundError):
                Drive(credentials_path=Path(tmp) / "missing", auth_mode="oauth")

    def test_refresh_failure_is_blocked_and_redacted(self):
        session = Mock()
        session.request.side_effect = RefreshError("sensitive-token-must-not-leak")
        d = Drive(session=session, auth_mode="oauth")
        with self.assertRaises(DriveError) as caught:
            d.metadata("folder")
        self.assertTrue(caught.exception.blocked)
        self.assertNotIn("sensitive", str(caught.exception))

    def test_cloud_storage_and_missing_scope_rejected(self):
        with self.assertRaises(ValueError):
            load_credentials("/tmp/Mobile Documents/user.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user.json"
            save_credentials(self.credentials(), path)
            data = json.loads(path.read_text())
            data["scopes"] = ["openid"]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_credentials(path)

    def test_authorization_uses_loopback_pkce_and_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = Path(tmp) / "client.json"
            token = Path(tmp) / "token.json"
            client.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "test",
                            "client_secret": "test",
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                        }
                    }
                )
            )
            with patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config"
            ) as factory:
                factory.return_value.run_local_server.return_value = self.credentials()
                authorize(client, token)
                self.assertTrue(factory.call_args.kwargs["autogenerate_code_verifier"])
                args = factory.return_value.run_local_server.call_args.kwargs
                self.assertEqual(args["host"], "127.0.0.1")
                self.assertEqual(args["access_type"], "offline")
                self.assertEqual(args["prompt"], "consent")
                self.assertEqual(args["authorization_prompt_message"], "")
            with self.assertRaises(ValueError):
                authorize(client, client)


if __name__ == "__main__":
    unittest.main()
