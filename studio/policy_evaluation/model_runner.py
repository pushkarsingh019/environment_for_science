"""Provider-neutral multi-turn model loop over the scientific Runtime bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast

from jsonschema import Draft202012Validator
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from studio.bundle import EnvironmentBundle
from studio.runtime import (
    EnvironmentAction,
    PolicyAgentIdentity,
    RunSnapshot,
    RuntimeContractError,
    TraceEvent,
    validate_completed_run_snapshot,
)

from .runtime_bridge import (
    CanonicalActionExecution,
    CanonicalCallConflictError,
    EvaluationRuntimeBridge,
    ReplayableRuntimeState,
)
from .runtime_dependencies import (
    APPROVED_RUNTIME_PYTHON,
    ApprovedPythonRuntime,
    VerifiedRuntimeDistribution,
    require_approved_runtime_distribution_receipt,
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]{0,511}$")
_IP_ENDPOINT = re.compile(r"^[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?::[0-9]+)?(?:/|$)")
ModelProviderKind = Literal["local-openai-compatible", "openai-responses", "gemini-interactions"]
EvaluationProfile = Literal[
    "base-gemma-development-v1",
    "hosted-reference-smoke-v1",
]

BASE_GEMMA_MODEL = "google/gemma-4-E4B-it"
BASE_GEMMA_CHECKPOINT_REVISION = "ee0ef6023621cff504d758262d4e04895a5af4a2"
BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256 = (
    "cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503"
)
BASE_GEMMA_TOKENIZER_MANIFEST_SHA256 = (
    "88f73edddd41b7417ff93e3e410be277c9a138132013b13d9cdbdfcc42aec677"
)
BASE_GEMMA_RENDERER_REVISION = "f770dcaa362e3a6a13a96f039741b3b84ca4114e"
BASE_GEMMA_ADAPTER_REVISION = "local-gemma-openai-chat/1"
PINNED_VLLM_VERSION = "0.26.0+cu129"
PINNED_VLLM_SOURCE_REVISION = "568afb3a13806beb53bb2e6bd518269357b237c0"
PINNED_VLLM_WHEEL_SHA256 = "7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf"
MAX_PROVIDER_TOOL_CALLS: Literal[64] = 64


class ModelIdentity(_FrozenModel):
    """Stable requested-model identity, without endpoint or credential material."""

    provider: ModelProviderKind
    requested_model: str = Field(min_length=1, max_length=512)
    adapter_revision: str = Field(min_length=1, max_length=512)

    @field_validator("requested_model", "adapter_revision")
    @classmethod
    def reject_transport_material(cls, value: str) -> str:
        return _validated_safe_identifier(value)

    def policy_identity(self) -> PolicyAgentIdentity:
        return PolicyAgentIdentity(
            id=f"{self.provider}:{self.requested_model}@{self.adapter_revision}",
            name=f"{self.requested_model} ({self.adapter_revision})",
        )


class ModelToolCall(_FrozenModel):
    """One provider call, canonically identified by the episode runner."""

    call_id: str = Field(min_length=1)
    provider_call_id: str | None = Field(default=None, min_length=1)
    ordinal: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]

    @field_validator("call_id", "provider_call_id", "name")
    @classmethod
    def reject_unsafe_call_identity(cls, value: str | None) -> str | None:
        return _validated_safe_identifier(value) if value is not None else None

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> ModelToolCall:
        if (self.provider_call_id is None) != (self.ordinal is None):
            raise ValueError("canonical calls require provider identity and ordinal")
        if self.ordinal is not None and self.call_id != _canonical_call_id(self.ordinal):
            raise ValueError("canonical call ID does not match its ordinal")
        return self


class ModelMessage(_FrozenModel):
    """Canonical conversation message retained across provider turns."""

    role: Literal["user", "assistant", "tool"]
    content: str | dict[str, Any]
    response_id: str | None = Field(default=None, min_length=1)
    response_turn: int | None = Field(default=None, ge=1)
    tool_calls: tuple[ModelToolCall, ...] = ()
    tool_call_id: str | None = Field(default=None, min_length=1)
    provider_tool_call_id: str | None = Field(default=None, min_length=1)
    tool_call_ordinal: int | None = Field(default=None, ge=1)
    tool_name: str | None = Field(default=None, min_length=1)
    provider_state: tuple[dict[str, Any], ...] = ()

    @field_validator(
        "response_id",
        "tool_call_id",
        "provider_tool_call_id",
        "tool_name",
    )
    @classmethod
    def reject_unsafe_tool_identity(cls, value: str | None) -> str | None:
        return _validated_safe_identifier(value) if value is not None else None

    @model_validator(mode="after")
    def validate_role_shape(self) -> ModelMessage:
        if self.role == "assistant":
            if (self.response_id is None) != (self.response_turn is None):
                raise ValueError("assistant response identity must be complete")
            if (
                self.tool_call_id is not None
                or self.provider_tool_call_id is not None
                or self.tool_call_ordinal is not None
                or self.tool_name is not None
            ):
                raise ValueError("assistant messages cannot identify a tool result")
            if not isinstance(self.content, str):
                raise ValueError("assistant message content must be text")
        elif self.role == "tool":
            if (
                self.response_id is not None
                or self.response_turn is not None
                or self.tool_call_id is None
                or self.provider_tool_call_id is None
                or self.tool_call_ordinal is None
                or self.tool_name is None
                or self.tool_calls
                or self.provider_state
            ):
                raise ValueError("tool messages require one result identity")
            if not isinstance(self.content, dict):
                raise ValueError("tool message content must be structured")
        elif (
            self.response_id is not None
            or self.response_turn is not None
            or self.tool_calls
            or self.tool_call_id is not None
            or self.provider_tool_call_id is not None
            or self.tool_call_ordinal is not None
            or self.tool_name is not None
            or self.provider_state
        ):
            raise ValueError("user messages cannot contain tool lineage")
        elif not isinstance(self.content, dict):
            raise ValueError("user message content must be structured")
        return self

    @classmethod
    def user(cls, content: dict[str, Any]) -> ModelMessage:
        return cls(role="user", content=deepcopy(content))

    @classmethod
    def assistant(
        cls,
        content: str,
        *,
        tool_calls: tuple[ModelToolCall, ...] = (),
        response_id: str | None = None,
        response_turn: int | None = None,
        provider_state: tuple[dict[str, Any], ...] = (),
    ) -> ModelMessage:
        return cls(
            role="assistant",
            content=content,
            response_id=response_id,
            response_turn=response_turn,
            tool_calls=tool_calls,
            provider_state=tuple(deepcopy(provider_state)),
        )

    @classmethod
    def tool(
        cls,
        content: dict[str, Any],
        *,
        call_id: str,
        provider_call_id: str | None = None,
        ordinal: int | None = None,
        name: str,
    ) -> ModelMessage:
        return cls(
            role="tool",
            content=deepcopy(content),
            tool_call_id=call_id,
            provider_tool_call_id=provider_call_id or call_id,
            tool_call_ordinal=ordinal or 1,
            tool_name=name,
        )


class ModelTool(_FrozenModel):
    """Policy-visible projection of one bundle-declared action."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]

    @field_validator("name")
    @classmethod
    def reject_unsafe_tool_identity(cls, value: str) -> str:
        return _validated_safe_identifier(value)


class ModelSamplingSettings(_FrozenModel):
    """One explicit provider-appropriate sampling contract."""

    profile: Literal[
        "base-gemma-development-chat-v1",
        "hosted-reference-medium-v1",
    ] = "base-gemma-development-chat-v1"
    temperature: float | None = 0.0
    max_output_tokens: int = 2048
    tool_choice: Literal["auto"] = "auto"
    top_p: None = None
    seed: None = None
    streaming: Literal[False] = False
    store: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_scored_profile(self) -> ModelSamplingSettings:
        valid_temperature = (
            self.profile == "base-gemma-development-chat-v1"
            and self.temperature == 0.0
            or self.profile == "hosted-reference-medium-v1"
            and self.temperature is None
        )
        if not valid_temperature or self.max_output_tokens != 2048:
            raise ValueError("sampling settings do not match the approved scored profile")
        return self


class EvaluationBudgets(_FrozenModel):
    """External episode limits, separate from provider output limits."""

    max_turns: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    max_provider_tool_calls: Literal[64] = MAX_PROVIDER_TOOL_CALLS
    max_episode_seconds: Literal[900] = 900


class ModelPreflightRequest(_FrozenModel):
    """Endpoint-private challenge inputs for one scored run."""

    model: ModelIdentity
    profile: EvaluationProfile
    sampling: ModelSamplingSettings
    budgets: EvaluationBudgets
    transport_timeout_seconds: float = Field(default=900.0, gt=0.0, le=900.0)


class ModelRequest(_FrozenModel):
    """Complete stateless request at the provider boundary."""

    model: ModelIdentity
    turn: int = Field(ge=1)
    messages: tuple[ModelMessage, ...]
    tools: tuple[ModelTool, ...]
    sampling: ModelSamplingSettings = Field(default_factory=ModelSamplingSettings)
    budgets: EvaluationBudgets = Field(
        default_factory=lambda: EvaluationBudgets(
            max_turns=64,
            max_tool_calls=64,
        )
    )
    transport_timeout_seconds: float = Field(default=900.0, gt=0.0, le=900.0)

    @model_validator(mode="after")
    def validate_turn_budget(self) -> ModelRequest:
        if self.turn > self.budgets.max_turns:
            raise ValueError("model request turn exceeds its declared budget")
        return self


class TokenUsage(_FrozenModel):
    """Optional provider-reported accounting; absent values stay absent."""

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class ModelResponseMetadata(_FrozenModel):
    """Safe provider response timing and build metadata."""

    created_unix_seconds: int = Field(ge=0)
    finish_reason: Literal["stop", "tool_calls", "length"]
    system_fingerprint: str | None = Field(default=None, min_length=1, max_length=512)
    runtime_instance_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=512)
    service_tier: str | None = Field(default=None, min_length=1, max_length=512)
    provider_usage: dict[str, Any] | None = None

    @field_validator("system_fingerprint", "provider_request_id", "service_tier")
    @classmethod
    def reject_transport_fingerprint(cls, value: str | None) -> str | None:
        return _validated_safe_identifier(value) if value is not None else None


class ModelResponse(_FrozenModel):
    """Provider-normalized assistant response for one turn."""

    response_id: str = Field(min_length=1, max_length=512)
    returned_model: str = Field(min_length=1, max_length=512)
    message: ModelMessage
    usage: TokenUsage | None = None
    metadata: ModelResponseMetadata | None = None

    @field_validator("response_id", "returned_model")
    @classmethod
    def reject_transport_material(cls, value: str) -> str:
        return _validated_safe_identifier(value)

    @model_validator(mode="after")
    def require_assistant_message(self) -> ModelResponse:
        if self.message.role != "assistant":
            raise ValueError("a model response must contain an assistant message")
        return self


class MultimodalPromptLimits(_FrozenModel):
    """Text-only Gemma serving limits asserted by the inference process."""

    image: int = Field(ge=0)
    audio: int = Field(ge=0)
    video: int = Field(ge=0)

    @model_validator(mode="after")
    def require_text_only(self) -> MultimodalPromptLimits:
        if self.image != 0 or self.audio != 0 or self.video != 0:
            raise ValueError("the approved evaluation profile is text-only")
        return self


class VllmRuntimeConfig(_FrozenModel):
    """Critical server-owned vLLM configuration attested before inference."""

    dtype: Literal["bfloat16"]
    max_model_len: int = Field(ge=2048)
    tensor_parallel_size: int = Field(ge=1)
    gpu_memory_utilization: float = Field(gt=0.0, le=1.0)
    enforce_eager: Literal[True]
    max_num_seqs: int = Field(ge=1)
    generation_config: Literal["vllm"]
    tool_call_parser: Literal["gemma4"]
    enable_auto_tool_choice: Literal[True]
    enable_lora: Literal[False]
    disable_log_requests: Literal[True]
    limit_mm_per_prompt: MultimodalPromptLimits

    @model_validator(mode="after")
    def require_approved_base_calibration(self) -> VllmRuntimeConfig:
        if (
            self.max_model_len,
            self.tensor_parallel_size,
            self.gpu_memory_utilization,
            self.max_num_seqs,
        ) != (32768, 1, 0.35, 16):
            raise ValueError("vLLM settings do not match the approved base calibration")
        return self


class LocalGemmaServerEvidence(_FrozenModel):
    """Server-generated runtime claims authenticated by a fresh challenge."""

    attestation_version: Literal["science-local-gemma-runtime-attestation/1"]
    attestation_id: str = Field(min_length=1, max_length=512)
    runtime_instance_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    trusted_bootstrap_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    challenge_nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at_utc: datetime
    runtime_started_at_utc: datetime
    served_model: Literal["google/gemma-4-E4B-it"]
    checkpoint_revision: Literal["ee0ef6023621cff504d758262d4e04895a5af4a2"]
    checkpoint_weights_sha256: Literal[
        "cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503"
    ]
    tokenizer_revision: Literal["ee0ef6023621cff504d758262d4e04895a5af4a2"]
    tokenizer_manifest_sha256: Literal[
        "88f73edddd41b7417ff93e3e410be277c9a138132013b13d9cdbdfcc42aec677"
    ]
    renderer_revision: Literal["f770dcaa362e3a6a13a96f039741b3b84ca4114e"]
    vllm_version: Literal["0.26.0+cu129"]
    vllm_source_revision: Literal["568afb3a13806beb53bb2e6bd518269357b237c0"]
    vllm_wheel_sha256: Literal["7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf"]
    python_runtime: ApprovedPythonRuntime
    runtime_receipt_id: Literal["science-local-gemma-runtime-cp312-cu129/1"]
    runtime_distributions: tuple[VerifiedRuntimeDistribution, ...]
    product_distribution: VerifiedRuntimeDistribution
    python_bytecode_mode: Literal["fresh-private-prefix-no-write"]
    serving_root_filesystem_mode: Literal["kernel-read-only-mount"]
    network_scope: Literal["loopback-only"]
    api_key_authentication: Literal[True]
    attestation_middleware_revision: Literal["science-local-gemma-attestation-middleware/1"]
    vllm_config: VllmRuntimeConfig
    adapter_revision: Literal["local-gemma-openai-chat/1"]
    served_adapter: Literal["none"]
    sampling_profile: Literal["base-gemma-development-chat-v1"]
    max_episode_seconds: Literal[900]
    platform: Literal["linux-x86_64"]
    accelerator_architecture: str = Field(min_length=1, max_length=512)
    accelerator_count: int = Field(ge=1)
    cuda_version: str = Field(min_length=1, max_length=512)
    driver_version: str = Field(min_length=1, max_length=512)
    serving_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    serving_image_digest_provenance: Literal["operator-supplied"]
    evidence_scope: Literal["server-reported-runtime-state"]

    @field_validator(
        "attestation_id",
        "accelerator_architecture",
        "cuda_version",
        "driver_version",
    )
    @classmethod
    def reject_transport_metadata(cls, value: str) -> str:
        return _validated_safe_identifier(value)

    @field_validator("generated_at_utc", "runtime_started_at_utc")
    @classmethod
    def require_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("server attestation timestamps must be UTC")
        return value

    @model_validator(mode="after")
    def validate_runtime_order(self) -> LocalGemmaServerEvidence:
        if self.generated_at_utc < self.runtime_started_at_utc:
            raise ValueError("server attestation predates its runtime")
        if self.python_runtime != APPROVED_RUNTIME_PYTHON:
            raise ValueError("server attestation has an unapproved Python runtime")
        require_approved_runtime_distribution_receipt(self.runtime_distributions)
        if self.product_distribution.distribution != "science-environment-studio":
            raise ValueError("server attestation has an unverified product distribution")
        return self


class LocalGemmaRuntimeAttestation(LocalGemmaServerEvidence):
    """Authenticated server evidence safe to persist in an evaluation trace."""

    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    verification_method: Literal["hmac-sha256-server-challenge"]

    def signed_evidence_document(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={"signature", "evidence_digest", "verification_method"},
        )

    def verify_signature(self, attestation_key: str) -> bool:
        if len(attestation_key.encode("utf-8")) < 32:
            return False
        expected = hmac.new(
            attestation_key.encode("utf-8"),
            self._signed_evidence_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    @model_validator(mode="after")
    def validate_evidence_digest(self) -> LocalGemmaRuntimeAttestation:
        expected = (
            "sha256:" + hashlib.sha256(self._signed_evidence_json().encode("utf-8")).hexdigest()
        )
        if self.evidence_digest != expected:
            raise ValueError("attestation evidence digest does not match its fields")
        return self

    def _signed_evidence_json(self) -> str:
        return json.dumps(
            self.signed_evidence_document(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


class ModelRunMetadata(_FrozenModel):
    """Scored run window and any authenticated local serving evidence."""

    profile: EvaluationProfile
    started_at_utc: datetime
    completed_at_utc: datetime
    local_gemma_attestation: LocalGemmaRuntimeAttestation | None = None

    @field_validator("started_at_utc", "completed_at_utc")
    @classmethod
    def require_utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("run timestamps must be UTC")
        return value

    @model_validator(mode="after")
    def validate_run_window(self) -> ModelRunMetadata:
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("run completion predates its start")
        return self


class ModelProvider(Protocol):
    """Replaceable inference boundary used by local and hosted adapters."""

    def complete(self, request: ModelRequest) -> ModelResponse: ...


class ModelAttestationProvider(Protocol):
    """Optional server-evidence seam implemented by the real local provider."""

    def preflight(
        self,
        request: ModelPreflightRequest,
    ) -> LocalGemmaRuntimeAttestation: ...


class ModelResponseRecord(_FrozenModel):
    """Response identity and accounting retained outside message content."""

    turn: int = Field(ge=1)
    response_id: str = Field(min_length=1)
    returned_model: str = Field(min_length=1)
    usage: TokenUsage | None = None
    metadata: ModelResponseMetadata | None = None

    @field_validator("response_id", "returned_model")
    @classmethod
    def reject_transport_material(cls, value: str) -> str:
        return _validated_safe_identifier(value)


class ToolExecutionResult(_FrozenModel):
    """Structured public result for one attempted model tool call."""

    call_id: str = Field(min_length=1)
    provider_call_id: str = Field(min_length=1)
    ordinal: int = Field(ge=1)
    name: str = Field(min_length=1)
    status: Literal["ok", "error"]
    observation: dict[str, Any] | None = None
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    execution_id: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    cache_hit: bool | None = None
    retry_count: int | None = Field(default=None, ge=0)

    @field_validator("call_id", "provider_call_id", "name")
    @classmethod
    def reject_unsafe_tool_identity(cls, value: str) -> str:
        return _validated_safe_identifier(value)

    @model_validator(mode="after")
    def validate_result_shape(self) -> ToolExecutionResult:
        execution_fields = (self.execution_id, self.cache_hit, self.retry_count)
        if self.call_id != _canonical_call_id(self.ordinal):
            raise ValueError("tool result canonical ID does not match its ordinal")
        if self.status == "ok" and (
            self.observation is None
            or self.error_code is not None
            or any(value is None for value in execution_fields)
        ):
            raise ValueError("successful tool results require only an observation")
        if self.status == "error" and (
            self.observation is not None
            or self.error_code is None
            or any(value is not None for value in execution_fields)
        ):
            raise ValueError("failed tool results require only a safe error code")
        return self

    def policy_payload(self) -> dict[str, Any]:
        if self.status == "ok":
            return {"status": "ok", "observation": deepcopy(self.observation)}
        return {"status": "error", "error_code": self.error_code}


InfrastructureErrorCategory = Literal["adapter", "inference", "protocol"]
ProviderFailureCode = Literal[
    "adapter.invalid_response",
    "adapter.protocol_error",
    "adapter.unavailable",
    "inference.cancelled",
    "inference.overloaded",
    "inference.episode_timeout",
    "inference.timeout",
    "inference.unavailable",
]


class InfrastructureError(_FrozenModel):
    """Safe normalized non-scientific failure, never raw exception text."""

    category: InfrastructureErrorCategory
    code: str = Field(max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    summary: str = Field(min_length=1)


class ModelProviderFailure(Exception):
    """Explicit safe failure raised by a real provider adapter."""

    def __init__(
        self,
        *,
        category: Literal["adapter", "inference"],
        code: ProviderFailureCode,
    ) -> None:
        allowed_codes = {
            "adapter.invalid_response",
            "adapter.protocol_error",
            "adapter.unavailable",
            "inference.cancelled",
            "inference.overloaded",
            "inference.episode_timeout",
            "inference.timeout",
            "inference.unavailable",
        }
        if category not in {"adapter", "inference"} or code not in allowed_codes:
            raise ValueError("provider failure identity is not registered")
        if not code.startswith(f"{category}."):
            raise ValueError("provider failure codes must match their category")
        summary = (
            "The inference service failed."
            if category == "inference"
            else "The model adapter failed."
        )
        self.normalized_error = InfrastructureError(
            category=category,
            code=code,
            summary=summary,
        )
        super().__init__(code)


class CanonicalEvaluationTrace(_FrozenModel):
    """Canonical interaction evidence alongside, not inside, the Runtime digest."""

    trace_version: Literal["1.0"] = "1.0"
    model: ModelIdentity
    sampling: ModelSamplingSettings
    budgets: EvaluationBudgets
    run: ModelRunMetadata
    messages: tuple[ModelMessage, ...]
    responses: tuple[ModelResponseRecord, ...]
    tool_calls: tuple[ModelToolCall, ...]
    tool_results: tuple[ToolExecutionResult, ...]
    accepted_actions: tuple[EnvironmentAction, ...]
    runtime_executions: tuple[CanonicalActionExecution, ...]
    runtime_events: tuple[TraceEvent, ...]
    runtime_trace_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    infrastructure_error: InfrastructureError | None = None
    interaction_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_interaction_contract(self) -> CanonicalEvaluationTrace:
        if (
            not self.messages
            or self.messages[0].role != "user"
            or any(message.role == "user" for message in self.messages[1:])
        ):
            raise ValueError("canonical messages require exactly one initial user turn")
        assistant_messages: list[ModelMessage] = []
        cursor = 1
        while cursor < len(self.messages):
            assistant = self.messages[cursor]
            if assistant.role != "assistant":
                raise ValueError("canonical messages require ordered assistant response turns")
            if assistant.response_id is None or assistant.response_turn is None:
                raise ValueError("canonical assistant messages require response identity")
            assistant_messages.append(assistant)
            cursor += 1
            for call in assistant.tool_calls:
                if cursor >= len(self.messages):
                    raise ValueError("assistant calls require immediately linked tool messages")
                tool_message = self.messages[cursor]
                if (
                    tool_message.role != "tool"
                    or tool_message.tool_call_id != call.call_id
                    or tool_message.provider_tool_call_id != call.provider_call_id
                    or tool_message.tool_call_ordinal != call.ordinal
                    or tool_message.tool_name != call.name
                ):
                    raise ValueError("assistant calls require immediately linked tool messages")
                cursor += 1
        response_keys = tuple((response.turn, response.response_id) for response in self.responses)
        assistant_keys = tuple(
            (message.response_turn, message.response_id) for message in assistant_messages
        )
        if response_keys != assistant_keys or tuple(
            response.turn for response in self.responses
        ) != tuple(range(1, len(self.responses) + 1)):
            raise ValueError(
                "response records must correspond one-to-one with ordered assistant turns"
            )
        flattened_calls = tuple(
            call
            for message in self.messages
            if message.role == "assistant"
            for call in message.tool_calls
        )
        if flattened_calls != self.tool_calls:
            raise ValueError("assistant tool calls do not match canonical tool-call order")
        if any(call.provider_call_id is None or call.ordinal is None for call in self.tool_calls):
            raise ValueError("canonical tool calls require provider identity and ordinal")
        call_keys = [
            (call.call_id, call.provider_call_id, call.ordinal, call.name)
            for call in self.tool_calls
        ]
        if len({key[0] for key in call_keys}) != len(call_keys) or len(
            {key[2] for key in call_keys}
        ) != len(call_keys):
            raise ValueError("canonical tool-call identities must be unique")
        result_keys = [
            (
                result.call_id,
                result.provider_call_id,
                result.ordinal,
                result.name,
            )
            for result in self.tool_results
        ]
        message_keys = [
            (
                message.tool_call_id,
                message.provider_tool_call_id,
                message.tool_call_ordinal,
                message.tool_name,
            )
            for message in self.messages
            if message.role == "tool"
        ]
        if result_keys != call_keys or message_keys != call_keys:
            raise ValueError("every tool call requires one ordered call-linked result")
        tool_messages = tuple(message for message in self.messages if message.role == "tool")
        if any(
            message.content != result.policy_payload()
            for message, result in zip(tool_messages, self.tool_results)
        ):
            raise ValueError("tool messages do not match canonical execution results")
        successful = tuple(
            (call, result)
            for call, result in zip(self.tool_calls, self.tool_results)
            if result.status == "ok"
        )
        if len(successful) != len(self.runtime_executions):
            raise ValueError("successful tool results must match Runtime executions")
        for (call, result), execution in zip(successful, self.runtime_executions):
            if (
                call.call_id != execution.call_id
                or call.ordinal != execution.ordinal
                or EnvironmentAction(type=call.name, arguments=call.arguments) != execution.action
                or result.execution_id != execution.execution_id
                or result.observation != execution.observation
                or result.cache_hit != execution.cache_hit
                or result.retry_count != execution.retry_count
            ):
                raise ValueError("Runtime execution ledger does not match tool lineage")
        if self.accepted_actions != tuple(
            execution.action for execution in self.runtime_executions
        ):
            raise ValueError("accepted actions do not match Runtime execution ledger")
        if self.interaction_digest != _interaction_digest(
            model=self.model,
            sampling=self.sampling,
            budgets=self.budgets,
            run=self.run,
            messages=self.messages,
            responses=self.responses,
            tool_calls=self.tool_calls,
            tool_results=self.tool_results,
            accepted_actions=self.accepted_actions,
            runtime_executions=self.runtime_executions,
            runtime_events=self.runtime_events,
            runtime_trace_digest=self.runtime_trace_digest,
            infrastructure_error=self.infrastructure_error,
        ):
            raise ValueError("interaction digest does not match canonical evidence")
        return self


class EvaluationAttempt(_FrozenModel):
    """Exactly one scientifically completed run or one infrastructure failure."""

    scenario_id: str = Field(min_length=1)
    completed_run: RunSnapshot | None = None
    infrastructure_error: InfrastructureError | None = None
    trace: CanonicalEvaluationTrace

    @model_validator(mode="after")
    def validate_terminal_shape(self) -> EvaluationAttempt:
        if (self.completed_run is None) == (self.infrastructure_error is None):
            raise ValueError("an evaluation attempt requires one terminal outcome")
        if self.completed_run is not None:
            if self.completed_run.status != "completed":
                raise ValueError("a scientific outcome must be a completed Runtime run")
            if self.trace.infrastructure_error is not None:
                raise ValueError("a scientific outcome cannot contain an infrastructure error")
            validate_completed_run_snapshot(self.completed_run)
            completed_actions = tuple(
                EnvironmentAction.model_validate(event.action)
                for event in self.completed_run.trace
                if event.type == "action" and event.action is not None
            )
            if (
                self.trace.accepted_actions != completed_actions
                or self.trace.runtime_events != self.completed_run.trace
                or self.trace.runtime_trace_digest != self.completed_run.trace_digest
            ):
                raise ValueError("scientific trace evidence must match the completed Runtime run")
        elif self.trace.infrastructure_error != self.infrastructure_error:
            raise ValueError("the attempt and trace infrastructure errors must agree")
        return self


class CanonicalModelRunner:
    """Execute declared model tool calls through the sole scientific Runtime seam."""

    def __init__(
        self,
        *,
        bundle: EnvironmentBundle,
        runtime_bridge: EvaluationRuntimeBridge,
        provider: ModelProvider,
        max_turns: int,
        max_tool_calls: int,
        sampling: ModelSamplingSettings | None = None,
        profile: EvaluationProfile = "base-gemma-development-v1",
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_turns < 1 or max_tool_calls < 1:
            raise ValueError("model-loop budgets must be positive")
        self._bundle = bundle.model_copy(deep=True)
        self._runtime_bridge = runtime_bridge
        self._provider = provider
        self._max_turns = max_turns
        self._max_tool_calls = max_tool_calls
        self._sampling = sampling or ModelSamplingSettings()
        self._budgets = EvaluationBudgets(
            max_turns=max_turns,
            max_tool_calls=max_tool_calls,
        )
        self._profile = profile
        self._monotonic = monotonic
        self._tools = tuple(
            ModelTool(
                name=action.type,
                description=action.description,
                input_schema=deepcopy(action.input_schema),
            )
            for action in self._bundle.actions
        )
        self._tool_schemas = {
            action.type: deepcopy(action.input_schema) for action in self._bundle.actions
        }

    def run(
        self,
        *,
        scenario_id: str,
        objective: str,
        model: ModelIdentity,
    ) -> EvaluationAttempt:
        """Run one bounded episode and return scientific or infrastructure evidence."""
        if not objective:
            raise ValueError("the Policy objective must not be empty")
        episode_started_monotonic = self._monotonic()
        run_started_at_utc = datetime.now(timezone.utc)
        state = self._runtime_bridge.start(scenario_id, model.policy_identity())
        messages = [
            ModelMessage.user(
                {
                    "objective": objective,
                    "observation": deepcopy(state.snapshot.observation),
                }
            )
        ]
        responses: list[ModelResponseRecord] = []
        tool_calls: list[ModelToolCall] = []
        tool_results: list[ToolExecutionResult] = []
        local_gemma_attestation: LocalGemmaRuntimeAttestation | None = None

        preflight = getattr(self._provider, "preflight", None)
        if model.provider == "local-openai-compatible" and not callable(preflight):
            return self._failed_attempt(
                model=model,
                state=state,
                messages=messages,
                responses=responses,
                tool_calls=tool_calls,
                tool_results=tool_results,
                error=InfrastructureError(
                    category="adapter",
                    code="adapter.invalid_attestation",
                    summary="The local model server did not provide runtime attestation.",
                ),
                run_started_at_utc=run_started_at_utc,
                local_gemma_attestation=None,
            )
        if callable(preflight):
            remaining = self._remaining_episode_seconds(episode_started_monotonic)
            if remaining <= 0.0:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=_episode_timeout_error(),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=None,
                )
            try:
                local_gemma_attestation = LocalGemmaRuntimeAttestation.model_validate(
                    preflight(
                        ModelPreflightRequest(
                            model=model,
                            profile=self._profile,
                            sampling=self._sampling,
                            budgets=self._budgets,
                            transport_timeout_seconds=remaining,
                        )
                    )
                )
            except ModelProviderFailure as error:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        error.normalized_error,
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=None,
                )
            except (TypeError, ValidationError):
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        InfrastructureError(
                            category="adapter",
                            code="adapter.invalid_attestation",
                            summary="The model server attestation was invalid.",
                        ),
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=None,
                )
            except TimeoutError:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        InfrastructureError(
                            category="inference",
                            code="inference.timeout",
                            summary="The inference request exceeded its time limit.",
                        ),
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=None,
                )
            except Exception:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        InfrastructureError(
                            category="adapter",
                            code="adapter.provider_exception",
                            summary="The model adapter could not complete the request.",
                        ),
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=None,
                )
            if self._episode_expired(episode_started_monotonic):
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=_episode_timeout_error(),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )

        for turn in range(1, self._max_turns + 1):
            remaining = self._remaining_episode_seconds(episode_started_monotonic)
            if remaining <= 0.0:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=_episode_timeout_error(),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            try:
                response = ModelResponse.model_validate(
                    self._provider.complete(
                        ModelRequest(
                            model=model,
                            turn=turn,
                            messages=tuple(messages),
                            tools=self._tools,
                            sampling=self._sampling,
                            budgets=self._budgets,
                            transport_timeout_seconds=remaining,
                        )
                    )
                )
            except ModelProviderFailure as error:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        error.normalized_error,
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            except ValidationError:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        InfrastructureError(
                            category="adapter",
                            code="adapter.invalid_response",
                            summary="The model adapter returned an invalid response.",
                        ),
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            except TimeoutError:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        InfrastructureError(
                            category="inference",
                            code="inference.timeout",
                            summary="The inference request exceeded its time limit.",
                        ),
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            except Exception:
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=self._deadline_error_or(
                        InfrastructureError(
                            category="adapter",
                            code="adapter.provider_exception",
                            summary="The model adapter could not complete the request.",
                        ),
                        episode_started_monotonic,
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            if any(
                call.provider_call_id is not None or call.ordinal is not None
                for call in response.message.tool_calls
            ):
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=InfrastructureError(
                        category="protocol",
                        code="protocol.preassigned_canonical_call_id",
                        summary="The provider crossed the canonical call identity boundary.",
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            if (
                len(tool_calls) + len(response.message.tool_calls)
                > self._budgets.max_provider_tool_calls
            ):
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=InfrastructureError(
                        category="protocol",
                        code="protocol.provider_tool_call_budget_exceeded",
                        summary="The provider exceeded the episode tool-call limit.",
                    ),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            canonical_calls = tuple(
                ModelToolCall(
                    call_id=_canonical_call_id(len(tool_calls) + offset),
                    provider_call_id=call.call_id,
                    ordinal=len(tool_calls) + offset,
                    name=call.name,
                    arguments=deepcopy(call.arguments),
                )
                for offset, call in enumerate(
                    response.message.tool_calls,
                    start=1,
                )
            )
            canonical_message = ModelMessage.assistant(
                cast(str, response.message.content),
                tool_calls=canonical_calls,
                response_id=response.response_id,
                response_turn=turn,
                provider_state=response.message.provider_state,
            )
            messages.append(canonical_message)
            responses.append(
                ModelResponseRecord(
                    turn=turn,
                    response_id=response.response_id,
                    returned_model=response.returned_model,
                    usage=response.usage,
                    metadata=response.metadata,
                )
            )
            tool_calls.extend(call.model_copy(deep=True) for call in canonical_calls)
            if self._episode_expired(episode_started_monotonic):
                for call in canonical_calls:
                    self._append_tool_error(
                        call=call,
                        error_code="tool.episode_timeout",
                        messages=messages,
                        tool_results=tool_results,
                    )
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=_episode_timeout_error(),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            if response.metadata is not None and response.metadata.finish_reason == "length":
                for call in canonical_calls:
                    self._append_tool_error(
                        call=call,
                        error_code="tool.output_budget_exhausted",
                        messages=messages,
                        tool_results=tool_results,
                    )
                completed = self._runtime_bridge.finalize_incomplete(
                    state,
                    termination_reason="output_budget_exhausted",
                )
                return self._completed_attempt(
                    model=model,
                    completed=completed,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    state=state,
                    episode_started_monotonic=episode_started_monotonic,
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            if not canonical_calls:
                completed = self._runtime_bridge.finalize_incomplete(
                    state,
                    termination_reason="model_ended_before_terminal",
                )
                return self._completed_attempt(
                    model=model,
                    completed=completed,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    state=state,
                    episode_started_monotonic=episode_started_monotonic,
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            reached_terminal = False
            budget_exhausted = False
            for call_index, call in enumerate(canonical_calls):
                if self._episode_expired(episode_started_monotonic):
                    for unexecuted in canonical_calls[call_index:]:
                        self._append_tool_error(
                            call=unexecuted,
                            error_code="tool.episode_timeout",
                            messages=messages,
                            tool_results=tool_results,
                        )
                    return self._failed_attempt(
                        model=model,
                        state=state,
                        messages=messages,
                        responses=responses,
                        tool_calls=tool_calls,
                        tool_results=tool_results,
                        error=_episode_timeout_error(),
                        run_started_at_utc=run_started_at_utc,
                        local_gemma_attestation=local_gemma_attestation,
                    )
                if reached_terminal:
                    self._append_tool_error(
                        call=call,
                        error_code="tool.episode_terminal",
                        messages=messages,
                        tool_results=tool_results,
                    )
                    continue
                if budget_exhausted or len(state.accepted_actions) >= self._max_tool_calls:
                    budget_exhausted = True
                    self._append_tool_error(
                        call=call,
                        error_code="tool.budget_exhausted",
                        messages=messages,
                        tool_results=tool_results,
                    )
                    continue
                schema = self._tool_schemas.get(call.name)
                if schema is None:
                    self._append_tool_error(
                        call=call,
                        error_code="tool.unknown_action",
                        messages=messages,
                        tool_results=tool_results,
                    )
                    continue
                if next(Draft202012Validator(schema).iter_errors(call.arguments), None):
                    self._append_tool_error(
                        call=call,
                        error_code="tool.invalid_arguments",
                        messages=messages,
                        tool_results=tool_results,
                    )
                    continue
                action = EnvironmentAction(
                    type=call.name,
                    arguments=deepcopy(call.arguments),
                )
                try:
                    if call.ordinal is None:
                        raise CanonicalCallConflictError("canonical call is missing its ordinal")
                    application = self._runtime_bridge.apply_idempotent(
                        state,
                        call_id=call.call_id,
                        ordinal=call.ordinal,
                        action=action,
                    )
                    state = application.state
                except CanonicalCallConflictError:
                    self._append_tool_error(
                        call=call,
                        error_code="tool.canonical_call_conflict",
                        messages=messages,
                        tool_results=tool_results,
                    )
                    for unexecuted in canonical_calls[call_index + 1 :]:
                        self._append_tool_error(
                            call=unexecuted,
                            error_code="tool.protocol_aborted",
                            messages=messages,
                            tool_results=tool_results,
                        )
                    return self._failed_attempt(
                        model=model,
                        state=state,
                        messages=messages,
                        responses=responses,
                        tool_calls=tool_calls,
                        tool_results=tool_results,
                        error=InfrastructureError(
                            category="protocol",
                            code="protocol.canonical_call_conflict",
                            summary="A canonical tool call was reused inconsistently.",
                        ),
                        run_started_at_utc=run_started_at_utc,
                        local_gemma_attestation=local_gemma_attestation,
                    )
                except RuntimeContractError:
                    self._append_tool_error(
                        call=call,
                        error_code="tool.action_rejected",
                        messages=messages,
                        tool_results=tool_results,
                    )
                    continue
                result = ToolExecutionResult(
                    call_id=call.call_id,
                    provider_call_id=call.provider_call_id or call.call_id,
                    ordinal=call.ordinal,
                    name=call.name,
                    status="ok",
                    observation=deepcopy(application.observation),
                    execution_id=application.execution_id,
                    cache_hit=application.cache_hit,
                    retry_count=application.retry_count,
                )
                tool_results.append(result)
                messages.append(
                    ModelMessage.tool(
                        result.policy_payload(),
                        call_id=call.call_id,
                        provider_call_id=call.provider_call_id,
                        ordinal=call.ordinal,
                        name=call.name,
                    )
                )
                if state.snapshot.status == "awaiting_verification":
                    reached_terminal = True
            if self._episode_expired(episode_started_monotonic):
                return self._failed_attempt(
                    model=model,
                    state=state,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    error=_episode_timeout_error(),
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            if reached_terminal:
                completed = self._runtime_bridge.finalize(state)
                return self._completed_attempt(
                    model=model,
                    completed=completed,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    state=state,
                    episode_started_monotonic=episode_started_monotonic,
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )
            if budget_exhausted or len(state.accepted_actions) >= self._max_tool_calls:
                completed = self._runtime_bridge.finalize_incomplete(
                    state,
                    termination_reason="tool_call_budget_exhausted",
                )
                return self._completed_attempt(
                    model=model,
                    completed=completed,
                    messages=messages,
                    responses=responses,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    state=state,
                    episode_started_monotonic=episode_started_monotonic,
                    run_started_at_utc=run_started_at_utc,
                    local_gemma_attestation=local_gemma_attestation,
                )

        if self._episode_expired(episode_started_monotonic):
            return self._failed_attempt(
                model=model,
                state=state,
                messages=messages,
                responses=responses,
                tool_calls=tool_calls,
                tool_results=tool_results,
                error=_episode_timeout_error(),
                run_started_at_utc=run_started_at_utc,
                local_gemma_attestation=local_gemma_attestation,
            )
        completed = self._runtime_bridge.finalize_incomplete(
            state,
            termination_reason="turn_budget_exhausted",
        )
        return self._completed_attempt(
            model=model,
            completed=completed,
            messages=messages,
            responses=responses,
            tool_calls=tool_calls,
            tool_results=tool_results,
            state=state,
            episode_started_monotonic=episode_started_monotonic,
            run_started_at_utc=run_started_at_utc,
            local_gemma_attestation=local_gemma_attestation,
        )

    def _remaining_episode_seconds(self, episode_started_monotonic: float) -> float:
        elapsed = self._monotonic() - episode_started_monotonic
        if elapsed < 0.0:
            return 0.0
        return max(0.0, float(self._budgets.max_episode_seconds) - elapsed)

    def _episode_expired(self, episode_started_monotonic: float) -> bool:
        return self._remaining_episode_seconds(episode_started_monotonic) <= 0.0

    def _deadline_error_or(
        self,
        error: InfrastructureError,
        episode_started_monotonic: float,
    ) -> InfrastructureError:
        if self._episode_expired(episode_started_monotonic):
            return _episode_timeout_error()
        return error

    @staticmethod
    def _append_tool_error(
        *,
        call: ModelToolCall,
        error_code: str,
        messages: list[ModelMessage],
        tool_results: list[ToolExecutionResult],
    ) -> None:
        if call.provider_call_id is None or call.ordinal is None:
            raise ValueError("tool errors require a canonical call identity")
        result = ToolExecutionResult(
            call_id=call.call_id,
            provider_call_id=call.provider_call_id,
            ordinal=call.ordinal,
            name=call.name,
            status="error",
            error_code=error_code,
        )
        tool_results.append(result)
        messages.append(
            ModelMessage.tool(
                result.policy_payload(),
                call_id=call.call_id,
                provider_call_id=call.provider_call_id,
                ordinal=call.ordinal,
                name=call.name,
            )
        )

    def _completed_attempt(
        self,
        *,
        model: ModelIdentity,
        completed: RunSnapshot,
        messages: list[ModelMessage],
        responses: list[ModelResponseRecord],
        tool_calls: list[ModelToolCall],
        tool_results: list[ToolExecutionResult],
        state: ReplayableRuntimeState,
        episode_started_monotonic: float,
        run_started_at_utc: datetime,
        local_gemma_attestation: LocalGemmaRuntimeAttestation | None,
    ) -> EvaluationAttempt:
        if self._episode_expired(episode_started_monotonic):
            return self._failed_attempt(
                model=model,
                state=state,
                messages=messages,
                responses=responses,
                tool_calls=tool_calls,
                tool_results=tool_results,
                error=_episode_timeout_error(),
                run_started_at_utc=run_started_at_utc,
                local_gemma_attestation=local_gemma_attestation,
            )
        run = ModelRunMetadata(
            profile=self._profile,
            started_at_utc=run_started_at_utc,
            completed_at_utc=datetime.now(timezone.utc),
            local_gemma_attestation=local_gemma_attestation,
        )
        trace = _trace(
            model=model,
            sampling=self._sampling,
            budgets=self._budgets,
            run=run,
            messages=messages,
            responses=responses,
            tool_calls=tool_calls,
            tool_results=tool_results,
            accepted_actions=tuple(
                EnvironmentAction.model_validate(event.action)
                for event in completed.trace
                if event.type == "action" and event.action is not None
            ),
            runtime_executions=state.executions,
            runtime_events=completed.trace,
            runtime_trace_digest=completed.trace_digest,
            infrastructure_error=None,
        )
        return EvaluationAttempt(
            scenario_id=completed.scenario_id,
            completed_run=completed.model_copy(deep=True),
            trace=trace,
        )

    def _failed_attempt(
        self,
        *,
        model: ModelIdentity,
        state: ReplayableRuntimeState,
        messages: list[ModelMessage],
        responses: list[ModelResponseRecord],
        tool_calls: list[ModelToolCall],
        tool_results: list[ToolExecutionResult],
        error: InfrastructureError,
        run_started_at_utc: datetime,
        local_gemma_attestation: LocalGemmaRuntimeAttestation | None,
    ) -> EvaluationAttempt:
        run = ModelRunMetadata(
            profile=self._profile,
            started_at_utc=run_started_at_utc,
            completed_at_utc=datetime.now(timezone.utc),
            local_gemma_attestation=local_gemma_attestation,
        )
        trace = _trace(
            model=model,
            sampling=self._sampling,
            budgets=self._budgets,
            run=run,
            messages=messages,
            responses=responses,
            tool_calls=tool_calls,
            tool_results=tool_results,
            accepted_actions=state.accepted_actions,
            runtime_executions=state.executions,
            runtime_events=state.snapshot.trace,
            runtime_trace_digest=state.snapshot.trace_digest,
            infrastructure_error=error,
        )
        return EvaluationAttempt(
            scenario_id=state.scenario_id,
            infrastructure_error=error,
            trace=trace,
        )


def _trace(
    *,
    model: ModelIdentity,
    sampling: ModelSamplingSettings,
    budgets: EvaluationBudgets,
    run: ModelRunMetadata,
    messages: list[ModelMessage],
    responses: list[ModelResponseRecord],
    tool_calls: list[ModelToolCall],
    tool_results: list[ToolExecutionResult],
    accepted_actions: tuple[EnvironmentAction, ...],
    runtime_executions: tuple[CanonicalActionExecution, ...],
    runtime_events: tuple[TraceEvent, ...],
    runtime_trace_digest: str,
    infrastructure_error: InfrastructureError | None,
) -> CanonicalEvaluationTrace:
    immutable_messages = tuple(item.model_copy(deep=True) for item in messages)
    immutable_responses = tuple(item.model_copy(deep=True) for item in responses)
    immutable_tool_calls = tuple(item.model_copy(deep=True) for item in tool_calls)
    immutable_tool_results = tuple(item.model_copy(deep=True) for item in tool_results)
    immutable_accepted_actions = tuple(item.model_copy(deep=True) for item in accepted_actions)
    immutable_runtime_executions = tuple(item.model_copy(deep=True) for item in runtime_executions)
    immutable_runtime_events = tuple(item.model_copy(deep=True) for item in runtime_events)
    interaction_digest = _interaction_digest(
        model=model,
        sampling=sampling,
        budgets=budgets,
        run=run,
        messages=immutable_messages,
        responses=immutable_responses,
        tool_calls=immutable_tool_calls,
        tool_results=immutable_tool_results,
        accepted_actions=immutable_accepted_actions,
        runtime_executions=immutable_runtime_executions,
        runtime_events=immutable_runtime_events,
        runtime_trace_digest=runtime_trace_digest,
        infrastructure_error=infrastructure_error,
    )
    return CanonicalEvaluationTrace(
        model=model.model_copy(deep=True),
        sampling=sampling.model_copy(deep=True),
        budgets=budgets.model_copy(deep=True),
        run=run.model_copy(deep=True),
        messages=immutable_messages,
        responses=immutable_responses,
        tool_calls=immutable_tool_calls,
        tool_results=immutable_tool_results,
        accepted_actions=immutable_accepted_actions,
        runtime_executions=immutable_runtime_executions,
        runtime_events=immutable_runtime_events,
        runtime_trace_digest=runtime_trace_digest,
        infrastructure_error=infrastructure_error,
        interaction_digest=interaction_digest,
    )


def _interaction_digest(
    *,
    model: ModelIdentity,
    sampling: ModelSamplingSettings,
    budgets: EvaluationBudgets,
    run: ModelRunMetadata,
    messages: tuple[ModelMessage, ...],
    responses: tuple[ModelResponseRecord, ...],
    tool_calls: tuple[ModelToolCall, ...],
    tool_results: tuple[ToolExecutionResult, ...],
    accepted_actions: tuple[EnvironmentAction, ...],
    runtime_executions: tuple[CanonicalActionExecution, ...],
    runtime_events: tuple[TraceEvent, ...],
    runtime_trace_digest: str,
    infrastructure_error: InfrastructureError | None,
) -> str:
    interaction = {
        "trace_version": "1.0",
        "model": model.model_dump(mode="json"),
        "sampling": sampling.model_dump(mode="json"),
        "budgets": budgets.model_dump(mode="json"),
        "run": run.model_dump(mode="json"),
        "messages": [item.model_dump(mode="json") for item in messages],
        "responses": [item.model_dump(mode="json") for item in responses],
        "tool_calls": [item.model_dump(mode="json") for item in tool_calls],
        "tool_results": [item.model_dump(mode="json") for item in tool_results],
        "accepted_actions": [item.model_dump(mode="json") for item in accepted_actions],
        "runtime_executions": [item.model_dump(mode="json") for item in runtime_executions],
        "runtime_events": [item.model_dump(mode="json") for item in runtime_events],
        "runtime_trace_digest": runtime_trace_digest,
        "infrastructure_error": (
            infrastructure_error.model_dump(mode="json")
            if infrastructure_error is not None
            else None
        ),
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                interaction,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )


def _validated_safe_identifier(value: str) -> str:
    lowered = value.lower()
    looks_like_endpoint = bool(
        "://" in lowered
        or lowered.startswith(("/", "\\", "localhost", "file:/"))
        or re.match(r"^[A-Za-z]:[\\/]", value)
        or _IP_ENDPOINT.match(value)
        or ".internal/" in lowered
        or ".local/" in lowered
    )
    if not _SAFE_IDENTIFIER.fullmatch(value) or looks_like_endpoint:
        raise ValueError("value must be a safe identifier without transport material")
    return value


def _canonical_call_id(ordinal: int) -> str:
    if ordinal < 1 or ordinal > 999_999:
        raise ValueError("canonical call ordinal is outside the supported episode range")
    return f"episode-call-{ordinal:06d}"


def _episode_timeout_error() -> InfrastructureError:
    return InfrastructureError(
        category="inference",
        code="inference.episode_timeout",
        summary="The evaluation episode exceeded its 900-second deadline.",
    )


__all__ = [
    "BASE_GEMMA_ADAPTER_REVISION",
    "BASE_GEMMA_CHECKPOINT_REVISION",
    "BASE_GEMMA_CHECKPOINT_WEIGHTS_SHA256",
    "BASE_GEMMA_MODEL",
    "BASE_GEMMA_RENDERER_REVISION",
    "BASE_GEMMA_TOKENIZER_MANIFEST_SHA256",
    "CanonicalEvaluationTrace",
    "CanonicalModelRunner",
    "EvaluationBudgets",
    "EvaluationProfile",
    "EvaluationAttempt",
    "InfrastructureError",
    "LocalGemmaRuntimeAttestation",
    "LocalGemmaServerEvidence",
    "ModelIdentity",
    "MAX_PROVIDER_TOOL_CALLS",
    "ModelMessage",
    "ModelPreflightRequest",
    "ModelProvider",
    "ModelProviderFailure",
    "ModelProviderKind",
    "ProviderFailureCode",
    "ModelRequest",
    "ModelResponse",
    "ModelResponseMetadata",
    "ModelResponseRecord",
    "ModelRunMetadata",
    "ModelSamplingSettings",
    "ModelTool",
    "ModelToolCall",
    "MultimodalPromptLimits",
    "PINNED_VLLM_SOURCE_REVISION",
    "PINNED_VLLM_VERSION",
    "PINNED_VLLM_WHEEL_SHA256",
    "TokenUsage",
    "ToolExecutionResult",
    "VllmRuntimeConfig",
]
