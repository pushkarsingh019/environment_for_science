"""Deterministic, display-oriented synthetic EEG evidence generation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any

from environments.eeg._domain import PreflightCase, SignalProfile

DISPLAY_SAMPLE_COUNT = 96
DISPLAY_SAMPLING_HZ = 64
FREQUENCY_BINS_HZ = (2.0, 6.0, 10.0, 18.0, 26.0)
SIGNAL_STAGE = "synthetic post-online-bandpass display window"


def build_eeg_window(
    case: PreflightCase,
    *,
    seed: int,
    procedure_configuration: Mapping[str, Any],
    state_revision: int,
    window_sequence: int,
    resolved: bool,
) -> dict[str, Any]:
    """Build one quantized display window indexed only by pinned logical inputs."""

    montage = _mapping(procedure_configuration.get("montage"), "Montage")
    recording_sites = _string_list(montage.get("recording_sites"), "recording sites")
    reference_site = _string(montage.get("reference"), "reference site")
    channel_sites = list(recording_sites)
    if case.optional_site is not None and case.optional_site not in channel_sites:
        channel_sites.append(case.optional_site)

    acquisition_profile = _mapping(
        procedure_configuration.get("acquisition_profile"),
        "acquisition profile",
    )
    sampling_hz = _integer(acquisition_profile.get("sampling_hz"), "sampling rate")
    online_bandpass_hz = _frequency_band(
        acquisition_profile.get("online_bandpass_hz"),
        "online bandpass",
    )
    profile = _visible_profile(case, resolved)
    if profile == "optional_noise" and case.optional_site in recording_sites:
        profile = "nominal"
    channels = [
        _channel_document(
            site,
            role="required" if site in recording_sites else "optional",
            samples=_samples(
                profile,
                site=site,
                target=case.target,
                seed=seed,
                display_sampling_hz=DISPLAY_SAMPLING_HZ,
                window_sequence=window_sequence,
                online_bandpass_hz=online_bandpass_hz,
            ),
        )
        for site in channel_sites
    ]
    return {
        "evidence_id": (
            f"eeg-{seed:x}-w{window_sequence:03d}-r{state_revision:03d}"
        ),
        "status": "current",
        "signal_stage": SIGNAL_STAGE,
        "source_sampling_hz": sampling_hz,
        "display_sampling_hz": DISPLAY_SAMPLING_HZ,
        "display_duration_seconds": DISPLAY_SAMPLE_COUNT / DISPLAY_SAMPLING_HZ,
        "window_start_sample": round(
            (window_sequence - 1)
            * (DISPLAY_SAMPLE_COUNT / DISPLAY_SAMPLING_HZ)
            * sampling_hz
        ),
        "display_sample_count": DISPLAY_SAMPLE_COUNT,
        "display_representation": (
            "Synthetic downsampled display window; acquisition metadata remains "
            f"{sampling_hz} Hz."
        ),
        "channels": channels,
        "reference_comparison": {
            "site": reference_site,
            "samples": _reference_samples(
                profile,
                seed=seed,
                display_sampling_hz=DISPLAY_SAMPLING_HZ,
                window_sequence=window_sequence,
                online_bandpass_hz=online_bandpass_hz,
            ),
        },
        "measurement_note": (
            "Synthetic display samples support comparative inspection; no universal "
            "readiness threshold is implied."
        ),
    }


def build_frequency_evidence(
    eeg_window: Mapping[str, Any],
) -> dict[str, Any]:
    """Measure fixed frequency bins from the exact displayed channel samples."""

    display_sampling_hz = _integer(
        eeg_window.get("display_sampling_hz"), "display sampling rate"
    )
    raw_channels = eeg_window.get("channels")
    if not isinstance(raw_channels, Sequence) or isinstance(
        raw_channels, (str, bytes, bytearray)
    ):
        raise ValueError("EEG channels must be a sequence")

    channel_samples: list[tuple[str, list[float]]] = []
    frequency_channels: list[dict[str, Any]] = []
    for raw_channel in raw_channels:
        channel = _mapping(raw_channel, "EEG channel")
        site = _string(channel.get("site"), "channel site")
        samples = _number_list(channel.get("samples"), "channel samples")
        channel_samples.append((site, samples))
        frequency_channels.append(
            {
                "site": site,
                "magnitudes": [
                    _rounded(
                        _dft_magnitude(samples, display_sampling_hz, frequency_hz)
                    )
                    for frequency_hz in FREQUENCY_BINS_HZ
                ],
            }
        )

    reference_comparison = _mapping(
        eeg_window.get("reference_comparison"),
        "reference comparison",
    )
    reference_site = _string(reference_comparison.get("site"), "reference site")
    reference_samples = _number_list(
        reference_comparison.get("samples"),
        "reference comparison samples",
    )
    return {
        "source_window_id": _string(eeg_window.get("evidence_id"), "evidence id"),
        "status": _string(eeg_window.get("status"), "evidence status"),
        "signal_stage": _string(eeg_window.get("signal_stage"), "signal stage"),
        "bins_hz": list(FREQUENCY_BINS_HZ),
        "channels": frequency_channels,
        "reference_comparison": {
            "site": reference_site,
            "magnitudes": [
                _rounded(
                    _dft_magnitude(
                        reference_samples,
                        display_sampling_hz,
                        frequency_hz,
                    )
                )
                for frequency_hz in FREQUENCY_BINS_HZ
            ],
        },
        "relationships": {
            "mean_absolute_pairwise_waveform_correlation": _rounded(
                _mean_pairwise_correlation([samples for _, samples in channel_samples])
            ),
            "mean_absolute_reference_waveform_correlation": _rounded(
                _mean_reference_correlation(
                    [samples for _, samples in channel_samples],
                    reference_samples,
                )
            ),
        },
        "measurement_note": (
            "Magnitudes and relationships are derived from the displayed channel and "
            "reference-comparison samples; they do not name a cause."
        ),
    }


def _visible_profile(case: PreflightCase, resolved: bool) -> SignalProfile:
    if not resolved:
        return case.signal_profile
    if case.signal_profile in {"quiet_dynamic", "optional_noise"}:
        return case.signal_profile
    return "nominal"


def _samples(
    profile: SignalProfile,
    *,
    site: str,
    target: str | None,
    seed: int,
    display_sampling_hz: int,
    window_sequence: int,
    online_bandpass_hz: tuple[float, float],
) -> list[float]:
    phase = _unit(seed, site, "phase") * math.tau
    sequence_phase = (window_sequence - 1) * 0.173
    values: list[float] = []
    for sample_index in range(DISPLAY_SAMPLE_COUNT):
        time_seconds = (
            (window_sequence - 1) * DISPLAY_SAMPLE_COUNT + sample_index
        ) / display_sampling_hz
        baseline = (
            _band_limited_sine(
                8.0,
                10.0,
                time_seconds,
                phase + sequence_phase,
                online_bandpass_hz,
            )
            + _band_limited_sine(
                3.5,
                6.0,
                time_seconds,
                phase * 0.43,
                online_bandpass_hz,
            )
            + 1.2 * _signed(seed, site, window_sequence, sample_index)
        )
        value = _profile_value(
            profile,
            baseline=baseline,
            site=site,
            target=target,
            seed=seed,
            sample_index=sample_index,
            time_seconds=time_seconds,
            online_bandpass_hz=online_bandpass_hz,
        )
        values.append(_rounded(value))
    return values


def _profile_value(
    profile: SignalProfile,
    *,
    baseline: float,
    site: str,
    target: str | None,
    seed: int,
    sample_index: int,
    time_seconds: float,
    online_bandpass_hz: tuple[float, float],
) -> float:
    targeted = site == target
    if profile == "quiet_dynamic":
        return baseline * 0.22
    if profile == "local_noise" and targeted:
        return (
            baseline
            + _band_limited_sine(
                34.0,
                18.0,
                time_seconds,
                0.4,
                online_bandpass_hz,
            )
            + 13.0 * _signed(seed, site, "local", sample_index)
        )
    if profile == "intermittent" and targeted:
        if 18 <= sample_index < 34 or 63 <= sample_index < 75:
            return 0.15 * _signed(seed, site, "dropout", sample_index)
        return baseline + 20.0 * _signed(seed, site, "unstable", sample_index)
    if profile == "flat" and targeted:
        return 0.2
    if profile == "clipped" and targeted:
        return max(-24.0, min(24.0, baseline * 5.2))
    if profile == "reference_shared":
        return baseline + _reference_component(time_seconds, online_bandpass_hz)
    if profile == "ground_shared":
        slow_displacement = _band_limited_sine(
            30.0,
            2.0,
            time_seconds,
            0.7,
            online_bandpass_hz,
        )
        if _frequency_is_visible(2.0, online_bandpass_hz):
            slow_displacement += (sample_index - DISPLAY_SAMPLE_COUNT / 2) * 0.32
        return baseline + slow_displacement
    if profile == "environment_shared":
        return baseline + _band_limited_sine(
            31.0,
            26.0,
            time_seconds,
            0.2,
            online_bandpass_hz,
        )
    if profile == "participant_activity":
        scale = 31.0 if site in {"FC3", "FC4"} else 13.0
        envelope = 0.65 + _band_limited_sine(
            0.35,
            2.0,
            time_seconds,
            0.0,
            online_bandpass_hz,
        )
        return baseline + envelope * _band_limited_sine(
            scale,
            26.0,
            time_seconds,
            0.1,
            online_bandpass_hz,
        )
    if profile == "optional_noise" and targeted:
        return baseline + _band_limited_sine(
            38.0,
            18.0,
            time_seconds,
            0.8,
            online_bandpass_hz,
        )
    return baseline


def _reference_samples(
    profile: SignalProfile,
    *,
    seed: int,
    display_sampling_hz: int,
    window_sequence: int,
    online_bandpass_hz: tuple[float, float],
) -> list[float]:
    values: list[float] = []
    phase = _unit(seed, "FCz", "reference") * math.tau
    for sample_index in range(DISPLAY_SAMPLE_COUNT):
        time_seconds = (
            (window_sequence - 1) * DISPLAY_SAMPLE_COUNT + sample_index
        ) / display_sampling_hz
        baseline = _band_limited_sine(
            4.0,
            10.0,
            time_seconds,
            phase,
            online_bandpass_hz,
        )
        if profile == "reference_shared":
            baseline += _reference_component(time_seconds, online_bandpass_hz)
        elif profile == "ground_shared":
            baseline += _band_limited_sine(
                14.0,
                2.0,
                time_seconds,
                0.7,
                online_bandpass_hz,
            )
        values.append(_rounded(baseline))
    return values


def _reference_component(
    time_seconds: float,
    online_bandpass_hz: tuple[float, float],
) -> float:
    return _band_limited_sine(
        24.0,
        6.0,
        time_seconds,
        0.3,
        online_bandpass_hz,
    ) + _band_limited_sine(
        15.0,
        18.0,
        time_seconds,
        0.1,
        online_bandpass_hz,
    )


def _band_limited_sine(
    amplitude: float,
    frequency_hz: float,
    time_seconds: float,
    phase: float,
    online_bandpass_hz: tuple[float, float],
) -> float:
    if not _frequency_is_visible(frequency_hz, online_bandpass_hz):
        return 0.0
    return amplitude * math.sin(math.tau * frequency_hz * time_seconds + phase)


def _frequency_is_visible(
    frequency_hz: float,
    online_bandpass_hz: tuple[float, float],
) -> bool:
    low_hz, high_hz = online_bandpass_hz
    return low_hz <= frequency_hz <= high_hz


def _channel_document(site: str, *, role: str, samples: list[float]) -> dict[str, Any]:
    minimum = min(samples)
    maximum = max(samples)
    rail = max(abs(minimum), abs(maximum))
    rail_count = sum(abs(abs(value) - rail) < 1e-9 for value in samples)
    near_zero_count = sum(abs(value) < 0.5 for value in samples)
    return {
        "site": site,
        "role": role,
        "samples": samples,
        "measurements": {
            "range_uv": _rounded(maximum - minimum),
            "unique_value_count": len(set(samples)),
            "rail_fraction": _rounded(rail_count / len(samples)),
            "near_zero_fraction": _rounded(near_zero_count / len(samples)),
        },
    }


def _dft_magnitude(samples: Sequence[float], sampling_hz: int, frequency_hz: float) -> float:
    real = 0.0
    imaginary = 0.0
    for index, value in enumerate(samples):
        angle = math.tau * frequency_hz * index / sampling_hz
        real += value * math.cos(angle)
        imaginary -= value * math.sin(angle)
    return 2.0 * math.hypot(real, imaginary) / len(samples)


def _mean_pairwise_correlation(channels: Sequence[Sequence[float]]) -> float:
    correlations = [
        abs(_correlation(left, right))
        for left_index, left in enumerate(channels)
        for right in channels[left_index + 1 :]
    ]
    return sum(correlations) / len(correlations) if correlations else 1.0


def _mean_reference_correlation(
    channels: Sequence[Sequence[float]], reference: Sequence[float]
) -> float:
    correlations = [abs(_correlation(channel, reference)) for channel in channels]
    return sum(correlations) / len(correlations) if correlations else 0.0


def _correlation(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    denominator = left_scale * right_scale
    return numerator / denominator if denominator > 0 else 0.0


def _unit(*parts: object) -> float:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    integer = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
    return integer / float(2**64 - 1)


def _signed(*parts: object) -> float:
    return _unit(*parts) * 2.0 - 1.0


def _rounded(value: float) -> float:
    return round(float(value), 3)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _frequency_band(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise ValueError(f"{label} must contain two frequencies")
    values = list(value)
    if len(values) != 2 or any(
        isinstance(item, bool) or not isinstance(item, (int, float))
        for item in values
    ):
        raise ValueError(f"{label} must contain two numeric frequencies")
    low_hz, high_hz = (float(item) for item in values)
    if low_hz < 0 or high_hz <= low_hz:
        raise ValueError(f"{label} must be an increasing non-negative frequency pair")
    return low_hz, high_hz


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"{label} must be a non-empty string list")
    return list(value)


def _number_list(value: object, label: str) -> list[float]:
    if not isinstance(value, list) or not value or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in value
    ):
        raise ValueError(f"{label} must be a non-empty numeric list")
    return [float(item) for item in value]
