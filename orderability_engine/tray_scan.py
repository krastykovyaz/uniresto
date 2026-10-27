"""Photo of a plate or tray -> which dishes of the day's menu are on it.

The customer takes a picture; a vision model is shown the photo together with the day's menu (just names and
categories) and says which of THOSE dishes it sees. It can only ever answer with dishes that really are on the menu:
anything else it says is dropped here, so the app never invents a dish. Everything after that -- the nutrition
facts, the portion weights, the price -- is the app's own data for the matched dishes, priced by the same
recalculate_order() that prices a basket.

The photo is shrunk, sent to the recognizer and thrown away: it is not written to disk or logged. The recognizer is
swappable (TrayRecognizer): GeminiTrayRecognizer asks Google's Gemini API, trying a list of models in turn until one
answers (GEMINI_API_KEY, optionally GEMINI_MODELS); ClaudeTrayRecognizer talks to the Anthropic Messages API
(ANTHROPIC_API_KEY); FixedTrayRecognizer returns recorded answers (tests and the local demo). Without a key the
feature is simply off (GET /api/tray-scan/available says so, and the button is not shown).

Two answers come back: the menu dishes that ARE in the photo ("items"), and the menu dishes CLOSEST to what the
photo shows when that is not on the menu ("similar": a fruit cup for a photo of fruit, a sandwich for a sandwich).
So a photo of a packed lunch from home, or of food from anywhere, still finds something on today's menu.

Nothing here is a measurement: it is a guess about a picture, and the app says so.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import time
from typing import Protocol

import requests
from PIL import Image

logger = logging.getLogger("uniresto.tray_scan")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
REQUEST_TIMEOUT_SECONDS = 25
MAX_SIDE = 1024  # plenty to tell dishes apart, and keeps the request small and cheap
MAX_DISHES = 8  # more than a tray can hold; anything beyond is noise
MAX_SIMILAR = 4


class TrayScanError(Exception):
    """The recognizer could not answer (network, quota, an unreadable reply). The route turns it into a 502."""


class TrayRecognizer(Protocol):
    def identify(self, jpeg: bytes, candidates: list[dict]) -> "list[dict] | dict":
        """`candidates`: [{"id", "name", "category"}] -- the day's menu. Returns {"items": [{"id", "quantity"}],
        "similar": [{"id"}]}: the dishes seen in the photo, and the closest ones for what is not on the menu (a bare
        list means just "items"). Ids not in `candidates` are ignored by the caller."""


def prepare_image(jpeg: bytes) -> bytes:
    """The photo as sent to the recognizer: at most MAX_SIDE px on the long side, re-encoded JPEG."""
    with Image.open(io.BytesIO(jpeg)) as img:
        img = img.convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)
        return out.getvalue()


def validate_matches(raw: object, candidates: list[dict], max_quantity: int) -> list[dict]:
    """Keeps only well-formed answers about dishes that exist on today's menu: each id once, quantity clamped to
    1..max_quantity, at most MAX_DISHES dishes. Anything else the model said is dropped."""
    allowed = {c["id"] for c in candidates}
    if not isinstance(raw, list):
        return []
    seen: set[int] = set()
    matches: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        dish_id, quantity = entry.get("id"), entry.get("quantity", 1)
        if isinstance(dish_id, bool) or not isinstance(dish_id, int) or dish_id not in allowed or dish_id in seen:
            continue
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            quantity = 1
        seen.add(dish_id)
        matches.append({"id": dish_id, "quantity": max(1, min(quantity, max_quantity))})
        if len(matches) == MAX_DISHES:
            break
    return matches


def validate_scan(raw: object, candidates: list[dict], max_quantity: int) -> tuple[list[dict], list[dict]]:
    """(items, similar) from a recognizer's answer (a dict, or a bare list meaning only "items"), both checked
    against the menu. A dish is in at most one list, and a similar dish is always one portion."""
    items_raw, similar_raw = (raw.get("items"), raw.get("similar")) if isinstance(raw, dict) else (raw, None)
    items = validate_matches(items_raw, candidates, max_quantity)
    taken = {m["id"] for m in items}
    similar = [{"id": m["id"], "quantity": 1} for m in validate_matches(similar_raw, candidates, 1) if m["id"] not in taken]
    return items, similar[:MAX_SIMILAR]


_PROMPT = """This is a photo of food, from a university canteen or from anywhere else. Below is the canteen's menu for the day.

Answer two things, using only dishes of THIS menu, by their id:
1. "items": the menu dishes you can see in the photo, and how many portions of each.
   - If you are not reasonably sure a menu dish is in the photo, leave it out. A wrong dish is worse than a missing one.
   - Count portions only when you can clearly see more than one. Otherwise use 1.
2. "similar": for food in the photo that is NOT on the menu (or when the photo shows no menu dish at all), up to 4
   menu dishes that are the closest equivalent, meaning the same kind of food (a fruit cup for fruit, a sandwich for a
   sandwich, a salad for a salad, a soft drink for a soft drink). Include a dish only when it is a genuinely close
   match, and never list a dish in both lists. If nothing on the menu is close, leave the list empty.

Reply with JSON only, no other text:
{{"items": [{{"id": <menu id>, "quantity": <number>}}], "similar": [{{"id": <menu id>}}]}}

Menu (id | category | name):
{menu}
"""


class ClaudeTrayRecognizer:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, session: requests.Session | None = None):
        self._api_key = api_key
        self._model = model
        self._http = session or requests

    def identify(self, jpeg: bytes, candidates: list[dict]) -> dict:
        menu = "\n".join(f"{c['id']} | {c['category']} | {c['name']}" for c in candidates)
        body = {
            "model": self._model,
            "max_tokens": 600,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")},
                        },
                        {"type": "text", "text": _PROMPT.format(menu=menu)},
                    ],
                }
            ],
        }
        try:
            response = self._http.post(
                API_URL,
                headers={"x-api-key": self._api_key, "anthropic-version": API_VERSION, "content-type": "application/json"},
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            text = "".join(block.get("text", "") for block in response.json().get("content", []) if block.get("type") == "text")
        except (requests.RequestException, ValueError) as exc:
            # The message of a RequestException can echo the URL but never carries the key (it travels in a header).
            logger.warning("tray scan request failed: %s", type(exc).__name__)
            raise TrayScanError("the recognizer could not be reached") from exc
        return _items_from_reply(text)


def _items_from_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise TrayScanError("the recognizer's reply had no JSON")
    try:
        answer = json.loads(text[start : end + 1])
        items, similar = answer.get("items"), answer.get("similar")
    except (ValueError, AttributeError) as exc:
        raise TrayScanError("the recognizer's reply was not valid JSON") from exc
    return {"items": items if isinstance(items, list) else [], "similar": similar if isinstance(similar, list) else []}


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tried in this order; the first to answer wins. Overridable with GEMINI_MODELS (comma separated) because Google
# retires and renames models: a name that no longer exists just falls through to the next one.
DEFAULT_GEMINI_MODELS = ("gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-3.5-flash")
GEMINI_PER_MODEL_TIMEOUT_SECONDS = 15
GEMINI_TOTAL_BUDGET_SECONDS = 28  # the request holds a web worker; never let the loop outlast it by much


class GeminiTrayRecognizer:
    """Asks Gemini, model after model. Quota (429), overload (5xx), an unknown model (404) or a bad request for
    that model (400) move on to the next model; a rejected key (401/403) stops at once, since no model would
    accept it. The key travels in a header, never in the URL, so it cannot end up in an access log."""

    def __init__(self, api_key: str, models: tuple[str, ...] | list[str] = DEFAULT_GEMINI_MODELS,
                 session: requests.Session | None = None, clock=time.monotonic):
        if not models:
            raise ValueError("at least one Gemini model is needed")
        self._api_key = api_key
        self._models = tuple(models)
        self._http = session or requests
        self._clock = clock

    def identify(self, jpeg: bytes, candidates: list[dict]) -> dict:
        menu = "\n".join(f"{c['id']} | {c['category']} | {c['name']}" for c in candidates)
        body = {
            "contents": [
                {
                    "parts": [
                        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(jpeg).decode("ascii")}},
                        {"text": _PROMPT.format(menu=menu)},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 2048, "responseMimeType": "application/json"},
        }
        started = self._clock()
        last_problem = "no model answered"
        for model in self._models:
            if self._clock() - started >= GEMINI_TOTAL_BUDGET_SECONDS:
                break
            try:
                response = self._http.post(
                    GEMINI_URL.format(model=model),
                    headers={"x-goog-api-key": self._api_key, "content-type": "application/json"},
                    json=body,
                    timeout=GEMINI_PER_MODEL_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                last_problem = f"{model}: {type(exc).__name__}"
                logger.warning("tray scan: %s failed (%s), trying the next model", model, type(exc).__name__)
                continue
            if response.status_code in (401, 403):
                logger.warning("tray scan: Gemini rejected the API key (%s)", response.status_code)
                raise TrayScanError("the recognizer rejected its credentials")
            if response.status_code >= 400:
                last_problem = f"{model}: HTTP {response.status_code}"
                logger.warning("tray scan: %s answered HTTP %s, trying the next model", model, response.status_code)
                continue
            try:
                return _items_from_reply(_gemini_text(response.json()))
            except (TrayScanError, ValueError) as exc:
                # An unreadable or blocked reply from this model: another model may do better.
                last_problem = f"{model}: unreadable reply"
                logger.warning("tray scan: %s gave an unreadable reply (%s), trying the next model", model, type(exc).__name__)
        raise TrayScanError(f"no Gemini model could answer ({last_problem})")


def _gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:  # e.g. the prompt was blocked
        raise TrayScanError("the recognizer returned no answer")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts)


class FixedTrayRecognizer:
    """Recorded answers, looked up by the photo's SHA-256 (of the bytes the route hands over). For tests and the
    local demo only -- it recognises nothing, it replays what was recorded for exactly that image."""

    def __init__(self, answers: "dict[str, list[dict] | dict]"):
        self._answers = answers

    @staticmethod
    def key(jpeg: bytes) -> str:
        return hashlib.sha256(jpeg).hexdigest()

    def identify(self, jpeg: bytes, candidates: list[dict]) -> "list[dict] | dict":
        return self._answers.get(self.key(jpeg), [])


def recognizer_from_env() -> TrayRecognizer | None:
    """Gemini when GEMINI_API_KEY is set (models from GEMINI_MODELS, comma separated, else the default list), else
    Claude when ANTHROPIC_API_KEY is set, else None (feature off)."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        models = tuple(m.strip() for m in os.environ.get("GEMINI_MODELS", "").split(",") if m.strip()) or DEFAULT_GEMINI_MODELS
        return GeminiTrayRecognizer(gemini_key, models)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        return ClaudeTrayRecognizer(api_key, os.environ.get("TRAY_SCAN_MODEL", "").strip() or DEFAULT_MODEL)
    return None
