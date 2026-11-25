import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))
from detect import History, Hunt, hunt_frame, RfWatch, expand_frame, limit_current, Tracker, WifiTracker, is_fixed, led_frame, parse  # noqa: E402

IPHONE = bytes([2, 1, 0x1A, 7, 0xFF, 0x4C, 0x00, 0x10, 0x03, 1, 2, 3])
AIRPODS = bytes([6, 0xFF, 0x4C, 0x00, 0x07, 0x01, 0x00])
BUDS = bytes([3, 0x03, 0x2C, 0xFE]) + bytes([12, 0x09]) + b"Galaxy Buds"
SAMSUNG = bytes([5, 0xFF, 0x75, 0x00, 1, 2])
RANDOM = bytes([0x5A, 1, 2, 3, 4, 5])   # 주소가 바뀌는 기기
FIXED = bytes([0xD0, 1, 2, 3, 4, 5])    # 고정 주소 기기


class ParseTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(parse(IPHONE)[0], "Apple 기기(아이폰·패드·워치)")
        self.assertEqual(parse(AIRPODS)[0], "Apple 이어폰(에어팟류)")
        self.assertEqual(parse(BUDS), ("무선 이어폰", "Galaxy Buds"))   # 이름이 우선
        self.assertEqual(parse(BUDS[:4])[0], "안드로이드 이어폰(빠른 페어링)")
        self.assertEqual(parse(SAMSUNG)[0], "Samsung 기기")

    def test_broken_data(self):
        self.assertEqual(parse(b""), ("", ""))
        self.assertEqual(parse(bytes([30, 0xFF, 0x4C])), ("", ""))
        self.assertEqual(parse(bytes([3, 0xFF, 0x4C, 0x00, 0x10])), ("Apple 기기", ""))

    def test_fixed(self):
        self.assertTrue(is_fixed(0, RANDOM))
        self.assertTrue(is_fixed(1, FIXED))
        self.assertFalse(is_fixed(1, RANDOM))


class TrackerTest(unittest.TestCase):
    def feed(self, tr, addr, start, end, rssi, atype=1, adv=IPHONE):
        for t in range(start, end + 1):
            tr.seen(t, atype, addr, rssi, adv)

    def test_stays_in_room(self):
        tr = Tracker()
        self.feed(tr, RANDOM, 0, 9, -60)
        self.assertEqual(tr.alert_count(9), 0)
        self.feed(tr, RANDOM, 10, 12, -60)
        self.assertEqual(tr.alert_count(12), 1)
        self.assertTrue(tr.snapshot(12)[0]["al"])
        self.assertEqual(tr.alert_count(12 + 60), 1)
        self.assertEqual(tr.alert_count(12 + 61), 0)

    def test_passerby_ignored(self):
        tr = Tracker()
        self.feed(tr, RANDOM, 0, 6, -60)
        self.assertEqual(tr.alert_count(30), 0)
        self.feed(tr, RANDOM, 40, 46, -60)   # 20초 넘게 끊겼으므로 다시 셈
        self.assertEqual(tr.alert_count(46), 0)

    def test_weak_signal_ignored(self):
        tr = Tracker()
        self.feed(tr, RANDOM, 0, 60, -88)
        self.assertEqual(tr.alert_count(60), 0)

    def test_baseline_only_fixed(self):
        tr = Tracker()
        tr.start_learning(0, 60)
        self.feed(tr, FIXED, 0, 30, -55)
        self.feed(tr, RANDOM, 0, 30, -55)
        self.assertEqual(tr.base, {FIXED})
        self.assertEqual(tr.learning_left(100), 0)
        self.feed(tr, FIXED, 100, 130, -55)
        self.feed(tr, RANDOM, 100, 130, -55)
        self.assertEqual(tr.alert_count(130), 1)

    def test_limits(self):
        tr = Tracker(max_dev=5)
        for i in range(20):
            tr.seen(i, 1, bytes([0x40, 0, 0, 0, 0, i]), -60, b"")
        self.assertEqual(len(tr.devs), 5)
        tr.sweep(19 + 181)
        self.assertEqual(len(tr.devs), 0)


class WifiTest(unittest.TestCase):
    HOT = (b"AndroidAP", bytes([0x7A, 1, 2, 3, 4, 5]), 6, -55, 3, 0)
    DIRECT = (b"DIRECT-ab-Tab", bytes([0x12, 1, 2, 3, 4, 6]), 1, -60, 3, 0)
    FAR = (b"apt-wifi", bytes([0x00, 1, 2, 3, 4, 7]), 11, -88, 3, 0)
    OURS = (b"SCOUT-2F-B", bytes([0x28, 1, 2, 3, 4, 8]), 6, -40, 3, 0)

    def test_hotspot_needs_two_scans(self):
        wt = WifiTracker()
        wt.scan_result(0, [self.HOT, self.FAR, self.OURS])
        self.assertEqual(wt.alert_count(0), 0)
        wt.scan_result(20, [self.HOT, self.DIRECT, self.FAR, self.OURS])
        self.assertEqual(wt.alert_count(20), 1)
        rows = wt.snapshot(20)
        self.assertEqual(rows[0]["s"], "AndroidAP")
        self.assertEqual(rows[0]["k"], "휴대 기기 핫스팟 추정")
        self.assertNotIn("SCOUT-2F-B", [r["s"] for r in rows])
        wt.scan_result(40, [self.DIRECT, self.FAR])
        self.assertEqual(wt.alert_count(40), 1)   # 핫스팟은 사라졌고 직접 연결이 2회째
        self.assertEqual(wt.snapshot(40)[0]["k"], "기기 간 직접 연결(Wi-Fi Direct)")

    def test_baseline_and_forget(self):
        wt = WifiTracker()
        wt.scan_result(0, [self.HOT], learning=True)
        wt.scan_result(20, [self.HOT])
        wt.scan_result(40, [self.HOT])
        self.assertEqual(wt.alert_count(40), 0)
        wt.scan_result(40 + 181, [])
        self.assertEqual(len(wt.nets), 0)

    def test_name_hint(self):
        adv = bytes([14, 0x09]) + b"Ray-Ban Meta "
        self.assertEqual(parse(adv)[0], "스마트안경 추정")


class LedTest(unittest.TestCase):
    G, R, B, Y, W, O = (0, 40, 0), (40, 0, 0), (0, 0, 40), (40, 25, 0), (40, 40, 40), (0, 0, 0)

    def test_idle_green(self):
        self.assertEqual(led_frame(0, 0, 0, 0), [self.G] + [self.O] * 9)
        self.assertEqual(led_frame(0, 0, 0, 5), [self.G] + [self.O] * 9)

    def test_counts_and_colors(self):
        f = led_frame(3, 3, 0, 7)
        self.assertEqual(f, [self.R] * 3 + [self.O] + [self.B] * 3 + [self.O] * 3)   # 빨강과 파랑 사이를 띄움
        self.assertEqual(led_frame(4, 6, 0, 7), [self.R] * 4 + [self.B] * 6)       # 칸이 모자라면 붙임

    def test_overflow_keeps_every_kind(self):
        f = led_frame(6, 30, 1, 0)
        self.assertEqual(len(f), 10)
        self.assertEqual(f.count(self.R), 6)
        self.assertEqual(f.count(self.B), 3)
        self.assertEqual(f[-1], self.W)

    def test_learning(self):
        f = led_frame(0, 5, 0, 0, learning=True)
        self.assertEqual(f.count(self.G), 5)


class HistoryTest(unittest.TestCase):
    def test_bins_and_events(self):
        h = History(hours=1)
        h.sample(0, 0, 0)
        self.assertEqual(h.bins, [])
        h.sample(65, 0, 2)
        h.sample(70, 1, 3)
        self.assertEqual(h.bins, [[1, 3, 1]])
        h.note(65, b"a", "bt", "Apple", -70)
        h.note(100, b"a", "bt", "Apple 이어폰", -60)
        h.note(400, b"a", "bt", "Apple 이어폰", -65)     # 2분 넘게 끊겼으므로 새 사건
        self.assertEqual(len(h.events), 2)
        self.assertEqual(h.events[0], [65, 100, "bt", "Apple 이어폰", -60])
        h.sample(65 + 3700, 0, 1)                      # 1시간 지난 것은 지움
        self.assertEqual(len(h.bins), 1)
        self.assertEqual([e[0] for e in h.events], [400])   # 65초에 시작한 사건만 지워짐
        d = h.dump(5000)
        self.assertEqual((d["start"], d["hours"]), (0, 1))

    def test_event_cap_and_alert_lists(self):
        h = History(max_events=5)
        for i in range(20):
            h.note(i, i, "bt", "x", -60)
        self.assertEqual(len(h.events), 5)
        tr = Tracker()
        for t in range(0, 13):
            tr.seen(t, 1, RANDOM, -60, IPHONE)
        self.assertEqual(tr.alerts(12)[0][1], "Apple 기기(아이폰·패드·워치)")
        wt = WifiTracker()
        hot = (b"AndroidAP", bytes([0x7A, 1, 2, 3, 4, 5]), 6, -55, 3, 0)
        wt.scan_result(0, [hot]); wt.scan_result(20, [hot])
        self.assertEqual(wt.alerts(20)[0][1:3], ("AndroidAP", "휴대 기기 핫스팟 추정"))


class LedSizeTest(unittest.TestCase):
    def test_expand_to_60_and_10(self):
        f = led_frame(1, 2, 0, 7)
        self.assertEqual(expand_frame(f, 10), f)
        big = expand_frame(f, 60)
        self.assertEqual(len(big), 60)
        off = (0, 0, 0)
        self.assertEqual(big[:6], [(40, 0, 0)] * 5 + [off])          # 칸마다 마지막 LED는 꺼짐
        self.assertEqual(big[6:12], [off] * 6)                       # 빨강과 파랑 사이 빈 칸
        self.assertEqual(big[12:24], ([(0, 0, 40)] * 5 + [off]) * 2)
        self.assertEqual(big[24:], [off] * 36)
        self.assertEqual(len(expand_frame(f, 8)), 8)
        odd = expand_frame(f, 64)
        self.assertEqual((len(odd), odd[60:]), (64, [(0, 0, 0)] * 4))

    def test_current_limit(self):
        full = [(255, 255, 255)] * 60          # 16mA x 3색 x 60개 = 2880mA
        out = limit_current(full, 250)
        ma = sum(r + g + b for r, g, b in out) * 16 / 255
        self.assertLessEqual(ma, 250)
        self.assertGreater(ma, 200)
        dim = [(0, 0, 40)] * 10
        self.assertEqual(limit_current(dim, 250), dim)


class HuntTest(unittest.TestCase):
    def test_follows_one_device(self):
        h = Hunt(secs=300)
        self.assertFalse(h.active(0))
        h.start(100, b"\x01\x02\x03\x04\x05\x06", label="이어폰")
        self.assertTrue(h.active(100))
        self.assertTrue(h.lost(0))                  # 아직 한 번도 안 잡힘
        for i, r in enumerate((-70, -72, -40, -71, -69)):   # -40 하나는 튄 값
            h.feed(1000 + i * 100, r)
        self.assertEqual(h.level(), -70)            # 가운데 값이라 튄 값에 끌려가지 않는다
        self.assertFalse(h.lost(1500))
        self.assertTrue(h.lost(1400 + 3001))        # 3초 넘게 안 잡히면 끊김
        self.assertEqual(h.bars(1400 + 3001), 0)
        self.assertFalse(h.active(100 + 300))       # 5분 뒤 스스로 끝남

    def test_closer_means_more_bars(self):
        far, near = Hunt(), Hunt()
        far.start(0, b"a")
        near.start(0, b"a")
        for i in range(8):
            far.feed(i, -85)
            near.feed(i, -40)
        self.assertLess(far.bars(10), near.bars(10))
        self.assertEqual(near.peak, -40)
        st = near.status(1, 10)
        self.assertTrue(st["on"])
        self.assertEqual(st["r"], -40)
        near.stop()
        self.assertEqual(near.status(1, 10), {"on": False})

    def test_led_meter(self):
        f = hunt_frame(4, 0, False, 10, 40)
        self.assertEqual(sum(1 for c in f if c != (0, 0, 0)), 4)
        lost = hunt_frame(0, 0, True, 10, 40)
        self.assertEqual(sum(1 for c in lost if c != (0, 0, 0)), 1)
        self.assertEqual(sum(1 for c in hunt_frame(0, 3, True, 10, 40) if c != (0, 0, 0)), 0)


if __name__ == "__main__":
    unittest.main()
