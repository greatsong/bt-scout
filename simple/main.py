# 교실 블루투스 감지기 - 심플 버전 (Pico 2 WH + Grove 쉴드 + 색이 바뀌는 LED 줄 → D16)
# 이 파일 하나만 피코에 main.py로 저장하면 됩니다.
# 없음: 첫 칸 초록 / 있음: 잡힌 수만큼 파랑 칸 (최대 10칸)
# LED가 60개면 한 칸이 LED 6개가 된다. 아래 N만 바꾸면 된다.

import time
import bluetooth
import neopixel
from machine import Pin

N = 10           # LED 개수. 10개짜리면 10, 60개짜리면 60
RSSI_MIN = -75   # 이 세기 이상만 '가까이 있음'. 더 멀리 잡으려면 -85
PERSIST = 10     # 이만큼(초) 계속 잡혀야 감지 (복도 지나가는 사람 거름)
HOLD = 60        # 마지막으로 잡힌 뒤 불을 켜 두는 시간(초)
BRIGHT = 40      # 밝기 1~255

leds = neopixel.NeoPixel(Pin(16), N)   # 800kHz 신호, 색 순서 GRB
PER = max(1, N // 10)                  # 한 칸에 쓰는 LED 수
devs = {}        # 기기 주소 -> [처음 잡힌 때, 마지막으로 잡힌 때]
ble = bluetooth.BLE()


def on_ble(event, data):
    if event == 5:                     # 블루투스 신호 하나 수신
        addr, rssi = bytes(data[1]), data[3]
        if rssi < RSSI_MIN:
            return
        now = time.time()
        d = devs.get(addr)
        if d is not None and now - d[1] <= 20:
            d[1] = now
        elif d is not None or len(devs) < 100:
            devs[addr] = [now, now]
    elif event == 6:                   # 스캔이 끝나면 다시 시작
        ble.gap_scan(0, 100000, 50000, False)


ble.active(True)
ble.irq(on_ble)
ble.gap_scan(0, 100000, 50000, False)  # 끝없이 듣기만 한다

tick = 0
shown = -1
while True:
    now = time.time()
    count = 0
    for addr, d in list(devs.items()):
        if now - d[1] > HOLD:
            del devs[addr]
        elif d[1] - d[0] >= PERSIST:
            count += 1
    for i in range(N):
        leds[i] = (0, 0, BRIGHT) if i // PER < count else (0, 0, 0)
    if count == 0:
        for i in range(PER):
            leds[i] = (0, BRIGHT, 0)
    leds.write()
    if count != shown:
        print("감지된 블루투스 기기:", count)
        shown = count
    tick += 1
    time.sleep(0.5)
