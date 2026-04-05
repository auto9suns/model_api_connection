"""
gemini_uploader.py - Upload video to Gemini File API and wait until ACTIVE.

Usage:
    from gemini_uploader import upload_video
    uri = upload_video("video.mp4", api_key="AIza...")
"""
import time

try:
    import google.generativeai as genai
except ImportError:
    genai = None


def upload_video(video_path: str, api_key: str) -> str:
    """
    Upload a video file to Gemini File API.
    Polls until processing is complete, then returns the file URI.

    Parameters
    ----------
    video_path : str
        Local path to the video file.
    api_key : str
        Gemini API key (GEMINI_API_KEY).

    Returns
    -------
    str
        The file URI, e.g. "https://generativelanguage.googleapis.com/v1beta/files/..."
    """
    if genai is None:
        raise ImportError(
            "google-generativeai not installed. Run: pip install google-generativeai"
        )

    genai.configure(api_key=api_key)
    print(f"Uploading to Gemini File API: {video_path}")

    video_file = genai.upload_file(path=video_path)
    print(f"Upload started: {video_file.name}, waiting for processing...")

    while video_file.state.name == "PROCESSING":
        time.sleep(3)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name != "ACTIVE":
        raise RuntimeError(
            f"Gemini file processing failed: state={video_file.state.name}"
        )

    print(f"Ready: {video_file.uri}")
    return video_file.uri
