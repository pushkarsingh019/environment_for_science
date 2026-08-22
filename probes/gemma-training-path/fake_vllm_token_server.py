"""CPU-only fake of vLLM's token-in endpoint for the local plumbing probe.

It does not run a model. It emits one canonical Gemma 4 tool call followed by a
final answer, with aligned token IDs and log probabilities. Never use it for a
model-quality claim.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from transformers import AutoTokenizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18081)
    parser.add_argument("--model", default="fake-gemma-policy")
    parser.add_argument("--tokenizer", default="google/gemma-4-E4B-it")
    parser.add_argument(
        "--revision", default="ee0ef6023621cff504d758262d4e04895a5af4a2"
    )
    parser.add_argument("--log", type=Path, default=Path("fake-vllm-requests.jsonl"))
    return parser.parse_args()


ARGS = parse_args()
TOKENIZER = AutoTokenizer.from_pretrained(ARGS.tokenizer, revision=ARGS.revision)


def choice(token_ids: list[int]) -> dict:
    return {
        "index": 0,
        "token_ids": token_ids,
        "finish_reason": "stop",
        "logprobs": {
            "content": [
                {"token": f"token_id:{token_id}", "logprob": -0.1}
                for token_id in token_ids
            ]
        },
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        return

    def send_json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("models"):
            self.send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": ARGS.model,
                            "object": "model",
                            "max_model_len": 2048,
                        }
                    ],
                },
            )
            return
        if self.path.rstrip("/").endswith("health"):
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": {"message": f"unknown path {self.path}"}})

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size) or b"{}")
        prompt_ids = body.get("token_ids") or []
        prompt = TOKENIZER.decode(prompt_ids, skip_special_tokens=False)
        ARGS.log.parent.mkdir(parents=True, exist_ok=True)
        with ARGS.log.open("a") as output:
            output.write(
                json.dumps({"path": self.path, "prompt": prompt, "body": body}) + "\n"
            )

        if not self.path.rstrip("/").endswith("inference/v1/generate"):
            self.send_json(404, {"error": {"message": f"unknown path {self.path}"}})
            return

        if "<|tool_response>" not in prompt:
            completion = (
                '<|tool_call>call:proof_choose_route{route:<|"|>amber<|"|>}<tool_call|>'
            )
        else:
            matches = re.findall(
                r"response:proof_choose_route\{value:<\|\"\|>([^<]+)<\|\"\|>\}",
                prompt,
            )
            completion = matches[-1] if matches else "missing"

        completion_ids = TOKENIZER.encode(completion, add_special_tokens=False)
        self.send_json(
            200,
            {
                "request_id": f"fake-{time.time_ns()}",
                "choices": [choice(completion_ids)],
            },
        )


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler).serve_forever()
