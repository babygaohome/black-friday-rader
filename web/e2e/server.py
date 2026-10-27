"""Test harness for e2e/smoke.js: the real API with a fake JB Hi-Fi site and in-process realtime (no Redis).
GET /__scan/<fixture.html> switches the fake page and scans every offer. Run from the repo root."""
import asyncio, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import uvicorn
from dealradar.alerts.cooldown import MemoryCooldown
from dealradar.api.app import create_app
from dealradar.core.config import Settings
from dealradar.core.db import create_all, make_engine, make_session_factory
from dealradar.realtime.hub import Hub, LocalBroadcaster
from dealradar.retailers.registry import RetailerRegistry
from dealradar.runtime import build_runtime, find_due, run_scan
from dealradar.scanning.locks import MemoryLock
from retailers.jbhifi.adapter import JBHiFiAdapter
from tests.test_module_f import Site

DB = Path(tempfile.gettempdir()) / "dealradar-e2e.db"
DB.unlink(missing_ok=True)  # every run starts empty
engine = make_engine(f"sqlite+aiosqlite:///{DB}")
sf = make_session_factory(engine)
site = Site()
reg = RetailerRegistry(); reg.register(JBHiFiAdapter(fetcher=site))
hub = Hub()
app = create_app(sf, reg, "e2e-secret", hub=hub, cors_origins=["http://localhost:3000"])
rt = build_runtime(Settings(database_url="sqlite+aiosqlite:///:memory:"), lock=MemoryLock(), cooldown=MemoryCooldown(),
                   registry=reg, session_factory=sf, broadcaster=LocalBroadcaster(hub))

asyncio.run(create_all(engine))

@app.get("/__scan/{page}")
async def scan(page: str):
    site.page = page
    async with sf() as s:
        from sqlalchemy import select
        from dealradar.models import Offer
        ids = (await s.execute(select(Offer.id))).scalars().all()
    return [(await run_scan(rt, i)).status for i in ids]

uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
