"""Documented one-command startup prerequisite reporting."""

from studio.__main__ import (
    console_startup_commands,
    external_prerequisite_summary,
)


def test_clean_checkout_installs_locked_console_dependencies_before_build() -> None:
    assert console_startup_commands(node_modules_present=False) == (
        ("npm", "ci", "--ignore-scripts"),
        ("npm", "run", "build"),
    )
    assert console_startup_commands(node_modules_present=True) == (
        ("npm", "run", "build"),
    )


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
