# MeowBot — اجرای محلی در Termux (بدون Railway)

## نصب
```bash
pkg update -y
pkg install python git -y
cd ~
git clone https://github.com/commander1405/Meowbot.git
cd Meowbot
pip install -r requirements.txt
```

## اجرا
پیش‌فرض `LOCAL_MODE=1` است: دیتابیس **SQLite در حافظه**، بدون اتصال به Railway.
با بستن ربات داده‌ها پاک می‌شوند.

```bash
export LOCAL_MODE=1
python main.py
```

اگر بخواهی روی فایل ذخیره شود:
```bash
export LOCAL_MODE=1
export SQLITE_PATH=$HOME/meowbot.db
python main.py
```

برای PostgreSQL/Railway (اختیاری):
```bash
export LOCAL_MODE=0
export DATABASE_URL="postgresql://..."
python main.py
```
