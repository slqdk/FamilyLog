"""Mock Ollama server for tests and the browser check (not shipped as a feature).

Emulates enough of the Ollama HTTP API for FamilyLog:
  /api/version /api/tags /api/show /api/ps /api/chat (streaming, thinking,
  JSON format, images, token timings)

Run:  python tools/mock_ollama.py [port]     (default 127.0.0.1:11434;
      env MOCK_OLLAMA_PORT works too)

The answers are tailored to the sections' prompts, told apart by their
system prompt (kept from SLQ's mock, ledger branches unchanged):
  Økonomi    - the search (JSON), the answer (repeats the app's "Result:"
               line, so a test sees the model was handed the exact numbers),
               merchant categories (JSON)
  FamilyMap  - Spørg Alf's understanding (JSON), the web pick (JSON), the
               answer (links the first listed place as [[id]]), and a
               Danish photo description for a message with images
No real data in here.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {
    "qwen3.6:27b": {"size": 17_400_000_000, "family": "qwen3", "params": "27B",
                    "quant": "Q4_K_M", "ctx": 131072, "tps": 28.0, "thinking": True},
    "gemma4:12b": {"size": 8_100_000_000, "family": "gemma3", "params": "12B",
                   "quant": "Q4_K_M", "ctx": 131072, "tps": 44.0, "thinking": False},
    "qwen3-vl:8b": {"size": 6_100_000_000, "family": "qwen3vl", "params": "8B",
                    "quant": "Q4_K_M", "ctx": 32768, "tps": 40.0, "thinking": False},
}

_loaded: dict[str, float] = {}   # model -> load wall time


def _tok(s: str) -> int:
    return max(1, len(s) // 4)


def _ledger_spec(text: str) -> dict:
    """A plausible search for the Økonomi questions the tests ask."""
    spec: dict = {"merchants": [], "words": [], "categories": [], "kinds": [],
                  "from": None, "to": None, "direction": "out", "group": "none",
                  "measure": "sum", "order": "largest", "top": None,
                  "includeTransfers": False}
    prev = re.search(r"^Previous search: (\{.*\})$", text, re.M)
    if prev:
        spec.update(json.loads(prev.group(1)))
        text = text.split("New question:", 1)[-1]
    low = text.lower()
    for shop in ("davidsens", "netto", "proshop", "nowhere-shop"):
        if shop in low:
            spec["merchants"] = [shop]
    if "betalingsservice" in low:
        spec["kinds"] = ["betalingsservice"]
    if "groceries" in low:
        spec["categories"] = ["groceries"]
    if "most expensive" in low:
        spec.update(measure="list", order="largest", top=3)
    if "per month" in low:
        spec["group"] = "month"
    if "2025" in low:
        spec.update({"from": "2025-01-01", "to": "2025-12-31"})
    if "transfer" in low:
        spec["includeTransfers"] = True
    return spec


_FM_CATS = {"legeplads": "playground", "playground": "playground", "pizza": "restaurant",
            "restaurant": "restaurant", "spise": "restaurant", "museum": "attraction",
            "strand": "nature", "skov": "nature", "svømmehal": "activity"}


def _fm_intent(question: str) -> dict:
    low = question.lower()
    cats = sorted({c for w, c in _FM_CATS.items() if w in low})
    m = re.search(r"\bi ([A-ZÆØÅ][\wæøå]+)", question)
    words = [w for w in ("pizza", "sushi", "is") if re.search(rf"\b{w}\b", low)]
    age = re.search(r"(\d+)\s*år", low)
    return {"location": m.group(1) if m else None, "nearMe": not m,
            "categories": cats, "keywords": words,
            "age": int(age.group(1)) if age else None, "radiusKm": None}


def _answer_for(model: str, messages: list[dict], fmt) -> tuple[str, str]:
    """(thinking, answer) for the sections' prompts."""
    last = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last = m.get("content") or ""
            break
    think = ""
    if MODELS.get(model, {}).get("thinking"):
        think = f"The user asks: {last[:80]}... I should answer concisely."
    system = next((m.get("content") or "" for m in messages if m.get("role") == "system"), "")

    # ---- Økonomi ----
    if "bank transactions into a search" in system:
        return think, json.dumps(_ledger_spec(last))
    if "You answer questions about the person's own bank transactions" in system:
        m = re.search(r"^Result: (.*)$", last, re.M)
        rows = re.findall(r"^- (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| ([^|]+) \|", last, re.M)[:2]
        table = ("\n\n| Dato | Navn | Beløb |\n| :--- | :--- | :--- |\n"
                 + "\n".join(f"| {d} | {n.strip()} | {a.strip()} |" for d, n, a in rows)) if rows else ""
        if table:                    # a Markdown table, as a real model writes one (FamilyLog 0.3.13)
            return think, ("From the ledger: " + (m.group(1) if m else "nothing matched.")
                           + ("\n\nOwn transfers were left out." if "Own transfers left out" in last else "")
                           + table)
        return think, ("From the ledger: " + (m.group(1) if m else "nothing matched.")
                       + "\n\nOwn transfers were left out." if "Own transfers left out" in last
                       else "From the ledger: " + (m.group(1) if m else "nothing matched."))
    if "You sort shops and payees" in system:
        out = {}
        for line in last.splitlines():
            mm = re.match(r"^(\d+)\. (.*)$", line)
            if mm:
                text = mm.group(2).lower()
                out[mm.group(1)] = ("leisure" if "ishock" in text else
                                    "fast-food" if "grill" in text else
                                    "nonsense-key" if "bogus" in text else "other")
        return think, json.dumps(out)

    # ---- Alf on the front page (FamilyLog 0.2.0) ----
    if system.startswith("Afgør hvad familiemedlemmets"):
        msg = last.split("Sidste besked:", 1)[-1].strip()
        low = msg.lower()
        places = any(w in low for w in ("legeplads", "restaurant", "pizza", "spise ude",
                                        "udflugt", "museum", "strand", "svømmehal"))
        if "og i " in low and "Samtalen indtil nu" in last:      # a follow-up
            places = True
        # 0.3.11: the family's Dagbog and Cyklus - "Hvordan har Mette det?", "Sannes cyklus"
        family = any(w in low for w in ("haft det", "har det", "hvordan har", "humør", "dagbog", "cyklus", "menstruation"))
        m = re.search(r"\b(?:har|til|om|får|med)\s+(\w+?)s?\b(?:\s|\?|$)", msg)
        person = m.group(1) if family and m else None
        # 0.3.12: one's own Økonomi - "Hvor meget har jeg brugt hos Davidsens?"
        money = not family and any(w in low for w in ("brugt", "penge", "økonomi", "forbrug", "kostet", "og i 20"))
        if money and not person:
            m2 = re.search(r"\bhar\s+([A-ZÆØÅ]\w+?)s?\s+brugt", msg)
            person = m2.group(1) if m2 else None
        return think, json.dumps({"places": places and not money, "family": family, "money": money,
                                  "person": person, "question": msg})
    if "fra familiens Dagbog og Cyklus" in system:
        heads = [ln[3:] for ln in last.splitlines() if ln.startswith("## ")]
        facts = [ln for ln in last.splitlines() if ln.startswith(("- ", "Cyklus", "Hun deler"))]
        return think, "Alf om familien: " + " | ".join(heads + facts[:6])
    if system.startswith("Du er Alf, en venlig hjælper"):
        n = sum(1 for m in messages if m.get("role") == "user")
        return think, f"Hej! Det er Alf. Du skrev: \"{last[:80]}\" ({n} beskeder i samtalen)."

    # ---- FamilyMap ----
    if system.startswith("Du hjælper en familie"):
        return think, json.dumps(_fm_intent(last))
    if system.startswith("Nedenfor er søgeresultater"):
        return think, json.dumps({"places": []})
    if system.startswith("Du er Alf"):
        m = re.search(r"^\[(\d+)\] ([^,(]+)", last, re.M)
        if m:
            return think, f"Prøv {m.group(2).strip()} [[{m.group(1)}]] - den passer til spørgsmålet."
        return think, "Jeg fandt ingen steder, der passer. Prøv at udvide søgningen."
    if any(msg.get("images") for msg in messages):
        return think, "En legeplads med gynger og en sandkasse i solskin. Der er bænke i skyggen."
    return think, "Mock answer."


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _hub_refuses(self) -> bool:
        """SLQ Hub's gate, roughly (FamilyLog 0.4.0): a Bearer key that is not an
        slqhub_ key, or one with "revoked" in it, gets 401. No header: plain Ollama."""
        auth = self.headers.get("Authorization")
        if auth is not None and (not auth.startswith("Bearer slqhub_") or "revoked" in auth):
            self._json({"error": "invalid or disabled API key"}, 401)
            return True
        return False

    def do_GET(self):
        if self._hub_refuses():
            return
        if self.path == "/api/version":
            return self._json({"version": "0.32.5-mock"})
        if self.path == "/api/tags":
            return self._json({"models": [
                {"name": n, "model": n, "size": m["size"], "modified_at": "2026-07-01T00:00:00Z",
                 "details": {"family": m["family"], "parameter_size": m["params"],
                             "quantization_level": m["quant"]}} for n, m in MODELS.items()]})
        if self.path == "/api/ps":
            return self._json({"models": [
                {"name": n, "model": n, "size": MODELS[n]["size"],
                 "size_vram": MODELS[n]["size"], "context_length": MODELS[n]["ctx"],
                 "expires_at": "2026-12-31T00:00:00Z"} for n in _loaded]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(length) or b"{}")
        if self._hub_refuses():
            return
        if self.path == "/api/show":
            m = MODELS.get(req.get("model") or req.get("name") or "")
            if not m:
                return self._json({"error": "model not found"}, 404)
            return self._json({"model_info": {f"{m['family']}.context_length": m["ctx"]}})
        if self.path == "/api/chat":
            return self._stream_chat(req)
        self._json({"error": "not found"}, 404)

    def _stream_chat(self, req):
        model = req.get("model") or ""
        if model not in MODELS:
            return self._json({"error": f"model '{model}' not found"}, 404)
        first_load = model not in _loaded
        if first_load:
            _loaded.clear()          # one model on the card at a time
            _loaded[model] = time.time()
            time.sleep(0.2)          # pretend to load
        think, answer = _answer_for(model, req.get("messages", []), req.get("format"))

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def frame(obj):
            self.wfile.write((json.dumps(obj) + "\n").encode())
            self.wfile.flush()

        low = " ".join((m.get("content") or "") for m in req.get("messages", [])).lower()
        pace = 0.2 if "slowly" in low else 0.01
        if req.get("think") is False:
            think = ""
        if think:
            words = think.split(" ")
            for i in range(0, len(words), 4):
                frame({"model": model, "message": {"role": "assistant",
                       "thinking": " ".join(words[i:i + 4]) + " ", "content": ""}, "done": False})
                time.sleep(pace)
        for i in range(0, len(answer), 40):
            frame({"model": model, "message": {"role": "assistant", "content": answer[i:i + 40]},
                   "done": False})
            time.sleep(pace)
        tps = MODELS[model]["tps"] or 30
        prompt_text = " ".join((m.get("content") or "") for m in req.get("messages", []))
        p_tok, r_tok = _tok(prompt_text), _tok(answer) + _tok(think)
        frame({"model": model, "message": {"role": "assistant", "content": ""}, "done": True,
               "done_reason": "stop",
               "prompt_eval_count": p_tok,
               "prompt_eval_duration": int(p_tok / (tps * 14) * 1e9),
               "eval_count": r_tok,
               "eval_duration": int(r_tok / tps * 1e9),
               "load_duration": int(2.5e9) if first_load else int(3e7),
               "total_duration": int(r_tok / tps * 1e9) + (int(2.5e9) if first_load else 0)})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("MOCK_OLLAMA_PORT", "11434"))
    print(f"mock ollama on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()
