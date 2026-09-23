from unittest.mock import MagicMock, patch

import pytest

from orderability_engine.mailer import is_configured, send_order_confirmation


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
def _clear_smtp_env(monkeypatch):
    # is_configured()/send_order_confirmation() read os.environ fresh on
    # every call (see mailer.py's docstring) -- start every test from a
    # clean slate regardless of what's actually set on this machine.
    for key in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_HOST", "SMTP_PORT", "SMTP_FROM_NAME"):
        monkeypatch.delenv(key, raising=False)


def test_is_configured_false_when_env_vars_unset():
    assert is_configured() is False


def test_is_configured_true_when_both_required_vars_set(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "uniresto@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password-placeholder")
    assert is_configured() is True


def test_is_configured_false_when_only_one_var_set(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "uniresto@gmail.com")
    assert is_configured() is False


def test_send_returns_not_sent_when_unconfigured():
    sent, error = send_order_confirmation("student@uni.lu", _order())
    assert sent is False
    assert "not configured" in error


def test_send_never_raises_and_reports_the_error_on_smtp_failure(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "uniresto@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password-placeholder")

    with patch("orderability_engine.mailer.smtplib.SMTP") as mock_smtp:
        mock_smtp.side_effect = OSError("connection refused")
        sent, error = send_order_confirmation("student@uni.lu", _order())

    assert sent is False
    assert "connection refused" in error


def test_send_succeeds_and_uses_configured_host_port_and_login(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "uniresto@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password-placeholder")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    with patch("orderability_engine.mailer.smtplib.SMTP", return_value=mock_conn) as mock_smtp:
        sent, error = send_order_confirmation("student@uni.lu", _order())

    assert sent is True
    assert error is None
    mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
    mock_conn.starttls.assert_called_once()
    mock_conn.login.assert_called_once_with("uniresto@gmail.com", "app-password-placeholder")
    mock_conn.send_message.assert_called_once()


def test_email_body_never_invents_data_only_uses_the_orders_own_fields(monkeypatch):
    # Sanity check on the message content itself: every line traces back
    # to a real field already on the order dict, nothing fabricated.
    monkeypatch.setenv("SMTP_USER", "uniresto@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password-placeholder")

    order = _order()
    captured = {}

    def _capture_send_message(msg):
        captured["msg"] = msg

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.send_message.side_effect = _capture_send_message
    with patch("orderability_engine.mailer.smtplib.SMTP", return_value=mock_conn):
        send_order_confirmation("student@uni.lu", order)

    body = captured["msg"].get_content()
    assert order["restaurant_name"] in body
    assert order["order_date"] in body
    assert "Rôti de porc Orloff x1" in body
    assert "Salad'bar x1" in body
    assert "€8.00" in body
    assert order["delivery_location"] in body
    assert f"Order #{order['id']}" in body


def test_email_omits_total_line_when_formula_has_no_price(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "uniresto@gmail.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password-placeholder")

    order = _order(totals={"formula": {"total": None, "reason": None}})
    captured = {}
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.send_message.side_effect = lambda msg: captured.update(msg=msg)
    with patch("orderability_engine.mailer.smtplib.SMTP", return_value=mock_conn):
        send_order_confirmation("student@uni.lu", order)

    assert "Total:" not in captured["msg"].get_content()
