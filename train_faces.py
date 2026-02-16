import cv2
import os
import numpy as np
import json
from PIL import Image

path = 'dataset'
recognizer = cv2.face.LBPHFaceRecognizer_create()
detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

def getImagesAndLabels(path):
    faceSamples = []
    ids = []
    name_to_id = {}
    current_id = 0

    for root, dirs, files in os.walk(path):
        for file in files:
            if file.lower().endswith((".jpg", ".jpeg", ".png")):
                # Get the folder name
                name = os.path.basename(root).strip()  # Keep original case!
                
                # Skip if folder has less than 5 images (your requirement)
                folder_images = [f for f in os.listdir(root) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
                if len(folder_images) < 5:
                    print(f"[SKIP] {name} - only {len(folder_images)} images (need 5+)")
                    continue
                
                # If we haven't seen this person yet, give them a new ID
                if name not in name_to_id:
                    name_to_id[name] = current_id
                    print(f"Assigned ID {current_id} to {name}")
                    current_id += 1
                
                actual_id = name_to_id[name]
                img_path = os.path.join(root, file)
                
                try:
                    PIL_img = Image.open(img_path).convert('L')
                    img_numpy = np.array(PIL_img, 'uint8')
                    
                    faces = detector.detectMultiScale(img_numpy)
                    for (x, y, w, h) in faces:
                        faceSamples.append(img_numpy[y:y+h, x:x+w])
                        ids.append(actual_id)
                except Exception as e:
                    print(f"[ERROR] Failed to process {img_path}: {e}")
                    
    return faceSamples, ids, name_to_id

print("\n" + "="*50)
print("FACIAL RECOGNITION TRAINING")
print("="*50)
print("\n[INFO] Training faces. Please wait...")

faces, ids, name_map = getImagesAndLabels(path)

if len(faces) == 0:
    print("\n[ERROR] No face data found!")
else:
    print(f"\n[INFO] Found {len(faces)} face samples from {len(name_map)} people")
    
    # Train the model
    recognizer.train(faces, np.array(ids))
    recognizer.write('trainer.yml')
    
    # Save the name mapping to JSON (THIS IS THE KEY!)
    id_to_name = {v: k for k, v in name_map.items()}  # Reverse the mapping
    
    with open('labels.json', 'w') as f:
        json.dump(id_to_name, f, indent=2)
    
    print(f"\n[SUCCESS] Training complete!")
    print(f"  → Model saved to: trainer.yml")
    print(f"  → Labels saved to: labels.json")
    print(f"\n  Trained people:")
    for id_num, name in sorted(id_to_name.items()):
        count = ids.count(id_num)
        print(f"    ID {id_num}: {name} ({count} images)")
    
   