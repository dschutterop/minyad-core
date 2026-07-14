from __future__ import annotations

import re
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
    ROOT / "mobile-frontend" / "Dockerfile",
    ROOT / "reporting" / "Dockerfile",
]


def test_all_application_images_run_as_non_root() -> None:
    for dockerfile in DOCKERFILES:
        source = dockerfile.read_text()
        assert "useradd --uid 1000" in source, dockerfile
        assert "USER 1000:1000" in source, dockerfile
        assert source.index("USER 1000:1000") < source.index("CMD "), dockerfile


def test_compose_defaults_strategy_v2_primary_off() -> None:
    source = (ROOT / "docker-compose.yml").read_text()

    assert "STRATEGY_V2_PRIMARY: ${STRATEGY_V2_PRIMARY:-false}" in source


def test_open_meteo_callers_have_outbound_network_access() -> None:
    source = (ROOT / "docker-compose.yml").read_text()

    for service in ("minyad-strategy", "minyad-forecast"):
        match = re.search(rf"^  {service}:\n(?P<body>.*?)(?=^  [\\w-]+:|^networks:)", source, re.M | re.S)
        assert match is not None, service
        assert "networks: [minyad-internal, minyad-public]" in match.group("body"), service
