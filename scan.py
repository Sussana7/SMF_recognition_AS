import cv2
import json
from datetime import datetime
import time
import openpyxl
from openpyxl import Workbook
import os
from collections import defaultdict

# Configuration
EXCEL_FILE = 'attendance_log.xlsx'
CONFIDENCE_THRESHOLD = 80  # Adjusted
COOLDOWN_SECONDS = 30

# Setup recognizer
recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.read('trainer.yml')
faceCascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# Load names from JSON
with open('labels.json', 'r') as f:
    id_to_name = json.load(f)
    id_to_name = {int(k): v for k, v in id_to_name.items()}

print(f"[INFO] Loaded {len(id_to_name)} people: {list(id_to_name.values())}")

# Setup Excel
def setup_excel():
    if not os.path.exists(EXCEL_FILE):
        wb = Workbook()
        ws = wb.active
        ws.title = "Attendance"
        ws.append(['Name', 'Date', 'Time', 'Status'])
        wb.save(EXCEL_FILE)

def log_attendance(name):
    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
        now = datetime.now()
        ws.append([name, now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'), 'Present'])
        wb.save(EXCEL_FILE)
        print(f"✓ LOGGED: {name} at {now.strftime('%H:%M:%S')}")
        return True
    except Exception as e:
        print(f"[ERROR] {e}")
        return False

# Main system
setup_excel()
cam = cv2.VideoCapture(0)

last_logged = {}
# Smoothing: track last 5 predictions per face position
face_history = defaultdict(list)

print("\n" + "="*60)
print("MULTI-FACE ATTENDANCE SYSTEM")
print("="*60)
print(f"Registered: {list(id_to_name.values())}")
print("Press 'q' to quit")
print("="*60 + "\n")

frame_count = 0

while True:
    ret, frame = cam.read()
    if not ret:
        break
    
    frame_count += 1
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Better face detection settings
    faces = faceCascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(50, 50),
        maxSize=(300, 300)
    )
    
    # Clear old history
    if frame_count % 30 == 0:
        face_history.clear()
    
    for i, (x, y, w, h) in enumerate(faces):
        face_roi = gray[y:y+h, x:x+w]
        id_num, confidence = recognizer.predict(face_roi)
        
        # Create face identifier based on position
        face_key = f"{x//50}_{y//50}"
        
        # Smoothing: collect last 5 predictions for this face position
        if confidence < CONFIDENCE_THRESHOLD and id_num in id_to_name:
            face_history[face_key].append(id_num)
            if len(face_history[face_key]) > 5:
                face_history[face_key].pop(0)
            
            # Use most common prediction from last 5 frames
            if len(face_history[face_key]) >= 3:
                most_common = max(set(face_history[face_key]), key=face_history[face_key].count)
                name = id_to_name[most_common]
                color = (0, 255, 0)
                
                # Log attendance
                current_time = time.time()
                if name not in last_logged or (current_time - last_logged[name]) > COOLDOWN_SECONDS:
                    if log_attendance(name):
                        last_logged[name] = current_time
                
                label = f"{name} ({int(100-confidence)}%)"
            else:
                name = "Detecting..."
                color = (255, 255, 0)
                label = "Detecting..."
        else:
            name = "Unknown"
            color = (0, 0, 255)
            label = "Unknown"
            face_history[face_key] = []
        
        cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
        cv2.putText(frame, label, (x+5, y-10), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    
    cv2.putText(frame, f"Faces Detected: {len(faces)}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    cv2.imshow('Multi-Face Attendance', frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cam.release()
cv2.destroyAllWindows()