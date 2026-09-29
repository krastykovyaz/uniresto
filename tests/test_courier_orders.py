"""Order History's "My deliveries" tab: what a courier took, only for the courier."""

from urllib.parse import quote

from tests.test_app import (  # noqa: F401 -- `client` is a fixture, imported to be collected here
    _attacker,
    _create_basic_order,
    _hand_off,
    _mark_delivered,
    client,
)


def _mine(browser, email="courier@uni.lu"):
    return browser.get(f"/api/courier/orders?email={quote(email)}")


def test_a_courier_sees_what_they_took_and_delivered(client):
    delivered = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, delivered)
    _mark_delivered(client, delivered)
    in_hand = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, in_hand)
    # a different customer: the same one is capped at 2 orders a day
    untouched = _create_basic_order(client, customer_email="second-student@uni.lu")

    body = _mine(client).get_json()
    by_id = {o["id"]: o for o in body}
    assert set(by_id) == {delivered, in_hand}
    assert untouched not in by_id
    assert by_id[delivered]["delivered_at"] and by_id[in_hand]["delivered_at"] is None
    assert by_id[in_hand]["picked_up_at"]


def test_the_list_never_carries_contact_details(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    order = _mine(client).get_json()[0]
    for field in ("customer_email", "customer_phone", "courier_email", "courier_lang", "reward_email"):
        assert field not in order


def test_a_released_order_is_no_longer_mine(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    assert client.post(f"/api/orders/{order_id}/claim", json={"courier_email": "courier@uni.lu"}).status_code == 200
    assert [o["id"] for o in _mine(client).get_json()] == [order_id]
    assert client.post(f"/api/orders/{order_id}/unclaim", json={"courier_email": "courier@uni.lu"}).status_code == 200
    assert _mine(client).get_json() == []


def test_other_couriers_orders_are_not_listed(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("other@uni.lu")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id, courier_email="other@uni.lu")
    assert _mine(client).get_json() == []
    assert [o["id"] for o in _mine(client, "other@uni.lu").get_json()] == [order_id]


def test_plus_tag_variants_of_the_courier_address_are_one_courier(client):
    client.application.config["VERIFIED_EMAIL_STORE"].mark_verified("courier+x@uni.lu")
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    assert [o["id"] for o in _mine(client, "courier+x@uni.lu").get_json()] == [order_id]


def test_only_the_verifying_browser_can_read_a_couriers_list(client):
    order_id = _create_basic_order(client, customer_email="student@uni.lu")
    _hand_off(client, order_id)
    stranger = _attacker(client, "student@uni.lu")
    resp = _mine(stranger)
    assert resp.status_code == 403 and resp.get_json()["error"] == "email_not_verified"
    # and an address nobody verified is answered exactly the same
    assert _mine(stranger, "nobody@uni.lu").get_json() == resp.get_json()


def test_the_list_needs_a_university_address(client):
    assert client.get("/api/courier/orders").status_code == 400
    assert client.get("/api/courier/orders?email=someone@gmail.com").status_code == 400
