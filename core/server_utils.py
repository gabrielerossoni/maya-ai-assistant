"""
Utility per il server HTTP: selezione porta e banner.
Estratto da main.py per ridurre la complessità del punto di ingresso.
"""

import os
import socket
import sys


def pick_http_port(
    host: str = "127.0.0.1",
    *,
    max_attempts: int = 24,
) -> int:
    """
    Sceglie una porta TCP libera. Parte da MAYA_PORT (default 8000).
    Con MAYA_PORT_STRICT=1 usa solo quella e non prova altre (uvicorn fallirà se occupata).
    """
    first = int(os.environ.get("MAYA_PORT", "8000"))
    strict = os.environ.get("MAYA_PORT_STRICT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if strict:
        return first
    for port in range(first, first + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            return port
        except OSError:
            continue
    return first


def print_banner():
    PEACH = "\033[38;5;203m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print(f"\n{PEACH}╭───────────────────────────────────────────────────╮")
    print(f"│ {RESET}✷ Welcome to the {BOLD}MAYA{RESET} research preview!            {PEACH}│")
    print("╰───────────────────────────────────────────────────╯\n")

    print(f"{PEACH}{BOLD}")
    print(r" ███╗   ███╗  █████╗  ██╗   ██╗  █████╗ ")
    print(r" ████╗ ████║ ██╔══██╗ ╚██╗ ██╔╝ ██╔══██╗")
    print(r" ██╔████╔██║ ███████║  ╚████╔╝  ███████║")
    print(r" ██║╚██╔╝██║ ██╔══██║   ╚██╔╝   ██╔══██║")
    print(r" ██║ ╚═╝ ██║ ██║  ██║    ██║    ██║  ██║")
    print(r" ╚═╝     ╚═╝ ╚═╝  ╚═╝    ╚═╝    ╚═╝  ╚═╝")
    print(f"{RESET}")
    print(f" {GRAY}M.A.Y.A. - Multitask Advanced Yielding Assistant{RESET}")
    print(f" {GRAY}Sistema Agentico Locale - Offline First v1.0{RESET}\n")
