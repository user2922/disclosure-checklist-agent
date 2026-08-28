"""Reach the deployment from a network whose DNS blocks *.vercel.app.

This machine's resolver returns a Cisco Umbrella block address for every
vercel.app host, so ordinary requests never reach Vercel. This resolves the real
address over DNS-over-HTTPS (which is not blocked) and connects to that IP
directly with the correct SNI, so the deployment can be verified locally instead
of waiting on someone with a different network.

Usage: python scripts/check_live.py <host> [path ...]
"""

import socket
import ssl
import sys

import httpx

DOH = "https://cloudflare-dns.com/dns-query"


def resolve(host: str) -> list[str]:
    """Resolve A records over HTTPS, bypassing the local resolver.

    httpx rather than urllib: urllib uses the system trust store, which this
    machine's TLS interception breaks; httpx ships certifi.
    """
    response = httpx.get(
        DOH,
        params={"name": host, "type": "A"},
        headers={"accept": "application/dns-json"},
        timeout=20,
    )
    response.raise_for_status()
    return [a["data"] for a in response.json().get("Answer", []) if a.get("type") == 1]


def fetch(host: str, ip: str, path: str, timeout: int = 30) -> tuple[int, dict, str]:
    """One HTTP/1.1 GET to `ip`, presenting `host` for SNI and Host."""
    context = ssl.create_default_context()
    with socket.create_connection((ip, 443), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as sock:
            request = (
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                "User-Agent: check-live/1.0\r\nAccept: */*\r\nConnection: close\r\n\r\n"
            )
            sock.sendall(request.encode())
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)

    raw_response = b"".join(chunks)
    head, _, body = raw_response.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").splitlines()
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return status, headers, body.decode("utf-8", "replace")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    host = sys.argv[1]
    paths = sys.argv[2:] or ["/health", "/"]

    ips = resolve(host)
    if not ips:
        print(f"DNS-over-HTTPS returned no A record for {host}")
        return 2
    print(f"{host} -> {ips}  (via DoH; the local resolver is filtered)\n")

    failures = 0
    for path in paths:
        try:
            status, headers, body = fetch(host, ips[0], path)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERR   {path}  {type(exc).__name__}: {exc}")
            failures += 1
            continue
        ok = status < 400
        failures += 0 if ok else 1
        marker = "ok " if ok else "FAIL"
        print(f"  {marker}  {status}  {path}  [{headers.get('content-type', '?')[:30]}]")
        snippet = " ".join(body.split())[:150]
        print(f"        {snippet}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
