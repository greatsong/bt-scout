// 와이파이 청취기 (Seeed XIAO ESP32-C3)
// 주변 2.4GHz 와이파이 신호의 "보낸 기기 주소, 세기, 종류"만 모아 2초마다 피코로 보낸다.
// 신호의 내용은 읽지 않고 저장하지도 않는다. 이 보드는 전파를 내보내지 않는다.
//
// 피코로 보내는 줄:
//   A,<공유기 주소>,<세기>,<채널>,<이름(16진수)>        핫스팟·공유기
//   S,<기기 주소>,<세기>,<종류 P|C|D>,<채널>,<상대 공유기 주소 또는 ->   와이파이를 켠 기기
//   H,<줄 수>                                              2초마다 보내는 생존 신호

#include <WiFi.h>
#include "esp_wifi.h"

#define UART_TX_PIN D6
#define UART_RX_PIN D7
#define TABLE_SIZE 48
#define DWELL_MS 300
#define FLUSH_MS 2000

struct Entry {
  bool used;
  char kind;        // 'A' 공유기, 'P' 찾는 중, 'C' 접속 시도, 'D' 자료 전송
  uint8_t mac[6];
  uint8_t peer[6];
  bool hasPeer;
  int8_t rssi;
  uint8_t ch;
  uint8_t ssidLen;
  uint8_t ssid[32];
};

static Entry table_[TABLE_SIZE];
static Entry out_[TABLE_SIZE];
static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static volatile uint8_t channel_ = 1;

static void note(char kind, const uint8_t *mac, const uint8_t *peer, int8_t rssi,
                 const uint8_t *ssid, uint8_t ssidLen) {
  if (mac[0] & 0x01) return;  // 여러 기기에 뿌리는 주소는 제외
  portENTER_CRITICAL(&mux);
  Entry *slot = nullptr;
  for (int i = 0; i < TABLE_SIZE; i++) {
    Entry &e = table_[i];
    if (e.used && e.kind == kind && memcmp(e.mac, mac, 6) == 0) { slot = &e; break; }
    if (!e.used && slot == nullptr) slot = &e;
  }
  if (slot != nullptr) {
    if (!slot->used) {
      slot->used = true;
      slot->kind = kind;
      memcpy(slot->mac, mac, 6);
      slot->rssi = rssi;
      slot->hasPeer = false;
      slot->ssidLen = 0;
    } else if (rssi > slot->rssi) {
      slot->rssi = rssi;
    }
    slot->ch = channel_;
    if (peer != nullptr) { memcpy(slot->peer, peer, 6); slot->hasPeer = true; }
    if (ssid != nullptr && ssidLen <= 32) { memcpy(slot->ssid, ssid, ssidLen); slot->ssidLen = ssidLen; }
  }
  portEXIT_CRITICAL(&mux);
}

static void onPacket(void *buf, wifi_promiscuous_pkt_type_t type) {
  const wifi_promiscuous_pkt_t *pkt = (const wifi_promiscuous_pkt_t *)buf;
  const uint8_t *p = pkt->payload;
  int len = pkt->rx_ctrl.sig_len;
  if (len < 24) return;
  int8_t rssi = pkt->rx_ctrl.rssi;
  uint8_t ftype = (p[0] >> 2) & 0x03;
  uint8_t sub = (p[0] >> 4) & 0x0F;
  bool toDS = p[1] & 0x01;
  bool fromDS = p[1] & 0x02;
  const uint8_t *addr1 = p + 4;
  const uint8_t *addr2 = p + 10;
  const uint8_t *addr3 = p + 16;

  if (ftype == 0) {                       // 관리 신호
    if (sub == 8) {                       // 공유기·핫스팟이 자기를 알리는 신호
      const uint8_t *ssid = nullptr;
      uint8_t ssidLen = 0;
      if (len >= 38 && p[36] == 0 && p[37] <= 32 && 38 + p[37] <= len) {
        ssid = p + 38;
        ssidLen = p[37];
      }
      note('A', addr2, nullptr, rssi, ssid, ssidLen);
    } else if (sub == 4) {                // 기기가 주변 와이파이를 찾는 신호
      note('P', addr2, nullptr, rssi, nullptr, 0);
    } else if (sub == 0 || sub == 2 || sub == 11) {   // 접속 시도
      if (memcmp(addr2, addr3, 6) != 0) note('C', addr2, addr3, rssi, nullptr, 0);
    }
  } else if (ftype == 2) {                // 자료 신호: 기기 → 공유기 방향만
    if (toDS && !fromDS) note('D', addr2, addr1, rssi, nullptr, 0);
  }
}

static void printMac(const uint8_t *m) {
  for (int i = 0; i < 6; i++) Serial1.printf("%02x", m[i]);
}

static void flush() {
  portENTER_CRITICAL(&mux);
  memcpy(out_, table_, sizeof(table_));
  for (int i = 0; i < TABLE_SIZE; i++) table_[i].used = false;
  portEXIT_CRITICAL(&mux);

  int lines = 0;
  for (int i = 0; i < TABLE_SIZE; i++) {
    Entry &e = out_[i];
    if (!e.used) continue;
    if (e.kind == 'A') {
      Serial1.print("A,");
      printMac(e.mac);
      Serial1.printf(",%d,%u,", e.rssi, e.ch);
      for (int k = 0; k < e.ssidLen; k++) Serial1.printf("%02x", e.ssid[k]);
      Serial1.print("\n");
    } else {
      Serial1.print("S,");
      printMac(e.mac);
      Serial1.printf(",%d,%c,%u,", e.rssi, e.kind, e.ch);
      if (e.hasPeer) printMac(e.peer); else Serial1.print("-");
      Serial1.print("\n");
    }
    lines++;
  }
  Serial1.printf("H,%d\n", lines);
}

void setup() {
  Serial1.begin(115200, SERIAL_8N1, UART_RX_PIN, UART_TX_PIN);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  wifi_promiscuous_filter_t filter = {};
  filter.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA;
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(&onPacket);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_channel(channel_, WIFI_SECOND_CHAN_NONE);
}

void loop() {
  static uint32_t lastHop = 0, lastFlush = 0;
  uint32_t now = millis();
  if (now - lastHop >= DWELL_MS) {
    lastHop = now;
    channel_ = channel_ >= 13 ? 1 : channel_ + 1;
    esp_wifi_set_channel(channel_, WIFI_SECOND_CHAN_NONE);
  }
  if (now - lastFlush >= FLUSH_MS) {
    lastFlush = now;
    flush();
  }
  delay(5);
}
