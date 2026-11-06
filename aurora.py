"""墨尔本极光推送 —— 查 NOAA 太阳风/Kp 数据，有机会时推送到 ntfy。

用法:
  python aurora.py realtime   # 夜间每15分钟：当晚实时预警
  python aurora.py daily      # 每天一次：未来1-3天风暴预报
  python aurora.py test       # 发一条测试通知（带当前数据）
环境变量: NTFY_TOPIC（必填）
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MEL = ZoneInfo("Australia/Melbourne")
SWPC = "https://services.swpc.noaa.gov"
STATE_FILE = Path(__file__).with_name("state.json")

# ---- 阈值（墨尔本，地磁纬度约 -47°）----
KP_ALERT = 6.0          # 估算 Kp ≥ 6：南边海岸相机基本能拍到
KP_STRONG = 7.0         # Kp ≥ 7：肉眼也可能看到
BZ_ALERT = -10.0        # Bz 持续向南（nT）
SPEED_ALERT = 450.0     # 太阳风速度（km/s）
WATCH_KP = 6.0          # 未来3天预测 Kp ≥ 6 就提前提醒
REPEAT_HOURS = 3        # 同一场 3 小时内不重复提醒（除非升级）

# 看极光点（由近到远），每条提醒都带各点云量
SPOTS = [
    ("Malvern East 家附近", -37.875, 145.07),
    ("Ricketts Point 海边（约25分钟）", -37.995, 145.03),
    ("Cape Schanck / Flinders（约1小时20分）", -38.49, 144.95),
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "aurora-alert/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def rows(data):
    """NOAA products 有两种格式：表头+列表，或字典列表。统一成字典列表。"""
    if not data:
        return []
    if isinstance(data[0], dict):
        return data
    header = data[0]
    return [dict(zip(header, r)) for r in data[1:]]


def parse_time(s):
    s = str(s).replace("Z", "").replace("T", " ")
    dt = datetime.fromisoformat(s[:19])
    return dt.replace(tzinfo=timezone.utc)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def push(title, message, priority="high", tags="sparkles"):
    topic = os.environ["NTFY_TOPIC"].strip()
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            # 中文标题用 RFC 2047 编码，避免乱码
            "Title": "=?UTF-8?B?" + __import__("base64").b64encode(title.encode()).decode() + "?=",
            "Priority": priority,
            "Tags": tags,
            "Click": "https://www.swpc.noaa.gov/communities/aurora-dashboard-experimental",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("ntfy:", r.status)


# ---------------- 数据 ----------------
def current_conditions():
    now = datetime.now(timezone.utc)
    out = {"kp": None, "bz": None, "speed": None}

    kp_rows = get_json(f"{SWPC}/json/planetary_k_index_1m.json")
    recent = [r for r in kp_rows if now - parse_time(r["time_tag"]) <= timedelta(minutes=30)]
    vals = [num(r.get("estimated_kp", r.get("kp_index"))) for r in (recent or kp_rows[-5:])]
    vals = [v for v in vals if v is not None]
    out["kp"] = max(vals) if vals else None

    mag = rows(get_json(f"{SWPC}/products/solar-wind/mag-5-minute.json"))
    bz = [num(r.get("bz_gsm")) for r in mag
          if now - parse_time(r["time_tag"]) <= timedelta(minutes=25)]
    bz = [v for v in bz if v is not None]
    out["bz"] = sum(bz) / len(bz) if bz else None

    plasma = rows(get_json(f"{SWPC}/products/solar-wind/plasma-5-minute.json"))
    sp = [num(r.get("speed")) for r in plasma
          if now - parse_time(r["time_tag"]) <= timedelta(minutes=25)]
    sp = [v for v in sp if v is not None]
    out["speed"] = max(sp) if sp else None
    return out


def kp_forecast():
    """返回未来72小时的 (时间, 预测Kp) 列表。"""
    now = datetime.now(timezone.utc)
    data = rows(get_json(f"{SWPC}/products/noaa-planetary-k-index-forecast.json"))
    out = []
    for r in data:
        t = parse_time(r["time_tag"])
        kind = str(r.get("observed", "")).lower()
        kp = num(r.get("kp"))
        if kp is not None and kind == "predicted" and now <= t <= now + timedelta(hours=72):
            out.append((t, kp))
    return out


def cloud_cover():
    """各看点未来几小时平均云量，返回多行文字；失败返回空字符串。"""
    try:
        lats = ",".join(str(s[1]) for s in SPOTS)
        lons = ",".join(str(s[2]) for s in SPOTS)
        d = get_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lats}&longitude={lons}&hourly=cloud_cover"
            "&forecast_hours=4&timezone=UTC"
        )
        if isinstance(d, dict):
            d = [d]
        lines = []
        for (name, _, _), loc in zip(SPOTS, d):
            v = [x for x in loc["hourly"]["cloud_cover"] if x is not None]
            if v:
                c = round(sum(v) / len(v))
                mark = "✅" if c < 40 else ("⚠️" if c < 70 else "❌")
                lines.append(f"{mark} {name} 云量 {c}%")
        return "\n☁️ 云量：\n" + "\n".join(lines) if lines else ""
    except Exception as e:
        print("cloud error:", e)
        return ""


def fmt(v, nd=1):
    return "—" if v is None else f"{v:.{nd}f}"


TIPS = "朝正南、避开路灯，手机夜景模式拍3秒以上（相机比肉眼明显）。"
WHERE = {
    3: "📍 强极光：家附近/Ricketts Point 海边就可能看到，去半岛更清楚。",
    2: "📍 家附近肉眼难见，建议去 Ricketts Point 拍，最好去半岛（Cape Schanck/Flinders）。",
    1: "📍 先别急着出门，等升级提醒；想抢先就往半岛开。",
}


# ---------------- 三种模式 ----------------
def run_realtime():
    hour = datetime.now(MEL).hour
    if 6 <= hour < 20:
        print("daytime in Melbourne, skip")
        return

    c = current_conditions()
    print("conditions:", c)
    kp, bz, speed = c["kp"], c["bz"], c["speed"]

    level = 0
    if kp is not None and kp >= KP_STRONG:
        level = 3
    elif kp is not None and kp >= KP_ALERT:
        level = 2
    elif bz is not None and speed is not None and bz <= BZ_ALERT and speed >= SPEED_ALERT:
        level = 1  # 太阳风已经很强，30-60分钟后可能升级

    if level == 0:
        print("no alert")
        return

    state = load_state()
    last = state.get("realtime", {})
    if last:
        since = datetime.now(timezone.utc) - datetime.fromisoformat(last["time"])
        if since < timedelta(hours=REPEAT_HOURS) and level <= last["level"]:
            print("already alerted recently")
            return

    cloud_txt = cloud_cover()
    data_txt = f"Kp {fmt(kp)} · Bz {fmt(bz)} nT · 风速 {fmt(speed, 0)} km/s"

    if level == 3:
        title, pri = "🔴 强极光！墨尔本肉眼可能看到", "urgent"
        body = "现在就有机会，强风暴进行中。"
    elif level == 2:
        title, pri = "🟠 极光预警：今晚墨尔本有机会", "high"
        body = "相机基本能拍到，肉眼可能淡淡一片。"
    else:
        title, pri = "🟡 极光可能来了（30–60分钟内）", "default"
        body = "太阳风变强、Bz 转南，可能会升级，可以准备出发。"

    push(title, f"{body}\n{data_txt}\n{WHERE[level]}{cloud_txt}\n{TIPS}", priority=pri)
    state["realtime"] = {"time": datetime.now(timezone.utc).isoformat(), "level": level}
    save_state(state)


def run_daily():
    fc = kp_forecast()
    if not fc:
        print("no forecast data")
        return
    peak_t, peak_kp = max(fc, key=lambda x: x[1])
    print("forecast peak:", peak_t, peak_kp)
    if peak_kp < WATCH_KP:
        return

    state = load_state()
    last = state.get("watch", {})
    peak_local = peak_t.astimezone(MEL)
    key = peak_local.strftime("%Y-%m-%d")
    if last.get("date") == key and peak_kp <= last.get("kp", 0):
        print("watch already sent")
        return

    nights = sorted({t.astimezone(MEL).strftime("%-m月%-d日") for t, k in fc if k >= WATCH_KP})
    push(
        "🌌 极光预报：未来几天有地磁暴",
        f"预测最高 Kp {fmt(peak_kp)}，大约在墨尔本时间 {peak_local.strftime('%-m月%-d日 %H:%M')} 前后。\n"
        f"可能的日子：{'、'.join(nights)}\n"
        "先留出这几晚，当晚条件达标会再实时提醒你。",
        priority="default",
        tags="milky_way",
    )
    state["watch"] = {"date": key, "kp": peak_kp}
    save_state(state)


def run_test():
    try:
        c = current_conditions()
        data_txt = f"当前 Kp {fmt(c['kp'])} · Bz {fmt(c['bz'])} nT · 风速 {fmt(c['speed'], 0)} km/s"
    except Exception as e:
        data_txt = f"（取数据出错：{e}）"
    try:
        fc = kp_forecast()
        peak = max(k for _, k in fc) if fc else None
        data_txt += f"\n未来3天预测最高 Kp {fmt(peak)}"
    except Exception as e:
        data_txt += f"\n（预报出错：{e}）"
    data_txt += cloud_cover()
    push("✅ 极光提醒已开通", "这是测试通知，系统正常运行。\n" + data_txt, priority="default", tags="white_check_mark")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "realtime"
    {"realtime": run_realtime, "daily": run_daily, "test": run_test}[mode]()
