# اجرای هم‌زمان بله + روبیکا روی Railway

## چرا روبیکا بالا نمی‌آمد؟
سرویس Railway فقط دستور Start را اجرا می‌کند. قبلاً فقط `python main.py` (MeowBot بله) بود؛
پس `mega_rubika` اصلاً استارت نمی‌شد.

## کار لازم در Railway
1. Settings → Deploy → **Custom Start Command**:
   ```
   python run_both.py
   ```
2. Redeploy

یا دو سرویس جدا از یک ریپو:
- سرویس Bale → `python main.py`
- سرویس Rubika → `python -m mega_rubika.main`

## متغیرهای اختیاری
- `RUN_BALE=0` فقط روبیکا
- `RUN_RUBIKA=0` فقط بله
- `RUBIKA_BOT_TOKEN` / `RUBIKA_OWNER_ID` (اگر نخواستی از config.py)

## هشدار شبکه
API روبیکا (`botapi.rubika.ir`) از بعضی دیتاسنترهای خارج ایران در دسترس نیست.
اگر لاگ روبیکا `Connection timeout` داد، سرور را روی لوکیشن نزدیک ایران بگذار
یا از VPS ایران استفاده کن. بله معمولاً از خارج بهتر جواب می‌دهد.
