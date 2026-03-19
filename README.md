# Smart Multi-Face Recognition Attendance System

A comprehensive, edge-to-cloud IoT attendance tracking system using ESP32 microcontrollers, OpenCV facial recognition, and a live Flask Web Dashboard.

## Features
- **Multi-Face Recognition**: Uses OpenCV and LBPH (Local Binary Patterns Histograms) to recognize multiple people simultaneously in a single frame.
- **Hardware Integration**: ESP32 main board equipped with a PIR sensor, Push Button, TFT display (ST7735), Buzzer, and RGB LED for physical interactions and status updates.
- **ESP32-CAM Video Stream**: Uses a dedicated ESP32-CAM module to securely stream JPEG frames over Wi-Fi to a PC server for heavy processing.
- **Live Web Dashboard**: A responsive, real-time dashboard built with Flask and TailwindCSS that allows administrators to view logs, monitor system status, and trigger remote enrollments directly from a web browser.
## Testing with Hardware (For Examiners)
**CRITICAL CONNECTIVITY NOTE:** The ESP32-CAM hardware *only* supports the **2.4 GHz Wi-Fi band**. It cannot connect to 5 GHz networks. Furthermore, iPhone Mobile Hotspots frequently use WPA3 or client isolation which blocks the ESP32. **Please use an Android smartphone or a Windows PC Mobile Hotspot set explicitly to the 2.4 GHz band.**

To test the physical ESP32 camera without the original developer's home Wi-Fi network, the codebase expects a standardized mobile hotspot:

1. On your Android smartphone or Windows PC, turn on your **Mobile Hotspot** (ensure it is set to **2.4 GHz**).
2. Set the Hotspot network name (SSID) to exactly: `Project_Testing`
3. Set the Hotspot password to exactly: `12345678`
4. Plug in the ESP32-CAM. Within 15 seconds, it will automatically connect to your hotspot.
5. Find the ESP32-CAM's IP address (visible on the hotspot connected devices screen).
6. Open `pc_server.py`, change `ESP32_CAM_URL = "http://YOUR_IP_HERE/capture"`, and run `python pc_server.py`.

## Testing & Evaluation without Hardware (For Examiners)
The project is built to ensure a flawless software evaluation even if the physical hardware is disconnected or unavailable.

If you run the system without being on the specific ESP32 Wi-Fi network:
1. The script will attempt to connect to the ESP32-CAM for 3 attempts.
2. If unreachable, it will gracefully output: `[CAMERA] ESP32-CAM unavailable. Falling back to local webcam...`
3. The system will activate your PC's built-in webcam instead. 
4. You can continue to use all features: pressing 'p' on the keyboard to simulate PIR motion scans, clicking "Start Face Scan" on the Local Web Dashboard (`http://localhost:5000`) for remote enrollment, and viewing live attendance logs across CSV and the Dashboard exactly as if the hardware was present!

## Software Installation
1. Install Python 3.9+
2. Install the necessary pip packages:
   ```bash
   pip install opencv-contrib-python requests pyserial flask openpyxl
   ```
3. Run the PC Server:
   ```bash
   python pc_server.py
   ```
4. Access the Live Dashboard:
   Open a web browser and navigate to `http://localhost:5000`

## Hardware Deployment (ESP32)
1. **ESP32-CAM**: Flashed with standard AI Thinker Camera Web Server sketch. Note the IP address and update `ESP32_CAM_URL` in `pc_server.py`.
2. **ESP32 Main Board**: Flash `esp32_main_board.py` using MicroPython via Thonny. Uses `machine.Pin.irq()` hardware interrupts for zero-latency interactions.

### Pin Configurations (ESP32)
- PIR Sensor: GPIO 13
- Push Button: GPIO 27
- TFT (ST7735): SCK=18, MOSI=23, CS=5, DC=2, RST=4
- RGB LED: R=25, G=26, B=33
- Buzzer: GPIO 14
- RTC (I2C): SDA=21, SCL=22

## System Workflows
- **Attendance Mode**: System idles until motion is detected or 'p' is pressed. It scans for 4 seconds, identifies all faces, outputs feedback (Buzzer/LED), and appends logs to CSV (`attendance_log.csv`).
- **Enrollment Mode**: Can be triggered structurally via the physical Push Button or remotely through the Web Dashboard. It gathers 20 continuous face frames, updates the dynamic LBPH model on-the-fly (`trainer.yml`), and saves the new identity.
