"""Unit tests for video_connector — no real API calls."""
import sys
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from video_connector import (
    chat_with_video,
    _messages_base64,
    _get_mime_type,
    VIDEO_INLINE_LIMIT,
)


@pytest.fixture
def small_video(tmp_path):
    v = tmp_path / "test.mp4"
    v.write_bytes(b"fake video data")
    return str(v)


@pytest.fixture
def large_video(tmp_path):
    v = tmp_path / "large.mp4"
    v.write_bytes(b"x" * (VIDEO_INLINE_LIMIT + 1))
    return str(v)


def test_messages_base64_structure(small_video):
    messages = _messages_base64(Path(small_video), "describe this")
    assert len(messages) == 1
    content = messages[0]["content"]
    assert content[0]["type"] == "video_url"
    assert content[0]["video_url"]["url"].startswith("data:video/mp4;base64,")
    assert content[1]["type"] == "text"
    assert content[1]["text"] == "describe this"


def test_messages_base64_encoding(small_video):
    messages = _messages_base64(Path(small_video), "test")
    url = messages[0]["content"][0]["video_url"]["url"]
    encoded = url.split("base64,")[1]
    assert base64.b64decode(encoded) == b"fake video data"


def test_mime_type_mp4():
    assert _get_mime_type(Path("video.mp4")) == "video/mp4"


def test_mime_type_mov():
    assert _get_mime_type(Path("clip.mov")) == "video/quicktime"


def test_mime_type_unknown_defaults_to_mp4():
    assert _get_mime_type(Path("video.xyz")) == "video/mp4"


def test_chat_with_video_small_uses_base64(small_video):
    mock_connector = MagicMock()
    mock_connector.chat.return_value = "summary text"

    with patch("video_connector.get_connector", return_value=mock_connector):
        result = chat_with_video(small_video, "describe", provider="gemini")

    assert result == "summary text"
    messages = mock_connector.chat.call_args[0][0]
    assert messages[0]["content"][0]["video_url"]["url"].startswith("data:")


def test_chat_with_video_large_gemini_uses_file_api(large_video):
    mock_connector = MagicMock()
    mock_connector.chat.return_value = "summary"

    with patch("video_connector.get_connector", return_value=mock_connector), \
         patch("video_connector._messages_gemini_file_api") as mock_file_api:
        mock_file_api.return_value = [{"role": "user", "content": []}]
        chat_with_video(large_video, "describe", provider="gemini")

    mock_file_api.assert_called_once()


def test_chat_with_video_large_qwen_uses_base64(large_video):
    """Large video + Qwen uses base64 (Qwen supports up to 2 GB via base64)."""
    mock_connector = MagicMock()
    mock_connector.chat.return_value = "summary"

    with patch("video_connector.get_connector", return_value=mock_connector), \
         patch("video_connector._messages_base64") as mock_b64:
        mock_b64.return_value = [{"role": "user", "content": []}]
        chat_with_video(large_video, "describe", provider="qwen")

    mock_b64.assert_called_once()


def test_chat_with_video_file_not_found():
    with pytest.raises(FileNotFoundError):
        chat_with_video("/nonexistent/video.mp4", "test", provider="gemini")


def test_chat_with_video_default_prompt(small_video):
    mock_connector = MagicMock()
    mock_connector.chat.return_value = "ok"

    with patch("video_connector.get_connector", return_value=mock_connector):
        chat_with_video(small_video, provider="qwen")

    messages = mock_connector.chat.call_args[0][0]
    text = messages[0]["content"][1]["text"]
    assert "Markdown" in text
