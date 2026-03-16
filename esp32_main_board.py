from machine import Pin, PWM
import time
import sys

# Setup PIR
pir = Pin(13, Pin.IN)

# Setup Buzzer
buzzer = PWM(Pin(14))
buzzer.freq(2000)
buzzer.duty(0)

print("\nCalibrating PIR (30 seconds - don't move)...")
for i in range(30, 0, -1):
    print(f"  {i}s", end='\r')
    time.sleep(1)

print("\nPIR Ready!")
buzzer.duty(1023)
time.sleep(0.1)
buzzer.duty(0)

print("\nWaiting for motion...")
print("="*50)

motion_active = False

while True:
    motion = pir.value()
    
    if motion == 1 and not motion_active:
        print("MOTION_DETECTED")      # Send to PC
        print("TRIGGER_CAMERA")        # ← NEW: Trigger ESP32-CAM
        
        # Beep 3 times
        for _ in range(3):
            buzzer.duty(1023)
            time.sleep(0.08)
            buzzer.duty(0)
            time.sleep(0.08)
        
        motion_active = True
        time.sleep(3)  # 3 second cooldown
        
    elif motion == 0:
        motion_active = False
    
    time.sleep(0.1)