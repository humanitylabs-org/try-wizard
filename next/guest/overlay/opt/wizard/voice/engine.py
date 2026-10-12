"""Wizard voice engine: local Parakeet speech-to-text behind the Transcriber app's OpenAI-compatible API.

Same model and runtime as the benchmarked Wizard Parakeet lane (meeting-transcription benchmark, 22 Aug 2026):
istupakov/parakeet-tdt-0.6b-v2-onnx @ 0bbb45a, INT8 encoder/decoder, onnx-asr on onnxruntime CPU, audio cut into
20-30 s pieces at the quietest point. Runs in the Transcriber app's engine container on the Hermes image already on
the box (it has Python 3.13 and ffmpeg), so voice adds the model and three Python wheels, not another image.

  GET  /health                      200 {"status":"ready"} | 503 {"status":"preparing", ...progress}
  GET  /v1/models                   the model, once ready
  POST /v1/audio/transcriptions     multipart: file, model?, response_format? (json|text|verbose_json)

First start downloads the model (pinned revision, every file checked against its SHA-256) into /data; the Python
wheels are installed by start.sh before this runs. Stdlib HTTP server; one transcription at a time.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL_ID = "istupakov/parakeet-tdt-0.6b-v2-onnx"
REVISION = "0bbb45a3365852604aef28b538a8f066f4ccaa85"
FILES = {  # name: (bytes, sha256)
    "encoder-model.int8.onnx": (652184014, "3e0581fda6ab843888b51e56d7ee78b6d5bc3237ec113af1f732d1d5286aa155"),
    "decoder_joint-model.int8.onnx": (8998286, "a449f49acd68979d418651dd2dcb737cc0f1bf0225e009e29ee326354edbf7d3"),
    "vocab.txt": (9384, "ec182b70dd42113aff6c5372c75cac58c952443eb22322f57bbd7f53977d497d"),
    "config.json": (97, "666903c76b9798caf2c210afd4f6cd60b08a8dbf9800ec8d7a3bc0d2148ac466"),
}
TOTAL = sum(b for b, _ in FILES.values())
DATA = Path(os.environ.get("VOICE_DATA", "/data"))
MODEL_DIR = DATA / "models" / "parakeet-tdt-0.6b-v2-int8"
PORT = int(os.environ.get("PORT", "8000"))
RATE = 16000
MAX_UPLOAD = 512 << 20

state = {"status": "preparing", "stage": "starting", "downloaded": 0, "total": TOTAL, "error": None}
model = None
lock = threading.Lock()


def log(*a):
    print("voice:", *a, file=sys.stderr, flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch_model() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    for name, (size, digest) in FILES.items():
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size == size and (dest.with_suffix(dest.suffix + ".ok").exists() or sha256(dest) == digest):
            dest.with_suffix(dest.suffix + ".ok").touch()
            done += size
            state["downloaded"] = done
            continue
        part = dest.with_suffix(dest.suffix + ".part")
        url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}"
        for attempt in range(1, 9):
            have = part.stat().st_size if part.exists() else 0
            try:
                req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
                with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab" if have and r.status == 206 else "wb") as f:
                    if r.status != 206:
                        have = 0
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                        have += len(chunk)
                        state["downloaded"] = done + have
                break
            except Exception as e:  # network blip: resume from what we have
                state["stage"] = f"download retry {attempt}: {type(e).__name__}"
                log("download", name, "attempt", attempt, e)
                time.sleep(min(60, 5 * attempt))
        else:
            raise RuntimeError(f"could not download {name}")
        if part.stat().st_size != size or sha256(part) != digest:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{name}: checksum mismatch, will download again")
        part.rename(dest)
        dest.with_suffix(dest.suffix + ".ok").touch()
        done += size
        state["downloaded"] = done
        log("have", name)


def prepare() -> None:
    global model
    delay = 10
    while True:
        try:
            state.update(stage="downloading model", error=None)
            fetch_model()
            state["stage"] = "loading model"
            import onnx_asr
            import onnxruntime as rt
            so = rt.SessionOptions()
            so.intra_op_num_threads = max(1, (os.cpu_count() or 2) - 1)
            so.enable_cpu_mem_arena = False   # give memory back between requests (the box shares RAM with every app)
            m = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v2", str(MODEL_DIR), quantization="int8",
                                    sess_options=so, providers=["CPUExecutionProvider"])
            model = m.with_timestamps()
            # Warm up so the first real request isn't the slow one.
            import numpy as np
            model.recognize(np.zeros(RATE, dtype=np.float32))
            state.update(status="ready", stage="ready")
            log("ready")
            return
        except Exception as e:
            state.update(status="preparing", stage="retrying", error=f"{type(e).__name__}: {str(e)[:300]}")
            log("prepare failed:", e)
            time.sleep(delay)
            delay = min(delay * 2, 600)


def decode(data: bytes):
    """Any audio/video ffmpeg reads -> 16 kHz mono float32."""
    import numpy as np
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                        "-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1"],
                       input=data, capture_output=True, timeout=600)
    if p.returncode != 0:
        raise ValueError("could not read audio: " + p.stderr.decode(errors="replace")[-300:])
    return np.frombuffer(p.stdout, dtype=np.float32).copy()


def pieces(audio):
    """Cut at the quietest 100 ms between 20 and 30 s (the benchmarked chunking), so words aren't split."""
    import numpy as np
    out, start, n = [], 0, len(audio)
    win = RATE // 10
    while n - start > 30 * RATE:
        lo, hi = start + 20 * RATE, start + 30 * RATE
        seg = audio[lo:hi][: (hi - lo) // win * win].reshape(-1, win)
        cut = lo + int(np.argmin((seg ** 2).mean(axis=1))) * win + win // 2
        out.append((start, audio[start:cut]))
        start = cut
    out.append((start, audio[start:]))
    return out


def transcribe(audio):
    import numpy as np
    text_parts, segments, words = [], [], []
    for off, chunk in pieces(audio):
        if len(chunk) < RATE // 10 or float(np.sqrt((chunk ** 2).mean())) < 1e-4:  # silence: no words
            continue
        r = model.recognize(chunk)
        t = (r.text or "").strip()
        if not t:
            continue
        s0 = off / RATE
        text_parts.append(t)
        segments.append({"id": len(segments), "start": round(s0, 2), "end": round(s0 + len(chunk) / RATE, 2), "text": t})
        cur = None
        for tok, ts in zip(r.tokens or [], r.timestamps or []):
            if tok.startswith(" ") or tok.startswith("\u2581") or cur is None:
                if cur:
                    words.append(cur)
                cur = {"word": tok.replace("\u2581", " ").strip(), "start": round(s0 + ts, 2), "end": round(s0 + ts + 0.08, 2)}
            else:
                cur["word"] += tok
                cur["end"] = round(s0 + ts + 0.08, 2)
        if cur:
            words.append(cur)
    return " ".join(text_parts), segments, words


class H(BaseHTTPRequestHandler):
    server_version = "wizard-voice/1"

    def log_message(self, fmt, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/health", "/healthz"):
            return self.send(200 if state["status"] == "ready" else 503, {**state, "model": MODEL_ID})
        if self.path.startswith("/v1/models"):
            data = [{"id": MODEL_ID, "object": "model", "owned_by": "istupakov", "task": "automatic-speech-recognition",
                     "language": ["en"]}] if state["status"] == "ready" else []
            return self.send(200, {"object": "list", "data": data})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/v1/audio/transcriptions"):
            return self.send(404, {"error": "not found"})
        if state["status"] != "ready":
            return self.send(503, {"error": {"message": "voice is still being prepared", **state}})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_UPLOAD:
            return self.send(413 if n else 400, {"error": {"message": "send one audio file up to 512 MB"}})
        body = self.rfile.read(n)
        msg = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: " + self.headers.get("Content-Type", "").encode() + b"\r\n\r\n" + body)
        fields, audio_bytes = {}, None
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "file":
                audio_bytes = part.get_payload(decode=True)
            elif name:
                fields[name] = (part.get_payload(decode=True) or b"").decode(errors="replace")
        if not audio_bytes:
            return self.send(400, {"error": {"message": "no file"}})
        try:
            audio = decode(audio_bytes)
        except Exception as e:
            return self.send(400, {"error": {"message": str(e)}})
        t0 = time.time()
        with lock:
            text, segments, words = transcribe(audio)
        dur = len(audio) / RATE
        log(f"transcribed {dur:.1f}s audio in {time.time() - t0:.1f}s")
        fmt = fields.get("response_format", "json")
        if fmt == "text":
            return self.send(200, text, "text/plain; charset=utf-8")
        if fmt == "verbose_json":
            out = {"task": "transcribe", "language": "en", "duration": round(dur, 2), "text": text, "segments": segments}
            if any(v == "word" for k, v in fields.items() if k.startswith("timestamp_granularities")):
                out["words"] = words
            return self.send(200, out)
        self.send(200, {"text": text})


if __name__ == "__main__":
    threading.Thread(target=prepare, daemon=True).start()
    log(f"listening on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
