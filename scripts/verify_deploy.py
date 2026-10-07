from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass
class CheckResult:
    path: str
    ok: bool
    status: int | None
    detail: str


def fetch(base_url: str, path: str, timeout: int) -> CheckResult:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = Request(url, headers={"User-Agent": "GastroFlow deploy verifier"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", errors="replace")
            if response.status >= 400:
                return CheckResult(path, False, response.status, "HTTP error")
            if path != "/ping" and not body.strip():
                return CheckResult(path, False, response.status, "empty response")
            return CheckResult(path, True, response.status, "ok")
    except HTTPError as exc:
        body = exc.read(300).decode("utf-8", errors="replace").strip().replace("\n", " ")
        detail = exc.reason if not body else f"{exc.reason}: {body[:180]}"
        return CheckResult(path, False, exc.code, detail)
    except URLError as exc:
        return CheckResult(path, False, None, str(exc.reason))
    except TimeoutError:
        return CheckResult(path, False, None, "timeout")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica un deploy publico de GastroFlow.")
    parser.add_argument("base_url", help="URL publica de Northflank, por ejemplo https://app.example.run")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    paths = ["/ping", "/", "/login", "/pedidos", "/gastos", "/catalogo-admin", "/promociones", "/admin"]
    results = [fetch(args.base_url, path, args.timeout) for path in paths]

    for result in results:
        mark = "OK" if result.ok else "FAIL"
        status = result.status if result.status is not None else "-"
        print(f"{mark:4} {status!s:>3} {result.path} {result.detail}")

    if not all(result.ok for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
