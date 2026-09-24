from unittest.mock import MagicMock, patch

import pytest

from orderability_engine.telegram_notify import is_configured, send_admin_notification


def _order(**overrides):
    defaults = dict(
        id=42,
        restaurant_name="UDL-CKB - Altius - Restaurant",
        order_date="2026-09-24",
        delivery_location="Maison du Savoir 4.150",
        customer_email="student@uni.lu",
        items=[{"name": "Rôti de porc Orloff", "quantity": 1}],
        totals={"formula": {"total": 6.00}},
    )
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def _clear_telegram_env(monkeypatch):
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)


def test_is_configured_false_when_env_vars_unset():
    assert is_configured() is False


def test_is_configured_true_when_both_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    assert is_configured() is True


def test_is_configured_false_when_only_one_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    assert is_configured() is False


def test_send_returns_not_sent_when_unconfigured():
    sent, error = send_admin_notification(_order())
    assert sent is False
    assert "not configured" in error


def test_send_never_raises_on_network_failure(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    with patch("orderability_engine.telegram_notify.requests.post", side_effect=OSError("connection refused")):
        sent, error = send_admin_notification(_order())
    assert sent is False
    assert "connection refused" in error


def test_send_succeeds_and_posts_to_the_right_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, error = send_admin_notification(_order())

    assert sent is True
    assert error is None
    call_kwargs = mock_post.call_args
    assert "123:abc" in call_kwargs.args[0]
    assert call_kwargs.kwargs["json"]["chat_id"] == "999"


def test_send_reports_telegram_api_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "chat not found"}
    mock_resp.status_code = 400
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp):
        sent, error = send_admin_notification(_order())

    assert sent is False
    assert error == "chat not found"


def test_message_never_invents_data_only_uses_the_orders_own_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    order = _order()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(order, admin_url="https://uniresto.carcard.space/admin/orders?token=x")

    text = mock_post.call_args.kwargs["json"]["text"]
    assert str(order["id"]) in text
    assert order["restaurant_name"] in text
    assert order["order_date"] in text
    assert "Rôti de porc Orloff x1" in text
    assert "€6.00" in text
    assert order["delivery_location"] in text
    assert order["customer_email"] in text
    assert "https://uniresto.carcard.space/admin/orders?token=x" in text


def test_no_reply_markup_when_mark_reviewing_url_not_given(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order())

    assert "reply_markup" not in mock_post.call_args.kwargs["json"]


def test_mark_reviewing_url_becomes_an_inline_url_button(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    url = "https://uniresto.carcard.space/admin/orders/42/mark-reviewing?token=x"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order(), mark_reviewing_url=url)

    payload = mock_post.call_args.kwargs["json"]
    button = payload["reply_markup"]["inline_keyboard"][0][0]
    assert button["url"] == url
    # A plain URL button, never a callback_query -- Telegram just opens
    # the link, no webhook/polling needed on our side (see the module
    # docstring on send_admin_notification).
    assert "callback_data" not in button
