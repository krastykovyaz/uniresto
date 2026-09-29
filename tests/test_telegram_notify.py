import datetime
from unittest.mock import MagicMock, patch

import pytest

from orderability_engine.telegram_notify import (
    is_configured,
    send_admin_notification,
    send_daily_report,
    send_dish_photo_review,
    send_feedback_notification,
    send_order_claimed_notification,
    send_order_released_notification,
)


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


def test_message_includes_customer_note_when_present(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    order = _order(customer_note="no onion, please")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(order)

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "no onion, please" in text


def test_mark_reviewing_url_becomes_an_inline_url_button(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    url = "https://uniresto.carcard.space/admin/orders/42/mark-reviewing?token=x"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order(), mark_reviewing_url=url)

    payload = mock_post.call_args.kwargs["json"]
    buttons = [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["url"] == url for b in buttons)
    # A plain URL button, never a callback_query -- Telegram just opens
    # the link, no webhook/polling needed on our side (see the module
    # docstring on send_admin_notification).
    assert all("callback_data" not in b for b in buttons)


def test_restopolis_url_becomes_an_inline_button_and_appears_in_the_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    url = "https://ssl.education.lu/eRestauration/CustomerServices/Menu/BtnChangeRestaurant?pRestaurantSelection=164"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order(), restopolis_url=url)

    payload = mock_post.call_args.kwargs["json"]
    buttons = [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]
    assert any(b["url"] == url for b in buttons)
    assert url in payload["text"]


def test_both_buttons_present_when_both_urls_given(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    restopolis_url = "https://ssl.education.lu/eRestauration/CustomerServices/Menu/BtnChangeRestaurant?pRestaurantSelection=164"
    reviewing_url = "https://uniresto.carcard.space/admin/orders/42/mark-reviewing?token=x"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order(), mark_reviewing_url=reviewing_url, restopolis_url=restopolis_url)

    buttons = [b for row in mock_post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"] for b in row]
    urls = {b["url"] for b in buttons}
    assert urls == {restopolis_url, reviewing_url}


def test_cancel_url_becomes_a_third_inline_button(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    restopolis_url = "https://ssl.education.lu/eRestauration/CustomerServices/Menu/BtnChangeRestaurant?pRestaurantSelection=164"
    reviewing_url = "https://uniresto.carcard.space/admin/orders/42/mark-reviewing?token=x"
    cancel_url = "https://uniresto.carcard.space/admin/orders/42/cancel?token=x"

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(
            _order(), mark_reviewing_url=reviewing_url, restopolis_url=restopolis_url, cancel_url=cancel_url
        )

    keyboard = mock_post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"]
    buttons = [b for row in keyboard for b in row]
    assert {b["url"] for b in buttons} == {restopolis_url, reviewing_url, cancel_url}
    assert next(b for b in buttons if b["url"] == cancel_url)["text"].endswith("Remove this order")
    # Removing is the last, most destructive button -- never above the others.
    assert keyboard[-1][0]["url"] == cancel_url
    assert all("callback_data" not in b for b in buttons)


def test_no_cancel_button_when_no_cancel_url_is_given(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order(), mark_reviewing_url="https://x/mark-reviewing?token=x")
    buttons = [b for row in mock_post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"] for b in row]
    assert not any("Remove" in b["text"] for b in buttons)


def test_items_are_grouped_by_their_real_restopolis_category(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    order = _order(
        items=[
            {"name": "Croissant fourré 70 g", "quantity": 1, "category": "02. Viennoiseries"},
            {"name": "Huit 80 g", "quantity": 1, "category": "02. Viennoiseries"},
            {"name": "Rôti de porc Orloff", "quantity": 1, "category": "Non-végétarien"},
        ]
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(order)

    text = mock_post.call_args.kwargs["json"]["text"]
    # Both viennoiseries items sit under ONE "02. Viennoiseries:" header,
    # not repeated per item -- the same real category the admin's own
    # Restopolis app groups dishes by, so this is directly matchable
    # against it regardless of whether that's the website or the app.
    assert text.count("02. Viennoiseries:") == 1
    assert "Non-végétarien:" in text
    viennoiseries_section = text.split("02. Viennoiseries:")[1].split("Non-végétarien:")[0]
    assert "Croissant fourré 70 g x1" in viennoiseries_section
    assert "Huit 80 g x1" in viennoiseries_section


def test_no_reply_markup_when_neither_url_given(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_notification(_order())

    assert "reply_markup" not in mock_post.call_args.kwargs["json"]


def test_feedback_send_returns_not_sent_when_unconfigured():
    sent, error = send_feedback_notification("Great app!", None)
    assert sent is False
    assert "not configured" in error


def test_feedback_message_includes_the_free_text(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, error = send_feedback_notification("Please add Belval restaurants", "student@uni.lu", admin_url="https://x/admin/feedback?token=y")

    assert sent is True
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "Please add Belval restaurants" in text
    assert "student@uni.lu" in text
    assert "https://x/admin/feedback?token=y" in text


def test_feedback_message_omits_contact_line_when_no_email_given(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_feedback_notification("Love the app", None)

    assert "Contact:" not in mock_post.call_args.kwargs["json"]["text"]


def test_daily_report_includes_every_real_count(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    counts = {"home": 42, "menu": 27, "orders": 8, "delivery": 5}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, error = send_daily_report(counts, datetime.date(2026, 9, 28))

    assert sent is True
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "2026-09-28" in text
    assert "42" in text
    assert "27" in text
    assert "8" in text
    assert "5" in text


def test_daily_report_includes_the_per_source_breakdown(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    counts = {
        "home": 42,
        "home_by_source": [("flyer-c", 30), ("(direct)", 12)],
        "menu": 27,
        "orders": 8,
        "delivery": 5,
    }
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_daily_report(counts, datetime.date(2026, 9, 28))

    text = mock_post.call_args.kwargs["json"]["text"]
    assert "flyer-c: 30" in text
    assert "(direct): 12" in text


def test_daily_report_omits_the_breakdown_when_absent(monkeypatch):
    # An older-shaped counts dict (no home_by_source key) must not crash
    # the send -- it just doesn't get that breakdown.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    counts = {"home": 42, "menu": 27, "orders": 8, "delivery": 5}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, error = send_daily_report(counts, datetime.date(2026, 9, 28))

    assert sent is True


def test_daily_report_returns_not_sent_when_unconfigured():
    sent, error = send_daily_report({"home": 0, "menu": 0, "orders": 0, "delivery": 0}, datetime.date(2026, 9, 28))
    assert sent is False
    assert "not configured" in error


def test_order_claimed_returns_not_sent_when_unconfigured():
    sent, error = send_order_claimed_notification(_order())
    assert sent is False
    assert "not configured" in error


def test_order_claimed_includes_the_order_and_location(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    order = _order(delivery_location="Maison du Savoir 4.150")
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, error = send_order_claimed_notification(order, admin_url="https://x/admin/orders?token=y")

    assert sent is True
    text = mock_post.call_args.kwargs["json"]["text"]
    assert f"Order #{order['id']}" in text
    assert "Maison du Savoir 4.150" in text
    assert "https://x/admin/orders?token=y" in text


def test_order_released_says_nobody_is_on_it(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, _ = send_order_released_notification(_order())
    assert sent is True
    text = mock_post.call_args.kwargs["json"]["text"]
    assert "released" in text
    assert f"#{_order()['id']}" in text


# ---------------------------------------------------------------------------
# send_dish_photo_review (Part 84)
# ---------------------------------------------------------------------------


def test_dish_photo_review_returns_not_sent_when_unconfigured():
    sent, error = send_dish_photo_review("Altius", "Végétarien", "Salad'bar", "https://x/photo.jpg", None, None, None)
    assert sent is False
    assert "not configured" in error


def test_dish_photo_review_hits_sendphoto_not_sendmessage(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        sent, error = send_dish_photo_review(
            "Altius", "Végétarien", "Salad'bar", "https://x/photo.jpg", None, None, None
        )
    assert sent is True
    assert error is None
    url = mock_post.call_args.args[0]
    assert url.endswith("/sendPhoto")
    payload = mock_post.call_args.kwargs["json"]
    assert payload["photo"] == "https://x/photo.jpg"
    assert "Salad'bar" in payload["caption"]
    assert "Altius" in payload["caption"]
    assert "Végétarien" in payload["caption"]


def test_dish_photo_review_includes_approve_and_reject_buttons(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    approve_url = "https://x/admin/dish-photos/1/approve?token=y"
    reject_url = "https://x/admin/dish-photos/1/reject?token=y"
    review_url = "https://x/admin/dish-photos/1?token=y"
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_dish_photo_review(
            "Altius", "Végétarien", "Salad'bar", "https://x/photo.jpg", review_url, approve_url, reject_url
        )
    buttons = [b for row in mock_post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"] for b in row]
    urls = {b["url"] for b in buttons}
    assert urls == {approve_url, reject_url, review_url}
    # Plain URL buttons, never callback_query -- same no-webhook reasoning
    # as every other admin button in this module.
    assert all("callback_data" not in b for b in buttons)


def test_dish_photo_review_no_buttons_when_no_admin_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_dish_photo_review("Altius", "Végétarien", "Salad'bar", "https://x/photo.jpg", None, None, None)
    assert "reply_markup" not in mock_post.call_args.kwargs["json"]


# ---------------------------------------------------------------------------
# The admin's "📊 Stats" button
# ---------------------------------------------------------------------------

from orderability_engine.telegram_notify import (  # noqa: E402
    STATS_BUTTON_TEXT,
    is_admin_chat,
    is_stats_request,
    send_admin_text,
    set_webhook,
    stats_keyboard,
    webhook_secret,
)


def _configure(monkeypatch, token="123:abc", chat="999"):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", chat)


def test_the_keyboard_is_one_persistent_stats_button():
    kb = stats_keyboard()
    assert kb["keyboard"] == [[{"text": STATS_BUTTON_TEXT}]]
    assert kb["is_persistent"] is True and kb["resize_keyboard"] is True


@pytest.mark.parametrize("text", [STATS_BUTTON_TEXT, "/stats", "/STATS", "/start", "/stats@UniRestoBot", " /stats ", "/stats now"])
def test_these_count_as_a_stats_request(text):
    assert is_stats_request(text)


@pytest.mark.parametrize("text", ["hello", "", None, "stats", "/statistics", "/help", "📊"])
def test_everything_else_does_not(text):
    assert not is_stats_request(text)


def test_only_the_admin_chat_is_the_admin(monkeypatch):
    _configure(monkeypatch)
    assert is_admin_chat(999) and is_admin_chat("999")
    assert not is_admin_chat(1000)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert not is_admin_chat(999)


def test_the_webhook_secret_comes_from_the_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert webhook_secret() is None
    _configure(monkeypatch, token="123:abc")
    first = webhook_secret()
    assert first and len(first) == 64 and all(c in "0123456789abcdef" for c in first)
    assert webhook_secret() == first  # stable
    _configure(monkeypatch, token="123:rotated")
    assert webhook_secret() != first  # rotating the token rotates the secret
    assert "123:abc" not in first


def test_send_admin_text_attaches_the_button_only_when_asked(monkeypatch):
    _configure(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        send_admin_text("plain")
        assert "reply_markup" not in mock_post.call_args.kwargs["json"]
        send_admin_text("with button", with_stats_button=True)
        assert mock_post.call_args.kwargs["json"]["reply_markup"] == stats_keyboard()
        assert mock_post.call_args.kwargs["json"]["chat_id"] == "999"


def test_set_webhook_registers_the_url_with_the_secret(monkeypatch):
    _configure(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": True}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp) as mock_post:
        assert set_webhook("https://example.test/telegram/webhook") == (True, None)
    assert mock_post.call_args.args[0].endswith("/bot123:abc/setWebhook")
    body = mock_post.call_args.kwargs["json"]
    assert body["url"] == "https://example.test/telegram/webhook"
    assert body["secret_token"] == webhook_secret()
    assert body["allowed_updates"] == ["message"]


def test_set_webhook_reports_telegrams_refusal_and_missing_config(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert set_webhook("https://x")[0] is False
    _configure(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ok": False, "description": "bad webhook: HTTPS url must be provided"}
    with patch("orderability_engine.telegram_notify.requests.post", return_value=mock_resp):
        assert set_webhook("http://x") == (False, "bad webhook: HTTPS url must be provided")
