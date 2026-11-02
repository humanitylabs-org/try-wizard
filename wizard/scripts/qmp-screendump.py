#!/usr/bin/env python3
"""Take a QEMU screendump through a QMP unix socket. usage: qmp-screendump.py SOCK OUT.ppm"""
import json
import socket
import sys

sock_path, out = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(10)
s.connect(sock_path)
f = s.makefile("rwb")


def read():
    while True:
        line = f.readline()
        if not line:
            raise SystemExit("qmp closed")
        msg = json.loads(line)
        if "event" not in msg:
            return msg


def cmd(name, **args):
    f.write(json.dumps({"execute": name, "arguments": args} if args else {"execute": name}).encode() + b"\n")
    f.flush()
    return read()


read()  # greeting
cmd("qmp_capabilities")
print("screendump:", cmd("screendump", filename=out))
print("status:", cmd("query-status").get("return"))
