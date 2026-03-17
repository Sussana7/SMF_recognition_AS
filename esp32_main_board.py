"""
ESP32 Main Board Controller — Smart Multi-Face Attendance System
================================================================
Upload this file to ESP32 as main.py via Thonny.

Hardware connected:
  - PIR Sensor        → GPIO 13 (input)
  - Buzzer            → GPIO 14 (PWM output)
  - Push Button       → GPIO 27 (input, pull-up)
  - NeoPixel LED Ring → GPIO 15 (data)
  - TFT Display (SPI) → SCK=18, MOSI=23, CS=5, DC=2, RST=4
  - RTC DS3231 (I2C)  → SDA=21, SCL=22

Serial protocol with PC (115200 baud):
  ESP32 → PC:
    MOTION_DETECTED          — PIR triggered
    MODE_ENROLL              — Button long-press (enter enrollment)
    MODE_ATTEND              — Button short-press (back to attendance)
    BUTTON_PRESS             — Button short press event
    RTC:<YYYY-MM-DD HH:MM:SS> — Timestamp from RTC

  PC → ESP32:
    RESULT:<count>:<name1>,<name2>,...   — Recognition results
    ENROLL_START:<name>                   — Enrollment started
    ENROLL_PROGRESS:<n>/20               — Enrollment capture progress
    ENROLL_DONE:<name>                    — Enrollment complete
    ENROLL_FAIL:<reason>                  — Enrollment failed
    STATUS:<message>                      — General status message
    SCANNING                              — Scan in progress
    NO_FACES                              — No faces found
"""

from machine import Pin, PWM, SPI, SoftI2C
import time
import sys

# ─────────────────── CONFIGURATION ───────────────────
# Adjust these values for your specific hardware

PIR_COOLDOWN = 3       # Seconds between PIR triggers
LONG_PRESS_MS = 3000   # Hold button 3s for enrollment mode
DISPLAY_TIMEOUT = 5    # Seconds to show result before returning to idle

# GPIO Pins
PIN_PIR    = 13
PIN_BUZZER = 14
PIN_BUTTON = 27
PIN_LED_R  = 25    # RGB LED Red pin
PIN_LED_G  = 26    # RGB LED Green pin
PIN_LED_B  = 33    # RGB LED Blue pin
PIN_TFT_SCK  = 18
PIN_TFT_MOSI = 23
PIN_TFT_CS   = 5
PIN_TFT_DC   = 2
PIN_TFT_RST  = 4
PIN_I2C_SDA  = 21
PIN_I2C_SCL  = 22

# ─────────────────── HARDWARE INIT ───────────────────

print("\n" + "=" * 50)
print("SMART MULTI-FACE ATTENDANCE SYSTEM")
print("ESP32 Main Board Controller v2.0")
print("=" * 50)

# --- PIR Sensor ---
print("\n[1/6] Initializing PIR sensor...")
pir = Pin(PIN_PIR, Pin.IN)
print("[OK] PIR on GPIO", PIN_PIR)

# --- Buzzer ---
print("[2/6] Initializing buzzer...")
buzzer = PWM(Pin(PIN_BUZZER))
buzzer.freq(2000)
buzzer.duty(0)
print("[OK] Buzzer on GPIO", PIN_BUZZER)

# --- Push Button (pull-up: reads 1 when not pressed, 0 when pressed) ---
print("[3/6] Initializing push button...")
button = Pin(PIN_BUTTON, Pin.IN, Pin.PULL_UP)
print("[OK] Button on GPIO", PIN_BUTTON)

# --- RGB LED (PWM) ---
print("[4/6] Initializing RGB LED...")
led_r = PWM(Pin(PIN_LED_R))
led_g = PWM(Pin(PIN_LED_G))
led_b = PWM(Pin(PIN_LED_B))
led_r.freq(1000)
led_g.freq(1000)
led_b.freq(1000)
led_r.duty(0)
led_g.duty(0)
led_b.duty(0)
print(f"[OK] RGB LED on GPIO {PIN_LED_R}(R), {PIN_LED_G}(G), {PIN_LED_B}(B)")

# --- RTC (I2C) — works with both DS3231 and DS1307 (TinyRTC) ---
print("[5/6] Initializing RTC...")
i2c = SoftI2C(sda=Pin(PIN_I2C_SDA), scl=Pin(PIN_I2C_SCL), freq=100000)
RTC_ADDR = 0x68  # DS3231 / DS1307 I2C address (both use 0x68)

rtc_available = False
try:
    devices = i2c.scan()
    if RTC_ADDR in devices:
        rtc_available = True
        print(f"[OK] DS3231 found at address 0x{RTC_ADDR:02X}")
    else:
        print(f"[WARNING] DS3231 not found. I2C devices: {['0x{:02X}'.format(d) for d in devices]}")
        print("  Timestamps will come from PC instead.")
except Exception as e:
    print(f"[WARNING] I2C error: {e}")
    print("  Timestamps will come from PC instead.")

# --- TFT Display (SPI) ---
print("[6/6] Initializing TFT display...")
tft_available = False

try:
    spi = SPI(2, baudrate=40000000, polarity=0, phase=0,
              sck=Pin(PIN_TFT_SCK), mosi=Pin(PIN_TFT_MOSI))
    tft_cs  = Pin(PIN_TFT_CS, Pin.OUT)
    tft_dc  = Pin(PIN_TFT_DC, Pin.OUT)
    tft_rst = Pin(PIN_TFT_RST, Pin.OUT)

    # Try to import ILI9341 driver — if not found, display features are disabled
    # Install: upload ili9341.py to the ESP32's filesystem
    try:
        import ili9341
        tft = ili9341.ILI9341(spi, cs=tft_cs, dc=tft_dc, rst=tft_rst,
                              w=320, h=240, r=1)  # r=1 for landscape
        tft.fill(0x0000)  # Clear to black
        tft_available = True
        print("[OK] TFT display (ILI9341) initialized")
    except ImportError:
        try:
            import st7789
            tft = st7789.ST7789(spi, 240, 320, cs=tft_cs, dc=tft_dc, reset=tft_rst)
            tft.init()
            tft.fill(0x0000)
            tft_available = True
            print("[OK] TFT display (ST7789) initialized")
        except ImportError:
            print("[WARNING] No TFT driver found (ili9341.py or st7789.py)")
            print("  Upload the appropriate driver to ESP32 filesystem.")
            print("  Display features disabled — serial output only.")
except Exception as e:
    print(f"[WARNING] TFT init error: {e}")
    print("  Display features disabled.")


# ─────────────────── HELPER FUNCTIONS ───────────────────

# --- RTC DS3231 Functions ---

def _bcd_to_dec(bcd):
    """Convert BCD byte to decimal."""
    return (bcd >> 4) * 10 + (bcd & 0x0F)

def _dec_to_bcd(dec):
    """Convert decimal to BCD byte."""
    return ((dec // 10) << 4) + (dec % 10)

def rtc_get_time():
    """Read current time from DS3231. Returns (year, month, day, hour, minute, second)."""
    if not rtc_available:
        return None
    try:
        data = i2c.readfrom_mem(RTC_ADDR, 0x00, 7)
        second = _bcd_to_dec(data[0] & 0x7F)
        minute = _bcd_to_dec(data[1])
        hour   = _bcd_to_dec(data[2] & 0x3F)
        day    = _bcd_to_dec(data[4])
        month  = _bcd_to_dec(data[5] & 0x1F)
        year   = _bcd_to_dec(data[6]) + 2000
        return (year, month, day, hour, minute, second)
    except Exception as e:
        print(f"[RTC ERROR] {e}")
        return None

def rtc_set_time(year, month, day, hour, minute, second):
    """Set DS3231 time."""
    if not rtc_available:
        return
    try:
        data = bytearray(7)
        data[0] = _dec_to_bcd(second)
        data[1] = _dec_to_bcd(minute)
        data[2] = _dec_to_bcd(hour)
        data[3] = _dec_to_bcd(0)  # Day of week (unused)
        data[4] = _dec_to_bcd(day)
        data[5] = _dec_to_bcd(month)
        data[6] = _dec_to_bcd(year - 2000)
        i2c.writeto_mem(RTC_ADDR, 0x00, data)
        print(f"[RTC] Time set to {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}")
    except Exception as e:
        print(f"[RTC ERROR] {e}")

def rtc_timestamp_str():
    """Get formatted timestamp string from RTC."""
    t = rtc_get_time()
    if t:
        return f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
    return "NO_RTC"


# --- RGB LED Functions ---

def _set_rgb(r, g, b):
    """Set RGB LED color (0-255 per channel). Maps to PWM duty (0-1023)."""
    led_r.duty(int(r * 4))   # 255 * 4 ≈ 1020 ≈ max duty
    led_g.duty(int(g * 4))
    led_b.duty(int(b * 4))

def led_clear():
    """Turn off LED."""
    _set_rgb(0, 0, 0)

def led_solid(r, g, b):
    """Set LED to a solid color."""
    _set_rgb(r, g, b)

def led_flash(r, g, b, times=3, on_ms=200, off_ms=200):
    """Flash LED a color N times."""
    for _ in range(times):
        led_solid(r, g, b)
        time.sleep_ms(on_ms)
        led_clear()
        time.sleep_ms(off_ms)

def led_breathing_step(r, g, b, step, max_steps=20):
    """Single step of a breathing animation. Call in a loop."""
    if step < max_steps // 2:
        brightness = step / (max_steps // 2)
    else:
        brightness = (max_steps - step) / (max_steps // 2)
    brightness = max(0.02, min(1.0, brightness))
    _set_rgb(int(r * brightness), int(g * brightness), int(b * brightness))

def led_pulse(r, g, b):
    """Quick pulse effect (replaces spinner for single LED)."""
    _set_rgb(r, g, b)
    time.sleep_ms(100)
    _set_rgb(r // 4, g // 4, b // 4)
    time.sleep_ms(100)


# --- Buzzer Functions ---

def buzz_beep(freq=2000, duration_ms=100):
    """Single beep."""
    buzzer.freq(freq)
    buzzer.duty(512)
    time.sleep_ms(duration_ms)
    buzzer.duty(0)

def buzz_success():
    """Success melody: ascending two-tone."""
    buzz_beep(1000, 150)
    time.sleep_ms(50)
    buzz_beep(2000, 250)

def buzz_fail():
    """Failure sound: low buzz."""
    buzz_beep(400, 500)

def buzz_motion():
    """Motion detected: 3 short beeps."""
    for _ in range(3):
        buzz_beep(2000, 80)
        time.sleep_ms(80)

def buzz_enrollment():
    """Enrollment complete: happy melody."""
    for freq in [800, 1000, 1200, 1600]:
        buzz_beep(freq, 100)
        time.sleep_ms(30)

def buzz_mode_switch():
    """Mode switch: two-tone."""
    buzz_beep(1500, 100)
    time.sleep_ms(50)
    buzz_beep(1000, 100)


# --- TFT Display Functions ---
# These functions wrap display calls so the code runs even without a TFT

# Color constants (RGB565 format)
COLOR_BLACK   = 0x0000
COLOR_WHITE   = 0xFFFF
COLOR_GREEN   = 0x07E0
COLOR_RED     = 0xF800
COLOR_BLUE    = 0x001F
COLOR_YELLOW  = 0xFFE0
COLOR_CYAN    = 0x07FF
COLOR_PURPLE  = 0xF81F
COLOR_ORANGE  = 0xFD20

def tft_clear(color=COLOR_BLACK):
    """Clear display."""
    if tft_available:
        try:
            tft.fill(color)
        except:
            pass

def tft_text(text, x, y, color=COLOR_WHITE, scale=2):
    """Draw text on display. scale=1 is 8px, scale=2 is 16px."""
    if tft_available:
        try:
            # Most MicroPython TFT drivers use .text(text, x, y, color)
            tft.text(text, x, y, color)
        except Exception as e:
            pass
    # Always print to serial as fallback
    print(f"[TFT] {text}")

def tft_show_idle(mode="ATTENDANCE"):
    """Show idle screen."""
    tft_clear()
    tft_text("Smart Attendance", 20, 10, COLOR_CYAN)
    tft_text("System v2.0", 50, 35, COLOR_CYAN)
    tft_text("─" * 20, 10, 60, COLOR_WHITE)
    if mode == "ATTENDANCE":
        tft_text("Mode: ATTENDANCE", 10, 85, COLOR_GREEN)
        tft_text("Waiting for", 10, 120, COLOR_WHITE)
        tft_text("motion...", 10, 145, COLOR_WHITE)
    else:
        tft_text("Mode: ENROLLMENT", 10, 85, COLOR_PURPLE)
        tft_text("Ready to enroll", 10, 120, COLOR_WHITE)
        tft_text("new face", 10, 145, COLOR_WHITE)

    # Show RTC time
    ts = rtc_timestamp_str()
    if ts != "NO_RTC":
        tft_text(ts, 10, 200, COLOR_YELLOW)

def tft_show_scanning():
    """Show scanning in progress."""
    tft_clear()
    tft_text("SCANNING...", 40, 50, COLOR_YELLOW)
    tft_text("Please look at", 10, 100, COLOR_WHITE)
    tft_text("the camera", 10, 125, COLOR_WHITE)

def tft_show_result(names, count):
    """Show recognition results."""
    tft_clear()
    if count > 0:
        tft_text(f"DETECTED: {count} face(s)", 10, 10, COLOR_GREEN)
        tft_text("─" * 20, 10, 35, COLOR_WHITE)
        y_pos = 55
        for i, name in enumerate(names[:5]):  # Show up to 5 names
            tft_text(f"  {i+1}. {name}", 10, y_pos, COLOR_GREEN)
            y_pos += 25
        tft_text("─" * 20, 10, y_pos + 5, COLOR_WHITE)
        tft_text("Attendance logged!", 10, y_pos + 25, COLOR_CYAN)
    else:
        tft_text("NO FACES", 60, 60, COLOR_RED)
        tft_text("DETECTED", 60, 90, COLOR_RED)
        tft_text("Try again", 50, 140, COLOR_YELLOW)

    ts = rtc_timestamp_str()
    if ts != "NO_RTC":
        tft_text(ts, 10, 210, COLOR_YELLOW)

def tft_show_enrollment(name, progress=""):
    """Show enrollment status."""
    tft_clear()
    tft_text("ENROLLMENT", 45, 20, COLOR_PURPLE)
    tft_text("─" * 20, 10, 45, COLOR_WHITE)
    tft_text(f"Name: {name}", 10, 70, COLOR_CYAN)
    if progress:
        tft_text(f"Capturing: {progress}", 10, 110, COLOR_YELLOW)
    tft_text("Look at camera", 10, 150, COLOR_WHITE)

def tft_show_message(title, message, color=COLOR_WHITE):
    """Show a generic message."""
    tft_clear()
    tft_text(title, 10, 40, color)
    tft_text("─" * 20, 10, 65, COLOR_WHITE)
    tft_text(message, 10, 90, COLOR_WHITE)


# ─────────────────── SYSTEM STATE ───────────────────

MODE_ATTENDANCE = "ATTENDANCE"
MODE_ENROLLMENT = "ENROLLMENT"

current_mode = MODE_ATTENDANCE
motion_active = False
last_pir_time = 0
button_press_time = 0
button_was_pressed = False
breath_step = 0
spinner_pos = 0
display_result_until = 0  # timestamp when result display expires
idle_display_shown = False

# ─────────────────── SERIAL I/O ───────────────────

def read_serial():
    """Non-blocking read from USB serial. Returns line or None."""
    try:
        if sys.stdin in []:  # MicroPython doesn't support select well
            return None
        # Use sys.stdin.readline with a check
        # On ESP32 MicroPython, we can use sys.stdin.buffer
        import select
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        result = poll.poll(0)  # Non-blocking
        if result:
            line = sys.stdin.readline().strip()
            if line:
                return line
    except:
        pass
    return None

def send_serial(message):
    """Send message to PC over serial."""
    print(message)


# ─────────────────── PIR CALIBRATION ───────────────────

print("\n[CALIBRATE] PIR sensor calibrating (30 seconds)...")
print("  Do not move in front of the sensor!")

tft_show_message("CALIBRATING", "PIR sensor...", COLOR_YELLOW)
led_solid(20, 20, 0)  # Dim yellow during calibration

for i in range(30, 0, -1):
    send_serial(f"CALIBRATING:{i}")
    if tft_available:
        tft_show_message("CALIBRATING", f"PIR: {i}s remaining", COLOR_YELLOW)
    time.sleep(1)

led_clear()
buzz_beep(2000, 100)  # Short beep when ready
print("\n[OK] PIR calibrated and ready!")

# Show initial idle screen
tft_show_idle(current_mode)

print("\n" + "=" * 50)
print("SYSTEM ACTIVE")
print("=" * 50)
print(f"Mode: {current_mode}")
if rtc_available:
    print(f"RTC Time: {rtc_timestamp_str()}")
print("Waiting for motion / button press...")
print("=" * 50 + "\n")


# ─────────────────── MAIN LOOP ───────────────────

while True:
    current_ms = time.ticks_ms()

    # ─── 1. CHECK PUSH BUTTON ───
    btn_pressed = (button.value() == 0)  # Active LOW with pull-up

    if btn_pressed and not button_was_pressed:
        # Button just pressed — record timestamp
        button_press_time = current_ms
        button_was_pressed = True

    elif not btn_pressed and button_was_pressed:
        # Button released — check how long it was held
        hold_duration = time.ticks_diff(current_ms, button_press_time)
        button_was_pressed = False

        if hold_duration >= LONG_PRESS_MS:
            # LONG PRESS → Toggle mode
            if current_mode == MODE_ATTENDANCE:
                current_mode = MODE_ENROLLMENT
                send_serial("MODE_ENROLL")
                buzz_mode_switch()
                led_flash(128, 0, 128, 2)  # Purple flash
                print("[MODE] Switched to ENROLLMENT mode")
            else:
                current_mode = MODE_ATTENDANCE
                send_serial("MODE_ATTEND")
                buzz_mode_switch()
                led_flash(0, 128, 0, 2)  # Green flash
                print("[MODE] Switched to ATTENDANCE mode")
            tft_show_idle(current_mode)
            idle_display_shown = True
        else:
            # SHORT PRESS → Manual trigger / confirm
            send_serial("BUTTON_PRESS")
            buzz_beep(1500, 50)
            print("[BUTTON] Short press")

    # ─── 2. CHECK PIR SENSOR ───
    if current_mode == MODE_ATTENDANCE:
        motion = pir.value()

        if motion == 1 and not motion_active:
            elapsed = time.ticks_diff(current_ms, last_pir_time)
            if elapsed > (PIR_COOLDOWN * 1000) or last_pir_time == 0:
                # Motion detected!
                last_pir_time = current_ms
                motion_active = True

                # Send timestamp with motion event
                ts = rtc_timestamp_str()
                send_serial("MOTION_DETECTED")
                send_serial(f"RTC:{ts}")

                # Feedback
                buzz_motion()
                tft_show_scanning()
                led_solid(80, 80, 0)  # Yellow = scanning
                idle_display_shown = False

                print(f"[PIR] Motion detected at {ts}")

        elif motion == 0:
            motion_active = False

    # ─── 3. CHECK SERIAL COMMANDS FROM PC ───
    cmd = read_serial()
    if cmd:
        if cmd.startswith("RESULT:"):
            # Format: RESULT:<count>:<name1>,<name2>,...
            try:
                parts = cmd.split(":", 2)
                count = int(parts[1])
                names = parts[2].split(",") if count > 0 else []

                print(f"[RESULT] {count} face(s): {names}")

                tft_show_result(names, count)
                display_result_until = time.ticks_add(current_ms, DISPLAY_TIMEOUT * 1000)
                idle_display_shown = False

                if count > 0:
                    # Success feedback
                    led_flash(0, 100, 0, 3, 200, 100)  # Green flash
                    buzz_success()
                else:
                    # No faces
                    led_flash(100, 0, 0, 2, 300, 200)  # Red flash
                    buzz_fail()

            except Exception as e:
                print(f"[ERROR] Parsing RESULT: {e}")

        elif cmd.startswith("ENROLL_START:"):
            name = cmd.split(":", 1)[1]
            print(f"[ENROLL] Starting enrollment for: {name}")
            tft_show_enrollment(name)
            led_solid(50, 0, 80)  # Purple = enrollment
            idle_display_shown = False

        elif cmd.startswith("ENROLL_PROGRESS:"):
            progress = cmd.split(":", 1)[1]
            print(f"[ENROLL] Progress: {progress}")
            if tft_available:
                # Update just the progress line
                tft_text(f"Capturing: {progress}   ", 10, 110, COLOR_YELLOW)

        elif cmd.startswith("ENROLL_DONE:"):
            name = cmd.split(":", 1)[1]
            print(f"[ENROLL] Completed: {name}")
            tft_show_message("ENROLLED!", f"{name} added", COLOR_GREEN)
            led_flash(0, 100, 0, 5, 150, 100)  # Green celebration
            buzz_enrollment()
            display_result_until = time.ticks_add(current_ms, DISPLAY_TIMEOUT * 1000)
            idle_display_shown = False
            # Return to attendance mode
            current_mode = MODE_ATTENDANCE
            send_serial("MODE_ATTEND")

        elif cmd.startswith("ENROLL_FAIL:"):
            reason = cmd.split(":", 1)[1]
            print(f"[ENROLL] Failed: {reason}")
            tft_show_message("ENROLL FAIL", reason, COLOR_RED)
            led_flash(100, 0, 0, 3, 300, 200)
            buzz_fail()
            display_result_until = time.ticks_add(current_ms, DISPLAY_TIMEOUT * 1000)
            idle_display_shown = False

        elif cmd == "SCANNING":
            tft_show_scanning()
            led_solid(80, 80, 0)  # Yellow
            idle_display_shown = False

        elif cmd == "NO_FACES":
            tft_show_result([], 0)
            led_flash(100, 0, 0, 2)
            buzz_fail()
            display_result_until = time.ticks_add(current_ms, DISPLAY_TIMEOUT * 1000)
            idle_display_shown = False

        elif cmd.startswith("STATUS:"):
            message = cmd.split(":", 1)[1]
            print(f"[STATUS] {message}")
            tft_show_message("STATUS", message, COLOR_CYAN)

        elif cmd.startswith("SET_TIME:"):
            # Format: SET_TIME:2026-03-16 14:30:00
            try:
                ts = cmd.split(":", 1)[1]
                parts = ts.split(" ")
                date_parts = parts[0].split("-")
                time_parts = parts[1].split(":")
                rtc_set_time(
                    int(date_parts[0]), int(date_parts[1]), int(date_parts[2]),
                    int(time_parts[0]), int(time_parts[1]), int(time_parts[2])
                )
            except Exception as e:
                print(f"[ERROR] Setting time: {e}")

    # ─── 4. IDLE ANIMATIONS ───
    if display_result_until > 0 and time.ticks_diff(current_ms, display_result_until) > 0:
        # Result display expired, return to idle
        display_result_until = 0
        idle_display_shown = False

    if display_result_until == 0 and not idle_display_shown:
        tft_show_idle(current_mode)
        idle_display_shown = True

    # Breathing animation when idle (non-blocking)
    if display_result_until == 0 and not motion_active:
        breath_step = (breath_step + 1) % 40  # Slower breathing
        if current_mode == MODE_ATTENDANCE:
            led_breathing_step(0, 0, 60, breath_step, 40)   # Blue breathing
        else:
            led_breathing_step(60, 0, 60, breath_step, 40)   # Purple breathing

    # Pulse animation when scanning
    if display_result_until == 0 and motion_active:
        led_pulse(80, 80, 0)  # Yellow pulse

    # ─── 5. SMALL DELAY ───
    time.sleep_ms(50)  # 20 Hz main loop