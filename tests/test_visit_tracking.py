"""The "app opened" ping: a QR's ?src= label has to reach the stats.

The app now calls /api/visit/<event>; /api/track/<event> (which ad and content
blockers drop because of the word "track") is kept for phones still holding the
previous page. Both feed the same counters."""

from tests.test_app import client  # noqa: F401 -- a fixture, imported to be collected here


def _home_sources(client):
    return dict(client.application.config["PAGE_VIEW_STORE"].source_counts("home"))


def test_the_new_visit_address_records_the_qr_label(client):
    resp = client.post("/api/visit/home", json={"source": "flyer-g"})
    assert resp.status_code == 200 and resp.get_json() == {"recorded": True}
    client.post("/api/visit/home", json={"source": "flyer-h"})
    client.post("/api/visit/home", json={"source": "flyer-h"})
    assert _home_sources(client) == {"flyer-h": 2, "flyer-g": 1}


def test_the_old_track_address_still_works_and_counts_the_same(client):
    client.post("/api/track/home", json={"source": "flyer-g"})
    client.post("/api/visit/home", json={"source": "flyer-g"})
    assert _home_sources(client) == {"flyer-g": 2}


def test_a_visit_without_a_label_is_filed_as_direct(client):
    from orderability_engine.admin_stats import build_stats_message

    client.post("/api/visit/home", json={})
    assert _home_sources(client) == {"(direct)": 1}  # no QR label -> the "(direct)" bucket
    message = build_stats_message(client.application.config["PAGE_VIEW_STORE"], client.application.config["ORDER_STORE"])
    assert "Opened the app: 1" in message and "(direct): 1" in message


def test_only_home_and_menu_can_be_reported_and_both_addresses_agree(client):
    for prefix in ("/api/visit", "/api/track"):
        assert client.post(f"{prefix}/menu", json={}).status_code == 200
        assert client.post(f"{prefix}/delivery", json={}).status_code == 404
        assert client.post(f"{prefix}/admin", json={}).status_code == 404


def test_the_visit_address_is_rate_limited_like_the_old_one(client):
    codes = [client.post("/api/visit/home", json={"source": "flyer-g"}).status_code for _ in range(62)]
    assert codes[:60] == [200] * 60 and codes[60:] == [429, 429]
    # the limit is shared: the old address is cut off too, it is the same bucket
    assert client.post("/api/track/home", json={"source": "flyer-g"}).status_code == 429


def test_the_stats_message_lists_a_brand_new_qr_label(client):
    from orderability_engine.admin_stats import build_stats_message

    client.post("/api/visit/home", json={"source": "flyer-g"})
    client.post("/api/visit/home", json={"source": "flyer-h"})
    message = build_stats_message(client.application.config["PAGE_VIEW_STORE"], client.application.config["ORDER_STORE"])
    assert "flyer-g: 1" in message and "flyer-h: 1" in message
