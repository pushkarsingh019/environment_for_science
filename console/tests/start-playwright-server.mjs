import { spawn } from "node:child_process";
import { createHmac } from "node:crypto";
import { chmodSync, mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const testDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(testDirectory, "..", "..");
const privateTemporaryRoot = process.platform === "darwin" ? "/private/tmp" : tmpdir();
const artifactRoot = mkdtempSync(
  join(privateTemporaryRoot, "science-environment-playwright-"),
);
chmodSync(artifactRoot, 0o700);

const modelSocketPath = join(artifactRoot, "science-local-gemma.sock");
const modelApiKey = "playwright-contract-api-key-material-0000000000000000";
const attestationKey = "playwright-attestation-key-material-0000000000000000";
const runtimeInstanceId = "1".repeat(64);
const productWheelSha256 = "9".repeat(64);
const trustedBootstrapSha256 = "7".repeat(64);
const successActions = [
  "inspect_configuration",
  "inspect_eeg_signals",
  "inspect_onset_route",
  "inspect_response_timeline",
  "inspect_recording_timeline",
  "complete_preflight",
];
const runtimeDistributions = [
  {
    distribution: "jinja2",
    version: "3.1.6",
    wheel_sha256: "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67",
    import_module: "jinja2",
    import_origin: "jinja2/__init__.py",
  },
  {
    distribution: "safetensors",
    version: "0.7.0",
    wheel_sha256: "dac7252938f0696ddea46f5e855dd3138444e82236e3be475f54929f0c510d48",
    import_module: "safetensors",
    import_origin: "safetensors/__init__.py",
  },
  {
    distribution: "tokenizers",
    version: "0.22.2",
    wheel_sha256: "369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67",
    import_module: "tokenizers",
    import_origin: "tokenizers/__init__.py",
  },
  {
    distribution: "torch",
    version: "2.11.0+cu129",
    wheel_sha256: "68b83cb7d7d43bc67c2833c8aebaea6a966f2017c3389885affa3361c258b7e3",
    import_module: "torch",
    import_origin: "torch/__init__.py",
  },
  {
    distribution: "transformers",
    version: "5.6.2",
    wheel_sha256: "f8d3a1bb96778fed9b8aabfd0dd6e19843e4b0f2bb6b59f32b8a92051b0f348f",
    import_module: "transformers",
    import_origin: "transformers/__init__.py",
  },
  {
    distribution: "vllm",
    version: "0.26.0+cu129",
    wheel_sha256: "7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf",
    import_module: "vllm",
    import_origin: "vllm/__init__.py",
  },
].map((receipt) => ({
  ...receipt,
  record_manifest_sha256: "a".repeat(64),
  import_origin_sha256: "b".repeat(64),
  verification: "wheel-record-sha256+import-origin",
}));
let activeAttempt = 0;
let activeTurn = 0;
let pauseAttestations = false;
let pausedAttestationReached = null;
let releasePausedAttestation = null;

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => (
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    )).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "Content-Length": Buffer.byteLength(body),
    "Content-Type": "application/json",
    "X-Science-Runtime-Instance": runtimeInstanceId,
  });
  response.end(body);
}

async function requestJson(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function serverEvidence(challenge) {
  const generated = new Date(Math.floor(Date.now() / 1000) * 1000);
  const started = new Date(generated.getTime() - 60_000);
  return {
    attestation_version: "science-local-gemma-runtime-attestation/1",
    attestation_id: `playwright-contract-attestation-${String(activeAttempt).padStart(4, "0")}`,
    runtime_instance_id: runtimeInstanceId,
    trusted_bootstrap_sha256: trustedBootstrapSha256,
    python_bytecode_mode: "fresh-private-prefix-no-write",
    challenge_nonce: challenge,
    generated_at_utc: generated.toISOString().replace(".000Z", "Z"),
    runtime_started_at_utc: started.toISOString().replace(".000Z", "Z"),
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
    runtime_distributions: runtimeDistributions,
    product_distribution: {
      distribution: "science-environment-studio",
      version: "0.1.0",
      wheel_sha256: productWheelSha256,
      record_manifest_sha256: "c".repeat(64),
      import_module: "studio.policy_evaluation.gemma_server_bootstrap",
      import_origin: "studio/policy_evaluation/gemma_server_bootstrap.py",
      import_origin_sha256: "d".repeat(64),
      verification: "wheel-record-sha256+import-origin",
    },
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
    accelerator_architecture: "playwright-test-sm120",
    accelerator_count: 1,
    cuda_version: "test-12.9",
    driver_version: "test-610.43.02",
    serving_image_digest: `sha256:${"2".repeat(64)}`,
    serving_image_digest_provenance: "operator-supplied",
    evidence_scope: "server-reported-runtime-state",
  };
}

function validAttestationRequest(payload) {
  return payload.attestation_version === "science-local-gemma-runtime-attestation/1"
    && /^[0-9a-f]{64}$/.test(payload.challenge_nonce)
    && payload.expected_product_wheel_sha256 === productWheelSha256
    && payload.expected_trusted_bootstrap_sha256 === trustedBootstrapSha256
    && payload.requested_model === "google/gemma-4-E4B-it"
    && payload.adapter_revision === "local-gemma-openai-chat/1"
    && payload.sampling_profile === "base-gemma-development-chat-v1"
    && payload.sampling?.temperature === 0
    && payload.sampling?.max_output_tokens === 2048
    && payload.sampling?.tool_choice === "auto"
    && payload.sampling?.top_p === null
    && payload.sampling?.seed === null
    && payload.sampling?.streaming === false
    && payload.sampling?.store === false
    && payload.budgets?.max_turns === 64
    && payload.budgets?.max_tool_calls === 64
    && payload.budgets?.max_provider_tool_calls === 64
    && payload.budgets?.max_episode_seconds === 900;
}

function validChatRequest(payload) {
  return payload.model === "google/gemma-4-E4B-it"
    && Array.isArray(payload.messages)
    && Array.isArray(payload.tools)
    && payload.temperature === 0
    && payload.max_tokens === 2048
    && payload.tool_choice === "auto"
    && payload.stream === false;
}

const modelServer = createServer(async (request, response) => {
  try {
    if (
      request.method !== "POST"
      || request.headers.authorization !== `Bearer ${modelApiKey}`
    ) {
      sendJson(response, 401, { error: "test transport rejected" });
      return;
    }
    const payload = await requestJson(request);
    if (request.url === "/v1/science/runtime-attestations") {
      if (pauseAttestations) {
        pausedAttestationReached?.();
        await new Promise((resolvePromise) => {
          releasePausedAttestation = resolvePromise;
        });
        response.destroy();
        return;
      }
      if (!validAttestationRequest(payload)) {
        sendJson(response, 422, { error: "test attestation contract mismatch" });
        return;
      }
      activeAttempt += 1;
      activeTurn = 0;
      const attestation = serverEvidence(payload.challenge_nonce);
      const signature = createHmac("sha256", attestationKey)
        .update(canonicalJson(attestation))
        .digest("hex");
      sendJson(response, 200, { attestation, signature });
      return;
    }
    if (request.url !== "/v1/chat/completions" || !validChatRequest(payload)) {
      sendJson(response, 422, { error: "test chat contract mismatch" });
      return;
    }
    if (![8, 9, 10].includes(activeAttempt)) {
      sendJson(response, 503, { error: "scripted test inference unavailable" });
      return;
    }
    activeTurn += 1;
    if (activeAttempt === 10) {
      sendJson(response, 200, {
        id: `response-${activeAttempt}-${activeTurn}`,
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: "google/gemma-4-E4B-it",
        system_fingerprint: "playwright-contract-server-v1",
        choices: [{
          index: 0,
          finish_reason: "length",
          message: { role: "assistant", content: "Output budget exhausted." },
        }],
        usage: {
          prompt_tokens: 10,
          completion_tokens: 2048,
          total_tokens: 2058,
          prompt_tokens_details: { cached_tokens: 0 },
          completion_tokens_details: { reasoning_tokens: 0 },
        },
      });
      return;
    }
    const action = activeAttempt === 8
      ? successActions[activeTurn - 1]
      : "complete_preflight";
    const declared = payload.tools.some((tool) => tool?.function?.name === action);
    if (!action || !declared) {
      sendJson(response, 422, { error: "scripted action is not declared" });
      return;
    }
    sendJson(response, 200, {
      id: `response-${activeAttempt}-${activeTurn}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: "google/gemma-4-E4B-it",
      system_fingerprint: "playwright-contract-server-v1",
      choices: [{
        index: 0,
        finish_reason: "tool_calls",
        message: {
          role: "assistant",
          content: `Apply ${action}.`,
          tool_calls: [{
            id: `call-${activeTurn}`,
            type: "function",
            function: { name: action, arguments: "{}" },
          }],
        },
      }],
      usage: {
        prompt_tokens: 10,
        completion_tokens: 4,
        total_tokens: 14,
        prompt_tokens_details: { cached_tokens: 0 },
        completion_tokens_details: { reasoning_tokens: 0 },
      },
    });
  } catch {
    sendJson(response, 500, { error: "test model server failed" });
  }
});

await new Promise((resolvePromise, rejectPromise) => {
  modelServer.once("error", rejectPromise);
  modelServer.listen(modelSocketPath, resolvePromise);
});
chmodSync(modelSocketPath, 0o600);

const python = resolve(repositoryRoot, ".venv", "bin", "python");
const studioHost = "127.0.0.1";
const studioPort = 8000;
const controlPort = 8001;
let shuttingDown = false;
let restarting = false;
let studioProcess = null;
let resumeLockProcess = null;

function startStudio() {
  const child = spawn(
    python,
    [
      "-m",
      "studio",
      "--port",
      String(studioPort),
      "--artifact-root",
      artifactRoot,
    ],
    {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        SCIENCE_LOCAL_GEMMA_API_KEY: modelApiKey,
        SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY: attestationKey,
        SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256: productWheelSha256,
        SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256: trustedBootstrapSha256,
        SCIENCE_LOCAL_GEMMA_BASE_URL: "http://127.0.0.1/v1",
        SCIENCE_LOCAL_GEMMA_UNIX_SOCKET: modelSocketPath,
      },
      stdio: "inherit",
    },
  );
  studioProcess = child;
  child.on("exit", (code) => {
    if (studioProcess === child) studioProcess = null;
    if (!shuttingDown && !restarting) {
      modelServer.close();
      controlServer.close();
      rmSync(artifactRoot, { force: true, recursive: true });
      process.exit(code ?? 1);
    }
  });
  return child;
}

function waitForExit(child) {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve();
  return new Promise((resolvePromise) => child.once("exit", resolvePromise));
}

async function waitForStudio() {
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(
        `http://${studioHost}:${studioPort}/api/environment`,
      );
      if (response.ok) return;
    } catch {
      // Expected while the replacement process binds its loopback socket.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 50));
  }
  throw new Error("replacement Studio did not become ready");
}

async function alignModelScriptWithDurableProgress() {
  const response = await fetch(`http://${studioHost}:${studioPort}/api/evaluations`);
  if (!response.ok) throw new Error("could not load durable evaluation progress");
  const evaluations = await response.json();
  const completed = evaluations[0]?.progress?.completed_scenarios;
  if (!Number.isInteger(completed) || completed < 0 || completed > 32) {
    throw new Error("durable evaluation progress was malformed");
  }
  activeAttempt = completed;
  activeTurn = 0;
}

async function restartStudio() {
  if (restarting) throw new Error("Studio restart is already in progress");
  restarting = true;
  pauseAttestations = true;
  const boundary = new Promise((resolvePromise) => {
    pausedAttestationReached = resolvePromise;
  });
  await Promise.race([
    boundary,
    new Promise((_, rejectPromise) => {
      setTimeout(
        () => rejectPromise(new Error("evaluation did not reach a restart boundary")),
        5_000,
      );
    }),
  ]);
  const previous = studioProcess;
  previous?.kill("SIGKILL");
  if (previous) await waitForExit(previous);
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 1_400));
  pauseAttestations = false;
  pausedAttestationReached = null;
  releasePausedAttestation?.();
  releasePausedAttestation = null;
  startStudio();
  await waitForStudio();
  await alignModelScriptWithDurableProgress();
  restarting = false;
}

async function holdResumeTransition(evaluationId) {
  if (!/^evaluation-[0-9a-f]{32}$/.test(evaluationId)) {
    throw new Error("evaluation identity was malformed");
  }
  if (resumeLockProcess !== null) {
    throw new Error("resume transition lock is already held");
  }
  const lockPath = join(
    artifactRoot,
    "evaluations",
    ".evaluation-locks",
    `${evaluationId}.lock`,
  );
  const child = spawn(
    python,
    [
      "-c",
      [
        "import fcntl, pathlib, sys",
        "path = pathlib.Path(sys.argv[1])",
        "descriptor = path.open('a+b')",
        "fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX)",
        "print('locked', flush=True)",
        "sys.stdin.read(1)",
      ].join("; "),
      lockPath,
    ],
    { cwd: repositoryRoot, stdio: ["pipe", "pipe", "inherit"] },
  );
  await new Promise((resolvePromise, rejectPromise) => {
    const timeout = setTimeout(
      () => rejectPromise(new Error("resume transition lock timed out")),
      5_000,
    );
    child.once("error", (error) => {
      clearTimeout(timeout);
      rejectPromise(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      rejectPromise(new Error(`resume transition lock exited with ${code}`));
    });
    child.stdout.once("data", (data) => {
      clearTimeout(timeout);
      if (data.toString().trim() !== "locked") {
        rejectPromise(new Error("resume transition lock did not signal readiness"));
        return;
      }
      resolvePromise();
    });
  });
  resumeLockProcess = child;
}

async function releaseResumeTransition() {
  const child = resumeLockProcess;
  resumeLockProcess = null;
  if (child === null) return;
  child.stdin.end("x");
  await waitForExit(child);
}

const controlServer = createServer(async (request, response) => {
  if (request.method === "POST" && request.url === "/reset-model-script") {
    activeAttempt = 0;
    activeTurn = 0;
    response.writeHead(204).end();
    return;
  }
  if (request.method === "POST" && request.url === "/hold-resume-transition") {
    try {
      const payload = await requestJson(request);
      await holdResumeTransition(payload.evaluation_id);
      response.writeHead(204).end();
    } catch (error) {
      sendJson(response, 500, {
        error: error instanceof Error ? error.message : "Could not hold resume transition",
      });
    }
    return;
  }
  if (request.method === "POST" && request.url === "/release-resume-transition") {
    await releaseResumeTransition();
    response.writeHead(204).end();
    return;
  }
  if (request.method !== "POST" || request.url !== "/restart-studio") {
    response.writeHead(404).end();
    return;
  }
  try {
    await restartStudio();
    response.writeHead(204).end();
  } catch (error) {
    restarting = false;
    pauseAttestations = false;
    pausedAttestationReached = null;
    releasePausedAttestation?.();
    releasePausedAttestation = null;
    sendJson(response, 500, {
      error: error instanceof Error ? error.message : "Studio restart failed",
    });
  }
});

await new Promise((resolvePromise, rejectPromise) => {
  controlServer.once("error", rejectPromise);
  controlServer.listen(controlPort, studioHost, resolvePromise);
});
startStudio();

function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  void releaseResumeTransition();
  studioProcess?.kill(signal);
  controlServer.close();
  modelServer.close();
  rmSync(artifactRoot, { force: true, recursive: true });
  process.removeAllListeners(signal);
  process.kill(process.pid, signal);
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdown(signal));
}
