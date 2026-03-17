"""
Face Enrollment Script — Smart Multi-Face Attendance System
===========================================================
Standalone script to enroll a new person into the system.

Usage:
  python enroll_face.py

The script will:
  1. Ask for the person's name
  2. Capture 20 face images (from ESP32-CAM or local webcam)
  3. Save images to dataset/<PersonName>/
  4. Automatically retrain the LBPH model

Requirements:
  pip install opencv-contrib-python numpy pillow requests
"""

import cv2
import os
import sys
import time
import numpy as np
import json

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ─────────────────── CONFIGURATION ───────────────────

ESP32_CAM_IP = "10.56.216.13"  # Your ESP32-CAM's IP
ESP32_CAM_URL = f"http://{ESP32_CAM_IP}/capture"  # Arduino CameraWebServer (port 80)
DATASET_DIR = 'dataset'
TRAINER_FILE = 'trainer.yml'
LABELS_FILE = 'labels.json'
NUM_SAMPLES = 20

# ─────────────────── CAMERA ───────────────────

def get_frame_esp32():
    """Capture frame from ESP32-CAM."""
    try:
        resp = requests.get(ESP32_CAM_URL, timeout=5)
        if resp.status_code == 200:
            img_array = np.frombuffer(resp.content, dtype=np.uint8)
            return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except:
        pass
    return None

def get_frame_webcam(cam):
    """Capture frame from local webcam."""
    ret, frame = cam.read()
    return frame if ret else None

# ─────────────────── MAIN ───────────────────

def main():
    print("\n" + "=" * 50)
    print("  FACE ENROLLMENT")
    print("=" * 50)

    # Get person name
    name = input("\nEnter person's name: ").strip()
    if not name:
        print("[ERROR] Name cannot be empty!")
        return

    # Create directory
    person_dir = os.path.join(DATASET_DIR, name)
    os.makedirs(person_dir, exist_ok=True)
    existing = len([f for f in os.listdir(person_dir)
                     if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    print(f"[INFO] Directory: {person_dir} ({existing} existing images)")

    # Try camera sources
    cam = None
    use_esp32 = False

    if REQUESTS_AVAILABLE:
        print(f"\n[CAMERA] Trying ESP32-CAM at {ESP32_CAM_URL}...")
        frame = get_frame_esp32()
        if frame is not None:
            use_esp32 = True
            print("[OK] ESP32-CAM connected!")
        else:
            print("[WARNING] ESP32-CAM not reachable")

    if not use_esp32:
        print("[CAMERA] Using local webcam...")
        cam = cv2.VideoCapture(0)
        if not cam.isOpened():
            print("[ERROR] No camera available!")
            return
        print("[OK] Webcam ready")

    # Face detector
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    # Capture loop
    print(f"\n[CAPTURE] Capturing {NUM_SAMPLES} face samples for: {name}")
    print("  Instructions:")
    print("  - Look directly at the camera")
    print("  - Slowly turn your head left, right, up, down")
    print("  - Try different expressions (smile, neutral, etc.)")
    print("  - Press 'q' to cancel\n")

    captured = 0
    frame_count = 0

    while captured < NUM_SAMPLES:
        # Get frame
        if use_esp32:
            frame = get_frame_esp32()
        else:
            frame = get_frame_webcam(cam)

        if frame is None:
            time.sleep(0.3)
            continue

        frame_count += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(60, 60))

        if len(faces) > 0:
            # Take the largest face
            largest = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = largest

            # Every 3rd frame with a face, capture it (gives time for head movement)
            if frame_count % 3 == 0:
                face_roi = gray[y:y+h, x:x+w]
                filename = os.path.join(person_dir,
                                        f"{name}_{existing + captured + 1:03d}.jpg")
                cv2.imwrite(filename, face_roi)
                captured += 1
                print(f"  [{captured}/{NUM_SAMPLES}] Captured!")

            # Draw green box
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            cv2.putText(frame, f"Captured: {captured}/{NUM_SAMPLES}",
                        (x+5, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            cv2.putText(frame, "No face detected — look at camera",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Progress bar
        progress = int((captured / NUM_SAMPLES) * 300)
        cv2.rectangle(frame, (10, frame.shape[0]-40), (310, frame.shape[0]-20), (50,50,50), -1)
        cv2.rectangle(frame, (10, frame.shape[0]-40), (10+progress, frame.shape[0]-20), (0,255,0), -1)
        cv2.putText(frame, f"{captured}/{NUM_SAMPLES}", (320, frame.shape[0]-25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

        cv2.imshow('Enrollment', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("\n[CANCELLED] Enrollment cancelled by user")
            break

        time.sleep(0.3)

    # Cleanup camera
    if cam:
        cam.release()
    cv2.destroyAllWindows()

    if captured < 5:
        print(f"\n[ERROR] Only captured {captured} images. Need at least 5.")
        print("  Please try again with better lighting and positioning.")
        return

    # Retrain model
    print(f"\n[OK] Captured {captured} images for {name}")
    retrain = input("Retrain model now? (y/n): ").strip().lower()
    if retrain == 'y':
        print("\n[TRAINING] Retraining model...")
        os.system(f'{sys.executable} train_faces.py')
        print("[OK] Model retrained!")
    else:
        print(f"[INFO] Run 'python train_faces.py' later to include {name} in the model.")

    print(f"\n[DONE] Enrollment complete for: {name}")


if __name__ == '__main__':
    main()
