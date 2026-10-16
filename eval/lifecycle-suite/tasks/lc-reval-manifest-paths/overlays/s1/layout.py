from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent
