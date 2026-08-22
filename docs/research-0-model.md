# Research: identity of "Gemma 4 31B"

Date: 2026-08-22

## Bottom line

"Gemma 4 31B" is a size/name label, not a single unambiguous checkpoint. The official 31B checkpoints are:

- `google/gemma-4-31B` — pre-trained/base 31B Dense checkpoint.
- `google/gemma-4-31B-it` — instruction-tuned 31B Dense checkpoint; this is the likely model meant when a chat/inference UI says Gemma 4 31B.
- `google/gemma-4-31B-it-assistant` — the official MTP/speculative-decoding drafter for the instruction-tuned model.
- Official QAT/quantized variants for the IT model:
  - `google/gemma-4-31B-it-qat-q4_0-unquantized`
  - `google/gemma-4-31B-it-qat-q4_0-unquantized-assistant`
  - `google/gemma-4-31B-it-qat-q4_0-gguf`
  - `google/gemma-4-31B-it-qat-w4a16-ct`

Sources: Google Gemma 4 docs/model card and Hugging Face official Google collection/repos:
- https://ai.google.dev/gemma/docs/core
- https://ai.google.dev/gemma/docs/core/model_card_4
- https://huggingface.co/collections/google/gemma-4
- https://huggingface.co/collections/google/gemma-4-qat-q4-0

## Facts

### Naming and model IDs

Google's Gemma 4 model card says Gemma 4 is available in five sizes: E2B, E4B, 12B, 26B A4B, and 31B, with pre-trained and instruction-tuned variants. It describes the 31B model as a Dense model. Source: https://ai.google.dev/gemma/docs/core/model_card_4

The official Hugging Face Gemma 4 collection lists both `google/gemma-4-31B-it` and `google/gemma-4-31B`, and also lists `google/gemma-4-31B-it-assistant`. Source: https://huggingface.co/collections/google/gemma-4

The Google DeepMind Gemma 4 page links its “Try Gemma 4 in Google AI Studio” CTA to `model=gemma-4-31b-it`, which supports the assumption that chat/inference references to “Gemma 4 31B” usually mean the IT model. Source: https://deepmind.google/models/gemma/gemma-4/

### Architecture

The 31B model is a Dense Gemma 4 model, not the MoE `26B A4B` model. The Gemma 4 model card labels the column `31B Dense`. Source: https://ai.google.dev/gemma/docs/core/model_card_4

The official HF configs for `google/gemma-4-31B` and `google/gemma-4-31B-it` set:

- `architectures`: `Gemma4ForConditionalGeneration`
- `model_type`: `gemma4`
- top-level `dtype`: `bfloat16`
- `audio_config`: `null`
- text config: 60 hidden layers, hidden size 5376, intermediate size 21504, 32 attention heads, 16 KV heads, 4 global KV heads, sliding window 1024, vocabulary size 262144, max position embeddings 262144
- vision config: 27 layers, hidden size 1152, 16 attention heads, 280 soft tokens per image

Sources:
- https://huggingface.co/google/gemma-4-31B/raw/main/config.json
- https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json

The model card says Gemma 4 uses a hybrid attention mechanism interleaving local sliding-window attention with full global attention, with the final layer always global; global layers use unified Keys/Values and proportional RoPE. Source: https://ai.google.dev/gemma/docs/core/model_card_4

### Parameters

The public name “31B” is rounded/marketing scale. The Google model card says the `31B Dense` model has `30.7B` total parameters and a ~550M vision encoder. Source: https://ai.google.dev/gemma/docs/core/model_card_4

The official HF safetensors index metadata for both `google/gemma-4-31B` and `google/gemma-4-31B-it` reports `total_parameters: 32682372656`. Sources:
- https://huggingface.co/google/gemma-4-31B/raw/main/model.safetensors.index.json
- https://huggingface.co/google/gemma-4-31B-it/raw/main/model.safetensors.index.json

Therefore, use both numbers carefully:

- Official model-card size: `31B Dense`, listed as `30.7B`.
- Exact serialized HF checkpoint parameter count: `32,682,372,656` parameters.

### Modalities and context length

For 31B Dense, the model card lists supported modalities as Text and Image, not Audio. Source: https://ai.google.dev/gemma/docs/core/model_card_4

The model card lists the 31B Dense context length as 256K tokens. Source: https://ai.google.dev/gemma/docs/core/model_card_4

The official HF config sets `text_config.max_position_embeddings` to `262144`, matching 256K tokens. Sources:
- https://huggingface.co/google/gemma-4-31B/raw/main/config.json
- https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json

### Precision and quantization

The default/full checkpoints are bfloat16: the official HF configs set top-level `dtype` and text/vision `dtype` to `bfloat16`. Sources:
- https://huggingface.co/google/gemma-4-31B/raw/main/config.json
- https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json

Google's Gemma 4 overview says models can be used at default 16-bit precision or with lower precision quantization, and its memory table includes BF16 (16-bit), SFP8 (8-bit), and Q4_0 (4-bit) columns. Source: https://ai.google.dev/gemma/docs/core

Google's Gemma 4 QAT docs list official QAT formats:

- `-qat-q4_0-gguf` for llama.cpp / LM Studio.
- `-qat-w4a16-ct` for vLLM / SGLang, using 4-bit weights and 16-bit activations.
- `-qat-q4_0-unquantized` and `-qat-q4_0-unquantized-assistant` for speculative decoding / conversion.
- mobile formats are only for E2B and E4B, not 31B.

Source: https://ai.google.dev/gemma/docs/core

The official HF QAT Q4_0 collection lists the 31B IT quantization-related repos:

- `google/gemma-4-31B-it-qat-q4_0-unquantized`
- `google/gemma-4-31B-it-qat-q4_0-unquantized-assistant`
- `google/gemma-4-31B-it-qat-q4_0-gguf`
- `google/gemma-4-31B-it-qat-w4a16-ct`

Source: https://huggingface.co/collections/google/gemma-4-qat-q4-0

### License and access

Gemma 4 model card states license: Apache 2.0. Source: https://ai.google.dev/gemma/docs/core/model_card_4

The Google Gemma Apache 2.0 license page is: https://ai.google.dev/gemma/apache_2

The official HF repos tag/card-data list `license: apache-2.0`, are public, and are not gated (`gated: false` in the collection/API). Sources:
- https://huggingface.co/google/gemma-4-31B
- https://huggingface.co/google/gemma-4-31B-it
- https://huggingface.co/collections/google/gemma-4

### MTP / speculative decoding

Gemma 4 has official MTP/speculative-decoding support. The overview says all Gemma 4 models, including 31B, include a dedicated draft model for speculative decoding. Source: https://ai.google.dev/gemma/docs/core

The MTP overview says Gemma 4 implements MTP by extending the base model with a smaller, faster draft model that shares the input embedding table and builds on the target model's last-layer activations. Source: https://ai.google.dev/gemma/docs/mtp/overview

The HF MTP guide says a new series of autoregressive drafter models was released alongside the main Gemma 4 lineup; it refers to the drafter as the MTP head. It lists `google/gemma-4-31B-it` as a valid target and derives the assistant as `TARGET_MODEL_ID + "-assistant"`. Source: https://ai.google.dev/gemma/docs/mtp/mtp

The official assistant config for 31B IT sets:

- `architectures`: `Gemma4AssistantForCausalLM`
- `model_type`: `gemma4_assistant`
- `backbone_hidden_size`: 5376
- assistant text config: 4 hidden layers, hidden size 1024, max position embeddings 262144

Source: https://huggingface.co/google/gemma-4-31B-it-assistant/raw/main/config.json

Important distinction: the main model checkpoints (`google/gemma-4-31B`, `google/gemma-4-31B-it`) do not advertise `Gemma4AssistantForCausalLM` in their own configs; the assistant/drafter is a separate official checkpoint. Sources:
- https://huggingface.co/google/gemma-4-31B/raw/main/config.json
- https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json
- https://huggingface.co/google/gemma-4-31B-it-assistant/raw/main/config.json

## Assumptions / ambiguity

- If the user says only “Gemma 4 31B,” that could mean either the base `google/gemma-4-31B` or instruction-tuned `google/gemma-4-31B-it` checkpoint. If the context is chat, Google AI Studio, or hosted inference, assume `google/gemma-4-31B-it` unless told otherwise.
- “31B” is not the exact serialized parameter count. It is the official rounded size label. The Google model card reports `30.7B`; the HF safetensors index reports `32,682,372,656` serialized parameters.
- “Native MTP heads” can be misleading. Gemma 4 31B has official/native MTP support through separate assistant/drafter checkpoints. The main checkpoint config itself does not contain an embedded assistant architecture.
