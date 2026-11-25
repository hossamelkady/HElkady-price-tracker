# price-tracker

Track product prices on Amazon Egypt (and most online shops) and get a Telegram or email alert when a price drops or hits your target.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Track a product (price is auto-detected for amazon.eg and common shops)
python price_tracker.py add "Sony WH-1000XM5" "https://www.amazon.eg/dp/B0XXXXXX" --target 9000

# If auto-detection picks the wrong number, point it at the price yourself
python price_tracker.py add "Keyboard" "https://shop.example.com/kb" --selector ".sale-price"

# See everything you're tracking
python price_tracker.py list

# Check prices now
python price_tracker.py check

# Stop tracking
python price_tracker.py remove "Sony WH-1000XM5"
```

History is stored in `products.json` next to the script, so you can see how the price moved over time.

## Alerts

`check` sends an alert through any channel you configure:

**Telegram** — create a bot with [@BotFather](https://t.me/BotFather), message it once, then:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"
```

**Email** (e.g. a Gmail app password):

```bash
export SMTP_HOST="smtp.gmail.com" SMTP_PORT="587"
export SMTP_USER="you@gmail.com" SMTP_PASSWORD="app-password"
export ALERT_EMAIL_TO="you@gmail.com"
```

## Run it daily

Linux/macOS cron, every day at 9 AM:

```
0 9 * * * cd /path/to/price-tracker && /usr/bin/python3 price_tracker.py check >> tracker.log 2>&1
```

Windows: use Task Scheduler with the same `check` command.

## Run the tests

The tests run fully offline against sample pages:

```bash
python -m unittest discover -s tests -v
```

## Notes

- Some sites block bots. If `check` reports a fetch error for a product, give it a custom `--selector` or check that site less often.
- Prices are parsed as numbers in whatever currency the page shows; Egyptian sites are assumed EGP.

---

# متتبع الأسعار

تابع أسعار منتجات على أمازون مصر (ومعظم المتاجر) واستقبل تنبيه على تيليجرام أو الإيميل لما السعر ينزل أو يوصل للسعر اللي محدده.

## التثبيت

```bash
pip install -r requirements.txt
```

## الاستخدام

```bash
# أضف منتج للمتابعة
python price_tracker.py add "سماعة سوني" "https://www.amazon.eg/dp/B0XXXXXX" --target 9000

# شوف المنتجات اللي بتتابعها
python price_tracker.py list

# افحص الأسعار دلوقتي
python price_tracker.py check

# امسح منتج
python price_tracker.py remove "سماعة سوني"
```

تاريخ الأسعار بيتخزن في ملف `products.json` جنب السكربت.

## التنبيهات

**تيليجرام:** اعمل بوت من @BotFather وابعتله رسالة، وبعدين ظبط متغيرين:

```bash
export TELEGRAM_BOT_TOKEN="التوكن"
export TELEGRAM_CHAT_ID="رقم الشات"
```

**إيميل:** باستخدام SMTP (مثلا Gmail App Password) بمتغيرات `SMTP_HOST` و`SMTP_USER` و`SMTP_PASSWORD` و`ALERT_EMAIL_TO`.

## تشغيل يومي

على لينكس/ماك باستخدام cron، أو على ويندوز بـ Task Scheduler بنفس أمر `check`.
