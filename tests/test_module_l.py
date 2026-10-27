import io
import json
import logging
import re

import httpx
import pytest

from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.api.app import create_app
from dealradar.cli import set_admin
from dealradar.core.config import Settings
from dealradar.observability.logs import JsonFormatter, configure_logging, log_event
from dealradar.observability.metrics import LATENCY_BUCKETS, AppMetrics, render
from dealradar.retailers.registry import RetailerRegistry
from dealradar.runtime import build_runtime, find_due, run_scan
from dealradar.scanning.locks import MemoryLock
from retailers.jbhifi.adapter import JBHiFiAdapter
from tests.test_module_f import URL, Site


# ---------- structured logs ----------
def test_json_line_has_doc_fields_and_context():
    stream = io.StringIO()
    configure_logging("price-worker", "INFO", stream)
    log_event(logging.getLogger("t"), "scan_failed", logging.WARNING, retailer="jbhifi", offer_id="o1", error="parse_error", skipped=None)
    line = json.loads(stream.getvalue())
    assert line["service"] == "price-worker" and line["event"] == "scan_failed" and line["level"] == "warning"
    assert line["retailer"] == "jbhifi" and line["offer_id"] == "o1" and line["error"] == "parse_error"
    assert line["timestamp"].endswith("+00:00") and "skipped" not in line


def test_exceptions_are_logged_as_error_field_and_secrets_stay_out_of_the_event():
    stream = io.StringIO()
    configure_logging("api", "INFO", stream)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("t").exception("handler_crashed")
    line = json.loads(stream.getvalue())
    assert line["event"] == "handler_crashed" and "boom" in line["error"]


def test_log_level_filters():
    stream = io.StringIO()
    configure_logging("api", "WARNING", stream)
    logging.getLogger("t").info("quiet")
    assert stream.getvalue() == ""


def test_formatter_without_fields_still_works():
    rec = logging.LogRecord("n", logging.INFO, __file__, 1, "plain %s", ("msg",), None)
    assert json.loads(JsonFormatter("svc").format(rec))["event"] == "plain msg"


# ---------- exposition format ----------
def test_render_escapes_label_values():
    lines = render("m", "gauge", "h", [({"retailer": 'a"b\\c\nd'}, 1)])
    assert lines[2] == 'm{retailer="a\\"b\\\\c\\nd"} 1'


def test_latency_histogram_is_cumulative_and_counts_by_route():
    m = AppMetrics()
    m.observe("GET", "/x", 200, 0.02)
    m.observe("GET", "/x", 200, 0.3)
    m.observe("GET", "/x", 500, 9.0)
    text = "\n".join(m.render(ws_clients=2))
    assert 'dealradar_http_requests_total{method="GET",route="/x",status="200"} 2' in text
    assert 'dealradar_http_requests_total{method="GET",route="/x",status="500"} 1' in text
    assert 'duration_seconds_bucket{route="/x",le="0.01"} 0' in text
    assert 'duration_seconds_bucket{route="/x",le="0.05"} 1' in text
    assert 'duration_seconds_bucket{route="/x",le="0.5"} 2' in text
    assert f'duration_seconds_bucket{{route="/x",le="{LATENCY_BUCKETS[-1]}"}} 2' in text
    assert 'duration_seconds_bucket{route="/x",le="+Inf"} 3' in text and 'duration_seconds_count{route="/x"} 3' in text
    assert "dealradar_websocket_clients 2" in text and text.count("# TYPE dealradar_http_request_duration_seconds histogram") == 1


# ---------- /metrics endpoint + scan logging, end to end ----------
@pytest.fixture
def site():
    return Site()


@pytest.fixture
def registry(site):
    r = RetailerRegistry()
    r.register(JBHiFiAdapter(fetcher=site))
    return r


@pytest.fixture
async def client(factory, registry):
    app = create_app(factory, registry, secret_key="test-secret")

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
        c.app = app
        yield c


async def signup(client, email="u@example.com"):
    r = await client.post("/auth/register", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def sample(text: str, name: str, **labels) -> float:
    want = ",".join(f'{k}="{v}"' for k, v in labels.items())
    pattern = rf"^{re.escape(name)}{{{re.escape(want)}}} (\S+)$" if labels else rf"^{re.escape(name)} (\S+)$"
    found = re.search(pattern, text, re.M)
    assert found, f"{name}{{{want}}} not in metrics"
    return float(found.group(1))


async def test_metrics_requires_admin(client, factory):
    assert (await client.get("/metrics")).status_code == 401
    h = await signup(client)
    assert (await client.get("/metrics", headers=h)).status_code == 403
    await set_admin(factory, "u@example.com")
    r = await client.get("/metrics", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")


async def test_api_metrics_use_route_templates_and_count_errors(client, factory):
    h = await signup(client)
    await set_admin(factory, "u@example.com")
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=h)).json()["product_id"]
    await client.get(f"/products/{pid}", headers=h)
    await client.get(f"/products/{pid}/history", headers=h)
    await client.get("/does-not-exist")
    assert (await client.get("/boom")).status_code == 500
    text = (await client.get("/metrics", headers=h)).text
    assert pid not in text  # raw ids never become label values
    assert sample(text, "dealradar_http_requests_total", method="GET", route="/products/{product_id}", status="200") == 1
    assert sample(text, "dealradar_http_requests_total", method="GET", route="unmatched", status="404") == 1
    assert sample(text, "dealradar_http_requests_total", method="GET", route="/boom", status="500") == 1


async def test_scan_metrics_business_metrics_and_logs(client, factory, registry, site, caplog):
    h = await signup(client)
    await set_admin(factory, "u@example.com")
    pid = (await client.post("/products/from-url", json={"url": URL}, headers=h)).json()["product_id"]
    await client.post("/watchlist", json={"product_id": pid, "target_price": "400"}, headers=h)
    rt = build_runtime(Settings(database_url="sqlite+aiosqlite:///:memory:"), lock=MemoryLock(), cooldown=MemoryCooldown(),
                       registry=registry, session_factory=factory)
    [due] = await find_due(rt)

    with caplog.at_level(logging.INFO):
        site.page = "jbhifi_sale.html"
        await run_scan(rt, due.offer_id)  # 549 -> 399: a price change and a target hit

        async def blocked(url):
            return httpx.Response(429, text="slow down", request=httpx.Request("GET", url))

        registry.get("jbhifi")._fetcher = blocked
        await run_scan(rt, due.offer_id)

    events = {r.getMessage(): r.fields for r in caplog.records if hasattr(r, "fields")}
    assert events["scan_ok"]["retailer"] == "jbhifi" and events["scan_ok"]["offer_id"] == str(due.offer_id)
    assert events["scan_ok"]["price_changed"] is True
    assert events["scan_failed"]["retailer"] == "jbhifi" and events["scan_failed"]["error"] == "rate_limit"
    assert events["alert_created"]["type"] == "TARGET_PRICE_HIT"
    assert next(r for r in caplog.records if r.getMessage() == "scan_failed").levelno == logging.WARNING

    text = (await client.get("/metrics", headers=h)).text
    assert sample(text, "dealradar_scans_1h", retailer="jbhifi", status="OK") == 1
    assert sample(text, "dealradar_scans_1h", retailer="jbhifi", status="FAILED") == 1
    assert sample(text, "dealradar_scan_failures_1h", retailer="jbhifi", error_type="RATE_LIMIT") == 1
    assert sample(text, "dealradar_price_changes_24h") == 1  # the unchanged re-scan and the initial snapshot do not count
    assert sample(text, "dealradar_alerts_24h", type="TARGET_PRICE_HIT") == 1
    assert 0 < sample(text, "dealradar_retailer_success_rate", retailer="jbhifi") < 1
    assert sample(text, "dealradar_retailer_captcha_rate", retailer="jbhifi") > 0
    assert sample(text, "dealradar_retailer_status", retailer="jbhifi", status="ONLINE") == 1
    assert sample(text, "dealradar_suspicious_prices_24h") == 0
    assert sample(text, "dealradar_websocket_clients") == 0
