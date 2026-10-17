"""FamilyMap: the vision model describes each visit photo (2.44.0).

Automatic on upload (Søren's choice): every new photo becomes a job in the
app's one model queue (core/jobqueue), so it waits behind whatever else
this app runs on the card and never beside it. The queue frees ComfyUI
before each job when Settings say so (comfyFreeFirst).

The description is for the model that answers day ideas in release 3, not
for the family: a few Danish sentences on what the place offers. It does
not describe the people in the picture - they are the family.

The model is FamilyMap's own `visionModel`, else the vision role in
Settings (FamilyLog 0.1.0; never the chat model). Without one, photos are marked
`nomodel` and wait; the admin's "Describe waiting photos" queues them once
a model is chosen. The queue is in memory, so a restart forgets queued
photos the same way - they show as waiting and the same button restarts
them.
"""
from __future__ import annotations

import base64

from app.core import jobqueue, logs, ollama

from . import familymap as fm

PROMPT = (
    "Du beskriver et billede fra en families besøg et sted, så en assistent "
    "senere kan foreslå udflugter. Skriv 2-3 korte sætninger på dansk om hvad "
    "billedet viser om STEDET: omgivelser, faciliteter, aktiviteter, mad, "
    "stemning, årstid og vejr. Beskriv ikke personernes udseende, og gæt ikke "
    "på hvem de er. Kun beskrivelsen, ingen indledning.")
MAX_CHARS = 1000
# Queue ids: negative, and far from feeds (which use -feed_id), so a photo
# job can never share a queue key with anything else.
QUEUE_BASE = 1_000_000


def queue_key(photo_id: int) -> int:
    return -(QUEUE_BASE + photo_id)


async def describe_one(photo_id: int, model: str) -> None:
    """Runs inside the queue. Owns its error handling: whatever happens,
    the photo ends in done or failed, never stuck in queued."""
    try:
        path = fm.photo_file(photo_id)
        ctx = fm.photo_context(photo_id) or {}
        hint = (f"Stedet er {ctx['placeName']} ({ctx['category']})."
                if ctx else "")
        image = base64.b64encode(path.read_bytes()).decode("ascii")
        parts: list[str] = []
        async for piece in ollama.stream_chat(model, [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"{hint} Beskriv billedet.".strip(),
                 "images": [image]}]):
            parts.append(piece)
        text = " ".join("".join(parts).split())[:MAX_CHARS]
        if not text:
            raise RuntimeError(f"{model} returned no text.")
        fm.set_describe_state(photo_id, "done", description=text)
    except fm.NotFound:
        return                      # deleted while it waited
    except Exception as exc:
        logs.record_exception(exc, f"FamilyMap photo description {photo_id}")
        fm.set_describe_state(photo_id, "failed",
                              error=(str(exc) or exc.__class__.__name__)[:500])


def enqueue(photo_ids: list[int]) -> dict:
    """Queue these photos, or mark them `nomodel` when none is chosen.
    Must be called from a running event loop (async endpoints do)."""
    model = fm.vision_model()
    if not model:
        for pid in photo_ids:
            fm.set_describe_state(pid, "nomodel")
        return {"queued": 0, "nomodel": len(photo_ids)}
    for pid in photo_ids:
        fm.set_describe_state(pid, "queued")
        gen: dict = {"text": "", "thinking": "", "done": False, "error": None,
                     "model": model, "usage": {}}

        def factory(pid=pid, gen=gen):
            async def run():
                try:
                    await describe_one(pid, model)
                finally:
                    gen["done"] = True
            return run()
        jobqueue.submit(queue_key(pid), "familymap-photo", gen, factory)
    return {"queued": len(photo_ids), "nomodel": 0}
