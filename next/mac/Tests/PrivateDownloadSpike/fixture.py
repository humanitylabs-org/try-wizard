"""Explicit local session fixture; never connects to GitHub or impersonates a user."""
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200); self.end_headers(); return
        if self.path == '/signin':
            self.send_response(302)
            self.send_header('Set-Cookie', 'fixture_session=local-test; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('Location', '/release'); self.end_headers(); return
        if self.headers.get('Cookie') != 'fixture_session=local-test':
            self.send_response(403); self.end_headers(); return
        payload = b'explicit-local-session-fixture\n'*1024 if self.path == '/asset' else b'<title>Local fixture only</title>'
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream' if self.path == '/asset' else 'text/html')
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers(); self.wfile.write(payload)
HTTPServer(('127.0.0.1',48937), Handler).serve_forever()
