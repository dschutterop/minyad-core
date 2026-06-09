from pathlib import Path


def test_project_declares_required_services():
    compose = Path("docker-compose.yml").read_text()
    for service in ["minyad-ingest", "minyad-control", "minyad-forecast", "minyad-api", "minyad-dashboard"]:
        assert f"  {service}:" in compose
