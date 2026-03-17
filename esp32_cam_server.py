"""
ESP32-CAM Server — Smart Multi-Face Attendance System
=====================================================
Upload this file to ESP32-CAM as main.py via Thonny.

BEFORE UPLOADING:
  1. Update WIFI_SSID and WIFI_PASSWORD below (lines 18-19)
  2. Note the IP address printed on boot — enter it in pc_server.py

Endpoints:
  GET /capture   — Returns a single JPEG frame
  GET /status    — Returns JSON system status
  GET /stream    — MJPEG stream (for enrollment live preview)
"""

import camera
import network
import socket
import time
import json
from machine import Pin

# ─────────────────── CONFIGURATION ───────────────────
WIFI_SSID = "YOUR_WIFI_NAME"          # ← CHANGE THIS
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"  # ← CHANGE THIS
SERVER_PORT = 8080

# ─────────────────── CAMERA INIT ───────────────────
print("\n" + "=" * 50)
print("ESP32-CAM Server v2.0")
print("=" * 50)

print("\n[1/3] Initializing camera...")

camera_ready = False
for attempt in range(3):
    try:
        # Deinit first in case of restart
        try:
            camera.deinit()
        except:
            pass
        time.sleep_ms(200)

        camera.init(0, format=camera.JPEG, framesize=camera.FRAME_VGA)
        camera.quality(10)  # Lower = better quality (10-63)
        camera.framesize(camera.FRAME_VGA)  # 640x480
        camera_ready = True
        print("[OK] Camera ready (VGA 640x480)")
        break
    except Exception as e:
        print(f"[RETRY {attempt+1}/3] Camera init failed: {e}")
        time.sleep(1)

if not camera_ready:
    print("[ERROR] Camera initialization failed after 3 attempts!")
    print("  Check ribbon cable connection and power supply.")

# ─────────────────── WIFI CONNECTION ───────────────────
print("\n[2/3] Connecting to WiFi...")

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

def connect_wifi():
    """Connect to WiFi with retry logic."""
    if wlan.isconnected():
        return True

    print(f"  Connecting to: {WIFI_SSID}")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    timeout = 20
    while not wlan.isconnected() and timeout > 0:
        print(f"  Waiting... {timeout}s", end='\r')
        time.sleep(1)
        timeout -= 1

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print(f"\n[OK] WiFi connected!")
        print(f"  IP Address: {ip}")
        print(f"  Capture:    http://{ip}:{SERVER_PORT}/capture")
        print(f"  Status:     http://{ip}:{SERVER_PORT}/status")
        print(f"  Stream:     http://{ip}:{SERVER_PORT}/stream")
        return True
    else:
        print("\n[ERROR] WiFi connection failed!")
        return False

if not connect_wifi():
    print("[WARNING] Starting without WiFi — will retry on each request")

# ─────────────────── HTTP SERVER ───────────────────
print("\n[3/3] Starting HTTP server...")

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind(('0.0.0.0', SERVER_PORT))
server_socket.listen(2)

print("[OK] Server ready!")
print("=" * 50)
print("Waiting for requests...\n")

request_count = 0
boot_time = time.time()

# ─────────────────── REQUEST HANDLER ───────────────────

def parse_request(data):
    """Parse HTTP request and return the path."""
    try:
        request_line = data.decode().split('\r\n')[0]
        method, path, _ = request_line.split(' ', 2)
        return method, path
    except:
        return 'GET', '/capture'

def send_response(client, status, content_type, body):
    """Send HTTP response."""
    header = f'HTTP/1.1 {status}\r\n'
    header += f'Content-Type: {content_type}\r\n'
    header += f'Content-Length: {len(body)}\r\n'
    header += 'Access-Control-Allow-Origin: *\r\n'
    header += 'Connection: close\r\n'
    header += '\r\n'
    client.send(header.encode())
    client.send(body)

def handle_capture(client):
    """Handle /capture — return single JPEG frame."""
    if not camera_ready:
        send_response(client, '503 Service Unavailable', 'text/plain',
                      b'Camera not available')
        return

    img = camera.capture()
    if img and len(img) > 0:
        send_response(client, '200 OK', 'image/jpeg', img)
        return len(img)
    else:
        send_response(client, '500 Internal Server Error', 'text/plain',
                      b'Capture failed')
        return 0

def handle_status(client):
    """Handle /status — return JSON system status."""
    status = {
        'camera': camera_ready,
        'wifi': wlan.isconnected(),
        'ip': wlan.ifconfig()[0] if wlan.isconnected() else 'N/A',
        'uptime': time.time() - boot_time,
        'requests': request_count,
        'free_memory': 0
    }
    try:
        import gc
        gc.collect()
        status['free_memory'] = gc.mem_free()
    except:
        pass

    body = json.dumps(status).encode()
    send_response(client, '200 OK', 'application/json', body)

def handle_stream(client):
    """Handle /stream — MJPEG stream for live preview."""
    if not camera_ready:
        send_response(client, '503 Service Unavailable', 'text/plain',
                      b'Camera not available')
        return

    boundary = b'--frame'
    header = 'HTTP/1.1 200 OK\r\n'
    header += 'Content-Type: multipart/x-mixed-replace; boundary=frame\r\n'
    header += 'Access-Control-Allow-Origin: *\r\n'
    header += '\r\n'
    client.send(header.encode())

    try:
        while True:
            img = camera.capture()
            if img and len(img) > 0:
                frame_header = boundary + b'\r\n'
                frame_header += b'Content-Type: image/jpeg\r\n'
                frame_header += f'Content-Length: {len(img)}\r\n'.encode()
                frame_header += b'\r\n'
                client.send(frame_header)
                client.send(img)
                client.send(b'\r\n')
            time.sleep_ms(100)  # ~10 FPS
    except:
        pass  # Client disconnected

# ─────────────────── MAIN LOOP ───────────────────

while True:
    try:
        # Auto-reconnect WiFi if disconnected
        if not wlan.isconnected():
            print("[WIFI] Reconnecting...")
            connect_wifi()

        client_socket, client_addr = server_socket.accept()
        request_count += 1

        try:
            request_data = client_socket.recv(1024)
            method, path = parse_request(request_data)

            if path == '/capture' or path == '/':
                size = handle_capture(client_socket)
                print(f"[{request_count}] {client_addr[0]} → /capture ({size} bytes)")

            elif path == '/status':
                handle_status(client_socket)
                print(f"[{request_count}] {client_addr[0]} → /status")

            elif path == '/stream':
                print(f"[{request_count}] {client_addr[0]} → /stream (started)")
                handle_stream(client_socket)
                print(f"  Stream ended")

            else:
                send_response(client_socket, '404 Not Found', 'text/plain',
                              b'Not found. Use /capture, /status, or /stream')
                print(f"[{request_count}] {client_addr[0]} → {path} (404)")

        except Exception as e:
            print(f"[ERROR] Request handling: {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass

    except KeyboardInterrupt:
        print("\nStopping server...")
        break
    except Exception as e:
        print(f"[ERROR] Server: {e}")
        time.sleep(1)

# Cleanup
server_socket.close()
wlan.active(False)
if camera_ready:
    camera.deinit()
print("[OK] Server stopped")