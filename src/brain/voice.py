from pathlib import Path

VOICE_GUIDE_PATH = Path("data/voice_guide.md")
VOICE_GUIDE_EXAMPLE_PATH = Path("data/voice_guide.example.md")


def load_voice_guide(path: Path = VOICE_GUIDE_PATH) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    if VOICE_GUIDE_EXAMPLE_PATH.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy data/voice_guide.example.md to data/voice_guide.md "
            "and fill in your own voice guide before running the agent."
        )
    raise FileNotFoundError(
        f"{path} not found and no example file exists. "
        "See data/voice_guide.example.md in the repository."
    )
