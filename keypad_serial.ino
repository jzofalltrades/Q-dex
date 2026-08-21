// keypad_serial.ino
// ESP32-C3 Super Mini - 9 direct push buttons over USB serial.
//
// IMPORTANT: Arduino IDE -> Tools -> USB CDC On Boot -> Enabled  before flashing.
// Each button: one leg -> GPIO, other leg -> GND. Internal pull-ups used.
//
// Button roles in the app:
//   enter     = SELECT (open menu item)
//   cancel    = BACK
//   pageleft  = SCAN (gameplay)
//   pageright = BACK
//   tab       = switch tab / region
//   up/down/left/right = navigation
//
// GPIO 2 is a strapping pin; if "tab" misbehaves move it to GPIO 21.

const int NUM_BTN = 9;
int btnPins[NUM_BTN] = {0, 1, 2, 3, 4, 5, 6, 7, 10};
const char* btnKeys[NUM_BTN] = {
  "enter",     // GPIO 0  - SELECT
  "cancel",    // GPIO 1  - BACK
  "tab",       // GPIO 2  - TAB
  "up",        // GPIO 3
  "down",      // GPIO 4
  "right",     // GPIO 5
  "left",      // GPIO 6
  "pageleft",  // GPIO 7  - SCAN
  "pageright"  // GPIO 10 - BACK
};

bool lastState[NUM_BTN];

void setup() {
  Serial.begin(115200);
  for (int i = 0; i < NUM_BTN; i++) {
    pinMode(btnPins[i], INPUT_PULLUP);
    lastState[i] = HIGH;
  }
}

void loop() {
  for (int i = 0; i < NUM_BTN; i++) {
    bool state = digitalRead(btnPins[i]);
    if (lastState[i] == HIGH && state == LOW) {
      Serial.println(btnKeys[i]);
      delay(50);  // debounce
    }
    lastState[i] = state;
  }
  delay(10);
}
