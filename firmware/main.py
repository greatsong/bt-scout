# 복도 전파 감지기 (Raspberry Pi Pico 2 WH + Grove Shield, MicroPython)
# LED 줄(Grove RGB LED Stick 등): D16, 광대역 전파 센서(선택): A0
# 확인 화면: 감지기 와이파이에 붙어 http://192.168.4.1

import asyncio
import json
import time

import bluetooth
import neopixel
import network
from machine import ADC, Pin, WDT

import config
from detect import (History, Hunt, RfWatch, Tracker, WifiTracker,
                    expand_frame, hunt_frame, led_frame, limit_current)

SETTINGS = "settings.json"

STICK = config.LED_TYPE == "stick"
if STICK:
    # timing=1 은 800kHz, 0 은 400kHz 신호
    leds = neopixel.NeoPixel(Pin(config.LED_PIN), config.LED_COUNT,
                             timing=1 if config.LED_KHZ >= 800 else 0)
    if config.LED_ORDER == "RGB":
        leds.ORDER = (0, 1, 2, 3)
else:
    led_one = Pin(config.LED_PIN, Pin.OUT, value=0)
try:
    led_board = Pin("LED", Pin.OUT)    # 피코 본체의 작은 LED
except Exception:
    led_board = None

tr = Tracker(rssi_min=config.RSSI_MIN, persist=config.PERSIST, hold=config.HOLD)
wt = WifiTracker(rssi_min=config.WIFI_RSSI_MIN, skip_prefix=config.AP_SSID)
rf = RfWatch(delta=config.RF_DELTA)
hist = History(hours=config.HISTORY_HOURS)
hunt = Hunt(secs=config.HUNT_SECS)
state = {"scan_done": False, "wok": None, "hmode": False}


def log_error(where, e):
    """오류를 Thonny 창에 찍고 피코 안 error.txt에 마지막 것을 남긴다."""
    msg = "%s 오류: %r" % (where, e)
    print(msg)
    if state.get("err") != msg:
        state["err"] = msg
        try:
            with open("error.txt", "w") as f:
                f.write(msg)
        except Exception:
            pass


def load_settings():
    try:
        with open(SETTINGS) as f:
            s = json.load(f)
    except Exception:
        return
    tr.rssi_min = s.get("th", tr.rssi_min)
    tr.base = set(bytes.fromhex(h) for h in s.get("base", []))
    wt.base = set(bytes.fromhex(h) for h in s.get("wbase", []))


def save_settings():
    s = {"th": tr.rssi_min,
         "base": [a.hex() for a in tr.base],
         "wbase": [a.hex() for a in wt.base]}
    try:
        with open(SETTINGS, "w") as f:
            json.dump(s, f)
    except Exception as e:
        print("설정 저장 실패:", e)


def learning():
    return tr.learning_left(time.time()) > 0


def counts(now):
    """(핫스팟·직접 연결, 블루투스, 광대역 급증) 수"""
    n_rf = 1 if config.RF_SENSOR and config.RF_ALERT and rf.alert(now) else 0
    return wt.alert_count(now), tr.alert_count(now), n_rf


def alert_total(now):
    return sum(counts(now))


# ---------- 블루투스 스캔 ----------
ble = bluetooth.BLE()


def ble_irq(event, data):
    if event == 5:  # 광고 수신
        atype, addr, adv_type, rssi, adv = data
        a = bytes(addr)
        tr.seen(time.time(), atype, a, rssi, bytes(adv))
        if a == hunt.addr and not hunt.wifi:
            hunt.feed(time.ticks_ms(), rssi)
    elif event == 6:  # 스캔 종료
        state["scan_done"] = True


def start_scan():
    state["scan_done"] = False
    # 끝없이 스캔. 블루투스와 와이파이가 안테나 하나를 나눠 쓰므로, 듣는 시간을 줄여
    # 확인용 와이파이가 휴대전화의 접속 요청에 답할 틈을 준다.
    if state["hmode"] and not hunt.wifi:
        # 정밀 탐색 중에는 고른 기기의 신호를 놓치지 않게 훨씬 자주 듣는다.
        ble.gap_scan(0, config.HUNT_INTERVAL_MS * 1000, config.HUNT_WINDOW_MS * 1000, False)
    else:
        ble.gap_scan(0, config.BLE_INTERVAL_MS * 1000, config.BLE_WINDOW_MS * 1000, config.BLE_ACTIVE)


# ---------- 확인용 와이파이 ----------
def start_ap():
    try:
        import rp2
        rp2.country("KR")
    except Exception:
        pass
    ap = network.WLAN(network.AP_IF)
    if config.AP_PASSWORD:
        ap.config(ssid=config.AP_SSID, password=config.AP_PASSWORD)
    else:
        ap.config(ssid=config.AP_SSID, security=0)   # 암호 없는 와이파이(시험용)
    try:
        ap.config(channel=config.AP_CHANNEL)
    except Exception:
        pass
    ap.active(True)
    try:
        ap.config(pm=0xa11140)   # 절전을 꺼서 접속이 끊기지 않게 한다
    except Exception:
        pass
    try:
        state["own"] = bytes(ap.config("mac"))
    except Exception:
        pass
    print("와이파이 주소:", ap.ifconfig()[0])
    return ap


def status_json():
    now = time.time()
    return json.dumps({
        "unit": config.UNIT,
        "alerts": alert_total(now),
        "counts": counts(now),
        "wok": state["wok"],
        "wifi": wt.snapshot(now),
        "rf": rf.status(now) if config.RF_SENSOR else None,
        "th": tr.rssi_min,
        "base": len(tr.base) + len(wt.base),
        "learn": tr.learning_left(now),
        "hunt": hunt.active(now),
        "total": len(tr.devs),
        "devs": tr.snapshot(now, 30),
    })


def history_json():
    now = time.time()
    d = hist.dump(now)
    d["unit"] = config.UNIT
    d["counts"] = counts(now)
    return json.dumps(d)


def record(now):
    """5초마다 호출: 지금 감지 중인 것을 기록에 남긴다."""
    n_hot, n_bt, n_rf = counts(now)
    hist.sample(now, n_hot, n_bt)
    for addr, kind, name, rssi in tr.alerts(now):
        label = (kind or "종류 모름") + (" · " + name if name else "")
        hist.note(now, addr, "bt", label, rssi)
    for bssid, ssid, kind, rssi in wt.alerts(now):
        hist.note(now, bssid, "hot", (ssid or "(이름 숨김)") + " · " + kind, rssi)


def hunt_label(addr, wifi):
    if wifi:
        d = wt.nets.get(addr)
        return (d[0] or "(이름 숨김)") if d else "와이파이 신호"
    d = tr.devs.get(addr)
    if not d:
        return "블루투스 기기"
    return (d[1] or "종류 모름") + (" · " + d[2] if d[2] else "")


def command(query):
    for part in query.split("&"):
        k, _, v = part.partition("=")
        if k in ("hunt", "whunt"):
            if v == "off":
                hunt.stop()
            else:
                addr = bytes.fromhex(v)
                hunt.start(time.time(), addr, k == "whunt", hunt_label(addr, k == "whunt"))
        elif k == "peak":
            hunt.clear_peak()
        elif k == "th":
            tr.rssi_min = max(-95, min(-40, int(v)))
            save_settings()
        elif k == "learn":
            tr.start_learning(time.time(), 60)
            wt.base = set()
            state["learn_save"] = True
        elif k == "clearbase":
            tr.base = set()
            wt.base = set()
            save_settings()


async def handle(reader, writer):
    try:
        line = await asyncio.wait_for(reader.readline(), 5)
        while True:
            h = await asyncio.wait_for(reader.readline(), 5)
            if h in (b"\r\n", b"\n", b""):
                break
        state["last_req"] = time.time()
        target = line.split()[1].decode()
        path, _, query = target.partition("?")
        if path != "/t" and (path != "/s" or not state.get("seen_s")):
            print("요청 받음:", target)      # 휴대전화의 요청이 피코까지 왔다는 표시
            if path == "/s":
                state["seen_s"] = True
        if path == "/s":
            body = status_json()
            ctype = "application/json"
        elif path == "/h":
            body = history_json()
            ctype = "application/json"
        elif path == "/t":
            body = json.dumps(hunt.status(time.time(), time.ticks_ms()))
            ctype = "application/json"
        elif path == "/cmd":
            command(query)
            body = status_json()
            ctype = "application/json"
        else:
            body = None
            ctype = "text/html; charset=utf-8"
        head = "HTTP/1.0 200 OK\r\nContent-Type: %s\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n" % ctype
        writer.write(head.encode())
        if body is None:
            with open("page.html", "rb") as f:
                while True:
                    chunk = f.read(1024)
                    if not chunk:
                        break
                    writer.write(chunk)
                    await writer.drain()
        else:
            # 한글이 든 글은 반드시 바이트로 바꿔 보낸다(글자 수와 바이트 수가 달라 깨진다).
            writer.write(body.encode())
            await writer.drain()
    except Exception as e:
        log_error("요청 처리", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


# ---------- 주변 와이파이 훑기 (핫스팟 탐지) ----------
async def wifi_watch():
    """주변 와이파이(핫스팟)를 훑는다.

    훑는 2~3초 동안은 확인용 와이파이와 화면이 잠깐 멈춘다. 그래서 누군가 화면을
    보고 있는 동안에는 훑는 간격을 길게 잡는다.
    """
    await asyncio.sleep(8)   # 켜진 직후에는 확인용 와이파이가 자리 잡을 시간을 준다
    try:
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
    except Exception as e:
        state["wok"] = False
        log_error("와이파이 탐지 시작", e)
        return
    print("핫스팟 훑기 준비됨")
    last = 0
    first = True
    while True:
        now = time.time()
        viewing = now - state.get("last_req", -999) < 15
        gap = 5 if learning() else config.WIFI_EVERY_VIEWING if viewing else config.WIFI_EVERY
        hunting = hunt.active(now)
        if hunting:
            # 블루투스 기기를 찾는 동안에는 훑지 않는다. 핫스팟을 찾는 동안에는 쉬지 않고 훑는다.
            gap = 3 if hunt.wifi else 99999
        if now - last >= gap:
            last = now
            try:
                found = sta.scan()
                wt.scan_result(time.time(), found, learning())
                state["wok"] = True
                if hunting and hunt.wifi:
                    for r in found:
                        if bytes(r[1]) == hunt.addr:
                            hunt.feed(time.ticks_ms(), r[3])
                            break
                if first:
                    first = False
                    print("핫스팟 첫 훑기 끝. 주변 와이파이", len(found), "개")
            except Exception as e:
                state["wok"] = False
                log_error("와이파이 훑기", e)
        await asyncio.sleep(1)


# ---------- 광대역 전파 세기 센서 (A0 = GP26) ----------
async def rf_watch():
    adc = ADC(26)
    sign = -1   # AD8317은 전파가 셀수록 출력 전압이 내려간다
    while True:
        peak = None
        for _ in range(5):
            lo = 65535
            for _ in range(200):
                v = adc.read_u16()
                if v < lo:
                    lo = v
            dbm = config.RF_INTERCEPT + sign * (lo * 3.3 / 65535) / config.RF_SLOPE
            if peak is None or dbm > peak:
                peak = dbm
            await asyncio.sleep_ms(180)
        rf.update(time.time(), peak)


# ---------- LED 10개 ----------
async def indicator():
    wdt = WDT(timeout=8000) if config.WATCHDOG else None
    tick = 0
    shown = None
    while True:
        try:
            now = time.time()
            if wdt:
                wdt.feed()
            if state["scan_done"]:
                start_scan()
            learn = tr.learning_left(now) > 0
            if state.get("learn_save") and not learn:
                state["learn_save"] = False
                save_settings()
            n_hot, n_bt, n_rf = counts(now)
            # 표시는 항상 10칸으로 만들고, LED 개수에 맞게 늘린다(60개면 한 칸이 LED 6개).
            frame = led_frame(n_hot, n_bt, n_rf, tick, learn, 10, config.LED_BRIGHT)
            hmode = hunt.active(now)
            if hmode != state["hmode"]:
                # 정밀 탐색을 시작하거나 끝낼 때 블루투스 듣는 주기를 바꿔 다시 시작한다.
                state["hmode"] = hmode
                if not hmode:
                    hunt.stop()
                try:
                    ble.gap_scan(None)
                except Exception:
                    pass
                state["scan_done"] = True
            if hmode:
                ms = time.ticks_ms()
                frame = hunt_frame(hunt.bars(ms), tick, hunt.lost(ms), 10, config.LED_BRIGHT)
            if STICK and frame != shown:
                full = limit_current(expand_frame(frame, config.LED_COUNT), config.LED_MAX_MA)
                for i in range(config.LED_COUNT):
                    leds[i] = full[i]
                leds.write()
                shown = frame
            # LED 하나: 정상은 3초마다 짧게, 감지는 계속 켜짐, 기준 측정 중은 빠르게 깜박임
            one = (tick % 2) if learn else 1 if (n_hot + n_bt + n_rf) else (1 if tick % 30 == 0 else 0)
            if hmode:   # 정밀 탐색: 신호가 셀수록 빠르게 깜박인다
                one = 1 if tick % (12 - hunt.bars(ms)) == 0 else 0
            if not STICK:
                led_one.value(one)
            if led_board is not None:
                led_board.value(one)
            if tick % 50 == 0:
                tr.sweep(now)
                record(now)
        except Exception as e:
            log_error("표시 루프", e)
        tick += 1
        await asyncio.sleep_ms(100)


async def main():
    load_settings()
    start_ap()                      # 와이파이를 먼저 세운 뒤에 블루투스를 켠다
    await asyncio.start_server(handle, "0.0.0.0", 80)
    await asyncio.sleep(2)
    ble.active(True)
    ble.irq(ble_irq)
    start_scan()
    print("블루투스 듣기 시작")
    if config.WIFI_SCAN:
        asyncio.create_task(wifi_watch())
    if config.RF_SENSOR:
        asyncio.create_task(rf_watch())
    print("감지기", config.UNIT, "시작. 와이파이", config.AP_SSID, "→ http://192.168.4.1")
    await indicator()


try:
    asyncio.run(main())
except Exception as e:
    log_error("시작", e)
    raise
