#!/usr/bin/env python3
"""End-to-end test of a deployment compose file.

Brings up <server>/<compose file> together with tests/compose.ci*.yml (Pebble
instead of Let's Encrypt, Yggdrasil peering with the test host), reads the
SIMPLEX_ADDRESS lines printed by the `addresses` service and, in parallel:

  * runs `/_server test 1 <address>` in the SimpleX Chat CLI for every
    smp/xftp address (and, for SMP, every published port);
  * opens every `info` address in headless Chromium and checks the page.

Requirements on the host: docker compose, simplex-chat CLI, Python Playwright
with Chromium, `<SERVER>_ADDR` resolving to 127.0.0.1 (see --addr), and for the
Yggdrasil variant: yggdrasil binary, root (or passwordless sudo) and IPv6.

Usage:
  tests/e2e.py --server smp --variant clearnet
  tests/e2e.py --server xftp --variant yggdrasil --artifacts out/
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"
PEBBLE_IMAGE = "ghcr.io/letsencrypt/pebble:2.10.3"
COMPOSE_FILES = {
    "clearnet": "docker-compose.yml",
    "yggdrasil": "docker-compose.clearnet+yggdrasil.yml",
}
YGG_LISTEN_PORT = 12345
# Port a client uses when the address has none.
DEFAULT_PORTS = {"smp": "5223", "xftp": "443"}
ADDRESS_RE = re.compile(r"^SIMPLEX_ADDRESS (\S+) (\S+) (\S+)$")
SERVER_URI_RE = re.compile(r"^(?P<proto>smp|xftp)://(?P<fp>[^@]+)@(?P<host>\[[^\]]+\]|[^:]+)(?::(?P<port>\d+))?$")


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("check", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def as_root(cmd: list[str]) -> list[str]:
    return cmd if os.geteuid() == 0 else ["sudo", "-n", *cmd]


@dataclass(frozen=True)
class Address:
    network: str
    kind: str
    value: str


@dataclass
class Result:
    name: str
    ok: bool
    detail: str


class Deployment:
    def __init__(self, server: str, variant: str, addr: str, workdir: Path, artifacts: Path):
        self.server = server
        self.variant = variant
        self.addr = addr
        self.workdir = workdir
        self.artifacts = artifacts
        self.project = f"e2e-{server}-{variant}"
        self.compose_file = COMPOSE_FILES[variant]
        self.env = dict(os.environ)
        self.ygg_client: subprocess.Popen | None = None

    # --- setup -----------------------------------------------------------

    def compose(self, *args: str, **kw) -> subprocess.CompletedProcess:
        files = ["-f", str(self.workdir / self.compose_file), "-f", str(TESTS / "compose.ci.yml")]
        if self.variant == "yggdrasil":
            files += ["-f", str(TESTS / "compose.ci.yggdrasil.yml")]
        return run(["docker", "compose", "-p", self.project, *files, *args], env=self.env, **kw)

    def prepare(self) -> None:
        src = REPO / self.server
        self.workdir.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / self.compose_file, self.workdir / self.compose_file)

        overrides = {
            f"{self.server.upper()}_ADDR": self.addr,
            "ACME_CA": "https://pebble:14000/dir",
        }
        if self.variant == "yggdrasil":
            overrides["YGG_PRIV_KEY"] = ygg_genconf()["PrivateKey"]
            overrides["YGG_PEERS"] = f"tcp://host.docker.internal:{YGG_LISTEN_PORT}"
        lines = [
            line for line in (src / ".env").read_text().splitlines()
            if line.split("=", 1)[0].strip() not in overrides
        ]
        lines += [f"{k}={v}" for k, v in overrides.items()]
        (self.workdir / ".env").write_text("\n".join(lines) + "\n")

        # Caddy must trust Pebble's HTTPS endpoint: take Pebble's root from its image.
        ca = self.workdir / "pebble.minica.pem"
        run(["docker", "pull", "-q", PEBBLE_IMAGE], stdout=subprocess.DEVNULL)
        cid = run(["docker", "create", PEBBLE_IMAGE], capture_output=True).stdout.strip()
        try:
            run(["docker", "cp", f"{cid}:/test/certs/pebble.minica.pem", str(ca)])
        finally:
            run(["docker", "rm", cid], stdout=subprocess.DEVNULL)
        self.env["PEBBLE_ROOT_CA"] = str(ca)

    def start_ygg_client(self) -> None:
        conf = ygg_genconf()
        conf.update(
            Listen=[f"tcp://0.0.0.0:{YGG_LISTEN_PORT}"],
            Peers=[],
            MulticastInterfaces=[],
            AdminListen="none",
            IfName="ygg-e2e",
        )
        path = self.workdir / "yggdrasil-client.json"
        path.write_text(json.dumps(conf))
        log_file = open(self.artifacts / "yggdrasil-client.log", "w")
        self.ygg_client = subprocess.Popen(
            as_root(["yggdrasil", "-useconffile", str(path)]), stdout=log_file, stderr=subprocess.STDOUT
        )
        address = run(["yggdrasil", "-useconffile", str(path), "-address"], capture_output=True).stdout.strip()
        log(f"Yggdrasil test node: {address}, listening on :{YGG_LISTEN_PORT}")

    def up(self) -> None:
        log(f"Starting {self.server}/{self.compose_file} (project {self.project})")
        self.compose("up", "-d", "--quiet-pull")

    def wait_addresses(self, timeout: int = 300) -> list[Address]:
        log("Waiting for the addresses service")
        cid = self.compose("ps", "-a", "-q", "addresses", capture_output=True).stdout.strip()
        code = run(["docker", "wait", cid], capture_output=True, timeout=timeout).stdout.strip()
        if code != "0":
            raise RuntimeError(f"addresses service exited with code {code}")

        logs = self.compose("logs", "--no-log-prefix", "--no-color", "addresses", capture_output=True).stdout
        from_logs = [line for line in logs.splitlines() if line.startswith("SIMPLEX_ADDRESS ")]
        from_file = (self.workdir / "addresses.txt").read_text().splitlines()
        if from_logs != from_file:
            raise RuntimeError(f"addresses.txt differs from logs:\n{from_file}\n{from_logs}")

        addresses = []
        for line in from_file:
            m = ADDRESS_RE.match(line)
            if not m:
                raise RuntimeError(f"malformed address line: {line!r}")
            addresses.append(Address(*m.groups()))
        for a in addresses:
            log(f"  {a.network:9} {a.kind:4} {a.value}")

        networks = ["clearnet"] + (["yggdrasil"] if self.variant == "yggdrasil" else [])
        expected = {(n, k) for n in networks for k in (self.server, "info")}
        got = {(a.network, a.kind) for a in addresses}
        if got != expected or len(addresses) != len(expected):
            raise RuntimeError(f"expected addresses {sorted(expected)}, got {sorted(got)}")
        return addresses

    def dump_logs(self) -> None:
        out = self.compose("logs", "--no-color", "--timestamps", check=False, capture_output=True)
        (self.artifacts / "compose.log").write_text(out.stdout + out.stderr)
        ps = self.compose("ps", "-a", check=False, capture_output=True)
        (self.artifacts / "compose-ps.txt").write_text(ps.stdout + ps.stderr)

    def down(self) -> None:
        self.compose("down", "-v", "--remove-orphans", check=False, capture_output=True)
        if self.ygg_client:
            run(as_root(["kill", str(self.ygg_client.pid)]), check=False)
            try:
                self.ygg_client.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


def ygg_genconf() -> dict:
    return json.loads(run(["yggdrasil", "-genconf", "-json"], capture_output=True).stdout)


def server_variants(uri: str, published_ports: list[str]) -> list[str]:
    """The address as printed, plus an explicit-port variant for every other published port."""
    m = SERVER_URI_RE.match(uri)
    if not m:
        raise RuntimeError(f"malformed server address: {uri!r}")
    port = m["port"] or DEFAULT_PORTS[m["proto"]]
    uris = [uri]
    for other in published_ports:
        if other != port:
            uris.append(f"{m['proto']}://{m['fp']}@{m['host']}:{other}")
    return uris


def check_server(cli: str, uri: str, dbdir: Path, deadline: float) -> Result:
    """`/_server test 1 <uri>` in the SimpleX Chat CLI, retried until it passes or the deadline."""
    name = f"server test {uri}"
    db = dbdir / re.sub(r"[^A-Za-z0-9]+", "_", uri)[-80:]
    db.mkdir(parents=True, exist_ok=True)
    last = ""
    attempt = 0
    while True:
        attempt += 1
        p = run(
            [cli, "-d", str(db / "chat"), "--user-display-name", "e2e", "-e", f"/_server test 1 {uri}", "-t", "1"],
            check=False, capture_output=True, timeout=180,
        )
        out = (p.stdout + p.stderr).strip()
        lines = [line for line in out.splitlines() if "server test" in line]
        last = lines[-1] if lines else out[-500:]
        if re.search(r"\b(SMP|XFTP) server test passed\b", out):
            return Result(name, True, f"{last} (attempt {attempt})")
        if time.monotonic() > deadline:
            return Result(name, False, last)
        time.sleep(5)


def check_info_page(url: str, marker: str, shots: Path, deadline: float) -> Result:
    """Open the information page in headless Chromium; it must show `marker` (the source code link)."""
    from playwright.sync_api import sync_playwright

    name = f"info page {url}"
    shot = shots / (re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_") + ".png")
    last = ""
    with sync_playwright() as pw:
        # Connect directly even if the environment sets an HTTP(S) proxy.
        browser = pw.chromium.launch(args=["--no-proxy-server"])
        try:
            # Pebble certificates are not publicly trusted.
            page = browser.new_page(ignore_https_errors=True)
            while True:
                try:
                    resp = page.goto(url, wait_until="load", timeout=30_000)
                    status = resp.status if resp else None
                    text = page.inner_text("body")
                    page.screenshot(path=str(shot), full_page=True)
                    if status == 200 and marker in page.content():
                        title = page.title()
                        return Result(name, True, f"HTTP {status}, title {title!r}, {len(text)} chars")
                    last = f"HTTP {status}, {marker!r} not found on the page"
                except Exception as e:  # noqa: BLE001 - report any navigation error
                    last = str(e).splitlines()[0]
                if time.monotonic() > deadline:
                    return Result(name, False, last)
                time.sleep(5)
        finally:
            browser.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", choices=["smp", "xftp"], required=True)
    ap.add_argument("--variant", choices=sorted(COMPOSE_FILES), required=True)
    ap.add_argument("--addr", help="server domain, must resolve to 127.0.0.1 (default: <server>.test)")
    ap.add_argument("--cli", default=os.environ.get("SIMPLEX_CHAT_CLI", "simplex-chat"), help="simplex-chat CLI binary")
    ap.add_argument("--workdir", type=Path, help="deployment directory (default: temporary)")
    ap.add_argument("--artifacts", type=Path, help="logs and screenshots (default: <workdir>/artifacts)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds for every check to pass")
    ap.add_argument("--keep", action="store_true", help="do not tear the deployment down")
    args = ap.parse_args()

    addr = args.addr or f"{args.server}.test"
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix=f"e2e-{args.server}-{args.variant}-"))
    artifacts = args.artifacts or workdir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    try:
        resolved = socket.gethostbyname(addr)
    except OSError:
        resolved = None
    if resolved != "127.0.0.1":
        log(f"{addr} must resolve to 127.0.0.1 (got {resolved}); add it to /etc/hosts")
        return 2
    if not shutil.which(args.cli):
        log(f"simplex-chat CLI not found: {args.cli}")
        return 2

    dep = Deployment(args.server, args.variant, addr, workdir, artifacts)
    results: list[Result] = []
    try:
        dep.prepare()
        if args.variant == "yggdrasil":
            dep.start_ygg_client()
        dep.up()
        addresses = dep.wait_addresses()

        env = dict(line.split("=", 1) for line in (workdir / ".env").read_text().splitlines()
                   if "=" in line and not line.lstrip().startswith("#"))
        ports = [env["SMP_PORT_TRANSPORT"], env["SMP_PORT_HTTPS"]] if args.server == "smp" else [env["XFTP_PORT_HTTPS"]]
        marker = env[f"{args.server.upper()}_CFG__INFORMATION__source_code"]

        deadline = time.monotonic() + args.timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = []
            for a in addresses:
                if a.kind == args.server:
                    for uri in server_variants(a.value, ports):
                        futures.append(pool.submit(check_server, args.cli, uri, workdir / "cli", deadline))
                elif a.kind == "info":
                    futures.append(pool.submit(check_info_page, a.value, marker, artifacts, deadline))
            results = [f.result() for f in futures]
    except Exception as e:  # noqa: BLE001 - any setup failure fails the run
        results.append(Result("setup", False, f"{type(e).__name__}: {e}"))
    finally:
        dep.dump_logs()
        if not args.keep:
            dep.down()

    log("")
    for r in results:
        log(f"{'PASS' if r.ok else 'FAIL'}  {r.name}: {r.detail}")
    ok = bool(results) and all(r.ok for r in results)
    log(f"\n{'OK' if ok else 'FAILED'}: {sum(r.ok for r in results)}/{len(results)} checks passed; artifacts in {artifacts}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
