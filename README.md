# Smart Multi-Face Attendance System

ESP32-based attendance system with facial recognition using LBPH algorithm.

## Files

### PC Files (Python):
- `train_faces.py` - Train facial recognition model
- `pc_attendance_with_pir.py` - PC program (uses webcam)
- `scan.py` - Standalone scanning script

### ESP32 Files (MicroPython):
- `esp32_main_board.py` - Upload to ESP32 Main Board as `main.py`
- `esp32_cam_server.py` - Upload to ESP32-CAM as `main.py`

### Data Files:
- `trainer.yml` - Trained LBPH model
- `labels.json` - Name mappings
- `attendance_log.xlsx` - Attendance records
- `dataset/` - Training images (5+ per person)

## Hardware Setup

### ESP32 Main Board:
- PIR Sensor → GPIO 13
- Buzzer → GPIO 14
- USB → PC

### ESP32-CAM:
- Connect to WiFi
- Update credentials in `esp32_cam_server.py` (lines 8-9)

## Usage

1. Train model: `python train_faces.py`
2. Upload `esp32_main_board.py` to ESP32 Main as `main.py`
3. Upload `esp32_cam_server.py` to ESP32-CAM as `main.py`
4. Update ESP32-CAM IP in PC code
5. Run: `python pc_attendance_with_pir.py`
```

---

## **📋 CREATE `.gitignore` FILE:**
```
__pycache__/
*.pyc
.vscode/
*.log
