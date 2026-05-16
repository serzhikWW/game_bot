"""
Gemini service — async wrapper around the google-generativeai SDK.

The SDK is synchronous; this module exposes an async surface by running
blocking calls in a thread pool. Two flows are supported:

  * `analyze_video(video_bytes, prompt, mime_type)`:
      upload → poll until ACTIVE → generate_content([video, prompt])
      → delete the uploaded file (cleanup is best-effort).

  * `analyze_text(prompt)`:
      generate_content(prompt) only — used by API-based plugins (Dota 2)
      that pass a structured payload as text.

Both return an `AnalysisOutput` with raw text + token count + elapsed seconds.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import google.generativeai as genai


logger = logging.getLogger(__name__)


DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_VIDEO_FPS = 5.0
UPLOAD_POLL_INTERVAL_S = 2.0
UPLOAD_POLL_TIMEOUT_S = 120.0
GENERATE_TIMEOUT_S = 120.0


class GeminiError(RuntimeError):
    """Raised when Gemini fails in a way the caller should surface to the user."""


class GeminiTimeoutError(GeminiError):
    """File upload processing or generation took longer than the configured limit."""


class GeminiUploadFailedError(GeminiError):
    """Uploaded file ended up in FAILED state."""


@dataclass
class AnalysisOutput:
    raw_text: str
    tokens_used: int
    processing_seconds: float


class GeminiService:
    """Async-friendly wrapper. Configure once at startup with `configure()`."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        video_fps: float = DEFAULT_VIDEO_FPS,
    ):
        self._api_key = api_key
        self._model_name = model
        self._video_fps = self._normalize_fps(video_fps)
        self._configured = False
        self._model: genai.GenerativeModel | None = None

    def configure(self) -> None:
        """Idempotent. Call once on startup."""
        if self._configured:
            return
        genai.configure(api_key=self._api_key)
        self._model = genai.GenerativeModel(self._model_name)
        self._configured = True
        logger.info("gemini_configured model=%s", self._model_name)

    @property
    def model(self) -> genai.GenerativeModel:
        if self._model is None:
            raise RuntimeError("GeminiService.configure() must be called before use")
        return self._model

    @property
    def video_fps(self) -> float:
        """Default frame sampling rate for video prompts."""
        return self._video_fps

    # --- public API ---------------------------------------------------

    async def analyze_text(self, prompt: str) -> AnalysisOutput:
        """Run a text-only prompt through the model."""
        started = time.monotonic()
        response = await asyncio.wait_for(
            asyncio.to_thread(self.model.generate_content, prompt),
            timeout=GENERATE_TIMEOUT_S,
        )
        return self._build_output(response, time.monotonic() - started)

    async def analyze_video(
        self,
        video_bytes: bytes,
        prompt: str,
        mime_type: str = "video/mp4",
        fps: float | None = None,
    ) -> AnalysisOutput:
        """Upload bytes → wait for ACTIVE → generate_content → delete file."""
        started = time.monotonic()
        video_fps = self._normalize_fps(fps if fps is not None else self._video_fps)
        uploaded = await self._upload_video(video_bytes, mime_type)
        try:
            await self._wait_until_active(uploaded)
            response = await asyncio.wait_for(
                self._generate_video_with_metadata(
                    uploaded,
                    prompt,
                    mime_type,
                    video_fps,
                ),
                timeout=GENERATE_TIMEOUT_S,
            )
        finally:
            await self._delete_file_safe(uploaded)
        return self._build_output_from_json(response, time.monotonic() - started)

    # --- internals ----------------------------------------------------

    async def _upload_video(self, video_bytes: bytes, mime_type: str):
        """Persist bytes to a temp file (the SDK takes a path) and upload."""
        # Run the blocking SDK calls + temp-file write in a thread.
        def _do_upload():
            suffix = ".mp4" if mime_type.endswith("mp4") else ""
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False
            ) as tmp:
                tmp.write(video_bytes)
                tmp_path = Path(tmp.name)
            try:
                return genai.upload_file(path=str(tmp_path), mime_type=mime_type)
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("temp_unlink_failed path=%s", tmp_path)

        uploaded = await asyncio.to_thread(_do_upload)
        logger.info(
            "gemini_upload name=%s state=%s size=%d",
            getattr(uploaded, "name", "?"),
            getattr(getattr(uploaded, "state", None), "name", "?"),
            len(video_bytes),
        )
        return uploaded

    async def _generate_video_with_metadata(
        self,
        uploaded,
        prompt: str,
        mime_type: str,
        fps: float,
    ) -> dict:
        """Call generateContent through REST so videoMetadata.fps is explicit."""
        file_uri = getattr(uploaded, "uri", None)
        if not file_uri:
            raise GeminiError("Gemini upload did not return a file URI for videoMetadata")

        uploaded_mime_type = getattr(uploaded, "mime_type", None) or mime_type
        model_name = self._model_name
        if model_name.startswith("models/"):
            model_name = model_name.removeprefix("models/")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "file_data": {
                                "mime_type": uploaded_mime_type,
                                "file_uri": file_uri,
                            },
                            "video_metadata": {"fps": fps},
                        },
                        {"text": prompt},
                    ],
                }
            ]
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }
        timeout = aiohttp.ClientTimeout(total=GENERATE_TIMEOUT_S)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    message = error.get("message") or str(data)
                    raise GeminiError(
                        f"Gemini generateContent failed "
                        f"(status={response.status}, fps={fps:g}): {message}"
                    )
                logger.info(
                    "gemini_generate_video model=%s fps=%s file=%s",
                    self._model_name,
                    f"{fps:g}",
                    getattr(uploaded, "name", "?"),
                )
                return data

    async def _wait_until_active(self, uploaded) -> None:
        """Poll `get_file` until state == ACTIVE or timeout/FAILED."""
        deadline = time.monotonic() + UPLOAD_POLL_TIMEOUT_S
        name = uploaded.name
        while True:
            state = uploaded.state.name if uploaded.state else "UNKNOWN"
            if state == "ACTIVE":
                return
            if state == "FAILED":
                raise GeminiUploadFailedError(
                    f"Gemini file upload failed for {name}"
                )
            if time.monotonic() > deadline:
                raise GeminiTimeoutError(
                    f"Gemini file did not become ACTIVE within "
                    f"{UPLOAD_POLL_TIMEOUT_S:.0f}s (last state={state})"
                )
            await asyncio.sleep(UPLOAD_POLL_INTERVAL_S)
            uploaded = await asyncio.to_thread(genai.get_file, name)

    async def _delete_file_safe(self, uploaded) -> None:
        """Best-effort cleanup; swallow errors so they don't mask the analysis."""
        name = getattr(uploaded, "name", None)
        if not name:
            return
        try:
            await asyncio.to_thread(genai.delete_file, name)
            logger.info("gemini_file_deleted name=%s", name)
        except Exception:
            logger.exception("gemini_file_delete_failed name=%s", name)

    @staticmethod
    def _build_output(response, elapsed: float) -> AnalysisOutput:
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            # Fallback: stitch parts together from candidates if .text is empty
            parts: list[str] = []
            for cand in getattr(response, "candidates", None) or []:
                for part in getattr(getattr(cand, "content", None), "parts", []) or []:
                    p = getattr(part, "text", None)
                    if p:
                        parts.append(p)
            text = "\n".join(parts).strip()

        if not text:
            raise GeminiError("Gemini returned an empty response")

        usage = getattr(response, "usage_metadata", None)
        tokens = int(getattr(usage, "total_token_count", 0) or 0)
        return AnalysisOutput(
            raw_text=text, tokens_used=tokens, processing_seconds=elapsed
        )

    @staticmethod
    def _build_output_from_json(data: dict, elapsed: float) -> AnalysisOutput:
        parts: list[str] = []
        for candidate in data.get("candidates", []) or []:
            content = candidate.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if text:
                    parts.append(text)

        text = "\n".join(parts).strip()
        if not text:
            raise GeminiError("Gemini returned an empty response")

        usage = data.get("usageMetadata") or data.get("usage_metadata") or {}
        tokens = int(
            usage.get("totalTokenCount")
            or usage.get("total_token_count")
            or 0
        )
        return AnalysisOutput(
            raw_text=text,
            tokens_used=tokens,
            processing_seconds=elapsed,
        )

    @staticmethod
    def _normalize_fps(fps: float) -> float:
        try:
            value = float(fps)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Gemini video FPS must be a number, got {fps!r}") from exc
        if value <= 0:
            raise ValueError(f"Gemini video FPS must be > 0, got {fps!r}")
        return value
