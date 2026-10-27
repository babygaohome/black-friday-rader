"""Telegram notifications (M14)."""
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from typing import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from dealradar.models import Alert, AlertType, Notification, NotificationStatus, Offer, Product, UserPreference
from dealradar.services.deals import DealAnalysis, analyze_offer

MAX_RETRIES = 3
Transport = Callable[[str, dict], Awaitable[httpx.Response]]

_HEADLINE = {
    AlertType.TARGET_PRICE_HIT: "🎯 TARGET PRICE HIT",
    AlertType.PRICE_DROP: "📉 PRICE DROP",
    AlertType.HISTORICAL_LOW: "🔥 NEW HISTORICAL LOW",
    AlertType.RESTOCK: "📦 BACK IN STOCK",
    AlertType.LOW_STOCK: "⚠️ LOW STOCK",
    AlertType.FLASH_DEAL: "⚡ FLASH DEAL",
}
_STOCK_LABEL = {"IN_STOCK": "✅ In Stock", "LOW_STOCK": "⚠️ Low Stock", "OUT_OF_STOCK": "❌ Out of Stock",
                "PREORDER": "🕒 Pre-order", "BACKORDER": "🕒 Backorder", "UNKNOWN": "❔ Stock unknown"}


def _aud(v: Decimal) -> str:
    return f"A${v:,.2f}".replace(".00", "")


_GRADE_LINE = {"EXTREME": "🔥 EXTREME DEAL", "VERY_GOOD": "🔥 VERY GOOD DEAL", "GOOD": "👍 GOOD DEAL"}


def format_alert(
    alert: Alert, product_name: str, retailer_name: str, stock: str, url: str, analysis: "DealAnalysis | None" = None
) -> dict:
    """Return the Telegram sendMessage payload (without chat_id) for an alert."""
    lines = ["🚨 <b>BLACK FRIDAY RADAR</b>", "", f"<b>{escape(_HEADLINE[alert.type])}</b>", escape(product_name), ""]
    if alert.previous_price and alert.previous_price > alert.price:
        pct = (alert.previous_price - alert.price) / alert.previous_price * 100
        lines += [f"{_aud(alert.previous_price)} → <b>{_aud(alert.price)}</b>", f"↓ {pct:.1f}%"]
    else:
        lines.append(f"<b>{_aud(alert.price)}</b>")
    if alert.deal_score is not None:
        lines += ["", f"⭐ Deal Score: {alert.deal_score}"]
        if analysis is not None and analysis.score.new_all_time_low:
            lines.append("📉 New all-time low")
        if analysis is not None and _GRADE_LINE.get(analysis.score.grade):
            lines.append(_GRADE_LINE[analysis.score.grade])
    if analysis is not None:
        d = analysis.discount
        if d.retailer_discount_pct is not None and d.actual_discount_pct is not None:
            lines += ["", f"Retailer discount: {d.retailer_discount_pct:g}%", f"Real vs 30-day price: {d.actual_discount_pct:g}%"]
            if d.verdict == "MISLEADING":
                lines.append("⚠️ Discount looks inflated")
    lines += ["", _STOCK_LABEL.get(stock, stock), "", "Retailer:", escape(retailer_name)]
    return {
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[{"text": "VIEW DEAL", "url": url}]]},
    }


class TelegramNotifier:
    def __init__(self, token: str, transport: Transport | None = None):
        self._token = token
        self._transport = transport

    async def _post(self, method: str, payload: dict) -> httpx.Response:
        if self._transport:
            return await self._transport(method, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            return await client.post(f"https://api.telegram.org/bot{self._token}/{method}", json=payload)

    async def deliver(self, session: AsyncSession, notification_id) -> NotificationStatus:
        n = await session.get(Notification, notification_id)
        if n is None or n.status == NotificationStatus.SENT:
            return NotificationStatus.SENT if n else NotificationStatus.FAILED
        alert = await session.get(Alert, n.alert_id)
        offer = await session.get(Offer, alert.offer_id)
        product = await session.get(Product, alert.product_id)
        prefs = await session.get(UserPreference, n.user_id)
        await session.refresh(offer, ["retailer"])
        if not prefs or not prefs.telegram_chat_id:
            n.status, n.error = NotificationStatus.FAILED, "no telegram chat id"
            await session.commit()
            return n.status

        analysis = await analyze_offer(session, offer)
        payload = format_alert(alert, product.name, offer.retailer.name, offer.stock_status.value, offer.url, analysis)
        payload["chat_id"] = prefs.telegram_chat_id
        try:
            resp = await self._post("sendMessage", payload)
            ok = resp.status_code == 200
            error = None if ok else f"HTTP {resp.status_code}"
            retryable = resp.status_code == 429 or resp.status_code >= 500
        except httpx.HTTPError as exc:
            ok, error, retryable = False, f"{type(exc).__name__}", True

        if ok:
            n.status, n.sent_at, n.error = NotificationStatus.SENT, datetime.now(timezone.utc), None
        else:
            n.retry_count += 1
            n.error = error
            n.status = NotificationStatus.RETRY if retryable and n.retry_count < MAX_RETRIES else NotificationStatus.FAILED
        await session.commit()
        return n.status
