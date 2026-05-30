"""Google Gemini API client (REST, urllib)."""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiApiError(Exception):
    pass


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: int = 30,
    ):
        if not api_key:
            raise ValueError("Gemini API key is required")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def generate_content(self, prompt: str, *, json_mode: bool = False) -> str:
        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        payload: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
        }
        if json_mode:
            payload["generationConfig"] = {"responseMimeType": "application/json"}

        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_sec) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            message = error_body
            try:
                message = json.loads(error_body).get("error", {}).get("message", error_body)
            except json.JSONDecodeError:
                pass
            raise GeminiApiError(f"HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise GeminiApiError(f"Network error: {exc.reason}") from exc

        text = self._extract_text(data)
        if not text:
            if "error" in data:
                err = data["error"]
                raise GeminiApiError(
                    f"{err.get('code')}: {err.get('message', 'Unknown Gemini error')}"
                )
            raise GeminiApiError("Empty response from Gemini")
        return text

    @staticmethod
    def _extract_text(response: dict) -> str:
        candidates = response.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts if "text" in part)

    @staticmethod
    def parse_json_response(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GeminiApiError("Failed to parse Gemini JSON response") from exc
