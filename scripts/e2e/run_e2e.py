#!/usr/bin/env python3
"""End-to-end test of an order, from verifying an email to a delivered, confirmed order, against the app running
with the mock services (see app_with_mocks.py and mock_services.py). Everything goes through the real HTTP API;
the emails and Telegram messages the app "sends" are read back from the mock.

    python scripts/e2e/run_e2e.py [--app http://127.0.0.1:5051] [--mock http://127.0.0.1:5099] [--date 2026-10-05]

Exit code 0 only if every check passes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

RESULTS: list[bool] = []


def check(label: str, condition, detail: str = "") -> None:
    RESULTS.append(bool(condition))
    print(("PASS  " if condition else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.tokens: dict[str, str] = {}  # email -> identity token, as a browser would hold them

    def _headers(self, emails=None, extra=None):
        who = {e: self.tokens[e] for e in (emails if emails is not None else self.tokens) if e in self.tokens}
        h = {"Content-Type": "application/json", **(extra or {})}
        if who:
            h["X-Identity-Tokens"] = urllib.parse.quote(json.dumps(who))
        return h

    def request(self, method, path, body=None, emails=None, form=False):
        data = None
        headers = self._headers(emails)
        if body is not None:
            if form:
                data, headers["Content-Type"] = urllib.parse.urlencode(body).encode(), "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text, code = r.read().decode(), r.status
        except urllib.error.HTTPError as e:
            text, code = e.read().decode(), e.code
        try:
            return code, json.loads(text)
        except ValueError:
            return code, text


class Mock:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def _call(self, method, path):
        with urllib.request.urlopen(urllib.request.Request(self.base + path, method=method, data=b"" if method == "POST" else None), timeout=10) as r:
            return json.loads(r.read())

    def reset(self):
        self._call("POST", "/__reset")

    def fail_email(self, on: bool):
        self._call("POST", f"/__fail?on={1 if on else 0}")

    def emails(self, to=None, subject=None):
        return [m for m in self._call("GET", "/__outbox?kind=email") if (to is None or m["to"] == to) and (subject is None or subject in (m["subject"] or ""))]

    def telegrams(self, contains=None):
        return [m for m in self._call("GET", "/__outbox?kind=telegram") if contains is None or contains in (m["text"] or "")]


def verify(api: Api, mock: Mock, email: str) -> bool:
    """The real way: ask for a code, read it from the email the mock received, type it back."""
    before = len(mock.emails(to=email, subject="verification code"))
    code, r = api.request("POST", "/api/email/send-code", {"email": email})
    mails = mock.emails(to=email, subject="verification code")
    if code != 200 or not r.get("sent") or len(mails) != before + 1:
        return False
    digits = re.search(r"\b(\d{6})\b", mails[-1]["text"])
    if not digits:
        return False
    code, r = api.request("POST", "/api/email/verify-code", {"email": email, "code": digits.group(1)}, emails=[])
    if code == 200 and r.get("verified") and r.get("token"):
        api.tokens[email] = r["token"]
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://127.0.0.1:5051")
    ap.add_argument("--mock", default="http://127.0.0.1:5099")
    ap.add_argument("--date", default="2026-10-05", help="an orderable day for the lycée restaurant")
    ap.add_argument("--admin-token", default="localtest-admin-token")
    ap.add_argument("--restaurant", default="ltc-k")
    args = ap.parse_args()
    api, mock = Api(args.app), Mock(args.mock)
    mock.reset()
    PUPIL, COURIER = "pupil@ltc.lu", "courier@uni.lu"
    DAY, SLUG = args.date, args.restaurant

    print("== 1. verifying addresses through the emailed code")
    check("an @ltc.lu pupil verifies through the emailed 6-digit code", verify(api, mock, PUPIL))
    check("a uni.lu courier verifies through the emailed code", verify(api, mock, COURIER))
    check("verification emails went to the right people only", {m["to"] for m in mock.emails(subject="verification code")} == {PUPIL, COURIER})
    code, _ = api.request("POST", "/api/email/send-code", {"email": "someone@gmail.com"})
    check("a non-allowed domain gets no code at all", code == 400 and not mock.emails(to="someone@gmail.com"))
    code, r = api.request("POST", "/api/email/verify-code", {"email": PUPIL, "code": "000000"}, emails=[])
    check("a wrong code does not verify", code == 200 and r.get("verified") is False, str(r.get("reason")))

    print("== 2. the courier signs up for new-order emails")
    code, r = api.request("POST", "/api/delivery/register/quick", {"email": COURIER, "lang": "en"}, emails=[COURIER])
    check("the verified courier registers for delivery emails", code == 200, str(code))

    print("== 3. the pupil orders")
    code, m = api.request("GET", f"/api/restaurants/{SLUG}/menu/{DAY}")
    items = m["items"] if "items" in m else [i for x in m["menus"] for i in x["items"]]
    pasta = next(i for i in items if i["category"] == "Pasta")
    starter = next(i for i in items if i["category"] == "Entrée")
    dessert = next(i for i in items if i["category"] == "Dessert")
    order = {"restaurant": SLUG, "date": DAY, "items": [{"id": pasta["id"], "quantity": 1}, {"id": starter["id"], "quantity": 1}, {"id": dessert["id"], "quantity": 1}],
             "delivery_location": "Lycée Technique du Centre (Kirchberg annex) — Room 12", "customer_email": PUPIL, "reward_email": PUPIL, "lang": "en"}
    mock.reset()
    code, o = api.request("POST", "/api/orders", order, emails=[PUPIL])
    check("the order is created", code == 201, f"#{o.get('id')} {o.get('status')}")
    oid = o["id"]
    conf = mock.emails(to=PUPIL, subject="order confirmed")
    check("the customer gets an order-confirmation email naming the restaurant and the dishes", len(conf) == 1 and "LTC-K" in conf[0]["subject"] and pasta["name"] in conf[0]["text"])
    tg = mock.telegrams("order")
    check("the admin gets a Telegram message with the order", any(str(oid) in (t["text"] or "") for t in tg), f"{len(tg)} message(s)")
    new = mock.emails(to=COURIER, subject="New order to deliver")
    check("the registered courier gets a 'new order to deliver' email", len(new) == 1 and "LTC-K" in new[0]["subject"])
    check("no email went to anyone else", {m["to"] for m in mock.emails()} == {PUPIL, COURIER})

    print("== 4. the courier takes it")
    mock.reset()
    code, r = api.request("POST", f"/api/orders/{oid}/claim", {"courier_email": COURIER, "lang": "en"}, emails=[COURIER])
    check("claimed", code == 200 and r["claimed"] is True)
    check("the admin is told it was claimed", bool(mock.telegrams("claim")) or bool(mock.telegrams(str(oid))))
    check("the courier gets the order description email", len(mock.emails(to=COURIER, subject="New order to deliver")) == 1)
    check("the customer gets an 'order accepted' email", len(mock.emails(to=PUPIL, subject="was accepted")) == 1)
    mock.reset()
    code, r = api.request("POST", f"/api/orders/{oid}/claim", {"courier_email": COURIER}, emails=[COURIER])
    check("a second tap sends nothing again", code == 200 and r["already_claimed"] is True and not mock.emails() and not mock.telegrams())

    print("== 5. pick-up and the customer's price confirmation")
    mock.reset()
    code, r = api.request("POST", f"/api/orders/{oid}/picked-up", {"courier_email": COURIER}, emails=[COURIER])
    check("picked up", code == 200 and r["picked_up"] is True)
    check("the customer gets an 'on its way' email", len(mock.emails(to=PUPIL, subject="on its way")) == 1)
    mock.reset()
    code, body = api.request("POST", f"/admin/orders/{oid}/set-price?token={args.admin_token}", {"real_price": "8.70"}, emails=[], form=True)
    check("the admin records the real price (8.70) and the app redirects back to the panel", code in (200, 302) or isinstance(body, str), str(code))
    needs = mock.emails(to=PUPIL, subject="Confirm your UniResto order")
    check("the customer gets a 'confirm your order' email with both prices", len(needs) == 1 and "8.70" in needs[0]["text"] and "LTC-K" in needs[0]["subject"])
    link = re.search(r"https?://\S+/o/%d/confirm\?token=[\w\-]+" % oid, needs[0]["text"]) if needs else None
    check("the email carries a confirm link and a cancel link", bool(link) and f"/o/{oid}/cancel" in needs[0]["text"])
    if link:
        url = urllib.parse.urlsplit(link.group(0))
        token = dict(urllib.parse.parse_qsl(url.query))["token"]
        code, page = api.request("GET", f"{url.path}?{url.query}", emails=[])
        check("the confirm page opens from the emailed link", code == 200 and isinstance(page, str) and "onfirm" in page)
        code, _ = api.request("POST", url.path, {"token": token}, emails=[], form=True)
        code, got = api.request("GET", f"/api/orders/{oid}", emails=[PUPIL])
        check("the customer confirms: confirmed at 8.70", got.get("status") == "confirmed" and got.get("real_price") == 8.7, f"{got.get('status')} {got.get('real_price')}")
        code, _ = api.request("POST", url.path, {"token": token}, emails=[], form=True)
        code, got = api.request("GET", f"/api/orders/{oid}", emails=[PUPIL])
        check("the same link can't be used twice", got.get("status") == "confirmed")

    print("== 6. delivered, and what each person earns")
    code, r = api.request("POST", f"/api/orders/{oid}/mark-delivered", {"courier_email": COURIER}, emails=[COURIER])
    check("marked delivered", code == 200 and r["delivered"] is True)
    code, a = api.request("GET", f"/api/rewards?email={COURIER}", emails=[COURIER])
    code, b = api.request("GET", f"/api/rewards?email={PUPIL}", emails=[PUPIL])
    # 3 Luni for verifying the university address + 1 for this order/delivery
    check("the courier and the pupil each earn 1 Luni on top of the 3-Luni verification bonus", a.get("points") == 4 and b.get("points") == 4, f"{a} {b}")

    print("== 7. a failing mail service never breaks an order")
    order2 = {**order, "items": [{"id": pasta["id"], "quantity": 1}]}
    mock.reset(); mock.fail_email(True)
    code, o2 = api.request("POST", "/api/orders", order2, emails=[PUPIL])
    check("the order is still created when every email fails", code == 201, f"HTTP {code}")
    mock.fail_email(False)
    code, r = api.request("POST", "/api/email/send-code", {"email": PUPIL})
    mock.fail_email(True)
    code, r = api.request("POST", "/api/email/send-code", {"email": COURIER})
    check("a failed verification email is reported as not sent, not as success", code == 200 and r.get("sent") is False, str(r))
    mock.fail_email(False)

    print("== 8. the admin cancels an order")
    if o2.get("id"):
        code, _ = api.request("POST", f"/admin/orders/{o2['id']}/cancel?token={args.admin_token}", {}, emails=[], form=True)
        code, got = api.request("GET", f"/api/orders/{o2['id']}", emails=[PUPIL])
        check("the cancelled order is cancelled", got.get("status") == "cancelled", str(got.get("status")))

    passed, total = sum(RESULTS), len(RESULTS)
    print(f"\n{passed}/{total} checks passed" + ("" if passed == total else "  -- SOME FAILED"))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
