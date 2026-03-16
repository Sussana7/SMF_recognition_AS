import camera
import network
import socket
import time
from machine import Pin


WIFI_SSID = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
SERVER_PORT = 8080

print("\n[1/3] Initializing camera...")

try:
    camera.init(0, format=camera.JPEG, framesize=camera.FRAME_VGA)
    camera.quality(10)
    print("[OK] Camera ready")
except Exception as e:
    print(f"[ERROR] Camera init failed: {e}")

print("\n[2/3] Connecting to WiFi...")

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

if not wlan.isconnected():
    print(f"Connecting to: {WIFI_SSID}")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    timeout = 20
    while not wlan.isconnected() and timeout > 0:
        print(f"  Waiting... {timeout}s", end='\r')
        time.sleep(1)
        timeout -= 1
    
    if wlan.isconnected():
        print("\n[OK] WiFi connected!")
    else:
        print("\n[ERROR] WiFi connection failed!")

ip_address = wlan.ifconfig()[0]
print(f"\nESP32-CAM IP: {ip_address}")
print(f"Capture URL: http://{ip_address}:{SERVER_PORT}/capture\n")

print("[3/3] Starting server...")

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind(('0.0.0.0', SERVER_PORT))
server_socket.listen(1)

print("[OK] Server ready!")
print("="*50)
print("Waiting for capture requests...\n")

request_count = 0

while True:
    try:
        client_socket, client_addr = server_socket.accept()
        request_count += 1
        
        print(f"[{request_count}] Request from {client_addr[0]}")
        
        request = client_socket.recv(1024)
        
        img = camera.capture()
        
        if img and len(img) > 0:
            response = b'HTTP/1.1 200 OK\r\n'
            response += b'Content-Type: image/jpeg\r\n'
            response += f'Content-Length: {len(img)}\r\n'.encode()
            response += b'\r\n'
            
            client_socket.send(response)
            client_socket.send(img)
            
            print(f"  Sent {len(img)} bytes")
        else:
            print("  Capture failed")
        
        client_socket.close()
    
    except KeyboardInterrupt:
        print("\nStopping...")
        break
    except Exception as e:
        print(f"[ERROR] {e}")

server_socket.close()
wlan.active(False)
camera.deinit()