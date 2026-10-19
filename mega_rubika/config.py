"""
MEGA BOT Rubika — Configuration
تمام تنظیمات محرمانه فقط از اینجا یا env خوانده می‌شوند.
توکن واقعی را خودت اینجا یا در .env بگذار. هیچ پیش‌فرض جعلی/واقعی ندارم.
"""
from __future__ import annotations
import os
from pathlib import Path

# مسیر پایه پروژه (برای دیتابیس پایدار)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

try:
    from dotenv import load_dotenv
    # اول .env ریشه ریپو، بعد محیط سیستم
    load_dotenv(BASE_DIR / ".env")
    load_dotenv()
except ImportError:
    pass

# --- تنظیمات اجباری ---
# اولویت با env؛ در غیر این صورت مقدار زیر (برای ریپوی پرایوت).
BOT_TOKEN: str = os.getenv(
    "RUBIKA_BOT_TOKEN",
    "CFBGIB0PENJLTJENBWIZPOKSVILEEIZLHZNZYJVBDIFBGLLCGTUBTNBJDXHPJCWW",
).strip()
# شناسه مالک (طبق درخواست)
OWNER_ID: str = os.getenv(
    "RUBIKA_OWNER_ID",
    "b0FSde30BEEl0af919ab0bfa8489edc5",
).strip()

# دیتابیس SQLite — مسیر ثابت تا با تغییر cwd خراب نشود
DATABASE_PATH: str = os.getenv(
    "RUBIKA_DATABASE_PATH",
    str(DATA_DIR / "mega_rubika.db"),
)

# لاگ
LOG_LEVEL: str = os.getenv("RUBIKA_LOG_LEVEL", "INFO")

# API روبیکا
RUBIKA_API_BASE: str = os.getenv(
    "RUBIKA_API_BASE",
    "https://botapi.rubika.ir/v3",
).rstrip("/")

# تایم‌اوت و پولینگ
POLL_TIMEOUT: int = int(os.getenv("RUBIKA_POLL_TIMEOUT", "25"))
REQUEST_TIMEOUT: int = int(os.getenv("RUBIKA_REQUEST_TIMEOUT", "30"))

# متن‌های قابل ویرایش
SUPPORT_TEXT: str = os.getenv(
    "RUBIKA_SUPPORT_TEXT",
    "پشتیبانی: با مالک ربات در تماس باشید.",
)
DONATION_TEXT: str = os.getenv(
    "RUBIKA_DONATION_TEXT",
    "برای حمایت مالی با مالک ربات هماهنگ کنید.",
)
ABOUT_TEXT: str = os.getenv(
    "RUBIKA_ABOUT_TEXT",
    "🤖 MEGA BOT — نسخه روبیکا\nربات چندمنظوره با پنل مدیریت، آمار و امکانات کاربردی.",
)
BOT_VERSION: str = os.getenv("RUBIKA_BOT_VERSION", "1.0.0-rubika")

# محدودیت نرخ (برای جلوگیری از اسپم)
RATE_LIMIT_PER_USER: float = float(os.getenv("RUBIKA_RATE_LIMIT", "0.8"))


def validate() -> None:
    """اگر توکن نباشد متوقف شو. OWNER_ID اختیاری است ولی بدون آن پنل مالک کار نمی‌کند."""
    if not BOT_TOKEN:
        raise SystemExit(
            "❌ RUBIKA_BOT_TOKEN خالی است. در mega_rubika/config.py یا env تنظیم کن."
        )
    if not OWNER_ID:
        import logging
        logging.getLogger("mega_rubika").warning(
            "OWNER_ID خالی است — پنل /owner غیرفعال می‌ماند تا شناسه شخصی (u0...) را بگذاری."
        )
