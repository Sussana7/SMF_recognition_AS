# Setup Instructions

## File Guide

### PC Files (Run on Computer):
- `train_faces.py` - Train the facial recognition model
- `pc_attendance_with_pir.py` - Main attendance system with ESP32-CAM
- `scan.py` - Standalone scanning script

### ESP32 Files (Upload via Thonny):

#### ESP32 Main Board (PIR + Buzzer):
1. Open `esp32_main_board.py` in Thonny
2. Connect ESP32 Main Board via USB
3. Save to MicroPython device as `main.py`

#### ESP32-CAM (Camera):
1. Open `esp32_cam_server.py` in Thonny
2. **UPDATE WiFi credentials** (lines 8-9):
   - WIFI_SSID = "Your_WiFi_Name"
   - WIFI_PASSWORD = "Your_Password"
3. Connect ESP32-CAM via USB
4. Save to MicroPython device as `main.py`
5. Copy the IP address that appears when it runs

#### Update PC Code:
1. Open `pc_attendance_with_pir.py`
2. Line 16: Update `ESP32_CAM_IP = "192.168.1.XXX"` with the IP from ESP32-CAM
3. Save and run

## Hardware Connections:
- PIR Sensor: GPIO 13 (ESP32 Main)
- Buzzer: GPIO 14 (ESP32 Main)
- ESP32 Main → PC: USB cable
- ESP32-CAM: WiFi connection

## Running the System:
1. Power on ESP32 Main Board (PIR calibrates for 30 seconds)
2. Power on ESP32-CAM (connects to WiFi)
3. Run `python pc_attendance_with_pir.py` on PC
4. Wave at PIR sensor to trigger attendance scan