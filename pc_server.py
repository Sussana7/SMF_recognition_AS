"""
PC Server — Smart Multi-Face Attendance System
===============================================
Main orchestrator running on the PC. Replaces pc_attendance_with_pir.py.

Features:
  - Fetches JPEG frames from ESP32-CAM via HTTP
  - Multi-face detection (Haar Cascade) and recognition (LBPH)
  - Attendance logging to Excel + CSV
  - Serial communication with ESP32 Main Board
  - Flask web dashboard on http://localhost:5000
  - Enrollment mode support

Requirements:
  pip install opencv-contrib-python flask openpyxl pyserial requests numpy pillow

Usage:
  python pc_server.py
"""

import cv2
import json
import time
import os
import sys
import threading
import csv
import queue
import numpy as np
from datetime import datetime
from collections import defaultdict

# Optional imports — installed separately
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    print("[WARNING] pyserial not installed. ESP32 serial disabled.")
    print("  Install: pip install pyserial")
    SERIAL_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    print("[WARNING] requests not installed. ESP32-CAM disabled, using local webcam.")
    print("  Install: pip install requests")
    REQUESTS_AVAILABLE = False

try:
    import openpyxl
    from openpyxl import Workbook
    OPENPYXL_AVAILABLE = True
except ImportError:
    print("[WARNING] openpyxl not installed. Excel logging disabled (CSV only).")
    print("  Install: pip install openpyxl")
    OPENPYXL_AVAILABLE = False

try:
    from flask import Flask, jsonify, render_template, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("[WARNING] Flask not installed. Web dashboard disabled.")
    print("  Install: pip install flask")


# ─────────────────── CONFIGURATION ───────────────────

# ESP32-CAM IP — update this after flashing the ESP32-CAM
# The Arduino CameraWebServer serves on port 80 (default HTTP port)
ESP32_CAM_IP = "10.56.216.13"  # Your ESP32-CAM's IP
ESP32_CAM_URL = f"http://{ESP32_CAM_IP}/capture"

# Files
EXCEL_FILE = 'attendance_log.xlsx'
CSV_FILE = 'attendance_log.csv'
LABELS_FILE = 'labels.json'
TRAINER_FILE = 'trainer.yml'
DATASET_DIR = 'dataset'

# Recognition settings
CONFIDENCE_THRESHOLD = 145 # Lower = stricter matching. Increased to 145 to support smaller faces when multiple people stand further back.
COOLDOWN_SECONDS = 30      # Don't re-log same person within this window
SCAN_DURATION = 4          # Seconds to scan for faces
MIN_DETECTIONS = 2         # Minimum frames a face must appear in to be logged
CAPTURE_INTERVAL = 0.3     # Seconds between frame captures from ESP32-CAM

# Flask dashboard
FLASK_PORT = 5000

# Display window
SHOW_OPENCV_WINDOW = True  # Set False for headless operation


# ─────────────────── GLOBAL STATE ───────────────────

attendance_log = []     # In-memory attendance log for dashboard
system_status = {
    'mode': 'ATTENDANCE',
    'last_scan': None,
    'last_result': None,
    'esp32_connected': False,
    'camera_source': 'unknown',
    'people_registered': 0,
    'total_attendance': 0,
}
current_mode = 'ATTENDANCE'
esp32_serial = None
recognizer = None
face_cascade = None
id_to_name = {}
last_logged = {}  # name → timestamp (cooldown tracking)
enrollment_queue = queue.Queue()


# ─────────────────── ESP32 SERIAL ───────────────────

def find_esp32():
    """Auto-detect ESP32 COM port. Lists all candidates and tries each."""
    if not SERIAL_AVAILABLE:
        return None
    candidates = []
    ports = serial.tools.list_ports.comports()
    print("  Available COM ports:")
    for port in ports:
        desc = port.description.upper()
        print(f"    {port.device}: {port.description}")
        if any(keyword in desc for keyword in ['USB', 'SERIAL', 'CH340', 'CP210', 'UART']):
            candidates.append(port.device)
    return candidates

def connect_esp32():
    """Connect to ESP32 via serial. Tries all candidate ports."""
    global esp32_serial
    candidates = find_esp32()
    if not candidates:
        print("[WARNING] No ESP32 COM ports found — running in PC-only mode")
        print("  Manual trigger: press 'p' in the OpenCV window")
        return False

    for port in candidates:
        try:
            print(f"  Trying {port}...")
            ser = serial.Serial(port, 115200, timeout=0.5)
            time.sleep(1)
            # Check if this port sends MicroPython data
            ser.reset_input_buffer()
            time.sleep(1)
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting).decode(errors='ignore')
                if any(kw in data for kw in ['MOTION', 'CALIBRAT', 'ATTENDANCE', 'BUTTON', 'MODE', 'PIR', 'RTC']):
                    esp32_serial = ser
                    system_status['esp32_connected'] = True
                    print(f"[OK] ESP32 connected on {port}")
                    return True
            # Even if no data yet, use the first port
            if esp32_serial is None:
                esp32_serial = ser
                system_status['esp32_connected'] = True
                print(f"[OK] ESP32 connected on {port} (waiting for data)")
                return True
        except Exception as e:
            print(f"    {port} failed: {e}")
    print("[WARNING] Could not connect to ESP32 — running in PC-only mode")
    print("  Manual trigger: press 'p' in the OpenCV window")
    return False

def send_to_esp32(message):
    """Send a command to ESP32 over serial."""
    if esp32_serial:
        try:
            esp32_serial.write((message + '\n').encode())
        except Exception as e:
            print(f"[SERIAL ERROR] {e}")

def read_esp32():
    """Non-blocking read from ESP32 serial. Returns line or None."""
    try:
        if esp32_serial and esp32_serial.in_waiting > 0:
            line = esp32_serial.readline().decode().strip()
            return line if line else None
    except Exception as e:
        # Ignore serial dropouts or permission errors momentarily
        pass
    return None


# ─────────────────── CAMERA ───────────────────

local_cam = None
using_esp32_cam = False

def init_camera():
    """Initialize camera source (ESP32-CAM or local webcam)."""
    global local_cam, using_esp32_cam

    # Try ESP32-CAM with retries (it can take 15-20s to boot)
    if REQUESTS_AVAILABLE:
        for attempt in range(3):
            try:
                print(f"[CAMERA] Trying ESP32-CAM at {ESP32_CAM_URL}... (attempt {attempt+1}/3)")
                resp = requests.get(ESP32_CAM_URL, timeout=8)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    using_esp32_cam = True
                    system_status['camera_source'] = f'ESP32-CAM ({ESP32_CAM_IP})'
                    print(f"[OK] ESP32-CAM connected ({len(resp.content)} bytes)")
                    return True
                else:
                    print(f"  Got status {resp.status_code}, {len(resp.content)} bytes — retrying...")
            except Exception as e:
                print(f"  Not reachable: {e}")
            time.sleep(3)

    # Fallback to local webcam
    print("[CAMERA] ESP32-CAM unavailable. Falling back to local webcam...")
    local_cam = cv2.VideoCapture(0)
    if local_cam.isOpened():
        system_status['camera_source'] = 'Local webcam'
        print("[OK] Local webcam ready")
        return True
    else:
        print("[ERROR] No camera available!")
        return False

def capture_frame():
    """Capture a single frame. Returns (success, frame) tuple."""
    if using_esp32_cam:
        try:
            resp = requests.get(ESP32_CAM_URL, timeout=1.0)
            if resp.status_code == 200:
                # Decode JPEG to OpenCV frame
                img_array = np.frombuffer(resp.content, dtype=np.uint8)
                frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if frame is not None:
                    return True, frame
        except Exception as e:
            print(f"[CAPTURE ERROR] {e}")
        return False, None
    else:
        if local_cam and local_cam.isOpened():
            return local_cam.read()
        return False, None


# ─────────────────── FACE RECOGNITION ───────────────────

def load_model():
    """Load the LBPH face recognition model and labels."""
    global recognizer, face_cascade, id_to_name

    print("[MODEL] Loading facial recognition model...")

    # Haar Cascade face detector
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    # LBPH face recognizer
    recognizer = cv2.face.LBPHFaceRecognizer_create()

    if os.path.exists(TRAINER_FILE):
        recognizer.read(TRAINER_FILE)
        print(f"[OK] Loaded model: {TRAINER_FILE}")
    else:
        print(f"[WARNING] Model file not found: {TRAINER_FILE}")
        print("  Run: python train_faces.py")

    # Load name labels
    if os.path.exists(LABELS_FILE):
        with open(LABELS_FILE, 'r') as f:
            id_to_name = json.load(f)
            id_to_name = {int(k): v for k, v in id_to_name.items()}
        system_status['people_registered'] = len(id_to_name)
        print(f"[OK] Loaded {len(id_to_name)} people: {list(id_to_name.values())}")
    else:
        print(f"[WARNING] Labels file not found: {LABELS_FILE}")

def recognize_faces():
    """
    Run multi-face recognition over multiple frames.
    Returns dict: {name: detection_count}
    """
    print("\n[SCANNING] Looking for faces...")
    send_to_esp32("SCANNING")

    detected_people = {}
    person_counts = defaultdict(int)
    frames_captured = 0

    start_time = time.time()
    while time.time() - start_time < SCAN_DURATION:
        ret, frame = capture_frame()
        if not ret or frame is None:
            time.sleep(CAPTURE_INTERVAL)
            continue

        frames_captured += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect all faces in this frame
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(50, 50),
            maxSize=(300, 300)
        )

        for (x, y, w, h) in faces:
            face_roi = gray[y:y+h, x:x+w]
            id_num, confidence = recognizer.predict(face_roi)
            
            # Print debug info to figure out what values we are getting
            guessed_name = id_to_name.get(id_num, "Unknown")
            print(f"    [DEBUG] Face detected at ({x},{y}). Best match: {guessed_name}. Distance (Confidence): {confidence:.1f}")

            # Simple tracking: If confidence is good, count the person
            if confidence < CONFIDENCE_THRESHOLD and id_num in id_to_name:
                name = id_to_name[id_num]
                person_counts[name] += 1
                
                # Draw green box
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                conf_pct = int(100 - min(confidence, 100))
                cv2.putText(frame, f"{name} ({conf_pct}%)", (x+5, y-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                # Unknown face
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
                cv2.putText(frame, f"Unknown ({int(confidence)})", (x+5, y-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        # Show scan progress on frame
        remaining = max(0, int(SCAN_DURATION - (time.time() - start_time)))
        cv2.putText(frame, f"Scanning... {remaining}s | Faces: {len(faces)}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if SHOW_OPENCV_WINDOW:
            cv2.imshow('Attendance System', frame)
            cv2.waitKey(1)

        time.sleep(CAPTURE_INTERVAL)

    # Filter out people who didn't meet MIN_DETECTIONS
    for name, count in person_counts.items():
        if count >= MIN_DETECTIONS:
            detected_people[name] = count

    print(f"  Captured {frames_captured} frames. Raw Detections: {dict(person_counts)}")
    return detected_people


# ─────────────────── ATTENDANCE LOGGING ───────────────────

def setup_logging():
    """Set up Excel and CSV attendance log files."""
    # CSV file
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Name', 'Date', 'Time', 'Status'])
        print(f"[OK] Created {CSV_FILE}")

    # Excel file
    if OPENPYXL_AVAILABLE:
        if not os.path.exists(EXCEL_FILE):
            wb = Workbook()
            ws = wb.active
            ws.title = "Attendance"
            ws.append(['Name', 'Date', 'Time', 'Status'])
            wb.save(EXCEL_FILE)
            print(f"[OK] Created {EXCEL_FILE}")
        else:
            print(f"[OK] Using existing {EXCEL_FILE}")

    # Load existing CSV entries into memory for dashboard
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Clean row to prevent JSON serialization errors (e.g. None keys)
                clean_row = {str(k): str(v) if v is not None else "" for k, v in row.items() if k is not None}
                # Only append valid rows
                if clean_row.get('Name') and str(clean_row.get('Name')).strip():
                    attendance_log.append(clean_row)
        system_status['total_attendance'] = len(attendance_log)

def log_attendance(name):
    """Log attendance to CSV, Excel, and in-memory list."""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')

    entry = {
        'Name': name,
        'Date': date_str,
        'Time': time_str,
        'Status': 'Present'
    }

    # CSV logging (always available)
    try:
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([name, date_str, time_str, 'Present'])
    except Exception as e:
        print(f"[CSV ERROR] {e}")

    # Excel logging
    if OPENPYXL_AVAILABLE:
        try:
            wb = openpyxl.load_workbook(EXCEL_FILE)
            ws = wb.active
            ws.append([name, date_str, time_str, 'Present'])
            wb.save(EXCEL_FILE)
        except Exception as e:
            print(f"[EXCEL ERROR] {e}")

    # In-memory log for dashboard
    attendance_log.append(entry)
    system_status['total_attendance'] = len(attendance_log)

    print(f"  [LOGGED] {name} at {time_str}")
    return True


# ─────────────────── ENROLLMENT ───────────────────

def enroll_face(person_name, num_samples=20):
    """
    Capture face samples for a new person from ESP32-CAM.
    Saves images to dataset/<person_name>/ and retrains the model.
    """
    print(f"\n[ENROLL] Starting enrollment for: {person_name}")
    send_to_esp32(f"ENROLL_START:{person_name}")

    # Create directory
    person_dir = os.path.join(DATASET_DIR, person_name)
    os.makedirs(person_dir, exist_ok=True)

    captured = 0
    attempts = 0
    max_attempts = num_samples * 5  # Allow some failed attempts

    print(f"  Capturing {num_samples} face samples...")
    print("  Please look at the camera and slowly turn your head.")

    while captured < num_samples and attempts < max_attempts:
        attempts += 1
        ret, frame = capture_frame()
        if not ret or frame is None:
            time.sleep(0.3)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(50, 50))

        if len(faces) > 0:
            # Take the largest face
            largest = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = largest
            face_roi = gray[y:y+h, x:x+w]

            # Save face image
            filename = os.path.join(person_dir, f"{person_name}_{captured+1:03d}.jpg")
            cv2.imwrite(filename, face_roi)
            captured += 1

            progress = f"{captured}/{num_samples}"
            send_to_esp32(f"ENROLL_PROGRESS:{progress}")
            print(f"  Captured {progress}")

            # Draw feedback on frame
            cv2.rectangle(frame, (x, y), (x+w, y+h), (128, 0, 255), 2)
            cv2.putText(frame, f"Enrolling: {progress}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 0, 255), 2)
        else:
            cv2.putText(frame, "No face detected — look at camera", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        if SHOW_OPENCV_WINDOW:
            cv2.imshow('Enrollment', frame)
            cv2.waitKey(1)

        time.sleep(0.5)  # Half-second between captures for variation

    if captured >= num_samples:
        print(f"\n[ENROLL] Captured {captured} images. Retraining model...")
        retrain_model()
        send_to_esp32(f"ENROLL_DONE:{person_name}")
        print(f"[ENROLL] Success! {person_name} enrolled.")
        return True
    else:
        reason = f"Only captured {captured}/{num_samples} images"
        send_to_esp32(f"ENROLL_FAIL:{reason}")
        print(f"[ENROLL] Failed: {reason}")
        return False

def retrain_model():
    """Retrain the LBPH model from all dataset images."""
    from PIL import Image

    print("[TRAIN] Retraining facial recognition model...")

    detector = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    face_samples = []
    ids = []
    name_to_id = {}
    current_id = 0

    for root, dirs, files in os.walk(DATASET_DIR):
        image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        if len(image_files) < 5:
            continue

        name = os.path.basename(root).strip()
        if name == DATASET_DIR or not name:
            continue

        if name not in name_to_id:
            name_to_id[name] = current_id
            current_id += 1

        actual_id = name_to_id[name]

        for file in image_files:
            img_path = os.path.join(root, file)
            try:
                pil_img = Image.open(img_path).convert('L')
                img_numpy = np.array(pil_img, 'uint8')

                faces = detector.detectMultiScale(img_numpy)
                for (x, y, w, h) in faces:
                    face_samples.append(img_numpy[y:y+h, x:x+w])
                    ids.append(actual_id)
            except Exception as e:
                print(f"  [ERROR] {img_path}: {e}")

    if len(face_samples) == 0:
        print("[TRAIN] No face data found!")
        return False

    # Train LBPH
    new_recognizer = cv2.face.LBPHFaceRecognizer_create()
    new_recognizer.train(face_samples, np.array(ids))
    new_recognizer.write(TRAINER_FILE)

    # Save labels
    new_id_to_name = {v: k for k, v in name_to_id.items()}
    with open(LABELS_FILE, 'w') as f:
        json.dump(new_id_to_name, f, indent=2)

    # Reload into current session
    global recognizer, id_to_name
    recognizer.read(TRAINER_FILE)
    id_to_name = {int(k): v for k, v in new_id_to_name.items()}
    system_status['people_registered'] = len(id_to_name)

    print(f"[TRAIN] Success! {len(face_samples)} samples from {len(name_to_id)} people")
    for id_num, name in sorted(new_id_to_name.items()):
        count = ids.count(id_num)
        print(f"  ID {id_num}: {name} ({count} images)")

    return True


# ─────────────────── FLASK WEB DASHBOARD ───────────────────

def start_flask():
    """Start Flask dashboard in a background thread."""
    if not FLASK_AVAILABLE:
        return

    app = Flask(__name__)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    @app.route('/')
    def dashboard():
        return render_template('index.html')

    @app.route('/api/status')
    def api_status():
        system_status['total_people'] = len(id_to_name)
        return jsonify(system_status)

    @app.route('/api/attendance')
    def api_attendance():
        return jsonify(attendance_log)

    @app.route('/api/enroll', methods=['POST'])
    def api_enroll():
        data = request.get_json() or {}
        name = data.get('name')
        if name:
            enrollment_queue.put(name)
            return jsonify({"status": "success", "message": f"Enrollment queued for {name}"})
        return jsonify({"status": "error", "message": "Name missing"}), 400

    # Run Flask without debug output
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)

    print(f"\n[DASHBOARD] Web dashboard: http://localhost:{FLASK_PORT}")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False, use_reloader=False)


# ─────────────────── MAIN SYSTEM ───────────────────

def main():
    global current_mode

    print("\n" + "=" * 60)
    print("  SMART MULTI-FACE ATTENDANCE SYSTEM")
    print("  PC Server v2.0")
    print("=" * 60)

    # Step 1: Load face recognition model
    print("\n[1/4] Loading facial recognition model...")
    load_model()

    # Step 2: Connect to ESP32
    print("\n[2/4] Connecting to ESP32 main board...")
    connect_esp32()

    # Step 3: Initialize camera
    print("\n[3/4] Initializing camera...")
    if not init_camera():
        print("[FATAL] No camera available. Exiting.")
        return

    # Step 4: Set up logging
    print("\n[4/4] Setting up attendance logging...")
    setup_logging()

    # Start Flask dashboard in background
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Ready!
    print("\n" + "=" * 60)
    print("  SYSTEM ACTIVE")
    print("=" * 60)
    print(f"  Mode:     {current_mode}")
    print(f"  Camera:   {system_status['camera_source']}")
    print(f"  ESP32:    {'Connected' if esp32_serial else 'Not connected'}")
    print(f"  People:   {list(id_to_name.values())}")
    if FLASK_AVAILABLE:
        print(f"  Dashboard: http://localhost:{FLASK_PORT}")
    print("=" * 60)
    print("\nWaiting for PIR motion detection...")
    if not esp32_serial:
        print("[INFO] Press 'p' in the OpenCV window to manually trigger scan")
        print("[INFO] Press 'e' to enter enrollment mode")
    print("Press 'q' to quit\n")

    scanning = False

    while True:
        # ─── Drain remote enrollment queue ───
        while True:
            try:
                remote_enroll_name = enrollment_queue.get_nowait()
                print(f"\n[DASHBOARD] Remote enrollment requested for: {remote_enroll_name}")
                current_mode = 'ENROLLMENT'
                system_status['mode'] = 'ENROLLMENT'
                send_to_esp32("MODE_ENROLL")
                enroll_face(remote_enroll_name)
                current_mode = 'ATTENDANCE'
                system_status['mode'] = 'ATTENDANCE'
                send_to_esp32("MODE_ATTEND")
            except queue.Empty:
                break

        # ─── Drain ESP32 serial messages ───
        while True:
            msg = read_esp32()
            if not msg:
                break
            
            if msg == "MOTION_DETECTED" and current_mode == 'ATTENDANCE':
                print("\n[PIR] Motion detected!")
                scanning = True
            elif msg == "MODE_ENROLL":
                current_mode = 'ENROLLMENT'
                system_status['mode'] = 'ENROLLMENT'
                print("\n[MODE] Switched to ENROLLMENT mode")
                print("Enter name for enrollment (or type 'cancel'). You can also use Web Dashboard:")
                name = input("> ").strip()
                if name and name.lower() != 'cancel':
                    enroll_face(name)
                current_mode = 'ATTENDANCE'
                system_status['mode'] = 'ATTENDANCE'
            elif msg == "MODE_ATTEND":
                current_mode = 'ATTENDANCE'
                system_status['mode'] = 'ATTENDANCE'
                print("\n[MODE] Switched to ATTENDANCE mode")
            elif msg.startswith("RTC:"):
                print(f"  [RTC] {msg[4:]}")
            elif msg == "BUTTON_PRESS":
                if current_mode == 'ATTENDANCE':
                    print("\n[BUTTON] Manual trigger!")
                    scanning = True

        # ─── Check keyboard in OpenCV window ───
        if SHOW_OPENCV_WINDOW:
            key = cv2.waitKey(1) & 0xFF
            if key == ord('p'):
                print("\n[MANUAL] Scan triggered!")
                scanning = True
            elif key == ord('e'):
                current_mode = 'ENROLLMENT'
                system_status['mode'] = 'ENROLLMENT'
                print("\n[MANUAL] Enrollment mode")
                print("Enter name for enrollment (or type 'cancel'):")
                name = input("> ").strip()
                if name and name.lower() != 'cancel':
                    enroll_face(name)
                current_mode = 'ATTENDANCE'
                system_status['mode'] = 'ATTENDANCE'
            elif key == ord('q'):
                break

        # ─── Run face recognition scan ───
        if scanning and current_mode == 'ATTENDANCE':
            detected = recognize_faces()

            if detected:
                names_list = list(detected.keys())
                count = len(names_list)
                print(f"\n[DETECTED] {count} people: {names_list}")

                system_status['last_scan'] = datetime.now().strftime('%H:%M:%S')
                system_status['last_result'] = names_list

                # Log each person (with cooldown)
                current_time = time.time()
                logged_names = []
                for name, det_count in detected.items():
                    if name not in last_logged or \
                       (current_time - last_logged[name]) > COOLDOWN_SECONDS:
                        log_attendance(name)
                        last_logged[name] = current_time
                        logged_names.append(name)
                    else:
                        remaining = int(COOLDOWN_SECONDS - (current_time - last_logged[name]))
                        print(f"  [COOLDOWN] {name} — wait {remaining}s")

                # Send results to ESP32
                if logged_names:
                    names_str = ",".join(logged_names)
                    send_to_esp32(f"RESULT:{len(logged_names)}:{names_str}")
                else:
                    send_to_esp32("RESULT:0:")
            else:
                print("\n[WARNING] No faces recognized")
                send_to_esp32("NO_FACES")

            scanning = False
            print("\n[READY] Waiting for next motion event...")
            time.sleep(2)

        # ─── Show live feed when idle ───
        if not scanning and SHOW_OPENCV_WINDOW:
            ret, frame = capture_frame()
            if ret and frame is not None:
                status_text = f"Mode: {current_mode} | Waiting for motion..."
                cv2.putText(frame, status_text, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                # Show registered people count
                cv2.putText(frame, f"Registered: {len(id_to_name)} people",
                            (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

                cv2.imshow('Attendance System', frame)

        time.sleep(0.05)  # Small delay to prevent CPU spinning

    # ─── Cleanup ───
    print("\n[SHUTDOWN] Stopping system...")
    if esp32_serial:
        esp32_serial.close()
    if local_cam:
        local_cam.release()
    cv2.destroyAllWindows()
    print("[OK] System stopped")


if __name__ == '__main__':
    main()
