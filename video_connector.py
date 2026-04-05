"""
video_connector.py - Universal video understanding via LLM

Usage:
    from video_connector import chat_with_video

    result = chat_with_video(
        video_path="video.mp4",
        prompt="总结这个视频的内容",
        provider="gemini",        # or "qwen"
    )
"""
import base64
import os
from pathlib import Path

from model_connector import get_connector

VIDEO_INLINE_LIMIT = 20 * 1024 * 1024  # 20 MB

DEFAULT_PROMPT = "请完整总结这个视频的内容，还原文字信息，保留结构，输出 Markdown 格式。"

_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/avi",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}


def chat_with_video(
    video_path: str,
    prompt: str = DEFAULT_PROMPT,
    *,
    provider: str,
    model: str | None = None,
    **kwargs,
) -> str:
    """
    Send a local video to an LLM and return the response text.

    Small videos (< 20 MB): base64-encoded inline — works with all providers.
    Large videos (>= 20 MB) + Gemini: uploaded via Gemini File API.
    Large videos (>= 20 MB) + Qwen: base64 inline (Qwen supports up to 2 GB).

    Parameters
    ----------
    video_path : str
        Local path to the video file.
    prompt : str
        Instruction sent alongside the video.
    provider : str
        Provider key from models_config.json (e.g. "gemini", "qwen").
    model : str, optional
        Model alias. Defaults to the provider's default_model.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    size = path.stat().st_size

    if size >= VIDEO_INLINE_LIMIT and provider == "gemini":
        messages = _messages_gemini_file_api(path, prompt)
    else:
        messages = _messages_base64(path, prompt)

    return get_connector().chat(messages, provider=provider, model=model, **kwargs)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _messages_base64(path: Path, prompt: str) -> list[dict]:
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    mime = _get_mime_type(path)
    return [{
        "role": "user",
        "content": [
            {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{data}"}},
            {"type": "text", "text": prompt},
        ],
    }]


def _messages_gemini_file_api(path: Path, prompt: str) -> list[dict]:
    from gemini_uploader import upload_video
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Export it or add to .env"
        )
    file_uri = upload_video(str(path), api_key)
    return [{
        "role": "user",
        "content": [
            {"type": "video_url", "video_url": {"url": file_uri}},
            {"type": "text", "text": prompt},
        ],
    }]


def _get_mime_type(path: Path) -> str:
    return _MIME_TYPES.get(path.suffix.lower(), "video/mp4")
