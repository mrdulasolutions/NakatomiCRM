"""Resolve and pin permitted HTTP destinations before connecting."""

import ipaddress
import socket

import httpx

from app.config import settings


def resolve_destination(host: str, port: int) -> str:
    addresses = sorted(
        {str(entry[4][0]) for entry in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    )
    allowed = {
        name.strip().casefold() for name in settings.INTEGRATION_PRIVATE_HOSTS.split(",") if name.strip()
    }
    if not addresses or (
        host.casefold() not in allowed
        and any(
            not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast
            for address in addresses
        )
    ):
        raise ValueError("Integration destination is outside the permitted network")
    return addresses[0]


def outgoing_request(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    redirects: int = 0,
    max_bytes: int = 1024 * 1024,
) -> httpx.Response:
    destination = httpx.URL(url)
    for hop in range(redirects + 1):
        host = destination.host
        if (
            destination.scheme not in ("http", "https")
            or not host
            or destination.username
            or destination.password
        ):
            raise ValueError("Invalid integration URL")
        port = destination.port or (443 if destination.scheme == "https" else 80)
        address = resolve_destination(host, port)
        authority = destination.netloc.decode("ascii")
        connection = destination.copy_with(host=address)
        with (
            httpx.Client(timeout=timeout, trust_env=False) as client,
            client.stream(
                method,
                connection,
                headers={**(headers or {}), "Host": authority},
                content=content,
                extensions={"sni_hostname": destination.raw_host.decode("ascii")},
            ) as response,
        ):
            if (
                response.is_redirect
                and hop < redirects
                and method == "GET"
                and response.headers.get("location")
            ):
                destination = destination.join(response.headers["location"])
                continue
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ValueError("Integration response exceeds size limit")
            copied_headers = httpx.Headers(response.headers)
            copied_headers.pop("content-encoding", None)
            copied_headers.pop("content-length", None)
            return httpx.Response(response.status_code, headers=copied_headers, content=bytes(body))
    raise ValueError("Integration redirect limit exceeded")
