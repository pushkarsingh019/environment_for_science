"""One strict transport-material boundary for evaluation artifacts.

The compiler and durable repository intentionally apply the same policy.  The
scanner recognizes transport coordinates and credential-shaped material, not
scientific vocabulary: public model/DOI/scenario identifiers and token counts
remain ordinary content.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping

_CREDENTIAL_KEY_ALIASES = {
    "accesstoken",
    "apikey",
    "apikeyvar",
    "auth",
    "authentication",
    "authorization",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "credential",
    "credentials",
    "githubpat",
    "hfpat",
    "huggingfacepat",
    "password",
    "passwd",
    "privatekey",
    "refreshtoken",
    "sessiontoken",
    "secret",
    "secretkey",
    "token",
}
_TRANSPORT_KEY_ALIASES = {
    "baseurl",
    "connectionstring",
    "endpoint",
    "host",
    "hostname",
    "privatehost",
    "proxyurl",
}
_SENSITIVE_KEY_SUFFIXES = (
    "accesstoken",
    "apikey",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "credential",
    "credentials",
    "password",
    "privatekey",
    "refreshtoken",
    "secretkey",
    "token",
)
_TRANSPORT_KEY_SUFFIXES = ("baseurl", "endpoint", "hostname", "privatehost")
_TRANSPORT_KEY_SEGMENT_SUFFIXES = {"host"}
_URL_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9+.-])[a-z][a-z0-9+.-]{1,31}://")
_FILE_URL_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9+.-])file:/")
_PRIVATE_DNS_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9-])"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:internal|lan|local|localdomain|localhost)"
    r"(?=$|[^A-Za-z0-9-])"
)
_RESERVED_DNS_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9-])"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"(?:example|invalid|test|onion)"
    r"(?=$|[^A-Za-z0-9-])"
)
_LOCALHOST_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9-])localhost(?:\.localdomain)?(?=$|[^A-Za-z0-9-])"
)
_SINGLE_LABEL_HOST_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9-]{1,62}:[0-9]{1,5}(?:/[^\s]*)?$"
)
_IPV4_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![A-Za-z0-9])")
_BRACKETED_IP_PATTERN = re.compile(r"\[[0-9A-Fa-f:.%]+\]")
_IPV6_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[0-9A-Fa-f]{0,4}:){2,}[0-9A-Fa-f:.%]{0,45}(?![A-Za-z0-9])"
)
_WINDOWS_DRIVE_PATTERN = re.compile(r"(?i)(?:^|[\s('\"=])[A-Z]:[\\/]")
_UNC_PATTERN = re.compile(r"(?:^|[\s('\"=])\\\\[^\\\s]+\\")
_HOST_PATH_PATTERN = re.compile(
    r"(?i)(?:^|[\s('\"=])/(?:users|home|srv|var|tmp|private|opt|etc|root)(?:/|$)"
)
_HOME_PATH_PATTERN = re.compile(r"(?:^|[\s('\"=])~[/\\]")
_HOME_VARIABLE_PATTERN = re.compile(
    r"(?i)(?:\$\{?(?:HOME|USERPROFILE)\}?|%(?:HOME|USERPROFILE)%)[/\\]"
)
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|auth[_-]?token|"
    r"bearer[_-]?token|client[_-]?secret|id[_-]?token|oauth[_-]?token|password|"
    r"private[_-]?key|secret|session[_-]?token|(?:[a-z0-9]+[_-])+token|token)"
    r"\s*['\"]?\s*[:=]\s*['\"]?\S+"
)
_BEARER_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9])bearer\s+\S+")
_CREDENTIAL_SIGNATURE_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"gh[pousr]_[A-Za-z0-9]{20,255}|"
    r"github_pat_[A-Za-z0-9_]{20,255}|"
    r"hf_[A-Za-z0-9]{20,255}|"
    r"sk-[A-Za-z0-9_-]{20,255}"
    r")(?![A-Za-z0-9])"
)
_CONTEXTUAL_SINGLE_LABEL_HOST_PATTERN = re.compile(
    r"(?i)\b(?:"
    r"(?:adapter|client|runtime|server)\s+(?:connection\s+)?(?:failed\s+)?(?:at|to|on)\b|"
    r"connection\s+failed\s+(?:at|to)\b|"
    r"connect(?:ed|ing)?\s+(?:at|to)\b"
    r")\s*['\"]?"
    r"(?=[A-Za-z0-9-]{2,63}\b)(?=[A-Za-z0-9-]*(?:-|[0-9]))"
    r"[A-Za-z][A-Za-z0-9-]{1,62}\b|"
    r"\b(?:host(?:name)?|server)\s*[:=]\s*['\"]?"
    r"[A-Za-z][A-Za-z0-9-]{1,62}\b"
)


class ArtifactSafetyError(ValueError):
    """Raised without echoing the unsafe artifact value."""


def validate_artifact_safe(value: object, *, key: str = "") -> None:
    """Reject credential, endpoint, private-host, and host-path material.

    Values are expected to be JSON-like, but tuples are accepted because typed
    in-memory evaluation records use them before JSON serialization.
    """

    if key and _sensitive_key(key):
        raise ArtifactSafetyError("evaluation artifact contains transport material")
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            validate_artifact_safe(child, key=str(child_key))
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            validate_artifact_safe(child, key=key)
        return
    if not isinstance(value, str):
        return
    if _contains_transport_material(value):
        raise ArtifactSafetyError("evaluation artifact contains transport material")


def contains_exact_material(value: object, forbidden: tuple[str, ...]) -> bool:
    """Return whether a JSON-like value contains evaluator-supplied private text."""

    if isinstance(value, Mapping):
        return any(
            contains_exact_material(str(child_key), forbidden)
            or contains_exact_material(child, forbidden)
            for child_key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_exact_material(child, forbidden) for child in value)
    if not isinstance(value, str):
        return False
    return any(material and material in value for material in forbidden)


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    segmented = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    segments = tuple(
        segment
        for segment in re.split(r"[^a-z0-9]+", segmented.casefold())
        if segment
    )
    return bool(
        normalized in _CREDENTIAL_KEY_ALIASES
        or normalized in _TRANSPORT_KEY_ALIASES
        or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)
        or normalized.endswith(_TRANSPORT_KEY_SUFFIXES)
        or (segments and segments[-1] in _TRANSPORT_KEY_SEGMENT_SUFFIXES)
    )


def _contains_transport_material(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.casefold()
    if (
        _URL_PATTERN.search(value)
        or _FILE_URL_PATTERN.search(value)
        or _PRIVATE_DNS_PATTERN.search(value)
        or _RESERVED_DNS_PATTERN.search(value)
        or _LOCALHOST_PATTERN.search(value)
        or _SINGLE_LABEL_HOST_PATTERN.fullmatch(stripped)
        or _CONTEXTUAL_SINGLE_LABEL_HOST_PATTERN.search(value)
        or _WINDOWS_DRIVE_PATTERN.search(value)
        or _UNC_PATTERN.search(value)
        or _HOST_PATH_PATTERN.search(value)
        or _HOME_PATH_PATTERN.search(value)
        or _HOME_VARIABLE_PATTERN.search(value)
        or _CREDENTIAL_ASSIGNMENT_PATTERN.search(value)
        or _BEARER_PATTERN.search(value)
        or _CREDENTIAL_SIGNATURE_PATTERN.search(value)
        or lowered.startswith(("/", "\\\\"))
    ):
        return True
    return any(not address.is_global for address in _ip_addresses(value))


def _ip_addresses(value: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    candidates = [match.group(0) for match in _IPV4_PATTERN.finditer(value)]
    candidates.extend(match.group(0).strip("[]") for match in _BRACKETED_IP_PATTERN.finditer(value))
    candidates.extend(match.group(0) for match in _IPV6_PATTERN.finditer(value))
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for candidate in candidates:
        without_zone = candidate.split("%", 1)[0]
        try:
            address = ipaddress.ip_address(without_zone)
        except ValueError:
            continue
        if address not in addresses:
            addresses.append(address)
    return tuple(addresses)


__all__ = [
    "ArtifactSafetyError",
    "contains_exact_material",
    "validate_artifact_safe",
]
