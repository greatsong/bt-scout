# 와이파이만 시험하는 파일. 블루투스 감지는 하지 않는다.
# Thonny에서 이 파일을 열고 초록 실행 단추(F5)를 누른다. 피코에 저장할 필요는 없다.
# 휴대전화에서 와이파이 SCOUT-TEST (암호 scouttest1)에 붙고 http://192.168.4.1 을 연다.

import socket
import time
import network

try:
    import rp2
    rp2.country("KR")
except Exception:
    pass

ap = network.WLAN(network.AP_IF)
ap.config(ssid="SCOUT-TEST", password="scouttest1")
ap.active(True)
try:
    ap.config(pm=0xa11140)
except Exception:
    pass
while not ap.active():
    time.sleep(0.1)
print("와이파이 SCOUT-TEST 준비됨. 주소:", ap.ifconfig()[0])

s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", 80))
s.listen(2)
while True:
    c, addr = s.accept()
    print("휴대전화가 접속함:", addr)
    try:
        c.recv(1024)
        c.send(b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
               + "<h1>연결 성공</h1><p>피코의 와이파이는 정상입니다.</p>".encode())
    finally:
        c.close()
