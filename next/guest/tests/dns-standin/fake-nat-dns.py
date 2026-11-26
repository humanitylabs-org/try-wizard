# Stand-in for the Mac NAT DNS on a Tailscale Mac (try-wizard#155/#192): every UDP answer comes back
# truncated (TC=1) and the TCP retry is a reply claiming 4 answers with none ("Received invalid reply").
import socket, struct, threading, sys
ip = sys.argv[1]
def reply(q, tc):
    tid = q[:2]; flags = 0x8180 | (0x0200 if tc else 0)
    # header: qd=1, an=4 (claimed), no answer records actually included
    end = 12
    while q[end] != 0: end += q[end] + 1
    question = q[12:end + 5]
    return tid + struct.pack('>HHHHH', flags, 1, 4, 0, 0) + question
def udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((ip, 53))
    while True:
        q, a = s.recvfrom(4096); s.sendto(reply(q, True), a)
def tcp():
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind((ip, 53)); s.listen(8)
    while True:
        c, _ = s.accept()
        try:
            n = struct.unpack('>H', c.recv(2))[0]; q = c.recv(n); r = reply(q, False); c.sendall(struct.pack('>H', len(r)) + r)
        except Exception: pass
        c.close()
threading.Thread(target=udp, daemon=True).start(); tcp()
