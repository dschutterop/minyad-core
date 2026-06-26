from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = [
    ROOT / "api" / "Dockerfile",
    ROOT / "control" / "Dockerfile",
    ROOT / "deadman" / "Dockerfile",
    ROOT / "forecast" / "Dockerfile",
    ROOT / "frontend" / "Dockerfile",
    ROOT / "ingestion" / "Dockerfile",
    ROOT / "migrate" / "Dockerfile",
    ROOT / "minyad-agent" / "Dockerfile",
    ROOT / "minyad-trade" / "Dockerfile",
    ROOT / "mobile-frontend" / "Dockerfile",
    ROOT / "reporting" / "Dockerfile",
]


def test_all_application_images_run_as_non_root() -> None:
    for dockerfile in DOCKERFILES:
        source = dockerfile.read_text()
        assert "useradd --uid 1000" in source, dockerfile
        assert "USER 1000:1000" in source, dockerfile
        assert source.index("USER 1000:1000") < source.index("CMD "), dockerfile
