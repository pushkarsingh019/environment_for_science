"""Documented one-command startup prerequisite reporting."""

from studio.__main__ import external_prerequisite_summary


def test_startup_reports_optional_credentials_without_values() -> None:
    secret = "never-print-this-provider-secret"

    configured = external_prerequisite_summary(
        {"OPENAI_API_KEY": secret, "GEMINI_API_KEY": ""}
    )
    offline = external_prerequisite_summary({})

    assert configured == (
        "OpenAI hosted reference: configured",
        "Gemini hosted reference: missing (offline fixture available)",
        "Gemma compute: approved GPU workstations only; no local model compute",
    )
    assert offline[0].endswith("missing (offline fixture available)")
    assert secret not in "\n".join(configured)
