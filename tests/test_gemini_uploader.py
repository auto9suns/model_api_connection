"""Unit tests for gemini_uploader — no real API calls."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def fake_video(tmp_path):
    v = tmp_path / "test.mp4"
    v.write_bytes(b"fake video content")
    return str(v)


def _make_mock_genai(state="ACTIVE"):
    mock_file = MagicMock()
    mock_file.name = "files/abc123"
    mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/abc123"
    mock_file.state.name = state

    mock_genai = MagicMock()
    mock_genai.upload_file.return_value = mock_file
    mock_genai.get_file.return_value = mock_file
    return mock_genai, mock_file


def test_upload_video_returns_uri(fake_video):
    mock_genai, _ = _make_mock_genai("ACTIVE")

    with patch("gemini_uploader.genai", mock_genai):
        from gemini_uploader import upload_video
        uri = upload_video(fake_video, "fake-api-key")

    assert uri == "https://generativelanguage.googleapis.com/v1beta/files/abc123"
    mock_genai.configure.assert_called_once_with(api_key="fake-api-key")
    mock_genai.upload_file.assert_called_once_with(path=fake_video)


def test_upload_video_polls_while_processing(fake_video):
    mock_file_processing = MagicMock()
    mock_file_processing.name = "files/xyz"
    mock_file_processing.state.name = "PROCESSING"

    mock_file_active = MagicMock()
    mock_file_active.name = "files/xyz"
    mock_file_active.uri = "https://example.com/files/xyz"
    mock_file_active.state.name = "ACTIVE"

    mock_genai = MagicMock()
    mock_genai.upload_file.return_value = mock_file_processing
    mock_genai.get_file.return_value = mock_file_active

    with patch("gemini_uploader.genai", mock_genai), \
         patch("gemini_uploader.time.sleep"):
        from gemini_uploader import upload_video
        uri = upload_video(fake_video, "key")

    mock_genai.get_file.assert_called_once_with("files/xyz")
    assert uri == "https://example.com/files/xyz"


def test_upload_video_raises_on_failed_state(fake_video):
    mock_genai, mock_file = _make_mock_genai("FAILED")

    with patch("gemini_uploader.genai", mock_genai):
        from gemini_uploader import upload_video
        with pytest.raises(RuntimeError, match="failed"):
            upload_video(fake_video, "key")
