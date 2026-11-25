#!/usr/bin/env python3
"""price-tracker: watch product prices (Amazon.eg and most shops) and alert on drops.

Add products with a URL, run `check` on a schedule (cron/Task Scheduler), and get
a Telegram or email alert when a price falls below its previous value or your target.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STORE_PATH = Path(__file__).with_name("products.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Selectors tried in order for known sites, most specific first.
SITE_SELECTORS = {
    "amazon.eg": [
        "#corePrice_feature_div .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".a-price .a-offscreen",
    ],
    "amazon.com": [".a-price .a-offscreen", "#priceblock_ourprice"],
    "jumia.com.eg": [".-b.-ubpt.-tal.-fs24.-prs", "[class*='price']"],
    "noon.com": ["[data-qa='div-price-now']", ".priceNow"],
}

CURRENCY = r"(?:EGP|جنيه|ج\.?\s?م\.?|LE|E£)"
NUM = r"(\d[\d,]*(?:\.\d{1,2})?)"
# A number touching a currency marker, before or after it ("EGP 12,499.00" / "3,250 جنيه").
CURRENCY_NUM_RE = re.compile(rf"(?:{CURRENCY}\s*{NUM})|(?:{NUM}\s*{CURRENCY})", re.IGNORECASE)
# Text that mentions a currency but is not the product price.
NOISE_RE = re.compile(
    r"shipping|delivery|free over|free for orders|orders over|minimum|save |off\b|rating|stars?|reviews?|"
    r"شحن|توصيل|تقييم|خصم|الحد الأدنى|وفر",
    re.IGNORECASE,
)


def _to_float(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_price(text: str, require_currency: bool = False) -> float | None:
    """Extract a plausible price from text.

    A number next to a currency marker wins over any other number, so ratings,
    model numbers and shipping thresholds that appear earlier in the text are
    ignored. Without a currency marker the first number is used, unless
    `require_currency` is set.
    """
    text = text.replace("٬", ",")
    m = CURRENCY_NUM_RE.search(text)
    if m:
        return _to_float(m.group(1) or m.group(2))
    if require_currency:
        return None
    m = re.search(NUM, text)
    return _to_float(m.group(1)) if m else None


def extract_price(html: str, url: str = "", selector: str | None = None) -> tuple[float | None, str]:
    """Return (price, how-it-was-found). Tries: your selector, site selectors,
    structured meta tags, then a regex over any element mentioning a currency."""
    soup = BeautifulSoup(html, "html.parser")

    def from_css(css: str) -> float | None:
        el = soup.select_one(css)
        return parse_price(el.get_text(" ", strip=True)) if el else None

    if selector:
        price = from_css(selector)
        if price is not None:
            return price, f"selector {selector}"

    domain = ""
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if m:
        domain = m.group(1)
    for site, selectors in SITE_SELECTORS.items():
        if site in domain:
            for css in selectors:
                price = from_css(css)
                if price is not None:
                    return price, f"{site} adapter ({css})"

    for attr in ("itemprop",):
        el = soup.find(attrs={attr: "price"})
        if el:
            price = parse_price(el.get("content") or el.get_text(" ", strip=True))
            if price is not None:
                return price, "meta itemprop=price"

    for el in soup.find_all(string=re.compile(r"EGP|جنيه|ج\.?م", re.IGNORECASE)):
        if NOISE_RE.search(el):
            continue
        price = parse_price(el, require_currency=True)
        if price is not None:
            return price, "currency-text scan"
    return None, "not found"


def fetch_price(url: str, selector: str | None = None, timeout: int = 30) -> tuple[float | None, str]:
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return extract_price(resp.text, url=url, selector=selector)


# --- store -----------------------------------------------------------------

def load_store(path: Path = STORE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"products": []}


def save_store(store: dict, path: Path = STORE_PATH) -> None:
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def find_product(store: dict, name_or_url: str) -> dict | None:
    for p in store["products"]:
        if p["name"] == name_or_url or p["url"] == name_or_url:
            return p
    return None


# --- check & alerts ----------------------------------------------------------

def check_all(store: dict, fetcher=fetch_price) -> list[dict]:
    """Fetch every product, append history, and return alert dicts for drops."""
    alerts: list[dict] = []
    now = datetime.now().isoformat(timespec="seconds")
    for p in store["products"]:
        try:
            price, how = fetcher(p["url"], p.get("selector"))
        except Exception as exc:  # network down, site blocked, etc.
            p.setdefault("history", []).append({"ts": now, "price": None, "error": str(exc)})
            continue
        last = next((h["price"] for h in reversed(p.get("history", [])) if h.get("price")), None)
        p.setdefault("history", []).append({"ts": now, "price": price, "via": how})
        if price is None:
            continue
        p["last_price"] = price
        p["last_checked"] = now
        reason = None
        if last is not None and price < last:
            reason = f"dropped from {last:,.2f} to {price:,.2f} EGP"
        if p.get("target_price") and price <= p["target_price"]:
            reason = (reason + "; " if reason else "") + f"hit your target of {p['target_price']:,.2f} EGP"
        if reason:
            alerts.append({"product": p["name"], "url": p["url"], "price": price, "reason": reason})
    return alerts


def send_telegram(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
        timeout=30,
    )
    resp.raise_for_status()


def send_email(host: str, port: int, user: str, password: str, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)


def notify(alerts: list[dict]) -> list[str]:
    """Send alerts through whichever channels are configured via env vars.

    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, and/or
    SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD ALERT_EMAIL_TO
    """
    if not alerts:
        return []
    lines = [f"🔻 {a['product']}: {a['reason']}\n{a['url']}" for a in alerts]
    text = "\n\n".join(lines)
    sent = []
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        send_telegram(token, chat_id, text)
        sent.append("telegram")
    if os.environ.get("SMTP_HOST") and os.environ.get("ALERT_EMAIL_TO"):
        send_email(
            os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")),
            os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"],
            os.environ["ALERT_EMAIL_TO"], f"Price alerts ({len(alerts)})", text,
        )
        sent.append("email")
    return sent


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Track product prices and alert on drops.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="Track a new product")
    a.add_argument("name")
    a.add_argument("url")
    a.add_argument("--selector", help="CSS selector for the price (auto-detected if omitted)")
    a.add_argument("--target", type=float, help="Alert when price falls to this or below")

    sub.add_parser("list", help="Show tracked products")

    r = sub.add_parser("remove", help="Stop tracking a product (name or URL)")
    r.add_argument("name_or_url")

    sub.add_parser("check", help="Fetch all prices now, record history, send alerts")

    args = p.parse_args(argv)
    store = load_store()

    if args.cmd == "add":
        if find_product(store, args.name) or find_product(store, args.url):
            p.error("that name or URL is already tracked")
        store["products"].append({
            "name": args.name, "url": args.url,
            "selector": args.selector, "target_price": args.target, "history": [],
        })
        save_store(store)
        print(f"Tracking {args.name}. Run `python price_tracker.py check` anytime.")
        return 0

    if args.cmd == "list":
        if not store["products"]:
            print("Nothing tracked yet. Add one with `python price_tracker.py add NAME URL`.")
            return 0
        for prod in store["products"]:
            last = prod.get("last_price")
            target = f" | target {prod['target_price']:,.2f}" if prod.get("target_price") else ""
            price = f"{last:,.2f} EGP" if last else "no price yet"
            print(f"- {prod['name']}: {price}{target}\n  {prod['url']}")
        return 0

    if args.cmd == "remove":
        prod = find_product(store, args.name_or_url)
        if not prod:
            p.error("not found")
        store["products"].remove(prod)
        save_store(store)
        print(f"Removed {prod['name']}.")
        return 0

    if args.cmd == "check":
        alerts = check_all(store)
        save_store(store)
        for prod in store["products"]:
            h = prod.get("history", [])[-1] if prod.get("history") else {}
            price = h.get("price")
            status = f"{price:,.2f} EGP" if price else f"unavailable ({h.get('error', 'price not found')})"
            print(f"{prod['name']}: {status}")
        if alerts:
            channels = notify(alerts)
            print(f"\n{len(alerts)} alert(s)" + (f" sent via {', '.join(channels)}." if channels else
                  " (no notifier configured: set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID or SMTP_* env vars)."))
            for a in alerts:
                print(f"  🔻 {a['product']}: {a['reason']}")
        else:
            print("\nNo price drops.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
