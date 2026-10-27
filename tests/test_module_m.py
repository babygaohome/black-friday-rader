import httpx

from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.api.app import create_app
from dealradar.core.config import Settings
from dealradar.retailers.registry import RetailerRegistry
from dealradar.runtime import build_runtime, find_due, run_scan
from dealradar.scanning.locks import MemoryLock
from retailers.jbhifi.adapter import JBHiFiAdapter
from tests.test_module_f import URL, Site


async def make(factory, **kw):
    site = Site()
    reg = RetailerRegistry()
    reg.register(JBHiFiAdapter(fetcher=site))
    app = create_app(factory, reg, secret_key="s", **kw)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t"), reg


async def signup(c):
    r = await c.post("/auth/register", json={"email": "u@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_cors_allows_only_configured_origins(factory):
    c, _ = await make(factory, cors_origins=["http://localhost:3000"])
    async with c:
        ok = await c.options("/watchlist", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
                                                    "Access-Control-Request-Headers": "authorization"})
        assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
        bad = await c.options("/watchlist", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in bad.headers


async def test_no_cors_headers_when_unconfigured(factory):
    c, _ = await make(factory)
    async with c:
        r = await c.get("/healthz", headers={"Origin": "http://localhost:3000"})
        assert "access-control-allow-origin" not in r.headers


async def test_scanner_status_for_war_room(factory):
    c, reg = await make(factory)
    async with c:
        assert (await c.get("/scanner/status")).status_code == 401
        h = await signup(c)
        pid = (await c.post("/products/from-url", json={"url": URL}, headers=h)).json()["product_id"]
        await c.post("/watchlist", json={"product_id": pid, "target_price": "400"}, headers=h)
        empty = (await c.get("/scanner/status", headers=h)).json()
        assert empty["last_scan_at"] is None and empty["retailers"][0]["code"] == "jbhifi"

        rt = build_runtime(Settings(database_url="sqlite+aiosqlite:///:memory:"), lock=MemoryLock(), cooldown=MemoryCooldown(),
                           registry=reg, session_factory=factory)
        [due] = await find_due(rt)
        await run_scan(rt, due.offer_id)
        status = (await c.get("/scanner/status", headers=h)).json()
        [jb] = status["retailers"]
        assert status["last_scan_at"] and jb["status"] == "ONLINE" and jb["last_scan_at"] and set(jb) == {
            "code", "name", "status", "success_rate", "last_success", "last_scan_at"}
