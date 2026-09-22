"""Small authenticated host client. Network errors must not expose credentials."""

import os
import httpx
from .config import secret


class Client:
    def __init__(self, url=None, token=None):
        self.session = httpx.Client(
            base_url=url or os.environ.get("ASR_API_URL", "http://127.0.0.1:8090"),
            headers={
                "Authorization": "Bearer " + (token or secret("ASR_WORKER_TOKEN"))
            },
            timeout=30,
        )

    def call(self, action, **body):
        response = self.session.post("/worker/" + action, json=body)
        response.raise_for_status()
        return response.json()

    def close(self):
        self.session.close()
