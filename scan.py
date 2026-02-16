import cv2
import csv
from datetime import datetime
import time

# 1. Setup Recognizer
recognizer = cv2.face.LBPHFaceRecognizer_create()
recognizer.read('trainer.yml') 
faceCascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# CRITICAL: This list MUST match the ID order from your train_faces.py output
# Usually: Folder 1 = Index 0, Folder 2 = Index 1, etc.
names = ['Ammanuel', 'Selasi', 'Joel', 'Samuel', 'Osei'] 

cam = cv2.VideoCapture(0)

# We use a DICTIONARY for cooldowns so that Selasi doesn't block Ammanuel!
last_logged = {name: 0 for name in names}
cooldown_seconds = 30 # Set to 30 seconds so it doesn't spam the Excel file

print("System Active: Scanning for anyone present... (Press 'q' to quit)")

while True:
    ret, frame = cam.read()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # detectMultiScale finds ALL faces in the current frame
    faces = faceCascade.detectMultiScale(gray, 1.2, 5)

    for (x, y, w, h) in faces:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
        
        id_num, confidence = recognizer.predict(gray[y:y+h, x:x+w])

        if (confidence < 75): # Adjust this if it's too strict/loose
            name = names[id_num]
            current_time = time.time()
            
            # Check cooldown ONLY for this specific person
            if current_time - last_logged.get(name, 0) > cooldown_seconds:
                with open('attendance_log.csv', 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([name, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
                
                print(f"MATCH FOUND: {name} is present.")
                last_logged[name] = current_time
        else:
            name = "Unknown"

        cv2.putText(frame, str(name), (x+5, y-5), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    cv2.imshow('Real-Time Attendance', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cam.release()
cv2.destroyAllWindows()