import cv2
import json
import time
import serial
import serial.tools.list_ports
import openpyxl
from openpyxl import Workbook
from datetime import datetime
import os

# Configuration
EXCEL_FILE = 'attendance_log.xlsx'
CONFIDENCE_THRESHOLD = 80
COOLDOWN_SECONDS = 30

# Find ESP32 port
def find_esp32():
    """Auto-detect ESP32 COM port"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if 'USB' in port.description or 'Serial' in port.description or 'CH340' in port.description:
            return port.device
    return None

# Setup
print("="*60)
print("PC ATTENDANCE SYSTEM WITH PIR")
print("="*60)

# Find ESP32
print("\n[1/4] Looking for ESP32...")
esp32_port = find_esp32()

if esp32_port:
    print(f"[OK] Found ESP32 on {esp32_port}")
    try:
        esp32 = serial.Serial(esp32_port, 115200, timeout=0.1)
        time.sleep(2)
        print("[OK] Connected to ESP32")
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        esp32 = None
else:
    print("[WARNING] ESP32 not found - running in PC-only mode")
    esp32 = None

# Load facial recognition model
print("\n[2/4] Loading facial recognition model...")
recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.read('trainer.yml')
faceCascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

with open('labels.json', 'r') as f:
    id_to_name = json.load(f)
    id_to_name = {int(k): v for k, v in id_to_name.items()}

print(f"[OK] Loaded {len(id_to_name)} people: {list(id_to_name.values())}")

# Setup Excel
print("\n[3/4] Setting up Excel logging...")
if not os.path.exists(EXCEL_FILE):
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    ws.append(['Name', 'Date', 'Time', 'Status'])
    wb.save(EXCEL_FILE)
print(f"[OK] Excel ready: {EXCEL_FILE}")

# Open camera
print("\n[4/4] Starting camera...")
cam = cv2.VideoCapture(0)
if not cam.isOpened():
    print("[ERROR] Camera not found!")
    exit()
print("[OK] Camera ready")

# Functions
def log_attendance(name):
    """Log to Excel"""
    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
        now = datetime.now()
        ws.append([name, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), 'Present'])
        wb.save(EXCEL_FILE)
        print(f"[LOGGED] {name}")
        return True
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

def send_to_esp32(message):
    """Send message to ESP32"""
    if esp32:
        try:
            esp32.write((message + '\n').encode())
        except:
            pass

def recognize_faces():
    """Run facial recognition"""
    print("\n[SCANNING] Looking for faces...")
    
    scan_duration = 5  # Scan for 5 seconds
    start_time = time.time()
    detected_people = {}
    
    while time.time() - start_time < scan_duration:
        ret, frame = cam.read()
        if not ret:
            continue
        
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = faceCascade.detectMultiScale(gray, 1.1, 4, minSize=(50, 50))
        
        for (x, y, w, h) in faces:
            face_roi = gray[y:y+h, x:x+w]
            id_num, confidence = recognizer.predict(face_roi)
            
            if confidence < CONFIDENCE_THRESHOLD and id_num in id_to_name:
                name = id_to_name[id_num]
                if name not in detected_people:
                    detected_people[name] = 0
                detected_people[name] += 1
                
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(frame, name, (x+5, y-10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)
                cv2.putText(frame, "Unknown", (x+5, y-10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        
        remaining = int(scan_duration - (time.time() - start_time))
        cv2.putText(frame, f"Scanning... {remaining}s", 
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow('Attendance System', frame)
        cv2.waitKey(1)
    
    return detected_people

# Main loop
print("\n" + "="*60)
print("SYSTEM ACTIVE")
print("="*60)
print("Waiting for PIR motion detection...")
if not esp32:
    print("[INFO] Press 'p' to manually trigger scan (ESP32 not connected)")
print("Press 'q' to quit")
print("="*60 + "\n")

last_logged = {}
scanning = False

while True:
    # Check for ESP32 messages
    if esp32 and esp32.in_waiting > 0:
        try:
            line = esp32.readline().decode().strip()
            if line == "MOTION_DETECTED":
                print("\n[PIR] MOTION DETECTED!")
                scanning = True
        except:
            pass
    
    # Manual trigger for testing
    key = cv2.waitKey(1) & 0xFF
    if key == ord('p'):
        print("\n[MANUAL] Trigger activated!")
        scanning = True
    elif key == ord('q'):
        break
    
    # Run facial recognition if triggered
    if scanning:
        detected = recognize_faces()
        
        if detected:
            print(f"\n[DETECTED] People found: {list(detected.keys())}")
            
            # Log each person
            current_time = time.time()
            for name, count in detected.items():
                if count >= 3:  # Must appear in at least 3 frames
                    if name not in last_logged or (current_time - last_logged[name]) > COOLDOWN_SECONDS:
                        log_attendance(name)
                        last_logged[name] = current_time
                        send_to_esp32("PERSON_LOGGED")
        else:
            print("\n[WARNING] No faces recognized")
        
        print("\n[READY] Waiting for next person...")
        scanning = False
        time.sleep(2)
    
    # Show live feed when not scanning
    if not scanning:
        ret, frame = cam.read()
        if ret:
            cv2.putText(frame, "Waiting for motion...", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow('Attendance System', frame)

# Cleanup
print("\n[SHUTDOWN] Stopping system...")
if esp32:
    esp32.close()
cam.release()
cv2.destroyAllWindows()
print("[OK] System stopped")