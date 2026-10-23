import json
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from api.db import Store
from api.models import (
    Insights,
    Packet,
    Rejection,
    Sample,
    SyncRequest,
    SyncResponse,
    SyncStatus,
)
from api.protocol import checksum
from api.scoring import compute_metrics, readiness_score, sleep_score


def packet_problem(packet: Packet, total_packets: int) -> str | None:
    """Why a packet must be rejected, or None if it is fine."""
    if packet.seq >= total_packets:
        return "seq_out_of_range"
    if not packet.samples:
        return "empty_packet"
    if checksum(packet.samples) != packet.checksum:
        return "bad_checksum"
    try:
        for raw in packet.samples:
            Sample.model_validate(raw)
    except ValidationError:
        return "invalid_samples"
    return None


def sync_status(conn: sqlite3.Connection, night_id: str, total_packets: int) -> SyncStatus:
    received = {r["seq"] for r in conn.execute("SELECT seq FROM packets WHERE night_id = ?", (night_id,))}
    missing = sorted(set(range(total_packets)) - received)
    return SyncStatus(
        night_id=night_id,
        sync_status="complete" if not missing else "partial",
        received_packets=len(received),
        total_packets=total_packets,
        missing_packets=missing,
    )


def create_app(db_path: str | None = None) -> FastAPI:
    store = Store(db_path or os.environ.get("RINGPULSE_DB", "ringpulse.db"))
    app = FastAPI(title="RingPulse sync API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/sync", response_model=SyncResponse)
    def sync(req: SyncRequest) -> SyncResponse:
        with store.connect() as conn:
            night = conn.execute(
                "SELECT device_id, total_packets FROM nights WHERE night_id = ?", (req.night_id,)
            ).fetchone()
            if night is None:
                conn.execute(
                    "INSERT INTO nights (night_id, device_id, total_packets) VALUES (?, ?, ?)",
                    (req.night_id, req.device_id, req.total_packets),
                )
            elif night["device_id"] != req.device_id or night["total_packets"] != req.total_packets:
                raise HTTPException(409, "night already registered with a different device or packet count")

            accepted = duplicates = 0
            rejected: list[Rejection] = []
            for packet in req.packets:
                problem = packet_problem(packet, req.total_packets)
                if problem:
                    rejected.append(Rejection(seq=packet.seq, reason=problem))
                    continue
                existing = conn.execute(
                    "SELECT checksum FROM packets WHERE night_id = ? AND seq = ?",
                    (req.night_id, packet.seq),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO packets (night_id, seq, checksum, samples_json) VALUES (?, ?, ?, ?)",
                        (req.night_id, packet.seq, packet.checksum, json.dumps(packet.samples)),
                    )
                    accepted += 1
                elif existing["checksum"] == packet.checksum:
                    duplicates += 1
                else:
                    rejected.append(Rejection(seq=packet.seq, reason="conflicting_duplicate"))

            status = sync_status(conn, req.night_id, req.total_packets)

        return SyncResponse(**status.model_dump(), accepted=accepted, duplicates=duplicates, rejected=rejected)

    @app.get("/nights/{night_id}", response_model=Insights)
    def night_insights(night_id: str) -> Insights:
        with store.connect() as conn:
            night = conn.execute("SELECT total_packets FROM nights WHERE night_id = ?", (night_id,)).fetchone()
            if night is None:
                raise HTTPException(404, "unknown night")
            status = sync_status(conn, night_id, night["total_packets"])
            rows = conn.execute(
                "SELECT samples_json FROM packets WHERE night_id = ? ORDER BY seq", (night_id,)
            ).fetchall()

        samples = [Sample.model_validate(raw) for row in rows for raw in json.loads(row["samples_json"])]
        formula = os.environ.get("RINGPULSE_READINESS_FORMULA", "v1")
        metrics = compute_metrics(samples)
        return Insights(
            **status.model_dump(),
            sleep_minutes=metrics.sleep_minutes if metrics else None,
            sleep_score=sleep_score(metrics) if metrics else None,
            readiness_score=readiness_score(metrics, formula) if metrics else None,
            readiness_formula=formula,
        )

    return app
