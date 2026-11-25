# 블루투스 광고 해석과 감지 판정. 하드웨어에 의존하지 않아 Mac의 python3로도 시험한다.

COMPANIES = {
    0x004C: "Apple",
    0x0075: "Samsung",
    0x0006: "Microsoft",
    0x00E0: "Google",
    0x0087: "Garmin",
    0x038F: "Xiaomi",
    0x027D: "Huawei",
    0x012D: "Sony",
    0x009E: "Bose",
    0x0057: "JBL/Harman",
    0x0067: "Jabra",
}

# Apple 제조사 자료 안의 종류 번호. 앞에 있을수록 먼저 표시한다.
APPLE_TYPES = (
    (0x07, "Apple 이어폰(에어팟류)"),
    (0x10, "Apple 기기(아이폰·패드·워치)"),
    (0x12, "Apple 나의 찾기 신호"),
    (0x02, "iBeacon 비콘"),
)

SERVICES = {
    0xFE2C: "안드로이드 이어폰(빠른 페어링)",
    0xFD5A: "삼성 스마트태그",
    0xFEED: "Tile 태그",
}


# 이름에 이런 낱말이 있으면 종류를 이렇게 표시한다(소문자로 비교).
NAME_HINTS = (
    ("glass", "스마트안경 추정"),
    ("ray-ban", "스마트안경 추정"),
    ("rayban", "스마트안경 추정"),
    ("rayneo", "스마트안경 추정"),
    ("xreal", "스마트안경 추정"),
    ("rokid", "스마트안경 추정"),
    ("airpods", "무선 이어폰"),
    ("buds", "무선 이어폰"),
    ("earphone", "무선 이어폰"),
    ("watch", "스마트워치"),
    ("cam", "카메라 추정"),
)


def _apple_kind(body):
    found = set()
    i = 0
    while i + 1 < len(body):
        found.add(body[i])
        i += 2 + body[i + 1]
    for code, label in APPLE_TYPES:
        if code in found:
            return label
    return "Apple 기기"


def parse(adv):
    """광고 자료에서 (기기 종류 추정, 이름)을 꺼낸다. 모르면 빈 문자열."""
    kind = ""
    name = ""
    i = 0
    n = len(adv)
    while i + 1 < n:
        ln = adv[i]
        if ln == 0 or i + 1 + ln > n:
            break
        t = adv[i + 1]
        body = adv[i + 2 : i + 1 + ln]
        if t == 0xFF and len(body) >= 2:
            cid = body[0] | (body[1] << 8)
            if cid == 0x004C:
                kind = _apple_kind(body[2:])
            elif cid in COMPANIES:
                kind = COMPANIES[cid] + " 기기"
        elif t in (0x08, 0x09):
            try:
                name = bytes(body).decode("utf-8")
            except Exception:
                name = ""
        elif t in (0x02, 0x03, 0x16) and len(body) >= 2 and not kind:
            uuid = body[0] | (body[1] << 8)
            if uuid in SERVICES:
                kind = SERVICES[uuid]
        i += 1 + ln
    low = name.lower()
    for word, label in NAME_HINTS:
        if word in low:
            kind = label
            break
    return kind, name


def is_fixed(atype, addr):
    """주소가 바뀌지 않는 기기인가. 휴대전화·이어폰은 대개 주소를 계속 바꾼다."""
    if atype == 0:
        return True
    return (addr[0] & 0xC0) == 0xC0


# 기기 한 대의 기록: 목록 칸 번호
_ATYPE, _KIND, _NAME, _RSSI, _LAST, _S_FIRST, _S_LAST = range(7)


class Tracker:
    def __init__(self, rssi_min=-75, persist=10, gap=20, hold=60, forget=180, max_dev=80):
        self.rssi_min = rssi_min  # 이 세기 이상이어야 '가까이 있음'
        self.persist = persist    # 가까이 있는 상태가 이만큼(초) 이어지면 감지
        self.gap = gap            # 이만큼(초) 끊기면 처음부터 다시 셈
        self.hold = hold          # 마지막으로 잡힌 뒤 불을 켜 두는 시간(초)
        self.forget = forget      # 안 보이는 기기를 지우는 시간(초)
        self.max_dev = max_dev
        self.devs = {}
        self.base = set()         # 기준 측정 때 있던 고정 기기(전자칠판 등)
        self.learn_until = 0

    def start_learning(self, now, secs=60):
        self.base = set()
        self.learn_until = now + secs

    def learning_left(self, now):
        return max(0, self.learn_until - now)

    def seen(self, now, atype, addr, rssi, adv):
        if now < self.learn_until and is_fixed(atype, addr) and len(self.base) < 150:
            self.base.add(addr)
        d = self.devs.get(addr)
        if d is None:
            if len(self.devs) >= self.max_dev:
                self._evict()
            d = [atype, "", "", rssi, now, None, None]
            self.devs[addr] = d
        else:
            d[_RSSI] = (d[_RSSI] * 3 + rssi) // 4
            d[_LAST] = now
        if adv:
            kind, name = parse(adv)
            if kind:
                d[_KIND] = kind
            if name:
                d[_NAME] = name
        if d[_RSSI] >= self.rssi_min:
            if d[_S_LAST] is None or now - d[_S_LAST] > self.gap:
                d[_S_FIRST] = now
            d[_S_LAST] = now

    def _evict(self):
        oldest = None
        for a, d in self.devs.items():
            if oldest is None or d[_LAST] < self.devs[oldest][_LAST]:
                oldest = a
        if oldest is not None:
            del self.devs[oldest]

    def sweep(self, now):
        for a in [a for a, d in self.devs.items() if now - d[_LAST] > self.forget]:
            del self.devs[a]

    def _alert(self, addr, d, now):
        if addr in self.base or d[_S_FIRST] is None:
            return False
        return d[_S_LAST] - d[_S_FIRST] >= self.persist and now - d[_S_LAST] <= self.hold

    def alert_count(self, now):
        n = 0
        for a, d in self.devs.items():
            if self._alert(a, d, now):
                n += 1
        return n

    def alerts(self, now):
        """감지 중인 기기: (주소, 종류, 이름, 세기)"""
        return [(a, d[_KIND], d[_NAME], d[_RSSI]) for a, d in self.devs.items() if self._alert(a, d, now)]

    def snapshot(self, now, limit=40):
        rows = []
        for a, d in self.devs.items():
            rows.append({
                "id": "%02X%02X" % (a[-2], a[-1]),
                "a": "".join("%02x" % x for x in a),
                "k": d[_KIND],
                "n": d[_NAME],
                "r": d[_RSSI],
                "age": now - d[_LAST],
                "al": self._alert(a, d, now),
                "b": a in self.base,
            })
        rows.sort(key=lambda r: (not r["al"], -r["r"]))
        return rows[:limit]


class WifiTracker:
    """와이파이 신호(핫스팟, 기기 간 직접 연결, 공유기)를 스캔 결과로 추적한다.

    피코는 '신호를 내보내는 쪽'(핫스팟·공유기)만 볼 수 있다. 남의 와이파이에
    붙어 있기만 한 기기는 보이지 않는다.
    """

    def __init__(self, rssi_min=-70, hits=2, hold=90, forget=180, skip_prefix="SCOUT"):
        self.rssi_min = rssi_min
        self.hits = hits          # 연속으로 이만큼 스캔에 강하게 잡히면 감지
        self.hold = hold
        self.forget = forget
        self.skip_prefix = skip_prefix  # 다른 감지기의 확인용 와이파이는 제외
        self.nets = {}            # bssid -> [ssid, rssi, channel, last, 연속 횟수]
        self.base = set()

    def scan_result(self, now, results, learning=False):
        seen = set()
        for r in results:
            bssid = bytes(r[1])
            try:
                ssid = bytes(r[0]).decode("utf-8")
            except Exception:
                ssid = "?"
            rssi = r[3]
            seen.add(bssid)
            if learning and len(self.base) < 100:
                self.base.add(bssid)
            d = self.nets.get(bssid)
            if d is None:
                if len(self.nets) >= 60:
                    continue
                d = [ssid, rssi, r[2], now, 0]
                self.nets[bssid] = d
            else:
                d[0], d[1], d[2], d[3] = ssid, rssi, r[2], now
            d[4] = d[4] + 1 if rssi >= self.rssi_min else 0
        for b in list(self.nets):
            d = self.nets[b]
            if b not in seen:
                d[4] = 0
                if now - d[3] > self.forget:
                    del self.nets[b]

    def _kind(self, bssid, ssid):
        if ssid.startswith("DIRECT-"):
            return "기기 간 직접 연결(Wi-Fi Direct)"
        if bssid[0] & 0x02:
            return "휴대 기기 핫스팟 추정"
        return "무선 공유기"

    def _alert(self, bssid, d, now):
        if bssid in self.base or d[0].startswith(self.skip_prefix):
            return False
        return d[4] >= self.hits and now - d[3] <= self.hold

    def alert_count(self, now):
        n = 0
        for b, d in self.nets.items():
            if self._alert(b, d, now):
                n += 1
        return n

    def alerts(self, now):
        """감지 중인 와이파이 신호: (주소, 이름, 종류, 세기)"""
        return [(b, d[0], self._kind(b, d[0]), d[1]) for b, d in self.nets.items() if self._alert(b, d, now)]

    def snapshot(self, now, limit=15):
        rows = []
        for b, d in self.nets.items():
            if d[0].startswith(self.skip_prefix):
                continue
            rows.append({
                "s": d[0] or "(이름 숨김)",
                "a": "".join("%02x" % x for x in b),
                "k": self._kind(b, d[0]),
                "r": d[1],
                "ch": d[2],
                "age": now - d[3],
                "al": self._alert(b, d, now),
                "b": b in self.base,
            })
        rows.sort(key=lambda r: (not r["al"], -r["r"]))
        return rows[:limit]


STA_KINDS = {
    "P": "주변 와이파이를 찾는 중",
    "C": "와이파이에 접속 시도",
    "D": "와이파이로 자료 전송 중",
}


class StaWatch:
    """와이파이를 켠 기기(공유기가 아닌 쪽). ESP32 청취기가 보내 준 것을 모은다.

    이런 기기는 주소를 수시로 바꾸므로 기기별로 세지 않고, '강한 신호가 잡힌
    10초 구간'이 최근 몇 분 안에 몇 번 있었는지로 판정한다.
    """

    def __init__(self, rssi_min=-70, hits=2, window=300, hold=120, forget=300):
        self.rssi_min = rssi_min
        self.hits = hits
        self.window = window
        self.hold = hold
        self.forget = forget
        self.devs = {}      # mac -> [rssi, last, kind, channel]
        self.base = set()   # 기준 측정 때 있던 고정 주소 기기(교실 컴퓨터, 프린터 등)
        self.events = []    # 강한 신호가 잡힌 10초 구간 번호

    def seen(self, now, mac, rssi, kind, ch, learning=False):
        if learning and not (mac[0] & 0x02) and len(self.base) < 150:
            self.base.add(mac)
        d = self.devs.get(mac)
        if d is None:
            if len(self.devs) >= 60:
                return
            self.devs[mac] = [rssi, now, kind, ch]
        else:
            d[0], d[1], d[2], d[3] = rssi, now, kind, ch
        if rssi >= self.rssi_min and mac not in self.base and not learning:
            b = now // 10
            if not self.events or self.events[-1] != b:
                self.events.append(b)

    def sweep(self, now):
        lo = (now - self.window) // 10
        while self.events and self.events[0] < lo:
            self.events.pop(0)
        for m in [m for m, d in self.devs.items() if now - d[1] > self.forget]:
            del self.devs[m]

    def alert(self, now):
        self.sweep(now)
        if len(self.events) < self.hits:
            return False
        return now - self.events[-1] * 10 <= self.hold + 10

    def alert_count(self, now):
        """감지 중이면 최근 1분 안에 강하게 잡힌 주소 수(최소 1). 주소가 바뀌어 실제보다 많을 수 있다."""
        if not self.alert(now):
            return 0
        n = 0
        for m, d in self.devs.items():
            if d[0] >= self.rssi_min and m not in self.base and now - d[1] <= 60:
                n += 1
        return max(1, n)

    def snapshot(self, now, limit=15):
        on = self.alert(now)
        rows = []
        for m, d in self.devs.items():
            strong = d[0] >= self.rssi_min and m not in self.base
            rows.append({
                "id": "%02X%02X" % (m[-2], m[-1]),
                "k": STA_KINDS.get(d[2], "와이파이 신호"),
                "r": d[0],
                "ch": d[3],
                "age": now - d[1],
                "al": on and strong and now - d[1] <= self.window,
                "b": m in self.base,
            })
        rows.sort(key=lambda r: (not r["al"], -r["r"]))
        return rows[:limit]


class RfWatch:
    """광대역 전파 세기 센서(AD8317). 평소 수준보다 갑자기 세진 순간을 센다."""

    def __init__(self, delta=10, hits=3, window=60):
        self.delta = delta    # 평소보다 이만큼(dB) 세면 '급증'
        self.hits = hits
        self.window = window
        self.floor = None     # 평소 수준
        self.cur = None
        self.events = []

    def update(self, now, dbm):
        self.cur = dbm
        if self.floor is None:
            self.floor = dbm
        elif dbm < self.floor + self.delta:
            self.floor += (dbm - self.floor) * 0.05
        else:
            self.floor += 0.02   # 계속 센 상태가 이어지면 아주 천천히 평소 수준으로 받아들임
            if not self.events or self.events[-1] != now:
                self.events.append(now)
        while self.events and self.events[0] < now - self.window:
            self.events.pop(0)

    def alert(self, now):
        return len([t for t in self.events if t >= now - self.window]) >= self.hits

    def status(self, now):
        if self.cur is None:
            return None
        return {"cur": round(self.cur), "floor": round(self.floor),
                "n": len([t for t in self.events if t >= now - self.window]), "al": self.alert(now)}


# ---------- LED 10개 표시 ----------
LED_OFF = (0, 0, 0)


def led_frame(n_hot, n_bt, n_sta, n_rf, tick, learning=False, warn=False, n=10, bright=40):
    """LED 10개에 켤 색을 정한다. tick은 0.1초마다 1씩 느는 수.

    빨강 = 와이파이(핫스팟, 기기 간 직접 연결, 와이파이를 켠 기기),
    파랑 = 블루투스 기기, 흰색 = 광대역 전파 급증.
    감지가 없으면 첫 칸이 초록으로 켜져 있다.
    """
    b = bright
    green = (0, b, 0)
    if learning:   # 기준 측정 중: 초록이 한 칸씩 번갈아 깜박임
        return [green if (i + tick // 3) % 2 == 0 else LED_OFF for i in range(n)]
    kinds = [((b, 0, 0), n_hot + n_sta), ((0, 0, b), n_bt), ((b, b, b), n_rf)]
    present = [[c, k] for c, k in kinds if k > 0]
    frame = []
    if not present:
        frame = [green] + [LED_OFF] * (n - 1)
    else:
        # 칸이 모자라도 잡힌 종류마다 최소 한 칸은 보이게 한다.
        take = [1] * len(present)
        left = n - len(present)
        for i, (c, k) in enumerate(present):
            more = min(k - 1, left)
            take[i] += more
            left -= more
        # 색이 다른 묶음 사이에 꺼진 칸을 하나 둔다(빨강과 파랑이 붙으면 보라색처럼 보인다).
        # 칸이 모자라면 띄우지 않는다.
        gaps = len(present) - 1 if sum(take) + len(present) - 1 <= n else 0
        for i, ((c, k), t) in enumerate(zip(present, take)):
            if i and gaps:
                frame.append(LED_OFF)
            frame += [c] * t
        frame += [LED_OFF] * (n - len(frame))
    if warn and frame[n - 1] == LED_OFF and tick % 10 < 5:
        frame[n - 1] = (b, b // 4, 0)   # 마지막 칸 주황 깜박임: ESP32에서 신호가 안 옴
    return frame


# ---------- 최근 N시간 기록 ----------
class History:
    """1분 단위 감지 수와 감지 사건 목록을 메모리에 보관한다. 전원이 꺼지면 사라진다."""

    def __init__(self, hours=6, max_events=60):
        self.hours = hours
        self.max_events = max_events
        self.start = None
        self.bins = []      # [분 번호, 블루투스, 핫스팟, 와이파이 켠 기기] (감지가 있던 분만)
        self.events = []    # [시작, 끝, 분류, 설명, 가장 센 세기]
        self.open = {}

    def sample(self, now, n_hot, n_bt, n_sta):
        if self.start is None:
            self.start = now
        m = now // 60
        if n_hot or n_bt or n_sta:
            if self.bins and self.bins[-1][0] == m:
                b = self.bins[-1]
                b[1] = max(b[1], n_bt)
                b[2] = max(b[2], n_hot)
                b[3] = max(b[3], n_sta)
            else:
                self.bins.append([m, n_bt, n_hot, n_sta])
        lo = m - self.hours * 60
        while self.bins and self.bins[0][0] < lo:
            self.bins.pop(0)
        while self.events and self.events[0][1] < now - self.hours * 3600:
            self.events.pop(0)

    def note(self, now, key, cat, label, rssi):
        e = self.open.get(key)
        if e is not None and now - e[1] <= 120:
            e[1] = now
            if rssi > e[4]:
                e[4] = rssi
            if label and len(label) > len(e[3]):
                e[3] = label
            return
        e = [now, now, cat, label, rssi]
        self.open[key] = e
        self.events.append(e)
        if len(self.events) > self.max_events:
            self.events.pop(0)
        if len(self.open) > 80:
            for k in [k for k, v in self.open.items() if now - v[1] > 120]:
                del self.open[k]

    def dump(self, now):
        return {"now": now, "start": self.start if self.start is not None else now,
                "hours": self.hours, "bins": self.bins, "events": self.events}


def expand_frame(frame, total):
    """10칸짜리 표시를 LED 개수에 맞게 늘린다. 60개면 한 칸이 LED 6개가 된다."""
    per = max(1, total // len(frame))
    out = []
    for c in frame:
        # 한 칸이 LED 3개 이상이면 마지막 하나는 꺼서 칸과 칸이 구분되어 보이게 한다.
        out += [c] * (per - 1) + [LED_OFF] if per >= 3 else [c] * per
    out = out[:total]
    return out + [LED_OFF] * (total - len(out))


def limit_current(frame, max_ma, ma_per_channel=16):
    """모든 LED가 쓰는 전류(추정)가 max_ma를 넘으면 전체 밝기를 낮춘다."""
    total = 0
    for r, g, b in frame:
        total += r + g + b
    ma = total * ma_per_channel / 255
    if ma <= max_ma or total == 0:
        return frame
    k = max_ma / ma
    return [(int(r * k), int(g * k), int(b * k)) for r, g, b in frame]


# ---------- 정밀 탐색: 고른 기기 하나의 신호 세기를 빠르게 따라간다 ----------
class Hunt:
    """감지기를 손에 들고 다니며 신호가 나오는 곳을 좁혀 갈 때 쓴다.

    신호 세기는 한 번 한 번이 크게 흔들리므로 최근 값 몇 개의 가운데 값을 쓴다.
    시각은 초(now)와 밀리초(ms) 두 가지를 쓴다. ms는 끊김을 빨리 알아채려는 것이다.
    """

    LOW, HIGH = -90, -35      # 눈금 0칸과 10칸에 해당하는 세기(dBm)

    def __init__(self, secs=300, keep=8):
        self.secs = secs      # 시작한 뒤 이만큼(초) 지나면 스스로 끝난다
        self.keep = keep
        self.addr = None
        self.stop()

    def start(self, now, addr, wifi=False, label=""):
        self.addr = addr
        self.wifi = wifi      # True면 핫스팟(와이파이). 2~3초에 한 번만 값이 온다
        self.label = label
        self.until = now + self.secs
        self.buf = []
        self.peak = None
        self.last = None
        self.n = 0

    def stop(self):
        self.addr = None
        self.wifi = False
        self.label = ""
        self.until = 0
        self.buf = []
        self.peak = None
        self.last = None
        self.n = 0

    def active(self, now):
        return self.addr is not None and now < self.until

    def feed(self, ms, rssi):
        self.buf.append(rssi)
        if len(self.buf) > (2 if self.wifi else self.keep):
            self.buf.pop(0)
        self.last = ms
        self.n += 1
        lv = self.level()
        if self.peak is None or lv > self.peak:
            self.peak = lv

    def level(self):
        """최근 값들의 가운데 값. 아직 없으면 None"""
        if not self.buf:
            return None
        b = sorted(self.buf)
        return b[len(b) // 2]

    def clear_peak(self):
        self.peak = self.level()

    def age_ms(self, ms):
        """마지막으로 잡힌 뒤 지난 시간(밀리초). 한 번도 안 잡혔으면 None"""
        if self.last is None:
            return None
        return max(0, ms - self.last)

    def lost(self, ms):
        a = self.age_ms(ms)
        return a is None or a > (9000 if self.wifi else 3000)

    def bars(self, ms, n=10):
        """세기를 0~n칸으로. 신호가 끊겼으면 0"""
        lv = self.level()
        if lv is None or self.lost(ms):
            return 0
        k = (lv - self.LOW) * n // (self.HIGH - self.LOW)
        return max(1, min(n, k))

    def status(self, now, ms):
        if not self.active(now):
            return {"on": False}
        return {
            "on": True,
            "a": "".join("%02x" % x for x in self.addr),
            "w": self.wifi,
            "label": self.label,
            "r": self.level(),
            "raw": self.buf[-1] if self.buf else None,
            "pk": self.peak,
            "age": self.age_ms(ms),
            "lost": self.lost(ms),
            "bars": self.bars(ms),
            "n": self.n,
            "left": self.until - now,
        }


def hunt_frame(bars, tick, lost=False, n=10, bright=40):
    """정밀 탐색 중의 LED: 신호가 셀수록 노란 칸이 많이 켜진다. 끊기면 첫 칸만 깜박인다."""
    y = (bright, bright * 2 // 3, 0)
    if lost or bars <= 0:
        return [y if tick % 6 < 3 else LED_OFF] + [LED_OFF] * (n - 1)
    return [y] * min(n, bars) + [LED_OFF] * (n - min(n, bars))
