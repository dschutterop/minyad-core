from pathlib import Path


def test_project_declares_required_services():
    compose = Path("docker-compose.yml").read_text()
    for service in ["minyad-ingest", "minyad-control", "minyad-forecast", "minyad-api", "minyad-dashboard"]:
        assert f"  {service}:" in compose


def test_application_services_wait_for_migrations_to_complete():
    compose = Path("docker-compose.yml").read_text()

    for service in ["minyad-ingest", "minyad-control", "minyad-forecast", "minyad-api"]:
        service_block = compose.split(f"  {service}:\n", 1)[1].split("\n  minyad-", 1)[0]
        assert "    depends_on:\n      minyad-migrate:\n        condition: service_completed_successfully" in service_block
