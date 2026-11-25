"""피코 없이 Mac에서 확인 화면을 미리 본다. 가상 기기 자료만 사용한다.

    python3 tools/preview_server.py   →  http://localhost:8765
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware")
sys.path.insert(0, ROOT)
import math  # noqa: E402
from detect import History, Hunt, RfWatch, StaWatch, Tracker, WifiTracker  # noqa: E402

UNIT = os.environ.get('UNIT', '1학년 1,2반')
QUIET = os.environ.get('QUIET') == '1'   # 1이면 가까운 가상 기기가 없는 조용한 감지기
hist = History(hours=6)
_now = int(time.time())
hist.start = _now - 5 * 3600
if not QUIET:
    for back, bt, hot in ((250, 1, 0), (249, 1, 0), (130, 2, 0), (129, 2, 1), (128, 1, 1), (40, 1, 0)):
        hist.bins.append([(_now - back * 60) // 60, bt, hot, 0])
    hist.events += [[_now - 250 * 60, _now - 248 * 60, 'bt', 'Apple 이어폰(에어팟류)', -66],
                    [_now - 130 * 60, _now - 127 * 60, 'bt', '무선 이어폰 · Galaxy Buds', -61],
                    [_now - 129 * 60, _now - 127 * 60, 'hot', 'AndroidAP_7731 · 휴대 기기 핫스팟 추정', -58]]

tr = Tracker()
wt = WifiTracker()
st = StaWatch()
rf = RfWatch()
hunt = Hunt()
STAS = [(bytes([0x3A, 9, 9, 9, 0x51, 0xEE]), -61, 'P', 6), (bytes([0x00, 9, 9, 9, 0x10, 0x02]), -57, 'D', 1),
        (bytes([0x9E, 9, 9, 9, 0x44, 0x0B]), -84, 'P', 11)]
WIFI = [(b'AndroidAP_7731', bytes([0x7A, 1, 2, 3, 4, 5]), 6, -55, 3, 0),
        (b'DIRECT-xy-Tab', bytes([0x12, 1, 2, 3, 4, 6]), 1, -62, 3, 0),
        (b'school-ap', bytes([0x00, 1, 2, 3, 4, 7]), 11, -85, 3, 0),
        (b'SCOUT-2F-B', bytes([0x28, 1, 2, 3, 4, 8]), 6, -50, 3, 0)]
last_w = [0]
T0 = int(time.time())
FAKE = [
    (1, bytes([0x5A, 1, 2, 3, 0xA1, 0xB2]), -58, bytes([7, 0xFF, 0x4C, 0x00, 0x10, 0x03, 1, 2, 3])),
    (1, bytes([0x61, 1, 2, 3, 0x0C, 0x77]), -66, bytes([3, 0x03, 0x2C, 0xFE, 12, 0x09]) + b"Galaxy Buds"),
    (0, bytes([0x00, 1, 2, 3, 0x33, 0x10]), -50, bytes([5, 0xFF, 0x75, 0x00, 1, 2])),
    (1, bytes([0x4B, 1, 2, 3, 0x9E, 0x05]), -90, b""),
]


def feed():
    now = int(time.time())
    for atype, addr, rssi, adv in FAKE:
        tr.seen(now, atype, addr, rssi - (30 if QUIET else 0), adv)
    if now - T0 < 14 and not QUIET:   # 잠깐 잡히다 사라지는 기기
        tr.seen(now, 1, bytes([0x66, 1, 2, 3, 0x7C, 0x21]), -63, bytes([6, 0xFF, 0x4C, 0x00, 0x07, 0x01, 0x00]))
    if now - last_w[0] >= 5:
        last_w[0] = now
        wt.scan_result(now, [(w[0], w[1], w[2], w[3] - (30 if QUIET else 0)) + w[4:] for w in WIFI], tr.learning_left(now) > 0)
        hist.sample(now, wt.alert_count(now), tr.alert_count(now), 0)
        for a, kind, name, rssi in tr.alerts(now):
            hist.note(now, a, 'bt', (kind or '종류 모름') + (' · ' + name if name else ''), rssi)
    for mac, rssi, kind, ch in STAS:
        st.seen(now, mac, rssi - (30 if QUIET else 0), kind, ch, tr.learning_left(now) > 0)
    rf.update(now, -48 + (22 if now % 20 < 2 else now % 3))
    return now


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        path, _, query = self.path.partition("?")
        now = feed()
        if path == "/cmd":
            for part in query.split("&"):
                k, _, v = part.partition("=")
                if k in ("hunt", "whunt"):
                    if v == "off":
                        hunt.stop()
                    else:
                        addr = bytes.fromhex(v)
                        d = tr.devs.get(addr)
                        n = wt.nets.get(addr)
                        label = (n[0] if n else "와이파이 신호") if k == "whunt" else \
                            ((d[1] or "종류 모름") + (" · " + d[2] if d[2] else "")) if d else "블루투스 기기"
                        hunt.start(now, addr, k == "whunt", label)
                elif k == "peak":
                    hunt.clear_peak()
                elif k == "th":
                    tr.rssi_min = int(v)
                elif k == "learn":
                    tr.start_learning(now, 60)
                    wt.base = set()
                    st.base = set()
                elif k == "clearbase":
                    tr.base = set()
                    wt.base = set()
                    st.base = set()
        ms = int(time.time() * 1000)
        if hunt.active(now):   # 가까워졌다 멀어지는 가상 신호
            hunt.feed(ms, int(-62 + 24 * math.sin(time.time() / 6) + (ms % 7) - 3))
        if path == "/t":
            body = json.dumps(hunt.status(now, ms)).encode()
            ctype = "application/json"
        elif path == "/h":
            d = hist.dump(now)
            d.update(unit=UNIT, counts=[wt.alert_count(now), tr.alert_count(now), st.alert_count(now), 0])
            body = json.dumps(d).encode()
            ctype = "application/json"
        elif path in ("/s", "/cmd"):
            body = json.dumps({
                "unit": UNIT, "alerts": tr.alert_count(now) + wt.alert_count(now) + st.alert_count(now), "wok": True,
                "sniff": True, "sta": st.snapshot(now), "rf": rf.status(now), "wifi": wt.snapshot(now),
                "th": tr.rssi_min, "counts": [wt.alert_count(now), tr.alert_count(now), st.alert_count(now), 0], "base": len(tr.base) + len(wt.base) + len(st.base),
                "learn": tr.learning_left(now), "hunt": hunt.active(now), "total": len(tr.devs), "devs": tr.snapshot(now),
            }).encode()
            ctype = "application/json"
        else:
            with open(os.path.join(ROOT, "page.html"), "rb") as f:
                body = f.read()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8765), H).serve_forever()
