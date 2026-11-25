import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from price_tracker import check_all, extract_price, parse_price  # noqa: E402

AMAZON_HTML = """
<html><body>
<div id="corePrice_feature_div">
  <span class="a-price aok-align-center"><span class="a-offscreen">EGP 12,499.00</span></span>
</div>
</body></html>
"""

META_HTML = """
<html><head><meta itemprop="price" content="850.50"></head><body><h1>Product</h1></body></html>
"""

ARABIC_HTML = """
<html><body><div class="product"><p>السعر: 3,250.00 جنيه شامل الضريبة</p></div></body></html>
"""

CUSTOM_HTML = """
<html><body><span class="deal">Only 199.99</span></body></html>
"""

NO_PRICE_HTML = "<html><body><p>Coming soon</p></body></html>"


class ParseTests(unittest.TestCase):
    def test_parse_price_formats(self):
        self.assertEqual(parse_price("EGP 12,499.00"), 12499.0)
        self.assertEqual(parse_price("3,250.00 جنيه"), 3250.0)
        self.assertEqual(parse_price("199.99"), 199.99)
        self.assertIsNone(parse_price("no numbers here"))
        self.assertIsNone(parse_price("0.00"))

    def test_amazon_adapter(self):
        price, how = extract_price(AMAZON_HTML, url="https://www.amazon.eg/dp/B0XXXX")
        self.assertEqual(price, 12499.0)
        self.assertIn("amazon.eg", how)

    def test_meta_itemprop_fallback(self):
        price, how = extract_price(META_HTML, url="https://shop.example.com/item/1")
        self.assertEqual(price, 850.5)
        self.assertIn("itemprop", how)

    def test_arabic_currency_scan(self):
        price, how = extract_price(ARABIC_HTML, url="https://shop.example.eg/p/9")
        self.assertEqual(price, 3250.0)
        self.assertIn("currency", how)

    def test_custom_selector_wins(self):
        price, how = extract_price(CUSTOM_HTML, url="https://x.example", selector=".deal")
        self.assertEqual(price, 199.99)
        self.assertIn("selector", how)

    def test_no_price_found(self):
        price, how = extract_price(NO_PRICE_HTML)
        self.assertIsNone(price)
        self.assertEqual(how, "not found")


class CheckTests(unittest.TestCase):
    def _store(self):
        return {"products": [{
            "name": "Headphones", "url": "https://www.amazon.eg/dp/B0XXXX",
            "selector": None, "target_price": None,
            "history": [{"ts": "2026-11-24T09:00:00", "price": 500.0}],
            "last_price": 500.0,
        }]}

    def test_drop_creates_alert(self):
        store = self._store()
        alerts = check_all(store, fetcher=lambda url, sel: (420.0, "fake"))
        self.assertEqual(len(alerts), 1)
        self.assertIn("500.00", alerts[0]["reason"])
        self.assertEqual(store["products"][0]["last_price"], 420.0)
        self.assertEqual(len(store["products"][0]["history"]), 2)

    def test_rise_creates_no_alert(self):
        store = self._store()
        alerts = check_all(store, fetcher=lambda url, sel: (550.0, "fake"))
        self.assertEqual(alerts, [])

    def test_same_price_no_alert(self):
        store = self._store()
        alerts = check_all(store, fetcher=lambda url, sel: (500.0, "fake"))
        self.assertEqual(alerts, [])

    def test_target_price_alert(self):
        store = self._store()
        store["products"][0]["target_price"] = 600.0
        alerts = check_all(store, fetcher=lambda url, sel: (599.0, "fake"))
        self.assertEqual(len(alerts), 1)
        self.assertIn("target", alerts[0]["reason"])

    def test_fetch_error_recorded_not_raised(self):
        store = self._store()

        def boom(url, sel):
            raise ConnectionError("timeout")

        alerts = check_all(store, fetcher=boom)
        self.assertEqual(alerts, [])
        last = store["products"][0]["history"][-1]
        self.assertIsNone(last["price"])
        self.assertIn("timeout", last["error"])


class NoiseTests(unittest.TestCase):
    def test_currency_number_wins_over_rating_and_model(self):
        self.assertEqual(parse_price("4.5 out of 5 stars | Model 2024 | EGP 1,299.00"), 1299.0)
        self.assertEqual(parse_price("iPhone 15 Pro 3,250.00 جنيه"), 3250.0)

    def test_scan_skips_shipping_text(self):
        html = "<html><body><p>Free shipping over EGP 500</p><p>Price: EGP 899.00</p></body></html>"
        price, _ = extract_price(html, url="https://shop.example.eg/p/1")
        self.assertEqual(price, 899.0)

    def test_scan_does_not_pick_bare_number_in_currency_text(self):
        html = "<html><body><p>Model 5000 available in EGP stores only</p></body></html>"
        price, _ = extract_price(html, url="https://shop.example.eg/p/2")
        self.assertIsNone(price)


if __name__ == "__main__":
    unittest.main()
