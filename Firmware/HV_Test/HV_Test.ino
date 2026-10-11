// Geiger counter HV bench test - ESP32 (Arduino core)
// Hysteretic boost control, pulse counting, rolling CPM, piezo click.
// Serial @ 115200. Send a number (5-120) to change the boost on-time in us.

// ---------------- Config ----------------
const int HV_PWM_PIN   = 4;    // -> gate driver input
const int HV_SENSE_PIN = 35;   // <- HV divider tap (must be an ADC1 pin)
const int PULSE_PIN    = 27;   // <- pulse shaper output (active low)
const int PIEZO_PIN    = 25;   // -> piezo

const float DIV_RATIO  = (300.0e6 + 680.0e3) / 680.0e3;   // HV = Vsense * ratio
const float HV_TARGET  = 370.0;
const float HV_HYST    = 5.0;
const float HV_ABS_MAX = 460.0;

const bool     BURST_FILTER = true;   // merge tube re-firing bursts into one count
const uint32_t BURST_GAP_US = 5000;   // quiet time required before a new count

const float USV_PER_CPM = 0.0057;     // SBM-20, Cs-137 basis

uint32_t onTimeUs = 60;
const uint32_t PERIOD_US = 500;

// ---------------- Counting ----------------
volatile uint32_t counts = 0;
volatile uint32_t rawPulses = 0;
volatile uint32_t lastPulseUs = 0;

void IRAM_ATTR onPulse() {
  uint32_t now = micros();
  rawPulses++;
  // Every pulse restarts the window, so a whole burst becomes one count.
  if (!BURST_FILTER || now - lastPulseUs > BURST_GAP_US) counts++;
  lastPulseUs = now;
}

uint32_t bucket[60] = {0};   // 60 x 1 s buckets for rolling CPM
uint8_t  bucketIdx = 0;
uint32_t lastBucketCount = 0, lastBucketMs = 0, secondsRun = 0;

float readHV() {
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(HV_SENSE_PIN);
  return (mv / 8.0f) / 1000.0f * DIV_RATIO;
}

void setup() {
  pinMode(HV_PWM_PIN, OUTPUT);
  digitalWrite(HV_PWM_PIN, LOW);
  Serial.begin(115200);
  analogSetPinAttenuation(HV_SENSE_PIN, ADC_2_5db);   // ~0-1.25 V input range
  pinMode(PULSE_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PULSE_PIN), onPulse, FALLING);
  delay(1000);
  Serial.printf("HV test start. Target %.0f V, burst filter %s.\n",
                HV_TARGET, BURST_FILTER ? "ON" : "OFF");
}

void loop() {
  static bool pulsing = true;
  static uint32_t lastPrint = 0;
  static uint32_t lastClicked = 0;

  float hv = readHV();

  if (hv > HV_ABS_MAX) {
    digitalWrite(HV_PWM_PIN, LOW);
    Serial.printf("OVERVOLTAGE %.0f V - halted. Reset to retry.\n", hv);
    while (true) delay(1000);
  }

  if (hv >= HV_TARGET) pulsing = false;
  else if (hv < HV_TARGET - HV_HYST) pulsing = true;

  if (pulsing) {
    digitalWrite(HV_PWM_PIN, HIGH);
    delayMicroseconds(onTimeUs);
    digitalWrite(HV_PWM_PIN, LOW);
    delayMicroseconds(PERIOD_US - onTimeUs);
  }

  if (Serial.available()) {
    long v = Serial.parseInt();
    if (v >= 5 && v <= 120) {
      onTimeUs = v;
      Serial.printf("on-time = %lu us\n", onTimeUs);
    }
  }

  if (millis() - lastBucketMs >= 1000) {
    lastBucketMs += 1000;
    uint32_t c = counts;
    bucket[bucketIdx] = c - lastBucketCount;
    lastBucketCount = c;
    bucketIdx = (bucketIdx + 1) % 60;
    if (secondsRun < 60) secondsRun++;
  }

  if (millis() - lastPrint > 1000) {
    lastPrint = millis();
    uint32_t sum = 0;
    for (int i = 0; i < 60; i++) sum += bucket[i];
    float cpm = secondsRun ? sum * 60.0f / secondsRun : 0;   // scaled until first minute fills
    Serial.printf("HV = %6.1f V  on=%lu us  total=%lu  raw=%lu  CPM=%5.1f%s  ~%.3f uSv/h\n",
                  hv, onTimeUs, counts, rawPulses, cpm,
                  secondsRun < 60 ? " (warming up)" : "", cpm * USV_PER_CPM);
  }

  if (counts != lastClicked) {
    lastClicked = counts;
    tone(PIEZO_PIN, 4000, 3);
  }
}