import io
import json

import pytest
import requests
from PIL import Image

from orderability_engine.photo_sanitize import sanitize_dish_photo
from orderability_engine.tray_scan import (
    ClaudeTrayRecognizer,
    DEFAULT_GEMINI_MODELS,
    FixedTrayRecognizer,
    GeminiTrayRecognizer,
    TrayScanError,
    prepare_image,
    recognizer_from_env,
    validate_matches,
    validate_scan,
)

CANDIDATES = [{"id": 1, "name": "Tajine", "category": "Plats"}, {"id": 2, "name": "Riz", "category": "Féculents"}, {"id": 7, "name": "Flan", "category": "Desserts"}]


def _jpeg(size=(40, 30), color=(200, 120, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


# ---- validate_matches: the model can only ever pick dishes that are on the menu

def test_only_dishes_on_the_menu_are_kept():
    assert validate_matches([{"id": 1, "quantity": 1}, {"id": 99, "quantity": 1}], CANDIDATES, 2) == [{"id": 1, "quantity": 1}]


def test_quantity_is_clamped_and_defaults_to_one():
    raw = [{"id": 1, "quantity": 9}, {"id": 2, "quantity": 0}, {"id": 7}]
    assert validate_matches(raw, CANDIDATES, 2) == [{"id": 1, "quantity": 2}, {"id": 2, "quantity": 1}, {"id": 7, "quantity": 1}]


def test_a_dish_is_listed_once():
    assert validate_matches([{"id": 1, "quantity": 1}, {"id": 1, "quantity": 2}], CANDIDATES, 2) == [{"id": 1, "quantity": 1}]


@pytest.mark.parametrize("raw", [None, "x", {"id": 1}, [None, 3, "a"], [{"id": "1"}], [{"id": True}], [{"id": 1.0}]])
def test_malformed_answers_give_nothing(raw):
    assert validate_matches(raw, CANDIDATES, 2) == []


def test_a_bool_quantity_counts_as_one():
    assert validate_matches([{"id": 1, "quantity": True}], CANDIDATES, 2) == [{"id": 1, "quantity": 1}]


def test_at_most_eight_dishes():
    many = [{"id": i, "name": f"d{i}", "category": "c"} for i in range(20)]
    assert len(validate_matches([{"id": i} for i in range(20)], many, 2)) == 8


# ---- prepare_image

def test_the_photo_is_shrunk_before_it_is_sent():
    with Image.open(io.BytesIO(prepare_image(_jpeg((4000, 3000))))) as img:
        assert max(img.size) == 1024


# ---- the Claude recognizer, against a fake HTTP session

class _Response:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class _Session:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def _reply(text):
    return _Response({"content": [{"type": "text", "text": text}]})


def test_the_request_carries_the_photo_the_menu_and_the_key_only_in_a_header():
    session = _Session(_reply('{"items": [{"id": 1, "quantity": 1}]}'))
    items = ClaudeTrayRecognizer("sk-secret", "some-model", session).identify(_jpeg(), CANDIDATES)

    url, kwargs = session.calls[0]
    assert items == {"items": [{"id": 1, "quantity": 1}], "similar": []}
    assert url == "https://api.anthropic.com/v1/messages"
    assert kwargs["headers"]["x-api-key"] == "sk-secret"
    assert "sk-secret" not in json.dumps(kwargs["json"])
    content = kwargs["json"]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert "1 | Plats | Tajine" in content[1]["text"] and "7 | Desserts | Flan" in content[1]["text"]
    assert kwargs["json"]["model"] == "some-model" and kwargs["timeout"] > 0


def test_a_reply_wrapped_in_prose_is_still_read():
    session = _Session(_reply('I can see:\n```json\n{"items": [{"id": 2, "quantity": 2}]}\n```'))
    assert ClaudeTrayRecognizer("k", session=session).identify(_jpeg(), CANDIDATES) == {"items": [{"id": 2, "quantity": 2}], "similar": []}


@pytest.mark.parametrize("reply", ["no json here", "{not json}", "}{"])
def test_an_unreadable_reply_is_an_error_not_a_guess(reply):
    with pytest.raises(TrayScanError):
        ClaudeTrayRecognizer("k", session=_Session(_reply(reply))).identify(_jpeg(), CANDIDATES)


def test_network_and_http_failures_become_one_error_that_never_shows_the_key():
    for session in (_Session(error=requests.ConnectionError("boom")), _Session(_Response({}, status=429))):
        with pytest.raises(TrayScanError) as raised:
            ClaudeTrayRecognizer("sk-secret", session=session).identify(_jpeg(), CANDIDATES)
        assert "sk-secret" not in str(raised.value)


# ---- configuration

def test_no_key_means_no_recognizer(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert recognizer_from_env() is None


def test_an_anthropic_key_turns_the_claude_recognizer_on(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("TRAY_SCAN_MODEL", "m-1")
    recognizer = recognizer_from_env()
    assert isinstance(recognizer, ClaudeTrayRecognizer) and recognizer._model == "m-1"


# ---- the recorded-answer recognizer used by tests and the demo

def test_the_fixed_recognizer_replays_only_what_was_recorded_for_that_exact_image():
    photo = _jpeg()
    recognizer = FixedTrayRecognizer({FixedTrayRecognizer.key(photo): [{"id": 1, "quantity": 1}]})
    assert recognizer.identify(photo, CANDIDATES) == [{"id": 1, "quantity": 1}]
    assert recognizer.identify(_jpeg(color=(1, 2, 3)), CANDIDATES) == []


# ---- the Gemini recognizer: models are tried in turn (free-plan quotas are per model)

class _Sequence:
    """A fake HTTP session answering each call in turn with the next item (a response, or an exception to raise)."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _gemini(text):
    return _Response({"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _model_of(call):
    return call[0].split("/models/")[1].split(":")[0]


def test_the_first_model_that_answers_wins_and_the_rest_are_not_asked():
    session = _Sequence(_gemini('{"items": [{"id": 1, "quantity": 1}]}'))
    items = GeminiTrayRecognizer("g-key", ["m-a", "m-b"], session).identify(_jpeg(), CANDIDATES)

    assert items == {"items": [{"id": 1, "quantity": 1}], "similar": []}
    assert [_model_of(c) for c in session.calls] == ["m-a"]


def test_a_quota_error_moves_on_to_the_next_model():
    session = _Sequence(_Response({}, status=429), _gemini('{"items": [{"id": 7, "quantity": 1}]}'))

    assert GeminiTrayRecognizer("k", ["m-a", "m-b"], session).identify(_jpeg(), CANDIDATES) == {"items": [{"id": 7, "quantity": 1}], "similar": []}
    assert [_model_of(c) for c in session.calls] == ["m-a", "m-b"]


@pytest.mark.parametrize("status", [404, 400, 500, 503])
def test_an_unknown_model_a_bad_request_or_an_overload_also_move_on(status):
    session = _Sequence(_Response({}, status=status), _gemini('{"items": []}'))

    assert GeminiTrayRecognizer("k", ["gone", "m-b"], session).identify(_jpeg(), CANDIDATES) == {"items": [], "similar": []}
    assert len(session.calls) == 2


def test_a_network_error_or_a_blocked_reply_moves_on_too():
    blocked = _Response({"candidates": []})  # e.g. the prompt was blocked
    session = _Sequence(requests.ConnectionError("down"), blocked, _gemini('{"items": [{"id": 2, "quantity": 1}]}'))

    assert GeminiTrayRecognizer("k", ["a", "b", "c"], session).identify(_jpeg(), CANDIDATES) == {"items": [{"id": 2, "quantity": 1}], "similar": []}
    assert len(session.calls) == 3


def test_a_rejected_key_stops_at_once():
    for status in (401, 403):
        session = _Sequence(_Response({}, status=status), _gemini('{"items": []}'))
        with pytest.raises(TrayScanError):
            GeminiTrayRecognizer("bad", ["m-a", "m-b"], session).identify(_jpeg(), CANDIDATES)
        assert len(session.calls) == 1  # no model would accept it


def test_when_every_model_fails_it_is_one_error():
    session = _Sequence(_Response({}, status=429), _Response({}, status=429), _Response({}, status=503))
    with pytest.raises(TrayScanError):
        GeminiTrayRecognizer("k", ["a", "b", "c"], session).identify(_jpeg(), CANDIDATES)


def test_the_loop_gives_up_when_the_time_budget_is_spent():
    ticks = iter([0, 0, 30, 30, 30])  # the second model would start after the 28 s budget
    session = _Sequence(_Response({}, status=429), _gemini('{"items": []}'))

    with pytest.raises(TrayScanError):
        GeminiTrayRecognizer("k", ["a", "b"], session, clock=lambda: next(ticks)).identify(_jpeg(), CANDIDATES)
    assert len(session.calls) == 1


def test_the_key_is_sent_in_a_header_never_in_the_url_or_the_body():
    session = _Sequence(_gemini('{"items": []}'))
    GeminiTrayRecognizer("g-secret", ["m-a"], session).identify(_jpeg(), CANDIDATES)

    url, kwargs = session.calls[0]
    assert kwargs["headers"]["x-goog-api-key"] == "g-secret"
    assert "g-secret" not in url and "g-secret" not in json.dumps(kwargs["json"])
    parts = kwargs["json"]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "image/jpeg"
    assert "1 | Plats | Tajine" in parts[1]["text"]
    assert kwargs["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_a_gemini_error_never_shows_the_key():
    session = _Sequence(_Response({}, status=403))
    with pytest.raises(TrayScanError) as raised:
        GeminiTrayRecognizer("g-secret", ["m"], session).identify(_jpeg(), CANDIDATES)
    assert "g-secret" not in str(raised.value)


def test_gemini_needs_at_least_one_model():
    with pytest.raises(ValueError):
        GeminiTrayRecognizer("k", [])


def test_a_gemini_key_selects_gemini_with_the_default_models(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("GEMINI_MODELS", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")  # Gemini wins when both are set

    recognizer = recognizer_from_env()

    assert isinstance(recognizer, GeminiTrayRecognizer) and recognizer._models == DEFAULT_GEMINI_MODELS


def test_gemini_models_can_be_listed_in_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GEMINI_MODELS", " model-one , ,model-two")

    assert recognizer_from_env()._models == ("model-one", "model-two")


# ---- "similar": the closest menu dishes for food that is not on the menu

def test_the_prompt_asks_for_similar_dishes_as_well_as_the_ones_seen():
    session = _Sequence(_gemini('{"items": [], "similar": []}'))
    GeminiTrayRecognizer("k", ["m"], session).identify(_jpeg(), CANDIDATES)

    prompt = session.calls[0][1]["json"]["contents"][0]["parts"][1]["text"]
    assert '"items"' in prompt and '"similar"' in prompt and "closest equivalent" in prompt


def test_a_reply_with_similar_dishes_is_read_in_full():
    session = _Sequence(_gemini('{"items": [{"id": 1, "quantity": 1}], "similar": [{"id": 2}, {"id": 7}]}'))

    answer = GeminiTrayRecognizer("k", ["m"], session).identify(_jpeg(), CANDIDATES)

    assert answer == {"items": [{"id": 1, "quantity": 1}], "similar": [{"id": 2}, {"id": 7}]}


def test_a_reply_without_a_similar_list_still_works():
    session = _Sequence(_gemini('{"items": [{"id": 1}]}'))
    assert GeminiTrayRecognizer("k", ["m"], session).identify(_jpeg(), CANDIDATES) == {"items": [{"id": 1}], "similar": []}


def test_validate_scan_keeps_only_menu_dishes_in_both_lists_and_never_lists_a_dish_twice():
    items, similar = validate_scan(
        {"items": [{"id": 1, "quantity": 2}], "similar": [{"id": 1}, {"id": 2, "quantity": 5}, {"id": 99}, {"id": 7}]}, CANDIDATES, 2
    )

    assert items == [{"id": 1, "quantity": 2}]
    assert similar == [{"id": 2, "quantity": 1}, {"id": 7, "quantity": 1}]  # not the item again, not a dish off the menu, one portion


def test_validate_scan_gives_at_most_four_similar_dishes():
    many = [{"id": i, "name": f"d{i}", "category": "c"} for i in range(10)]
    assert len(validate_scan({"items": [], "similar": [{"id": i} for i in range(10)]}, many, 2)[1]) == 4


def test_a_bare_list_answer_means_only_items():
    assert validate_scan([{"id": 1, "quantity": 1}], CANDIDATES, 2) == ([{"id": 1, "quantity": 1}], [])


@pytest.mark.parametrize("raw", [None, "x", 3, {"items": "no", "similar": "no"}, {}])
def test_validate_scan_survives_malformed_answers(raw):
    assert validate_scan(raw, CANDIDATES, 2) == ([], [])
