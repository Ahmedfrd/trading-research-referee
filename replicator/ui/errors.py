"""Short messages for the app. The main panel does not show tracebacks."""
from __future__ import annotations


def user_message(exc: BaseException) -> str:
    """One plain sentence for a failure the user can act on."""
    name = type(exc).__name__
    text = " ".join(str(exc).split())
    if name == "Unsupported":
        return text or "This strategy family cannot be generated."
    if name in {"LLMError", "Paused"}:
        return text or "The model step did not finish."
    if name == "FileNotFoundError":
        return "That file is not on disk. Upload the PDF from the Library tab."
    if "Traceback" in text or len(text) > 500:
        return f"The step did not finish ({name}). Check the paper, the spec, and the local data files."
    if not text:
        return f"The step did not finish ({name})."
    return text
