# LED 줄만 시험하는 파일 (네오픽셀: WS2812, WS2813 / Grove RGB LED Stick, LED 띠)
# Thonny에서 이 파일을 열고 초록 실행 단추(F5)를 누른다. 피코에 저장할 필요는 없다.
# LED는 쉴드의 D16 포트에 꽂는다.

import time
import neopixel
from machine import Pin

N = 10          # LED 개수. 10개짜리면 10, 60개짜리면 60
BRIGHT = 40     # 밝기 1~255
KHZ = 800       # 신호 속도. 안 켜지면 400으로 바꿔 본다
ORDER = "GRB"   # 1단계에서 빨강 대신 초록이 켜지면 "RGB"로 바꾼다

leds = neopixel.NeoPixel(Pin(16), N, timing=1 if KHZ >= 800 else 0)
if ORDER == "RGB":
    leds.ORDER = (0, 1, 2, 3)


def fill(color):
    for i in range(N):
        leds[i] = color
    leds.write()


# 전류를 아끼려고 전체를 켤 때는 밝기를 개수에 맞춰 낮춘다
b = max(4, min(BRIGHT, 250 * 255 // (16 * N)))

print("1단계: 전체 빨강")
fill((b, 0, 0))
time.sleep(2)
print("2단계: 전체 초록")
fill((0, b, 0))
time.sleep(2)
print("3단계: 전체 파랑")
fill((0, 0, b))
time.sleep(2)
print("4단계: 한 개씩 흰색으로 끝까지 (끝까지 가면 개수 N이 맞는 것)")
for i in range(N):
    fill((0, 0, 0))
    leds[i] = (BRIGHT, BRIGHT, BRIGHT)
    leds.write()
    time.sleep(0.08 if N > 20 else 0.3)
fill((0, 0, 0))
print("끝. 빨강→초록→파랑 순서였고 마지막 LED까지 켜졌으면 정상입니다.")
