from typing import Any, Protocol

from ring_sim.packets import PACKET_SIZE, make_packets


class HttpClient(Protocol):
    """Anything with .post(url, json=...): httpx.Client, FastAPI's TestClient, requests."""

    def post(self, url: str, *, json: Any) -> Any: ...


class RingSimulator:
    """A test ring holding one recorded night, ready to sync to the API."""

    def __init__(self, night: dict[str, Any], packet_size: int = PACKET_SIZE):
        self.night = night
        self._packets = make_packets(night["samples"], packet_size)

    @property
    def night_id(self) -> str:
        return self.night["night_id"]

    @property
    def device_id(self) -> str:
        return self.night["device_id"]

    def packets(self) -> list[dict[str, Any]]:
        """All packets in order. Pass a faulted copy (see faults.py) to `sync`."""
        return list(self._packets)

    def sync(self, client: HttpClient, packets: list[dict[str, Any]] | None = None) -> Any:
        """POST packets to /sync (all of them by default). Returns the HTTP response."""
        body = {
            "device_id": self.device_id,
            "night_id": self.night_id,
            "total_packets": len(self._packets),
            "packets": self.packets() if packets is None else packets,
        }
        return client.post("/sync", json=body)
