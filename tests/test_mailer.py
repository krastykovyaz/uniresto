from unittest.mock import MagicMock, patch

import pytest

from orderability_engine.mailer import (
    generate_verification_code,
    is_configured,
    send_order_confirmation,
    send_order_needs_confirmation,
    send_verification_code,
)


def _plain_text(msg):
    return msg["text"]


def _order(**overrides):
    defaults = dict(
        id=42,
        restaurant_name="UDL-CKB - Altius - Restaurant",
        order_date="2026-09-24",
        delivery_location="Maison du Savoir 4.150",
        items=[
            {"name": "Rôti de porc Orloff", "quantity": 1, "line_price": None},
            {"name": "Salad'bar", "quantity": 1, "line_price": None},
        ],
        totals={"formula": {"total": 8.00, "reason": None}},
    )
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def _clear_resend_env(monkeypatch):
    # is_configured()/send_order_confirmation() read os.environ fresh on
    # every call (see mailer.py's docstring) -- start every test from a
    # clean slate regardless of what's actually set on this machine.
    for key in ("RESEND_API_KEY", "RESEND_FROM_EMAIL", "RESEND_FROM_NAME"):
        monkeypatch.delenv(key, raising=False)


def _mock_response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = json_body or {"id": "resend-message-id"}
    resp.text = ""
    return resp


def test_is_configured_false_when_env_vars_unset():
    assert is_configured() is False


def test_is_configured_true_when_api_key_set(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")
    assert is_configured() is True


def test_send_returns_not_sent_when_unconfigured():
    sent, error = send_order_confirmation("student@uni.lu", _order())
    assert sent is False
    assert "not configured" in error


def test_send_never_raises_and_reports_the_error_on_api_failure(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    with patch("orderability_engine.mailer.requests.post") as mock_post:
        mock_post.side_effect = OSError("connection refused")
        sent, error = send_order_confirmation("student@uni.lu", _order())

    assert sent is False
    assert "connection refused" in error


def test_send_reports_error_message_on_http_error_status(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    with patch("orderability_engine.mailer.requests.post") as mock_post:
        mock_post.return_value = _mock_response(status_code=403, json_body={"message": "domain not verified"})
        sent, error = send_order_confirmation("student@uni.lu", _order())

    assert sent is False
    assert error == "domain not verified"


def test_send_succeeds_and_posts_to_resend_with_configured_from(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "noreply@unilu.space")
    monkeypatch.setenv("RESEND_FROM_NAME", "UniResto")

    with patch("orderability_engine.mailer.requests.post", return_value=_mock_response()) as mock_post:
        sent, error = send_order_confirmation("student@uni.lu", _order())

    assert sent is True
    assert error is None
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["headers"]["Authorization"] == "Bearer re_placeholder"
    payload = kwargs["json"]
    assert payload["from"] == "UniResto <noreply@unilu.space>"
    assert payload["to"] == ["student@uni.lu"]


def test_email_body_never_invents_data_only_uses_the_orders_own_fields(monkeypatch):
    # Sanity check on the message content itself: every line traces back
    # to a real field already on the order dict, nothing fabricated.
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    order = _order()
    with patch("orderability_engine.mailer.requests.post", return_value=_mock_response()) as mock_post:
        send_order_confirmation("student@uni.lu", order)

    payload = mock_post.call_args.kwargs["json"]
    body = payload["text"]
    assert order["restaurant_name"] in body
    assert order["order_date"] in body
    assert "Rôti de porc Orloff x1" in body
    assert "Salad'bar x1" in body
    assert "€8.00" in body
    assert order["delivery_location"] in body
    assert f"Order #{order['id']}" in body

    # And the same real data must also appear in the HTML part -- not
    # just the plain-text one, both are sent (see mailer.py's docstring
    # on why: multipart is itself a small anti-spam signal).
    html = payload["html"]
    assert order["restaurant_name"] in html
    assert "€8.00" in html


def test_email_omits_total_line_when_formula_has_no_price(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    order = _order(totals={"formula": {"total": None, "reason": None}})
    with patch("orderability_engine.mailer.requests.post", return_value=_mock_response()) as mock_post:
        send_order_confirmation("student@uni.lu", order)

    payload = mock_post.call_args.kwargs["json"]
    assert "Total:" not in payload["text"]


# ---------------------------------------------------------------------------
# Verification codes (Part 27)
# ---------------------------------------------------------------------------


def test_generate_verification_code_is_six_digits():
    for _ in range(20):  # a handful of samples, not just one -- catches an off-by-one in the zero-padding
        code = generate_verification_code()
        assert len(code) == 6
        assert code.isdigit()


def test_generate_verification_code_pads_leading_zeros():
    # secrets.randbelow(1_000_000) can return e.g. 42 -- must still come
    # back as "000042", not "42", or the code the user types would never
    # match what was actually issued.
    with patch("orderability_engine.mailer.secrets.randbelow", return_value=42):
        assert generate_verification_code() == "000042"


def test_send_verification_code_returns_not_sent_when_unconfigured():
    sent, error = send_verification_code("student@uni.lu", "123456")
    assert sent is False
    assert "not configured" in error


def test_send_verification_code_never_raises_on_api_failure(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")
    with patch("orderability_engine.mailer.requests.post") as mock_post:
        mock_post.side_effect = OSError("connection refused")
        sent, error = send_verification_code("student@uni.lu", "123456")
    assert sent is False
    assert "connection refused" in error


def test_send_verification_code_succeeds_and_includes_the_code_in_both_parts(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    with patch("orderability_engine.mailer.requests.post", return_value=_mock_response()) as mock_post:
        sent, error = send_verification_code("student@uni.lu", "654321")

    assert sent is True
    assert error is None
    payload = mock_post.call_args.kwargs["json"]
    assert payload["to"] == ["student@uni.lu"]
    assert "654321" in payload["text"]
    assert "654321" in payload["html"]
    # Subject is short and plainly states its purpose -- see mailer.py's
    # module docstring on avoiding clickbait-y subject lines.
    assert "verification code" in payload["subject"].lower()


# ---------------------------------------------------------------------------
# Real-price confirmation email (Part 30)
# ---------------------------------------------------------------------------


def test_send_order_needs_confirmation_returns_not_sent_when_unconfigured():
    order = _order()
    sent, error = send_order_needs_confirmation(
        "student@uni.lu", order, real_price=8.50, confirm_url="https://x/confirm", cancel_url="https://x/cancel"
    )
    assert sent is False
    assert "not configured" in error


def test_send_order_needs_confirmation_shows_both_prices_and_both_links(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    order = _order()  # totals.formula.total == 8.00 (the approximate/app price)
    with patch("orderability_engine.mailer.requests.post", return_value=_mock_response()) as mock_post:
        sent, error = send_order_needs_confirmation(
            "student@uni.lu",
            order,
            real_price=9.20,
            confirm_url="https://resto.unilu.space/o/42/confirm?token=abc",
            cancel_url="https://resto.unilu.space/o/42/cancel?token=abc",
        )

    assert sent is True
    assert error is None
    payload = mock_post.call_args.kwargs["json"]
    for blob in (payload["text"], payload["html"]):
        assert "€8.00" in blob  # the approximate price is still shown, not silently dropped
        assert "€9.20" in blob  # the real price
        assert "https://resto.unilu.space/o/42/confirm?token=abc" in blob
        assert "https://resto.unilu.space/o/42/cancel?token=abc" in blob
    assert f"Order #{order['id']}" in payload["text"]


def test_send_order_needs_confirmation_omits_approximate_price_when_unknown(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_placeholder")

    order = _order(totals={"formula": {"total": None, "reason": None}})
    with patch("orderability_engine.mailer.requests.post", return_value=_mock_response()) as mock_post:
        send_order_needs_confirmation(
            "student@uni.lu", order, real_price=9.20, confirm_url="https://x/confirm", cancel_url="https://x/cancel"
        )

    payload = mock_post.call_args.kwargs["json"]
    assert "Approximate price" not in payload["text"]
