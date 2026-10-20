"""Application-recorded service coverage, separate from model conclusions."""

SERVICES = {
    "grafana": "Grafana",
    "configdb": "ConfigDB",
    "daq_state": "Live DAQ state",
    "diagnostic_history": "GitHub issues / shared diagnostic store",
}


def unavailable_services() -> dict:
    """Current report workflows have no adapters for these evidence sources."""
    return {name: {"queried": False, "status": "unavailable"} for name in SERVICES}


def service_coverage_rows(manifest: dict) -> list[tuple[str, str]]:
    """Do not retroactively invent coverage metadata for saved reports."""
    records = manifest.get("service_coverage", {})
    rows = []
    for name, label in SERVICES.items():
        record = records.get(name, manifest.get("grafana", {}) if name == "grafana" else {})
        if record.get("queried") is False:
            status = "not queried"
            if record.get("status") in {"unavailable", "not_configured"}:
                status += " — integration unavailable in this workflow"
            status += "."
        else:
            status = "Query coverage not recorded or not recognized in this report."
        rows.append((label, status))
    return rows
