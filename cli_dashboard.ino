// AI CLI Dashboard for Waveshare ESP32-C6-LCD-1.47 (ST7789, landscape 320x172)
// USB-SERIAL build: receives /state JSON over USB (no WiFi -> much cooler/cooler).
// A host script writes the hub's /state JSON (one line) to the serial port.
// BOOT (GPIO9) cycles channels. On-board WS2812 (GPIO8) breathes on completion.
//
// Board:  esp32:esp32:esp32c6:CDCOnBoot=cdc   (Serial = USB CDC)
// Libs:   GFX Library for Arduino, ArduinoJson, U8g2

#include <ArduinoJson.h>
#include <U8g2lib.h>
#include <Arduino_GFX_Library.h>
#include "cjk_glyphs.h"          // 1-bit glyphs for "创意开发"
#include "welcome_glyphs.h"       // 1-bit glyphs for "主人欢迎回来"

#define BLACK    RGB565_BLACK
#define WHITE    RGB565_WHITE
#define RED      RGB565_RED
#define GREEN    RGB565(72, 232, 150)
#define YELLOW   RGB565(255, 211, 72)
#define CYAN     RGB565(61, 220, 235)
#define MAGENTA  RGB565(235, 120, 195)
#define DARKGREY RGB565(83, 98, 105)
#define NAVY     RGB565(11, 22, 55)     // splash background
#define HUD_BG   RGB565(12, 16, 19)      // dashboard background
#define HUD_PANEL RGB565(22, 27, 30)     // dashboard header/footer
#define HUD_GRID RGB565(43, 51, 56)      // low-contrast instrumentation
#define HUD_SOFT RGB565(146, 161, 164)   // secondary text
#define GOLD     RGB565(232, 196, 74)    // logo badge
#define PET      RGB565(235, 140, 95)    // pet body (coral)

// Waveshare ESP32-C6-LCD-1.47 pin map
#define LCD_DC   15
#define LCD_CS   14
#define LCD_SCK   7
#define LCD_MOSI  6
#define LCD_RST  21
#define LCD_BL   22
#define BOOT_BTN  9
#define RGB_PIN   8
#define BL_LEVEL 110   // backlight PWM 0-255 (dimmed to run cooler)

Arduino_DataBus *bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCK, LCD_MOSI, GFX_NOT_DEFINED);
Arduino_GFX *panel = new Arduino_ST7789(bus, LCD_RST, 1, true, 172, 320, 34, 0, 34, 0);
Arduino_Canvas *gfx = new Arduino_Canvas(320, 172, panel);

const int W = 320, H = 172;
const int NUM = 4;
struct Chan {
  String id = "";
  String name = "?";
  int windows = 0;
  String usage = "";
  String status = "idle";
  String tasks[5];
  String taskDisplay = "";
  int nTasks = 0;
  String pets[8];
  int nPets = 0;
};
Chan chans[NUM];
int view = 1;   // default to Codex
int focusSeen = -1;
uint32_t focusRevisionSeen = 0;
bool haveData = false;
bool everHadData = false;
int flashSeen = -1;
int btnPrev = HIGH;
uint32_t btnMs = 0;
uint32_t lastData = 0;
uint32_t animFrame = 0, lastAnim = 0;
uint32_t celebrateStart = 0;
bool celebrating = false;
String doneCli = "";
String doneCliId = "";
bool isSleep = false;
const uint32_t STALE_MS = 12000;
const uint32_t CELEBRATE_MS = 2200;

// serial line buffer
char buf[8192];
int blen = 0;
bool lineOverflow = false;

// LED breathing
bool ledActive = false;
uint32_t ledStart = 0;
const uint32_t LED_MS = 2600;
uint8_t ledR = 0, ledG = 180, ledB = 40;

static uint16_t statusColor(const String &s) {
  if (s == "running") return GREEN;
  if (s == "done") return YELLOW;
  return DARKGREY;
}
static uint16_t cliColor(const String &id) {
  if (id == "claude") return MAGENTA;
  if (id == "codex") return CYAN;
  if (id == "cursor") return GREEN;
  if (id == "qoder") return YELLOW;
  return WHITE;
}
static void setLedColorForCli(const String &id) {
  if (id == "claude")      { ledR = 150; ledG = 55;  ledB = 180; }
  else if (id == "codex")  { ledR = 0;   ledG = 150; ledB = 190; }
  else if (id == "cursor") { ledR = 40;  ledG = 180; ledB = 55;  }
  else if (id == "qoder")  { ledR = 190; ledG = 135; ledB = 20;  }
  else                     { ledR = 0;   ledG = 180; ledB = 40;  }
}
static String fit(const String &s, int maxChars) {
  if ((int)s.length() <= maxChars) return s;
  return s.substring(0, maxChars - 3) + "...";
}
static String displayStatus(const String &s) {
  return s == "running" || s == "done" || s == "unknown" ? s : String("idle");
}
static void centerText(const String &s, int y, int size, uint16_t color) {
  gfx->setTextSize(size);
  gfx->setTextColor(color);
  int x = (W - (int)s.length() * 6 * size) / 2;
  if (x < 0) x = 0;
  gfx->setCursor(x, y);
  gfx->print(s);
}

static void ledOff() { neopixelWrite(RGB_PIN, 0, 0, 0); }
static void ledTick() {
  if (!ledActive) return;
  uint32_t e = millis() - ledStart;
  if (e >= LED_MS) { ledActive = false; ledOff(); return; }
  float ph = (e / (float)LED_MS) * 2.0f * 2.0f * PI;
  float b = (1.0f - cosf(ph)) * 0.5f;
  neopixelWrite(RGB_PIN, (uint8_t)(b * ledR), (uint8_t)(b * ledG), (uint8_t)(b * ledB));
}

static void drawChannelDots() {
  int gap = 16, x0 = W - (NUM - 1) * gap - 9, y = H - 12;
  for (int i = 0; i < NUM; i++)
    gfx->fillCircle(x0 + i * gap, y, (i == view) ? 4 : 2,
                    (i == view) ? cliColor(chans[i].id) : DARKGREY);
}

static const char *statusLabel(const String &s) {
  if (s == "running") return "LIVE";
  if (s == "done") return "DONE";
  if (s == "unknown") return "N/A";
  return "IDLE";
}

static void drawHeader(const Chan &c) {
  uint16_t accent = cliColor(c.id);
  uint16_t stateColor = statusColor(c.status);
  gfx->fillRect(0, 0, W, 3, accent);
  gfx->fillRect(0, 3, W, 30, HUD_PANEL);

  gfx->fillCircle(11, 16, 4, stateColor);
  gfx->setTextSize(2);
  gfx->setTextColor(WHITE);
  gfx->setCursor(21, 10);
  gfx->print(fit(c.name, 9));

  gfx->setTextSize(1);
  gfx->setTextColor(stateColor);
  gfx->setCursor(145, 14);
  gfx->print(statusLabel(c.status));
  for (int i = 0; i < 3; i++)
    gfx->fillRect(178 + i * 5, 15, 3, 5,
                  c.status == "running" && (animFrame / 4) % 3 == (uint32_t)i ? GREEN : HUD_GRID);

  String wc = c.windows > 99 ? String("99+") :
              String(c.windows < 10 ? "0" : "") + String(c.windows);
  gfx->setTextSize(2);
  gfx->setTextColor(c.windows > 0 ? CYAN : DARKGREY);
  gfx->setCursor(W - wc.length() * 12 - 10, 5);
  gfx->print(wc);
  gfx->setTextSize(1);
  gfx->setTextColor(HUD_SOFT);
  gfx->setCursor(W - 34, 23);
  gfx->print("SESS");

  gfx->drawFastHLine(8, 33, W - 16, HUD_GRID);
}

static void drawTelemetryRail(int x, const String &st, uint32_t f, bool mirrored) {
  uint16_t c = st == "idle" ? HUD_GRID : statusColor(st);
  for (int i = 0; i < 6; i++) {
    int h = st == "running" ? 3 + (int)((f + i * 5) % 12) :
            st == "done" ? 5 + (int)((f + i * 2) % 7) : 3 + (i % 2);
    int yy = 47 + i * 11;
    int xx = mirrored ? x - 3 : x;
    gfx->fillRoundRect(xx, yy + (12 - h) / 2, 3, h, 1, c);
  }
}

static void drawMainFrame(uint16_t accent) {
  for (int y = 49; y <= 113; y += 16)
    gfx->drawFastHLine(30, y, W - 60, RGB565(19, 25, 28));
  gfx->drawFastHLine(8, 40, 14, accent);
  gfx->drawFastVLine(8, 40, 8, accent);
  gfx->drawFastHLine(W - 22, 121, 14, accent);
  gfx->drawFastVLine(W - 9, 114, 8, accent);
}

static void updateTaskDisplay(Chan &c) {
  gfx->setTextSize(1);
  String task = c.nTasks > 0 && c.tasks[0].length() ? c.tasks[0] :
                String(c.status == "running" ? "session active" :
                       c.status == "unknown" ? "no lifecycle signal" : "awaiting input");
  task.replace("\n", " ");
  task.replace("\r", " ");
  gfx->setFont(u8g2_font_chill7_h_cjk);
  gfx->setUTF8Print(true);
  int16_t x, y;
  uint16_t w, h;
  String shown = task;
  while (shown.length()) {
    gfx->getTextBounds(shown.c_str(), 0, 0, &x, &y, &w, &h);
    if (w <= 268) break;
    // Trim a whole UTF-8 code point so a clipped Chinese title stays valid.
    int end = task.length() - 1;
    while (end > 0 && ((uint8_t)task[end] & 0xC0) == 0x80) end--;
    task = task.substring(0, end);
    shown = task + "...";
  }
  c.taskDisplay = shown;
  gfx->setUTF8Print(false);
  gfx->setFont((const GFXfont *)nullptr);
}

static void drawTaskLine(const Chan &c) {
  gfx->setTextSize(1);
  gfx->setTextColor(HUD_SOFT);
  gfx->setCursor(8, 132);
  gfx->print("TASK");
  gfx->setFont(u8g2_font_chill7_h_cjk);
  gfx->setUTF8Print(true);
  gfx->setTextColor(WHITE);
  gfx->setCursor(44, 138);
  gfx->print(c.taskDisplay);
  gfx->setUTF8Print(false);
  gfx->setFont((const GFXfont *)nullptr);
}

static void drawFooter(const Chan &c) {
  gfx->fillRect(0, 143, W, H - 143, HUD_PANEL);
  gfx->drawFastHLine(0, 143, W, HUD_GRID);
  gfx->setTextSize(1);
  gfx->setTextColor(HUD_SOFT);
  gfx->setCursor(8, 146);
  gfx->print("USAGE");
  gfx->setTextSize(2);
  gfx->setTextColor(c.usage.length() ? CYAN : DARKGREY);
  gfx->setCursor(8, 155);
  gfx->print(fit(c.usage.length() ? c.usage : String("-- no usage --"), 20));
  drawChannelDots();
}

// animated desk pet — a distinct little act per status
static void drawPet(int cx, int cy, const String &st, uint32_t f) {
  if (st == "unknown") {
    gfx->drawRoundRect(cx - 28, cy - 22, 56, 46, 8, DARKGREY);
    gfx->setTextSize(3);
    gfx->setTextColor(HUD_SOFT);
    gfx->setCursor(cx - 9, cy - 11);
    gfx->print("?");
    return;
  }
  if (st == "done") {                    // CELEBRATE: hop + arms up + confetti
    int jump = (int)(fabsf(sinf(f * 0.5f)) * 9.0f);
    int by = cy - jump;
    int sw = 24 - jump * 2; if (sw < 6) sw = 6;
    gfx->fillRoundRect(cx - sw, cy + 28, sw * 2, 5, 2, RGB565(35, 40, 70));   // ground shadow
    gfx->fillRoundRect(cx - 33, by - 30, 6, 18, 3, PET);                       // arms raised
    gfx->fillRoundRect(cx + 27, by - 30, 6, 18, 3, PET);
    gfx->fillCircle(cx - 16, by - 20, 6, PET); gfx->fillCircle(cx + 16, by - 20, 6, PET);
    gfx->fillRoundRect(cx - 28, by - 22, 56, 46, 16, PET);
    gfx->drawLine(cx - 16, by - 1, cx - 11, by - 7, NAVY); gfx->drawLine(cx - 11, by - 7, cx - 6, by - 1, NAVY);
    gfx->drawLine(cx + 6, by - 1, cx + 11, by - 7, NAVY);  gfx->drawLine(cx + 11, by - 7, cx + 16, by - 1, NAVY);
    gfx->fillRoundRect(cx - 8, by + 6, 16, 7, 3, NAVY);                        // open smile
    uint16_t cc[3] = {YELLOW, CYAN, GREEN};
    for (int i = 0; i < 6; i++) {                                             // confetti
      int px = cx - 54 + ((i * 41 + (int)f * 3) % 108);
      int py = by - 26 + ((i * 19 + (int)f * 2) % 52);
      gfx->fillRect(px, py, 3, 3, cc[i % 3]);
    }
    return;
  }
  if (st == "idle") {                    // SLEEP: breathe + rising z's
    int br = (int)(sinf(f * 0.12f) * 2.0f);
    int by = cy + 2;
    gfx->fillCircle(cx - 16, by - 20, 6, PET); gfx->fillCircle(cx + 16, by - 20, 6, PET);
    gfx->fillRoundRect(cx - 28 - br, by - 20 + br, 56 + br * 2, 46 - br, 16, PET);   // breathing body
    gfx->drawFastHLine(cx - 18, by - 2, 11, NAVY); gfx->drawFastHLine(cx - 17, by - 1, 9, NAVY);
    gfx->drawFastHLine(cx + 7, by - 2, 11, NAVY);  gfx->drawFastHLine(cx + 8, by - 1, 9, NAVY);
    gfx->fillCircle(cx, by + 8, 1, NAVY);
    for (int k = 0; k < 3; k++) {                                            // z z z drifting up
      int prog = (int)((f / 3 + k * 9) % 30);
      gfx->setTextSize(prog < 15 ? 1 : 2);
      gfx->setTextColor(prog < 24 ? WHITE : DARKGREY);
      gfx->setCursor(cx + 24 + prog / 3, by - 16 - prog); gfx->print("z");
    }
    return;
  }
  // WORKING: bob + blink + paws typing on a keyboard
  int by = cy + (int)(sinf(f * 0.4f) * 2.0f);
  gfx->fillCircle(cx - 16, by - 20, 6, PET); gfx->fillCircle(cx + 16, by - 20, 6, PET);
  gfx->fillRoundRect(cx - 28, by - 22, 56, 46, 16, PET);
  bool blink = (f % 30) < 2;
  if (blink) { gfx->drawFastHLine(cx - 16, by - 3, 9, NAVY); gfx->drawFastHLine(cx + 7, by - 3, 9, NAVY); }
  else { gfx->fillCircle(cx - 11, by - 3, 4, NAVY); gfx->fillCircle(cx + 11, by - 3, 4, NAVY);
         gfx->fillCircle(cx - 12, by - 4, 1, WHITE); gfx->fillCircle(cx + 10, by - 4, 1, WHITE); }
  gfx->fillCircle(cx, by + 9, 2, NAVY);
  gfx->fillRoundRect(cx - 18, by + 26, 36, 7, 2, DARKGREY);                   // keyboard
  int tap = (f % 8) < 4 ? 0 : 4;
  gfx->fillCircle(cx - 9, by + 22 + tap, 4, PET);                            // paws tapping
  gfx->fillCircle(cx + 9, by + 22 + (4 - tap), 4, PET);
  gfx->setTextSize(2); gfx->setTextColor(CYAN);
  int d = (int)((f / 4) % 4); String dots = "";
  for (int i = 0; i < d; i++) dots += ".";
  gfx->setCursor(cx + 30, by - 22); gfx->print(dots);
}

// compact pet for when several sessions are active at once
static void drawMiniPet(int cx, int cy, const String &st, uint32_t f) {
  if (st == "unknown") {
    gfx->drawRoundRect(cx - 15, cy - 12, 30, 26, 6, DARKGREY);
    gfx->setTextSize(2);
    gfx->setTextColor(HUD_SOFT);
    gfx->setCursor(cx - 6, cy - 7);
    gfx->print("?");
    return;
  }
  int by = cy;
  if (st == "done") by = cy - (int)(fabsf(sinf(f * 0.5f)) * 5.0f);
  else if (st == "running") by = cy + (int)(sinf(f * 0.4f) * 2.0f);
  gfx->fillCircle(cx - 9, by - 11, 3, PET); gfx->fillCircle(cx + 9, by - 11, 3, PET);
  gfx->fillRoundRect(cx - 15, by - 12, 30, 26, 9, PET);
  if (st == "idle") {
    gfx->drawFastHLine(cx - 10, by - 1, 6, NAVY); gfx->drawFastHLine(cx + 4, by - 1, 6, NAVY);
    gfx->setTextSize(1); gfx->setTextColor(WHITE);
    gfx->setCursor(cx + 13, by - 12 - (int)((f / 4) % 8)); gfx->print("z");
  } else if (st == "done") {
    gfx->drawLine(cx - 9, by - 1, cx - 6, by - 4, NAVY); gfx->drawLine(cx - 6, by - 4, cx - 3, by - 1, NAVY);
    gfx->drawLine(cx + 3, by - 1, cx + 6, by - 4, NAVY); gfx->drawLine(cx + 6, by - 4, cx + 9, by - 1, NAVY);
    gfx->fillRoundRect(cx - 4, by + 4, 8, 4, 2, NAVY);
    if ((f / 4) % 2) { gfx->setTextSize(1); gfx->setTextColor(YELLOW); gfx->setCursor(cx - 18, by - 10); gfx->print("+"); gfx->setCursor(cx + 14, by + 2); gfx->print("+"); }
  } else {
    bool blink = (f % 30) < 2;
    if (blink) { gfx->drawFastHLine(cx - 9, by - 2, 6, NAVY); gfx->drawFastHLine(cx + 4, by - 2, 6, NAVY); }
    else { gfx->fillCircle(cx - 6, by - 2, 2, NAVY); gfx->fillCircle(cx + 6, by - 2, 2, NAVY); }
    gfx->fillCircle(cx, by + 5, 1, NAVY);
    gfx->setTextSize(1); gfx->setTextColor(CYAN);
    int d = (int)((f / 4) % 4); String s = ""; for (int i = 0; i < d; i++) s += ".";
    gfx->setCursor(cx + 13, by - 4); gfx->print(s);
  }
}

// full-screen completion celebration (shown briefly when any CLI finishes)
static void drawCelebrate(uint32_t f) {
  uint16_t accent = cliColor(doneCliId);
  String name = doneCli.length() ? doneCli : String("CLI");
  name.toUpperCase();
  gfx->fillScreen(HUD_BG);
  gfx->fillRect(0, 0, W, 4, accent);
  gfx->setTextSize(1);
  gfx->setTextColor(accent);
  gfx->setCursor(12, 12);
  gfx->print("TASK COMPLETE");
  gfx->setTextColor(HUD_SOFT);
  gfx->setCursor(W - 12 - name.length() * 6, 12);
  gfx->print(name);
  drawMainFrame(accent);
  drawPet(W / 2, 77, "done", f);
  centerText("DONE!", 118, 3, accent);
  centerText("READY FOR THE NEXT TASK", 151, 1, HUD_SOFT);
  uint32_t elapsed = millis() - celebrateStart;
  int remaining = elapsed >= CELEBRATE_MS ? 0 : (W - 16) * (CELEBRATE_MS - elapsed) / CELEBRATE_MS;
  gfx->fillRect(8, 166, remaining, 2, accent);
  gfx->flush();
}

static void drawConnection() {
  gfx->fillScreen(HUD_BG);
  gfx->fillRect(0, 0, W, 3, everHadData ? YELLOW : CYAN);
  centerText("CLI DASHBOARD", 18, 2, WHITE);
  gfx->drawRoundRect(143, 55, 34, 30, 4, HUD_SOFT);
  gfx->drawFastHLine(151, 63, 8, CYAN);
  gfx->drawFastHLine(161, 63, 8, CYAN);
  gfx->drawFastVLine(160, 85, 14, HUD_SOFT);
  gfx->drawFastHLine(150, 99, 21, HUD_SOFT);
  centerText(everHadData ? "HUB OFFLINE" : "CONNECTING", 111, 2, everHadData ? YELLOW : CYAN);
  centerText("USB / " + String((millis() - lastData) / 1000) + "s", 145, 1, HUD_SOFT);
  gfx->flush();
}

static void renderView() {
  if (!haveData) {
    drawConnection();
    return;
  }
  Chan &c = chans[view];
  uint16_t accent = cliColor(c.id);
  gfx->fillScreen(HUD_BG);
  drawHeader(c);
  drawMainFrame(accent);
  drawTelemetryRail(16, c.status, animFrame, false);
  drawTelemetryRail(W - 16, c.status, animFrame + 9, true);

  // middle: one big pet if <=1 session, else a grid of mini pets (each own state)
  int np = c.nPets;
  if (np <= 1) {
    String s = (np == 1) ? c.pets[0] : c.status;
    drawPet(W / 2, 80, s, animFrame);
    const char *cap; uint16_t capc;
    if (s == "running")   { cap = "WORKING"; capc = GREEN; }
    else if (s == "done") { cap = "COMPLETE"; capc = YELLOW; }
    else if (s == "unknown") { cap = "NO SIGNAL"; capc = HUD_SOFT; }
    else                  { cap = "READY"; capc = HUD_SOFT; }
    centerText(cap, 117, 1, capc);
  } else {
    int n = np > 6 ? 6 : np;
    int rows = (n <= 3) ? 1 : 2;
    int top = (rows == 1) ? n : (n + 1) / 2;   // balanced split (ceil on top)
    const int pitch = 92;                       // fixed spacing, each row centered
    int idx = 0;
    for (int r = 0; r < rows; r++) {
      int k = (r == 0) ? top : (n - top);
      int cyp = (rows == 1) ? 75 : (r == 0 ? 58 : 103);
      int startx = (W - (k - 1) * pitch) / 2;
      for (int ci = 0; ci < k; ci++) {
        drawMiniPet(startx + ci * pitch, cyp, c.pets[idx], animFrame + idx * 7);
        gfx->setTextSize(1);
        gfx->setTextColor(statusColor(c.pets[idx]));
        gfx->setCursor(startx + ci * pitch - 15, cyp + 17);
        gfx->print(String(idx + 1) + "/" + statusLabel(c.pets[idx]));
        idx++;
      }
    }
    int hidden = max(np, c.windows) - n;
    if (hidden > 0) {
      gfx->setTextSize(1); gfx->setTextColor(HUD_SOFT);
      String extra = "+" + String(hidden);
      gfx->setCursor(W - 10 - extra.length() * 6, 36); gfx->print(extra);
    }
  }

  drawTaskLine(c);
  drawFooter(c);
  gfx->flush();
}

// parse a /state JSON line and render
static void parseState(const char *body) {
  JsonDocument doc;
  if (deserializeJson(doc, body)) return;

  if (doc["capture"].as<bool>()) {
    Serial.printf("FRAME 320 172 RGB565LE %d\n", view);
    Serial.write((const uint8_t *)gfx->getFramebuffer(), W * H * 2);
    return;
  }

  // sleep packet from host
  if (doc["sleep"].as<bool>()) {
    if (!isSleep) {
      isSleep = true;
      celebrating = false;
      ledActive = false;
      ledOff();
      drawSleepScreen(animFrame);
    }
    lastData = millis();
    return;
  }
  JsonArray channels = doc["channels"].as<JsonArray>();
  if (channels.size() != NUM) return;
  for (JsonVariant channel : channels)
    if (!channel.is<JsonObject>()) return;
  // waking up: play welcome animation before restoring dashboard
  bool wasSleeping = isSleep;
  isSleep = false;

  int flash = doc["flash"] | 0;
  const char *dc = doc["done_cli"] | "";
  String dcName = "";
  int idx = 0;
  for (JsonObject ch : channels) {
    if (idx >= NUM) break;
    Chan &c = chans[idx];
    c.id = String((const char *)(ch["id"] | ""));
    c.name = String((const char *)(ch["name"] | "?"));
    c.windows = max(0, ch["windows"] | 0);
    c.usage = String((const char *)(ch["usage"] | ""));
    c.status = displayStatus(String((const char *)(ch["status"] | "idle")));
    c.nTasks = 0;
    for (JsonVariant t : ch["tasks"].as<JsonArray>()) {
      if (c.nTasks >= 5) break;
      const char *s = t.as<const char *>();
      c.tasks[c.nTasks++] = String(s ? s : "");
    }
    c.nPets = 0;
    for (JsonVariant p : ch["pets"].as<JsonArray>()) {
      if (c.nPets >= 8) break;
      const char *s = p.as<const char *>();
      c.pets[c.nPets++] = displayStatus(String(s ? s : "idle"));
    }
    if (dc[0] && strcmp((const char *)(ch["id"] | ""), dc) == 0) {
      dcName = c.name;
    }
    updateTaskDisplay(c);
    idx++;
  }
  haveData = true;
  everHadData = true;
  lastData = millis();
  int focusedView = doc["view"] | -1;
  uint32_t focusRevision = doc["focus_rev"] | (uint32_t)0;
  if (focusedView >= 0 && focusedView < NUM &&
      (focusedView != focusSeen || focusRevision != focusRevisionSeen)) {
    view = focusedView;
    focusSeen = focusedView;
    focusRevisionSeen = focusRevision;
  } else if (focusedView < 0) {
    focusSeen = -1;
    focusRevisionSeen = 0;
  }
  if (flashSeen >= 0 && flash > flashSeen) {
    doneCliId = String(dc);
    doneCli = dcName.length() ? dcName : String("CLI");
    setLedColorForCli(doneCliId);
    ledActive = true; ledStart = millis();
    celebrateStart = millis();
    celebrating = true;
  }
  flashSeen = flash;  // resync after a hub restart resets its counter
  if (wasSleeping) {
    drawWelcome();             // typewriter greeting before dashboard
  }
  if (celebrating && millis() - celebrateStart < CELEBRATE_MS) drawCelebrate(animFrame);
  else renderView();
}

static const int LOGO_CY = 84, LOGO_R = 22, LOGO_BX = 84;
static const int GLYPH_X0 = 118, GLYPH_Y = 68, GLYPH_PITCH = 36;

// gold "G" badge centered at (cx,cy)
static void drawBadge(int cx, int cy, int r) {
  gfx->fillCircle(cx, cy, r, GOLD);
  gfx->fillCircle(cx, cy, r - 3, NAVY);     // ring
  gfx->fillCircle(cx, cy, r - 6, GOLD);
  gfx->setTextSize(3);
  gfx->setTextColor(NAVY);
  gfx->setCursor(cx - 9, cy - 11);
  gfx->print("G");
}

// draw the first n CJK glyphs ("创意开发")
static void drawGlyphs(int n, uint16_t color) {
  for (int i = 0; i < n && i < GLYPH_N; i++)
    gfx->drawBitmap(GLYPH_X0 + i * GLYPH_PITCH, GLYPH_Y, GLYPHS[i], GLYPH_W, GLYPH_H, color);
}

// sleep screen: G badge + dim glyphs + floating Zzz
static void drawSleepScreen(uint32_t f) {
  gfx->fillScreen(NAVY);
  drawBadge(LOGO_BX, LOGO_CY, LOGO_R);
  drawGlyphs(GLYPH_N, RGB565(55, 60, 105));   // glyphs very dim
  // 3 z's at staggered phases floating up and right from the badge
  static const int Z_OFF[3] = {0, 14, 28};
  static const int Z_SZ[3]  = {2,  1,  1};
  static const int Z_DX[3]  = {2, 10, 16};
  static const char * const Z_CH[3] = {"Z", "z", "z"};
  const int cycle = 50;
  for (int k = 0; k < 3; k++) {
    int ph = (int)((f + Z_OFF[k]) % cycle);
    if (ph > cycle - 5) continue;              // hide during reset gap
    int ox = LOGO_BX + 26 + Z_DX[k] + ph / 4;
    int oy = LOGO_CY - 8 - ph * 2;
    uint8_t bright = (ph < cycle - 14) ? 210 : (uint8_t)(210 - (ph - (cycle - 14)) * 18);
    gfx->setTextSize(Z_SZ[k]);
    gfx->setTextColor(RGB565(bright, bright, 255));
    gfx->setCursor(ox, oy);
    gfx->print(Z_CH[k]);
  }
  gfx->flush();
}

// typewriter welcome on sleep→awake transition: "主人" / "欢迎回来"
static void drawWelcome() {
  // layout: two rows centered vertically, no overlap
  // Row1 "主人"   (2 glyphs × 32 = 64px)  y=46
  // Row2 "欢迎回来" (4 glyphs × 32 = 128px) y=94
  const int R1Y = 46, R2Y = 94;
  const int R1X = (W - 2 * (int)WEL_W) / 2;
  const int R2X = (W - 4 * (int)WEL_W) / 2;

  // initial blank
  gfx->fillScreen(NAVY);
  gfx->flush();
  delay(150);

  // typewriter row 1: 主人
  for (int i = 0; i < 2; i++) {
    gfx->fillScreen(NAVY);
    for (int j = 0; j <= i; j++)
      gfx->drawBitmap(R1X + j * WEL_W, R1Y, WEL_GLYPHS[j], WEL_W, WEL_H, GOLD);
    // typing cursor
    gfx->fillRect(R1X + (i + 1) * WEL_W + 2, R1Y + WEL_H - 4, 10, 3, GOLD);
    gfx->flush();
    delay(200);
  }

  // typewriter row 2: 欢迎回来
  for (int i = 0; i < 4; i++) {
    gfx->fillScreen(NAVY);
    for (int j = 0; j < 2; j++)                                     // keep row1
      gfx->drawBitmap(R1X + j * WEL_W, R1Y, WEL_GLYPHS[j], WEL_W, WEL_H, GOLD);
    for (int j = 0; j <= i; j++)                                     // row2 so far
      gfx->drawBitmap(R2X + j * WEL_W, R2Y, WEL_GLYPHS[2 + j], WEL_W, WEL_H, WHITE);
    if (i < 3)
      gfx->fillRect(R2X + (i + 1) * WEL_W + 2, R2Y + WEL_H - 4, 10, 3, WHITE);
    gfx->flush();
    delay(200);
  }

  delay(700);   // hold the complete message before showing dashboard
}

// the frozen end-state of the splash: G badge + "创意开发" (also the idle screen)
static void drawLogoFinal() {
  gfx->fillScreen(NAVY);
  drawBadge(LOGO_BX, LOGO_CY, LOGO_R);
  drawGlyphs(GLYPH_N, WHITE);
  gfx->flush();
}

// boot splash: G appears center -> slides left -> typewriter "创意开发"
static void splash() {
  for (int i = 0; i < 2; i++) {            // pop in at center
    gfx->fillScreen(NAVY); drawBadge(160, LOGO_CY, LOGO_R); gfx->flush(); delay(230);
  }
  for (int x = 160; x >= LOGO_BX; x -= 5) {  // slide left
    gfx->fillScreen(NAVY); drawBadge(x, LOGO_CY, LOGO_R); gfx->flush(); delay(16);
  }
  for (int n = 1; n <= GLYPH_N; n++) {     // typewriter glyphs
    gfx->fillScreen(NAVY);
    drawBadge(LOGO_BX, LOGO_CY, LOGO_R);
    drawGlyphs(n, WHITE);
    gfx->fillRect(GLYPH_X0 + n * GLYPH_PITCH - 4, GLYPH_Y + GLYPH_H - 4, 14, 3, GOLD);  // cursor
    gfx->flush();
    delay(230);
  }
  drawLogoFinal();                          // final, hold
  delay(800);
}

void setup() {
  setCpuFrequencyMhz(80);            // lower clock -> less heat
  Serial.begin(115200);              // USB CDC (CDCOnBoot=cdc)
  Serial.setRxBufferSize(sizeof(buf));
  Serial.setTxTimeoutMs(3000);
  pinMode(BOOT_BTN, INPUT_PULLUP);
  pinMode(LCD_BL, OUTPUT);
  digitalWrite(LCD_BL, LOW);         // backlight OFF until the screen is cleared
  ledOff();
  gfx->begin();
  gfx->setTextWrap(false);
  gfx->fillScreen(NAVY);             // paint splash bg first...
  gfx->flush();
  analogWrite(LCD_BL, BL_LEVEL);     // ...then turn backlight on -> no garbage flash
  splash();                          // boot animation -> rests on logo screen
  renderView();
}

void loop() {
  // BOOT -> next view
  int b = digitalRead(BOOT_BTN);
  if (b == LOW && btnPrev == HIGH && millis() - btnMs > 200) {
    view = (view + 1) % NUM;
    btnMs = millis();
    celebrating = false;
    if (!isSleep) renderView();
  }
  btnPrev = b;

  // read newline-delimited JSON from USB serial
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n') {
      buf[blen] = 0;
      if (!lineOverflow && blen > 1) parseState(buf);
      blen = 0;
      lineOverflow = false;
    } else if (ch != '\r') {
      if (blen < (int)sizeof(buf) - 1) buf[blen++] = ch;
      else lineOverflow = true;
    }
  }

  // animate at ~11 fps (sleep Zzz, celebration, or dashboard)
  if (millis() - lastAnim > 90) {
    lastAnim = millis();
    animFrame++;
    if (isSleep) {
      drawSleepScreen(animFrame);
    } else {
      if (celebrating && millis() - celebrateStart < CELEBRATE_MS) drawCelebrate(animFrame);
      else { celebrating = false; renderView(); }
    }
  }

  // stale-data hint if host stopped feeding
  if ((haveData || isSleep) && millis() - lastData > STALE_MS) {
    haveData = false;
    isSleep = false;
    celebrating = false;
    renderView();
  }
  ledTick();
  delay(15);
}
