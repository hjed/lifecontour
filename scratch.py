from datetime import datetime, UTC
from zoneinfo import ZoneInfo

# Event from Google Calendar: 2026-04-22T19:00:00+10:00 (Sydney 7PM)
dt = datetime.fromisoformat("2026-04-22T19:00:00+10:00")
dt_utc = dt.astimezone(UTC)
print(f"UTC datetime: {dt_utc}")

tz = ZoneInfo("Australia/Sydney")
dt_local = dt_utc.astimezone(tz)
print(f"Local time: {dt_local.time()}")

# Combining UTC date with UTC time
print(f"UTC combined: {datetime.combine(dt_utc.date(), dt_utc.time(), tzinfo=UTC)}")

# Combining Local date with Local time
dt_reconstructed_local = datetime.combine(dt_local.date(), dt_local.time(), tzinfo=tz)
print(f"Reconstructed UTC from local: {dt_reconstructed_local.astimezone(UTC)}")

