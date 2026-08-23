import { expect, test } from "@playwright/test";
import { decodeLocalGemmaAttestation } from "../src/api";

const rawDigest = "a".repeat(64);

function distribution(
  name: string,
  version: string,
  importModule: string,
  wheelSha256: string,
): Record<string, unknown> {
  return {
    distribution: name,
    version,
    wheel_sha256: wheelSha256,
    record_manifest_sha256: "b".repeat(64),
    import_module: importModule,
    import_origin: `${importModule}/__init__.py`,
    import_origin_sha256: "c".repeat(64),
    verification: "wheel-record-sha256+import-origin",
  };
}

function attestationFixture(): Record<string, unknown> {
  return {
    attestation_version: "science-local-gemma-runtime-attestation/1",
    attestation_id: "attestation-contract-test",
    runtime_instance_id: "1".repeat(64),
    trusted_bootstrap_sha256: "7".repeat(64),
    challenge_nonce: "d".repeat(64),
    generated_at_utc: "2026-08-23T04:00:00Z",
    runtime_started_at_utc: "2026-08-23T03:55:00Z",
    served_model: "google/gemma-4-E4B-it",
    checkpoint_revision: "ee0ef6023621cff504d758262d4e04895a5af4a2",
    checkpoint_weights_sha256: "cfbd3d2f1cd71bd471c37fe2bf8546d5028d41e5736f64e1ca6c6b8893125503",
    tokenizer_revision: "ee0ef6023621cff504d758262d4e04895a5af4a2",
    tokenizer_manifest_sha256: "88f73edddd41b7417ff93e3e410be277c9a138132013b13d9cdbdfcc42aec677",
    renderer_revision: "f770dcaa362e3a6a13a96f039741b3b84ca4114e",
    vllm_version: "0.26.0+cu129",
    vllm_source_revision: "568afb3a13806beb53bb2e6bd518269357b237c0",
    vllm_wheel_sha256: "7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf",
    python_runtime: {
      implementation: "cpython",
      version: "3.12",
      abi_tag: "cp312",
      platform: "linux-x86_64",
    },
    runtime_receipt_id: "science-local-gemma-runtime-cp312-cu129/1",
    runtime_distributions: [
      distribution("jinja2", "3.1.6", "jinja2", "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67"),
      distribution("safetensors", "0.7.0", "safetensors", "dac7252938f0696ddea46f5e855dd3138444e82236e3be475f54929f0c510d48"),
      distribution("tokenizers", "0.22.2", "tokenizers", "369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67"),
      distribution("torch", "2.11.0+cu129", "torch", "68b83cb7d7d43bc67c2833c8aebaea6a966f2017c3389885affa3361c258b7e3"),
      distribution("transformers", "5.6.2", "transformers", "f8d3a1bb96778fed9b8aabfd0dd6e19843e4b0f2bb6b59f32b8a92051b0f348f"),
      distribution("vllm", "0.26.0+cu129", "vllm", "7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf"),
    ],
    product_distribution: {
      ...distribution(
        "science-environment-studio",
        "0.1.0",
        "studio.policy_evaluation.gemma_server_bootstrap",
        "9".repeat(64),
      ),
      import_origin: "studio/policy_evaluation/gemma_server_bootstrap.py",
    },
    python_bytecode_mode: "fresh-private-prefix-no-write",
    serving_root_filesystem_mode: "kernel-read-only-mount",
    network_scope: "loopback-only",
    api_key_authentication: true,
    attestation_middleware_revision: "science-local-gemma-attestation-middleware/1",
    vllm_config: {
      dtype: "bfloat16",
      max_model_len: 32768,
      tensor_parallel_size: 1,
      gpu_memory_utilization: 0.35,
      enforce_eager: true,
      max_num_seqs: 16,
      generation_config: "vllm",
      tool_call_parser: "gemma4",
      enable_auto_tool_choice: true,
      enable_lora: false,
      disable_log_requests: true,
      limit_mm_per_prompt: { image: 0, audio: 0, video: 0 },
    },
    adapter_revision: "local-gemma-openai-chat/1",
    served_adapter: "none",
    sampling_profile: "base-gemma-development-chat-v1",
    max_episode_seconds: 900,
    platform: "linux-x86_64",
    accelerator_architecture: "sm120",
    accelerator_count: 1,
    cuda_version: "12.9",
    driver_version: "610.43.02",
    serving_image_digest: `sha256:${"2".repeat(64)}`,
    serving_image_digest_provenance: "operator-supplied",
    evidence_scope: "server-reported-runtime-state",
    signature: "e".repeat(64),
    evidence_digest: `sha256:${"f".repeat(64)}`,
    verification_method: "hmac-sha256-server-challenge",
  };
}

test("decodes the canonical URL-free direct-runtime receipt", () => {
  const decoded = decodeLocalGemmaAttestation(attestationFixture());

  expect(decoded.python_runtime).toEqual({
    implementation: "cpython",
    version: "3.12",
    abi_tag: "cp312",
    platform: "linux-x86_64",
  });
  expect(decoded.runtime_distributions.map((item) => [
    item.distribution,
    item.version,
  ])).toEqual([
    ["jinja2", "3.1.6"],
    ["safetensors", "0.7.0"],
    ["tokenizers", "0.22.2"],
    ["torch", "2.11.0+cu129"],
    ["transformers", "5.6.2"],
    ["vllm", "0.26.0+cu129"],
  ]);
  expect(decoded.product_distribution).toMatchObject({
    distribution: "science-environment-studio",
    version: "0.1.0",
    wheel_sha256: "9".repeat(64),
  });
  expect(decoded.runtime_instance_id).toBe("1".repeat(64));
  expect(decoded.trusted_bootstrap_sha256).toBe("7".repeat(64));
});

test("rejects incomplete, reordered, drifted, or URL-bearing receipts", () => {
  const incomplete = attestationFixture();
  (incomplete.runtime_distributions as unknown[]).pop();
  expect(() => decodeLocalGemmaAttestation(incomplete)).toThrow(/approved order/);

  const reordered = attestationFixture();
  (reordered.runtime_distributions as unknown[]).reverse();
  expect(() => decodeLocalGemmaAttestation(reordered)).toThrow(/approved order/);

  const drifted = attestationFixture();
  (drifted.python_runtime as Record<string, unknown>).abi_tag = "cp311";
  expect(() => decodeLocalGemmaAttestation(drifted)).toThrow(/cp312/);

  const urlBearing = attestationFixture();
  const first = (urlBearing.runtime_distributions as Record<string, unknown>[])[0];
  first.artifact_source = "https://private.invalid/runtime.whl";
  expect(() => decodeLocalGemmaAttestation(urlBearing)).toThrow(/artifact_source/);

  const productDrift = attestationFixture();
  (productDrift.product_distribution as Record<string, unknown>).import_origin = (
    "studio/policy_evaluation/gemma_attestation.py"
  );
  expect(() => decodeLocalGemmaAttestation(productDrift)).toThrow(/gemma_server_bootstrap/);

  const writableRoots = attestationFixture();
  writableRoots.serving_root_filesystem_mode = "writable-filesystem";
  expect(() => decodeLocalGemmaAttestation(writableRoots)).toThrow(/kernel-read-only-mount/);
});
