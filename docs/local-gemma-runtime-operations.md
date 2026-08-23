# Operate the attested local Gemma runtime

This is the scored-serving procedure for the approved CPython 3.12 Linux
x86_64 CUDA workstation. Preflight is offline, read-only, and fail closed. It
does not download, install, repair, or delete artifacts.

## Trust boundaries

The application directly verifies six third-party distributions that execute
the serving path: vLLM, PyTorch, Transformers, Tokenizers, Safetensors, and
Jinja2. It also verifies the installed `science-environment-studio` product
files against a separately staged product wheel. The signed receipt contains
only normalized, path-free evidence: names, versions, wheel SHA-256 digests,
installed-`RECORD` manifest digests, relative import origins and their digests,
the Python ABI, and a URL-free receipt ID.

This is not a complete dependency-closure attestation. Before the six-wheel
receipt can run, the verified product imports FastAPI, Pydantic, Starlette, and
their dependencies. The CUDA libraries, driver, system libraries, and Python
standard library also execute outside that receipt. The operator must therefore
pin and independently verify the complete immutable serving image. The signed
`SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST` is operator-supplied evidence of that
separate gate; the application does not discover or validate the image contents.

The trusted bootstrap and `deployment/science_local_gemma_launcher.c` are
staged outside the product wheel. The bootstrap SHA-256 must be pinned by both
the launcher and evaluator. The launcher is the trust root for starting Python:
it has no command-line configuration, validates two fixed secret files,
validates the non-secret environment, verifies the bootstrap before Python
starts, closes inherited descriptors, and calls `execve` with the exact command
and a newly constructed environment. The bootstrap's in-process self-check is
defense in depth. The launcher must be statically linked and have no ELF
`PT_INTERP`; otherwise `LD_PRELOAD` or `LD_AUDIT` could execute before the
launcher rejects those names. Network egress must likewise be blocked by the
host or container boundary; the application sets supported offline guards, but
those are not a firewall.

All serving-critical roots must be separate read-only mounts for the process
lifetime: the bootstrap, model snapshot, renderer checkout, installed Python
root, staged product wheel, and all six staged third-party wheels. A fresh
private writable bytecode-cache directory is the only Python cache. The
application verifies the kernel read-only flag and rejects symlinks and path
escapes. A privileged remount remains outside the unprivileged process threat
model and is an operator hardening responsibility.

## Approved artifacts

The model is the exact Hugging Face revision
[`ee0ef602...`](https://huggingface.co/google/gemma-4-E4B-it/tree/ee0ef6023621cff504d758262d4e04895a5af4a2).
Its materialized root must contain exactly nine top-level regular files:
`.gitattributes`, `README.md`, `model.safetensors`, `tokenizer.json`,
`tokenizer_config.json`, `config.json`, `generation_config.json`,
`processor_config.json`, and `chat_template.jinja`. Preflight checks the pinned
size and SHA-256 of the seven serving artifacts and rejects every additional
file, directory, or symlink. The two repository documents are inert allowed
members, not serving inputs.

The committed direct-runtime receipt is
`science-local-gemma-runtime-cp312-cu129/1`:

| Distribution | Exact artifact | SHA-256 | Audited immutable source |
| --- | --- | --- | --- |
| Jinja2 | `jinja2-3.1.6-py3-none-any.whl` | `85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67` | [PyPI](https://files.pythonhosted.org/packages/62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl) |
| Safetensors | `safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | `dac7252938f0696ddea46f5e855dd3138444e82236e3be475f54929f0c510d48` | [PyPI](https://files.pythonhosted.org/packages/a0/60/429e9b1cb3fc651937727befe258ea24122d9663e4d5709a48c9cbfceecb/safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl) |
| Tokenizers | `tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | `369cc9fc8cc10cb24143873a0d95438bb8ee257bb80c71989e3ee290e8d72c67` | [PyPI](https://files.pythonhosted.org/packages/2e/76/932be4b50ef6ccedf9d3c6639b056a967a86258c6d9200643f01269211ca/tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl) |
| PyTorch | `torch-2.11.0+cu129-cp312-cp312-manylinux_2_28_x86_64.whl` | `68b83cb7d7d43bc67c2833c8aebaea6a966f2017c3389885affa3361c258b7e3` | [official CUDA 12.9 index](https://download.pytorch.org/whl/cu129/torch-2.11.0%2Bcu129-cp312-cp312-manylinux_2_28_x86_64.whl) |
| Transformers | `transformers-5.6.2-py3-none-any.whl` | `f8d3a1bb96778fed9b8aabfd0dd6e19843e4b0f2bb6b59f32b8a92051b0f348f` | [PyPI](https://files.pythonhosted.org/packages/5d/95/0b0218149b0d6f14df35f5b8f676fa83df4f19ed253c3cc447107ef86eca/transformers-5.6.2-py3-none-any.whl) |
| vLLM | `vllm-0.26.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl` | `7632856147650da3ed8d1652b1b05ffaadcc62ea8e910fdaa6f8ce055b201ebf` | [pinned vLLM commit index](https://wheels.vllm.ai/568afb3a13806beb53bb2e6bd518269357b237c0/vllm-0.26.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl) |

These source URLs are operator documentation only. They never enter signed or
persisted evaluation evidence. Stage already audited files; serving does not
fetch them.

Build the product wheel once for the release, record its SHA-256 out of band,
and install that exact wheel into the immutable image. The product cannot
contain a trustworthy pin for its own wheel digest. Source, editable, local
direct-URL, and VCS installations are rejected. Separately stage
`deployment/science_local_gemma_bootstrap.py`, record its SHA-256, and configure
the evaluator with the same product and bootstrap digests.

## Stage the gated model once

First accept the model terms on the official
[`google/gemma-4-E4B-it`](https://huggingface.co/google/gemma-4-E4B-it) page and
create a read-only Hugging Face token. Never put the token in a command,
environment variable, file, shell history, ticket, log, or evaluation artifact.
The no-argument stager reads it only from an interactive hidden terminal prompt,
downloads the exact revision and nine-name allowlist from the fixed official
endpoint, verifies every serving file against its size and SHA-256 pin, and
atomically publishes `/approved/ro/model`. Before prompting, it sets the core
limit to zero and disables same-UID process inspection on Linux. Every
downloaded member must also have exactly one hard link, so a preserved cache
alias cannot mutate the published model after verification.

Prepare one new private host directory for the staging run. The fixed service
identity in this release is numeric UID/GID `65532:65532`:

```sh
sudo install -d -o 65532 -g 65532 -m 0700 \
  /operator/private/science-gemma-model-stage
```

The candidate-image build context must stage
`deployment/science_local_gemma_model_stager.py` byte-for-byte as
`science_local_gemma_model_stager.py`, then install it outside every writable
or bind-mounted root with this exact instruction:

```dockerfile
COPY --chown=0:0 --chmod=0444 science_local_gemma_model_stager.py /usr/local/libexec/science_local_gemma_model_stager.py
RUN test "$(sha256sum /usr/local/libexec/science_local_gemma_model_stager.py | cut -d ' ' -f 1)" = \
    45ef0d8319c27dd76b29b7a14a137cbe10e2190304b9dd2b8afd9749e9bfa980
```

`/usr/local/libexec` remains root-owned and image-immutable. Do not install the
stager only below `/approved/ro`: the private staging bind replaces that entire
path and would hide an image-owned executable there. Record the verified file
digest in the image receipt and invoke only the candidate image by digest; that
image identity transitively binds the immutable stager bytes.

Run the stager from the already pinned candidate image. This is the only step
that receives network egress. The clean environment supplies one audited
Python path but no credential, proxy, loader, or SDK setting:

```sh
docker run --rm -it --read-only --user 65532:65532 \
  --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 128 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,uid=65532,gid=65532,mode=0700 \
  --mount type=bind,src=/operator/private/science-gemma-model-stage,dst=/approved/ro \
  --entrypoint /usr/bin/env \
  <candidate-image-by-digest> \
  -i LC_ALL=C PYTHONPATH=/opt/science/python \
  /usr/bin/python3.12 -S -B \
  /usr/local/libexec/science_local_gemma_model_stager.py
```

Type the token only at `Hugging Face access token:`. A successful invocation
prints exactly `science-local-gemma-model-stage: PASS`. An argument, prompt,
fixed-root, or layout preflight rejection prints exactly
`science-local-gemma-model-stage: FAIL`; these pre-attempt validation failures
create no attempt. Once a unique attempt has been durably created, an ordinary
download or verification failure prints that same exact failure line, leaves
no published `model/`, and durably preserves the unique private attempt
directory for offline diagnosis.

If any storage durability step, rollback, or failed-payload preservation cannot
be proved, the tool instead exits 70 and prints exactly
`science-local-gemma-model-stage: FAIL MANUAL-QUARANTINE-REQUIRED`. This is a
fatal stop, not a model result. Do not inspect, promote, serve, delete, or retry
inside that host staging directory. Let the one-time container exit, remove its
network access, and—without listing contents or printing paths—rename the entire
fixed host staging directory to a new operator-chosen, mode-`0700` quarantine
name under `/operator/private/`. If that same-parent rename cannot be completed,
leave the directory untouched and escalate; never delete or partially move its
contents. Create a fresh empty `65532:65532`, mode-`0700` staging directory at
the original fixed path before retrying. Keep the quarantined directory offline
and never bind any `model/` it may contain into serving.

Never promote an ordinary failed attempt either. After success, remove network
access and mount only the published host `model/` subdirectory at
`/approved/ro/model` with `readonly`; do not mount `model-attempts/` into
serving. The serving preflight independently rechecks the exact tree, file
sizes, hashes, and kernel read-only flag.

## Required server settings

Provide these values through the approved service manager without logging
secrets or artifact paths:

- `SCIENCE_LOCAL_GEMMA_MODEL_ROOT=/approved/ro/model`: the exact nine-file
  snapshot mount published by the one-time stager.
- `SCIENCE_LOCAL_GEMMA_RENDERER_ROOT`: a read-only renderer checkout at
  `f770dcaa362e3a6a13a96f039741b3b84ca4114e`, clean including ignored and
  untracked files.
- `SCIENCE_LOCAL_GEMMA_PRODUCT_ROOT`: installed immutable Python root containing
  the product and its image-pinned dependencies.
- `SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL` and
  `SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256`: staged release wheel and its
  out-of-band digest.
- `SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256`: out-of-band digest of the
  separately staged bootstrap.
- `SCIENCE_LOCAL_GEMMA_JINJA2_WHEEL`,
  `SCIENCE_LOCAL_GEMMA_SAFETENSORS_WHEEL`,
  `SCIENCE_LOCAL_GEMMA_TOKENIZERS_WHEEL`, `SCIENCE_LOCAL_GEMMA_TORCH_WHEEL`,
  `SCIENCE_LOCAL_GEMMA_TRANSFORMERS_WHEEL`, and
  `SCIENCE_LOCAL_GEMMA_VLLM_WHEEL`: the six exact staged artifacts above.
- `SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_PATH` and
  `SCIENCE_LOCAL_GEMMA_NVIDIA_SMI_SHA256`: an absolute, root-owned,
  non-group/world-writable NVIDIA probe on a read-only mount and its pinned
  digest. A `PATH` lookup is never used.
- `SCIENCE_LOCAL_GEMMA_CUDA_VERSION=12.9` and
  `SCIENCE_LOCAL_GEMMA_SERVING_IMAGE_DIGEST=sha256:<64 lowercase hex>`.
- `/run/secrets/science-local-gemma-api-key` and
  `/run/secrets/science-local-gemma-attestation-key`: the two fixed secret
  mounts. Each must be a non-symlink regular file, owned by the launcher's
  unprivileged effective UID, mode `0400`, with one hard link. Each contains
  exactly one 32-to-4096-byte printable ASCII value with no whitespace or
  trailing newline, and the values must be distinct.

Give the launcher only the non-secret `SCIENCE_LOCAL_GEMMA_*` settings listed
above plus `CUDA_VISIBLE_DEVICES`, `CUDA_HOME`, and `CUDA_PATH` when the approved
image requires them. Never put either key value or a secret-file override in
container environment, image `ENV`, command, entrypoint, labels, or annotations.
The launcher discards only the named container housekeeping inputs `HOME`,
`HOSTNAME`, `PATH`, `NVIDIA_VISIBLE_DEVICES`, and
`NVIDIA_DRIVER_CAPABILITIES`; every other undeclared name is rejected. It also
rejects every undeclared `SCIENCE_LOCAL_GEMMA_*` or `CUDA_*` name and every
`LD_*`, `DYLD_*`, and `PYTHON*` name, including `LD_PRELOAD`,
`LD_LIBRARY_PATH`, `LD_AUDIT`, `LD_DEBUG`, `PYTHONHOME`, `PYTHONPATH`, and
`PYTHONHASHSEED`, before Python is created. Inherited `LANG`, `LC_ALL`, and
`LC_*` values are discarded; the launcher unconditionally supplies
`LC_ALL=C`. This prevents CPython 3.12 locale coercion from adding
`LC_CTYPE=C.UTF-8` after an otherwise empty `execve` environment. Its child
environment is the bootstrap's exact non-secret allowlist. It never contains
either secret. The bootstrap requires the fixed C locale, repeats the allowlist
as defense in depth, disables process dumping, and only then reads the two
fixed files. It erases each temporary byte buffer after decoding. After all
runtime evidence is verified, product code captures the two values in private
module state and clears both secrets and all artifact paths from `os.environ`
before importing vLLM. The remaining environment contains only approved CUDA
settings, `LC_ALL=C`, fixed offline guards, a fixed system `PATH`, the fixed
non-login identity names `USER=LOGNAME=science-gemma`, forced `spawn` workers,
and an empty vLLM plugin allowlist. It replaces every inherited home or cache
setting with exact mode-`0700` subdirectories beneath the already verified
private `PYTHONPYCACHEPREFIX`; this includes the home, temporary, XDG, Hugging
Face, PyTorch, Triton, vLLM, and CUDA cache roots. A defensive at-fork hook
clears preverified authentication state in any unexpected fork child. Use a
host/container egress-deny policy. Writable model, package, renderer, wheel, or
bootstrap mounts fail preflight.

## Build and verify the independent launcher

Build the production binary in a pinned Linux x86_64 toolchain, then copy only
the resulting root-owned non-writable binary into the immutable final image.
Use a config-clean final stage rather than inheriting CUDA image `ENV` entries:
NVIDIA CUDA bases commonly define `LD_LIBRARY_PATH`, and the launcher correctly
refuses to start when any `LD_*` name is present.

```sh
cc -std=c17 -O2 -Wall -Wextra -Werror \
  -static-pie -fstack-protector-strong -D_FORTIFY_SOURCE=3 \
  deployment/science_local_gemma_launcher.c \
  -Wl,-z,relro,-z,now,-z,noexecstack \
  -o /approved/ro/bin/science-local-gemma-launcher

! readelf -lW /approved/ro/bin/science-local-gemma-launcher | grep -q INTERP
ldd /approved/ro/bin/science-local-gemma-launcher 2>&1 \
  | grep -Eq 'not a dynamic executable|statically linked'
```

Record the compiler package/version, launcher SHA-256, and both command outputs
in the immutable image build receipt. The launcher also checks Linux auxiliary
vector state at runtime and refuses a dynamic interpreter. Run the container as
one fixed non-root UID/GID; the same UID must own the two `0400` secret files,
while `/run/secrets` itself is root-owned and not group/world writable.

The config-clean final image must contain exactly one passwd and group identity
for numeric `65532:65532`, both named `science-gemma`. Its passwd entry has the
nonexistent home `/nonexistent` and `/usr/sbin/nologin`; do not create that home.
`/etc/passwd` and `/etc/group` remain root-owned and not group/world writable.
This identity is required even though the post-attestation environment supplies
private cache roots: PyTorch and other native dependencies may resolve the
effective UID through libc while importing. Before promotion, prove
`pwd.getpwuid(65532)` returns only that record, the configured container user is
still `65532:65532`, and the exact clean-environment, read-only, network-none,
private-`/tmp` GPU import of vLLM and PyTorch succeeds.

## Pin the GPU CDI identity

The production launcher requires real and effective UID/GID `65532:65532` and
an exact supplementary-group vector of `[65532]`. Prove the latter with
`os.getgroups()` or `/proc/self/status` `Groups:`; `id -G` is insufficient
because it can print the primary GID even when that GID is absent from the
supplementary vector. The launcher performs this check before it parses serving
settings or opens either secret.

Docker's default NVIDIA CDI entry can add the host `video` and `render` GIDs.
Do not use `--gpus` for this release and do not weaken the launcher to accept
those groups. On the approved host, independently pin and verify root ownership,
non-writable modes, versions, and SHA-256 digests for `/usr/bin/nvidia-ctk` and
`/usr/bin/nvidia-cdi-hook`. The supported generator is NVIDIA Container Toolkit
`1.19.1`. Generate exactly one index-named device, without an `all` alias and
without device-node supplementary GIDs:

```sh
sudo /usr/bin/nvidia-ctk cdi generate \
  --device-name-strategy index \
  --devices 0 \
  --no-all-device \
  --vendor science.local \
  --class gemma-compute \
  --feature-flag no-additional-gids-for-device-nodes \
  --format json \
  --output /run/science-local-gemma-cdi-stage/generated.tmp
```

Create `/run/science-local-gemma-cdi-stage` with a no-replace `mkdir` that
fails if the path already exists, then make it root-owned with exact mode
`0700`. It and the root-owned, non-group/world-writable
`/var/run/cdi` discovery directory must be on the same filesystem. Before
publication, parse the generated JSON and prove all of the following:

- the kind is exactly `science.local/gemma-compute`;
- the complete device-name list is exactly `["0"]`;
- no object at any depth has an `additionalGids` member;
- the spec contains one selected physical GPU and no KFD, framebuffer, or
  other-GPU device; and
- the source is a root-owned, single-link regular file with no group or world
  write bit.

Record the spec digest, Toolkit and hook digests, Toolkit version, driver
version, exact generator argument vector, full device-node inventory, and
mount/hook counts and digests in an operator-private promotion receipt. The
generated spec contains machine-specific details; never commit it or copy it
into reports, traces, screenshots, or evaluation artifacts.

After validation, change the source to exact root ownership and mode `0444`,
fsync the source file, and fsync the staging directory. Publish it with a
same-filesystem hard link to the unique no-overwrite destination
`/var/run/cdi/science-local-gemma-ticket06.json`; link creation must fail if
any destination already exists. Fsync the CDI discovery directory, unlink the
staging name, fsync the staging directory, and only then remove the empty
staging directory. Do not overwrite NVIDIA's default spec. If link creation,
unlink, or any file or directory sync fails, do not launch against the
destination until an operator has reconciled its exact inode, digest, owner,
mode, and link count. A valid final file is root-owned, mode `0444`, has one
link, and makes exactly `science.local/gemma-compute=0` discoverable. Check both
CDI discovery directories and fail if that custom kind is defined anywhere
else.

Request that device with `--device science.local/gemma-compute=0`; never combine
it with `--gpus` or a second NVIDIA CDI device. In an otherwise production-shaped
inspection container, retain a private receipt for `os.getgroups()`, every
injected device node's path, major/minor number, mode and owner, and the absence
of KFD, framebuffer and other-GPU nodes. Also prove real/effective UID and GID
are `65532`, `os.getgroups()` is exactly `[65532]`, and `CapEff` is zero. Then
run the unmodified image entrypoint. A successful real launcher start,
authenticated preflight, and GPU vLLM response are the promotion proof; an
overridden entrypoint or import-only probe is not.

This native Toolkit spec is not claimed to be DRI-free or a minimal
compute-only ABI. It can include the selected GPU's DRI nodes and the Toolkit's
native userspace mounts and hooks. Those are an explicitly reviewed host-root
and driver trust residual outside the application receipt. Keep the container
read-only and egress-denied, retain only the one selected GPU, and repeat the
entire CDI inventory and launch proof after any driver or Toolkit change or
after the ephemeral `/run` spec is regenerated.

The fixed no-overwrite destination is one boot-generation artifact. To retire
it, first block new creates and stop every dependent container. Verify their
absence, atomically move or unlink the old file out of every CDI discovery
directory, fsync each changed directory, retain the retired digest privately,
and prove the custom kind is no longer discoverable. Only then publish a newly
staged generation and rerun every validation and live-launch gate; never
overwrite the old inode in place. Bind each private receipt to the staged and
final digest equality, final device/inode/UID/GID/mode/link count, both parent
directory stats, every publication and fsync result, the custom-kind uniqueness
proof, Docker and CDI runtime versions, the boot ID and generation time, and
all inventory, identity, capability, import, launcher, preflight, and response
results.

## Sole supported launch path

There is deliberately no package console entry point: importing package code
before authenticating that package would be circular. The sole container
entrypoint is the fixed launcher and it accepts no arguments:

```sh
/approved/ro/bin/science-local-gemma-launcher
```

After validating the fixed secret mounts, non-secret settings, executable
ownership, and bootstrap digest, the launcher replaces itself with this exact
argument shape. Only the approved absolute model path comes from the validated
non-secret environment:

```sh
/usr/bin/python3.12 -I -S -B /approved/ro/release/science_local_gemma_bootstrap.py \
  serve /approved/ro/model \
  --host 127.0.0.1 \
  --port 8000 \
  --served-model-name google/gemma-4-E4B-it \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.35 \
  --enforce-eager \
  --max-num-seqs 16 \
  --generation-config vllm \
  --tool-call-parser gemma4 \
  --enable-auto-tool-choice \
  --disable-log-requests \
  --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}' \
  --middleware studio.policy_evaluation.gemma_attestation:local_gemma_attestation_middleware
```

The executable must be the approved CPython 3.12 (`cp312`) Linux x86_64
interpreter from the immutable image. Argument order and cardinality are
canonical; global pre-command arguments, duplicate flags, and every undeclared
option, including remote-code, TLS, API-key, model, middleware, and
configuration overrides, are impossible through the launcher and are rejected
again by the bootstrap. The process uses a fresh private bytecode prefix,
disables writes, verifies all receipts before importing vLLM, then clears
artifact paths and runtime secrets from the process environment, retaining the
keys only in private authenticated-middleware state plus documented CUDA
settings, a fixed system `PATH`, and offline guards. The renderer verifier invokes only
`/usr/bin/git` with system/global configuration, hooks, fsmonitor, external
diffs, prompts, optional locks, lazy promisor fetches, and every transport
protocol disabled in a secret-free subprocess environment.

Mount the secrets as files, never environment values. The host source paths are
operator-private examples; the two container destinations are fixed by the
launcher:

```sh
docker create --read-only --user 65532:65532 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,uid=65532,gid=65532,mode=0700 \
  --mount type=bind,src=/operator/private/api-key,dst=/run/secrets/science-local-gemma-api-key,readonly \
  --mount type=bind,src=/operator/private/attestation-key,dst=/run/secrets/science-local-gemma-attestation-key,readonly \
  --entrypoint /approved/ro/bin/science-local-gemma-launcher \
  <serving-image-by-digest>
```

This excerpt specifies only secret transport and entrypoint identity. Add the
separately verified read-only artifact mounts, GPU allocation, and the
egress-denied shared-network/proxy boundary before starting the container.

Before using a candidate, inspect it and retain a redacted receipt proving that
`.Path`/`.Args` contain only the fixed no-argument launcher, `.Config.Env`
contains no API key, attestation key, `*_FILE`, `LD_*`, `DYLD_*`, or `PYTHON*`
name, and both secret destinations are read-only mounts. `docker inspect`
necessarily shows mount source/destination metadata; it must never contain the
secret file contents. The Python exec environment never contains either value.
The bootstrap necessarily holds them in process memory only after
`PR_SET_DUMPABLE=0`, and the product removes them from `os.environ` before
vLLM starts. Host root remains trusted; an unprivileged isolated UID, private
PID namespace, and no additional same-UID process in the serving container
close the remaining process-inspection path.

The fixed listener is `127.0.0.1:8000`. Every accepted Chat response carries
`X-Science-Runtime-Instance`, which must equal the signed per-process instance
ID before the evaluator parses or trusts the JSON. Response bodies are bounded
on both success and HTTP-error paths.

## Private SSH-to-namespace transport

The fixed vLLM listener is inside the egress-denied serving network namespace,
so a Docker bridge or published container port cannot safely substitute for the
loopback route. Stage `deployment/science_local_gemma_private_proxy.py`
separately, pin its SHA-256 out of band, and use exactly these two boundaries:

```text
owner-only evaluator Unix socket -> SSH stream-local forwarding
           -> group-authorized /run/science-local-gemma-proxy/science-local-gemma.sock
           -> serving-netns 127.0.0.1:8000
```

The namespace proxy must share the vLLM network namespace using
`--network container:<keeper>` or Compose `network_mode: service:keeper`; a
shared Docker bridge is not equivalent. There is no remote TCP listener or
second host process. Before launch, select one approved SSH login account and a
group whose complete membership authorizes this evaluation tunnel. Record the
account and group IDs privately, prove that the group contains no unapproved
member, and do not reuse a broad interactive group. Create
`/run/science-local-gemma-proxy` as an empty, non-symlink directory owned by UID
`65532`, assigned to that approved SSH group, and with exact Linux mode `2710`
(setgid plus owner `rwx` and group execute-only). Mount only that directory
read-write into the namespace-proxy container at the same path. The setgid bit
makes the proxy-created socket inherit the approved group without adding that
group to the serving identity. Keep the proxy script and interpreter read-only.
The vLLM container does not need this mount, and its serving-critical roots
remain read-only.

Start a secret-free network-namespace keeper first. Install and independently
verify IPv4 and IPv6 input/output default-drop rules in that namespace before
starting either serving process. Permit loopback traffic and only the explicitly
reviewed established-reply rule; do not permit a general external interface or
host-gateway route. Prove that an external address and the host gateway are
unreachable from a disposable process in the namespace. Record the keeper,
proxy, and serving image digests plus the firewall-rules hash outside evaluation
traces. Then start the namespace proxy with an empty environment:

```sh
/usr/bin/env -i /usr/bin/python3.12 -I -S -B \
  /approved/ro/release/science_local_gemma_private_proxy.py \
  namespace --socket-directory /run/science-local-gemma-proxy
```

Run it in the keeper network namespace as the same non-root UID as vLLM, with
all capabilities dropped and `no-new-privileges`. It accepts only the fixed
`science-local-gemma.sock`, creates it as mode `0660`, requires its group to
equal the mode-`2710` directory's approved group, and can connect only to
`127.0.0.1:8000`. The removed `host` role and every port, host, target,
connection-limit, or timeout override fail as invalid command lines. The one
proxy admits at most 16 group-authorized connections, uses a five-second
upstream connect timeout, preserves the 900-second bidirectional idle window,
and relays in bounded 64 KiB blocks. Start the attested vLLM service only after
the firewall and namespace-proxy checks pass.

The proxy emits no request, response, endpoint, or connection logs. API and
attestation keys are never configured on it and the attestation key never
crosses it. The bearer API key and private request/response bytes necessarily
transit the relay in bounded mutable buffers. The proxy therefore disables core
dumps and same-UID process inspection before opening its socket and erases every
used buffer after forwarding it.

Verify on the host that no process listens on remote TCP port `18000`, the
socket is owned by UID `65532`, its group is the approved SSH group, and its
mode is exactly `0660`. Also prove the directory remains owner `65532`, the same
approved group, and mode `2710`. Send `SIGTERM` to stop the proxy. It removes
the socket only when its device/inode still matches the socket it created.
Every pre-existing entry, symlink, replaced entry, unsafe directory mode,
non-owner directory, or non-canonical path fails closed and is never removed.
After an ungraceful crash, an operator must first prove that no live process
owns a stale entry before removing that exact socket manually; the proxy never
guesses that it is stale.

## Evaluator workstation

Run both the evaluator and its SSH tunnel under one dedicated evaluator service
identity. Create a private directory owned by that identity with exact mode
`0700`; its fixed socket path must not already exist. Forward Unix socket to
Unix socket, with no evaluator-side TCP listener:

```sh
ssh -N \
  -o StreamLocalBindMask=0177 \
  -L /approved/private/science-local-gemma/science-local-gemma.sock:/run/science-local-gemma-proxy/science-local-gemma.sock \
  <approved-workstation-alias>
```

The SSH account must be the one whose approved group owns the remote socket.
After connection, prove the local socket is owned by the dedicated evaluator
identity with exact mode `0600`; prove its parent remains owned by that identity
with exact mode `0700`. The Studio process must run as that same dedicated
identity. Do not use `StreamLocalBindUnlink`: a pre-existing path is an operator
stop, not something SSH may replace. No process may listen on evaluator TCP port
`18000`, and no process may listen on remote-host TCP port `18000`.

Configure:

- `SCIENCE_LOCAL_GEMMA_BASE_URL=http://127.0.0.1/v1`. This is the logical HTTP
  authority only; the transport does not dial TCP. Only literal `127.0.0.1` or
  `[::1]` loopback bases are accepted; `localhost` and trailing-dot hostnames
  are rejected.
- `SCIENCE_LOCAL_GEMMA_UNIX_SOCKET=/approved/private/science-local-gemma/science-local-gemma.sock`.
  The product rejects a missing socket, any other basename, symlinked path
  component, non-owner endpoint, mode other than `0600`, or parent directory
  mode other than `0700`.
- `SCIENCE_LOCAL_GEMMA_API_KEY` and
  `SCIENCE_LOCAL_GEMMA_ATTESTATION_KEY` with the server values.
- `SCIENCE_LOCAL_GEMMA_PRODUCT_WHEEL_SHA256` and
  `SCIENCE_LOCAL_GEMMA_TRUSTED_BOOTSTRAP_SHA256` with the independently audited
  release pins. Both are included in the signed challenge.

Do not capture token values, private hostnames, artifact paths, or SSH material
in reports, traces, screenshots, or generated evaluation artifacts. A fresh
signed preflight is required before Chat. Each scored episode has one
900-second monotonic deadline covering preflight, Chat, and Runtime actions;
expiry remains the unscored `inference.episode_timeout` infrastructure outcome.

## Run the development calibration

With the authenticated Unix tunnel active and the evaluator variables above
available only to the Studio process, start the normal loopback product:

```sh
.venv/bin/python -m studio
```

Open `http://127.0.0.1:8000`, choose **Evaluate**, and launch **Local base Gemma ·
development calibration**. The fixed plan reserves all 32 development scenarios
before inference starts. The console can be closed and reopened without losing
durable progress; an interrupted evaluation can be resumed, and every completed
scientific attempt can be replayed without contacting the model again.

Calibration is ready only when the completed matrix is within the configured
accuracy band, levels 1 and 2 each contain both a scientific success and failure,
there are no infrastructure errors, and every row carries authenticated local
runtime evidence. Adapter, attestation, timeout, and inference failures remain
unscored infrastructure outcomes rather than scientific failures.

## Run the native Verifiers conformance canary

The normal Python 3.9-compatible product environment intentionally excludes
Verifiers. Prepare a separate Python 3.11 checkout at the compiler-pinned commit;
the checkout must be clean and include Git history and tags so its distribution
version resolves exactly:

```sh
AUDITED_CHECKOUT="$PWD/../verifiers-audited"
VERIFIERS_VENV="$PWD/../verifiers-venv"
git clone https://github.com/PrimeIntellect-ai/verifiers.git "$AUDITED_CHECKOUT"
git -C "$AUDITED_CHECKOUT" checkout b878d009147876bfd1ba80feec770194f0b567c7
uv venv --python 3.11 "$VERIFIERS_VENV"
uv pip install --python "$VERIFIERS_VENV/bin/python" \
  -e "$AUDITED_CHECKOUT" 'mcp==1.28.1'
SCIENCE_VERIFIERS_PYTHON="$VERIFIERS_VENV/bin/python" \
  uv run pytest tests/evaluation/test_verifiers_native_conformance.py -q
```

The canary fails closed if the Verifiers commit, checkout cleanliness,
distribution version, MCP version, or pinned adapter source digests drift. It
exercises the native null harness against the product Runtime, including success,
scientific failure, incomplete termination, retry, privacy, and replay parity.
