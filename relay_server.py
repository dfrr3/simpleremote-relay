#!/usr/bin/env python3
import socket
import threading
import time
import secrets
import string
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

rooms = {}
lock = threading.Lock()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        html = f"""<!DOCTYPE html>
<html>
<head><title>SimpleRemote Relay</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; background: #1a1a2e; color: #eee; }}
h1 {{ color: #00d9ff; }}
.status {{ background: #16213e; padding: 20px; border-radius: 10px; margin: 20px 0; }}
.online {{ color: #00ff88; }}
code {{ background: #0f0f1a; padding: 2px 8px; border-radius: 4px; }}
</style>
</head>
<body>
<h1>SimpleRemote Relay</h1>
<div class="status">
<p><strong>Status:</strong> <span class="online">Online</span></p>
<p><strong>Active Rooms:</strong> {len(rooms)}</p>
</div>
<p>Relay server is running!</p>
</body>
</html>"""
        self.wfile.write(html.encode())
    
    def log_message(self, format, *args):
        pass

def generate_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(chars) for _ in range(8))
        if code not in rooms:
            return code

def relay_data(src, dst, room_code, direction):
    logger.info(f"Relay {direction} started for {room_code}")
    src.settimeout(1)
    try:
        while True:
            try:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
            except socket.timeout:
                continue
            except:
                break
    finally:
        logger.info(f"Relay {direction} ended for {room_code}")
        with lock:
            if room_code in rooms:
                r = rooms[room_code]
                for s in [r.get('host'), r.get('viewer')]:
                    if s:
                        try: s.close()
                        except: pass
                del rooms[room_code]

def handle_client(sock, addr):
    try:
        sock.settimeout(30)
        data = sock.recv(1024).decode('utf-8')
        msg = json.loads(data)
        role = msg.get('role')
        room_code = msg.get('room_code')
        password = msg.get('password')
        
        if role == 'host':
            room_code = generate_code()
            with lock:
                rooms[room_code] = {'host': sock, 'password': password, 'created': time.time()}
            logger.info(f"Host created room {room_code}")
            sock.send(json.dumps({'status': 'ok', 'room_code': room_code}).encode())
            
            # Wait for viewer
            start = time.time()
            while time.time() - start < 300:
                with lock:
                    if room_code in rooms and rooms[room_code].get('viewer'):
                        break
                time.sleep(0.1)
            
            with lock:
                if room_code in rooms and rooms[room_code].get('viewer'):
                    viewer = rooms[room_code]['viewer']
                    sock.settimeout(None)
                    relay_data(sock, viewer, room_code, 'host->viewer')
        
        elif role == 'viewer':
            if not room_code or room_code not in rooms:
                sock.send(json.dumps({'status': 'error', 'message': 'Room not found'}).encode())
                return
            
            room = rooms[room_code]
            if room.get('password') and room['password'] != password:
                sock.send(json.dumps({'status': 'error', 'message': 'Wrong password'}).encode())
                return
            
            with lock:
                rooms[room_code]['viewer'] = sock
            logger.info(f"Viewer joined room {room_code}")
            sock.send(json.dumps({'status': 'ok', 'room_code': room_code}).encode())
            
            # Start relay
            with lock:
                host = rooms[room_code].get('host')
            if host:
                sock.settimeout(None)
                relay_data(sock, host, room_code, 'viewer->host')
    
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        try: sock.close()
        except: pass

def cleanup_rooms():
    while True:
        time.sleep(60)
        now = time.time()
        with lock:
            to_del = [c for c, r in rooms.items() if not r.get('viewer') and now - r.get('created', 0) > 300]
            for c in to_del:
                r = rooms[c]
                for s in [r.get('host'), r.get('viewer')]:
                    if s:
                        try: s.close()
                        except: pass
                del rooms[c]
                logger.info(f"Cleaned up room {c}")

def main():
    http_port = int(os.environ.get('PORT', 10000))
    relay_port = int(os.environ.get('RELAY_PORT', 5899))
    
    # HTTP server for Render health checks
    def run_http():
        server = HTTPServer(('0.0.0.0', http_port), HealthHandler)
        logger.info(f"HTTP server on port {http_port}")
        server.serve_forever()
    
    threading.Thread(target=run_http, daemon=True).start()
    threading.Thread(target=cleanup_rooms, daemon=True).start()
    
    # TCP relay server
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', relay_port))
    srv.listen(50)
    
    logger.info(f"Relay server on port {relay_port}")
    logger.info("Server ready!")
    
    while True:
        try:
            srv.settimeout(1)
            sock, addr = srv.accept()
            threading.Thread(target=handle_client, args=(sock, addr), daemon=True).start()
        except socket.timeout:
            continue

if __name__ == '__main__':
    main()
