import cv2
import os
import numpy as np
from PIL import Image

path = 'dataset'
recognizer = cv2.face.LBPHFaceRecognizer_create()
detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

def getImagesAndLabels(path):
    faceSamples = []
    ids = []
    # Create a dictionary to map names to numbers
    # Example: {'ammanuel': 0, 'selasi': 1, 'joel': 2...}
    name_to_id = {}
    current_id = 0

    for root, dirs, files in os.walk(path):
        for file in files:
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                # Get the folder name
                name = os.path.basename(root).lower()
                
                # If we haven't seen this person yet, give them a new ID
                if name not in name_to_id:
                    name_to_id[name] = current_id
                    print(f"Assigned ID {current_id} to {name}")
                    current_id += 1
                
                actual_id = name_to_id[name]
                img_path = os.path.join(root, file)
                
                PIL_img = Image.open(img_path).convert('L')
                img_numpy = np.array(PIL_img, 'uint8')
                
                faces = detector.detectMultiScale(img_numpy)
                for (x, y, w, h) in faces:
                    faceSamples.append(img_numpy[y:y+h, x:x+w])
                    ids.append(actual_id)
                    
    return faceSamples, ids, name_to_id

print("\n [INFO] Training faces. Please wait...")
faces, ids, name_map = getImagesAndLabels(path)

if len(faces) == 0:
    print("\n [ERROR] No face data found!")
else:
    recognizer.train(faces, np.array(ids))
    recognizer.write('trainer.yml')
    print(f"\n [SUCCESS] {len(np.unique(ids))} people trained: {list(name_map.keys())}")
    print("!!! Remember this order for your Main Script names list !!!")