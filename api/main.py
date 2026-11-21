import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ai.detector import active_version
from api import alerts
from api.db import Store
from api.worker import Worker, check_silence, enqueue, process_pending
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
from api.scoring import READINESS_WEIGHTS, compute_metrics, readiness_score, sleep_score


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


def readiness_formula() -> str:
    """The configured readiness formula; an unknown value is a deployment error, not a request error."""
    formula = os.environ.get("RINGPULSE_READINESS_FORMULA", "v1")
    if formula not in READINESS_WEIGHTS:
        raise ValueError(
            f"RINGPULSE_READINESS_FORMULA={formula!r} is not one of {sorted(READINESS_WEIGHTS)}"
        )
    return formula


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_app(
    db_path: str | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
    notifier: alerts.Notifier | None = None,
    start_worker: bool | None = None,
    worker_interval: float = 0.5,
) -> FastAPI:
    """The API. The background worker starts with the app's lifespan (uvicorn, or `with TestClient(app)`);
    RINGPULSE_WORKER=0 turns it off. A plain TestClient(app) never runs it, so tests stay synchronous
    unless they ask for the worker."""
    formula = readiness_formula()  # fail fast at startup instead of with a 500 on the first request
    model_version = active_version()  # same rule for the model version
    rules = alerts.load_rules()
    notifier = notifier or alerts.LogNotifier()
    if start_worker is None:
        start_worker = os.environ.get("RINGPULSE_WORKER", "1") != "0"
    store = Store(db_path or os.environ.get("RINGPULSE_DB", "ringpulse.db"))

    def worker_step() -> None:
        process_pending(store, clock, notifier, model_version=model_version, formula=formula, rules=rules)
        check_silence(store, clock, notifier, rules)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker = Worker(worker_step, worker_interval) if start_worker else None
        if worker:
            worker.start()
        try:
            yield
        finally:
            if worker:
                worker.stop()

    app = FastAPI(title="RingPulse sync API", version="0.2.0", lifespan=lifespan)
    app.state.store = store
    app.state.worker_step = worker_step

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

            now = clock()
            conn.execute(
                "INSERT INTO devices (device_id, last_seen_at) VALUES (?, ?)"
                " ON CONFLICT(device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
                (req.device_id, now.isoformat()),
            )
            # Hand the night to the AI layer once, when this sync completed it. A repeat sync of a
            # complete night accepts nothing, so it never queues a second analysis.
            if status.sync_status == "complete" and accepted:
                enqueue(conn, req.night_id, now)

        return SyncResponse(**status.model_dump(), accepted=accepted, duplicates=duplicates, rejected=rejected)

    def insights_for(night_id: str) -> Insights:
        with store.connect() as conn:
            night = conn.execute("SELECT total_packets FROM nights WHERE night_id = ?", (night_id,)).fetchone()
            if night is None:
                raise HTTPException(404, "unknown night")
            status = sync_status(conn, night_id, night["total_packets"])
            rows = conn.execute(
                "SELECT samples_json FROM packets WHERE night_id = ? ORDER BY seq", (night_id,)
            ).fetchall()

        samples = [Sample.model_validate(raw) for row in rows for raw in json.loads(row["samples_json"])]
        formula = readiness_formula()
        metrics = compute_metrics(samples)
        return Insights(
            **status.model_dump(),
            sleep_minutes=metrics.sleep_minutes if metrics else None,
            sleep_score=sleep_score(metrics) if metrics else None,
            readiness_score=readiness_score(metrics, formula) if metrics else None,
            readiness_formula=formula,
        )

    # Declared before /nights/{night_id} so "latest" is not taken for a night id.
    @app.get("/nights/latest", response_model=Insights)
    def latest_night() -> Insights:
        """The night that most recently received a packet; if none has, the most recently registered one.
        This is what the app's Today screen shows."""
        with store.connect() as conn:
            row = conn.execute("SELECT night_id FROM packets ORDER BY rowid DESC LIMIT 1").fetchone()
            if row is None:
                row = conn.execute("SELECT night_id FROM nights ORDER BY rowid DESC LIMIT 1").fetchone()
        if row is None:
            raise HTTPException(404, "no nights yet")
        return insights_for(row["night_id"])

    @app.get("/nights/{night_id}", response_model=Insights)
    def night_insights(night_id: str) -> Insights:
        return insights_for(night_id)

    @app.get("/nights/{night_id}/analysis")
    def night_analysis(night_id: str):
        """What the AI layer concluded. 202 while the night is queued or still partial."""
        with store.connect() as conn:
            if conn.execute("SELECT 1 FROM nights WHERE night_id = ?", (night_id,)).fetchone() is None:
                raise HTTPException(404, "unknown night")
            row = conn.execute("SELECT * FROM analyses WHERE night_id = ?", (night_id,)).fetchone()
            job = conn.execute("SELECT status, error FROM jobs WHERE night_id = ?", (night_id,)).fetchone()
        if row is not None:
            return {"night_id": night_id, "status": "done", "model_version": row["model_version"],
                    "label": row["label"], "confidence": row["confidence"], "readiness": row["readiness"],
                    "analysed_at": row["analysed_at"]}
        if job is not None and job["status"] == "failed":
            return JSONResponse({"night_id": night_id, "status": "failed"}, status_code=500)
        status = "queued" if job is not None else "waiting_for_data"
        return JSONResponse({"night_id": night_id, "status": status}, status_code=202)

    @app.get("/alerts")
    def list_alerts(device_id: str) -> list[dict]:
        """Alerts for one device, newest first. A device only ever sees its own."""
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT id, rule_id, severity, message, night_id, created_at, last_seen_at, occurrences"
                " FROM alerts WHERE device_id = ? ORDER BY id DESC",
                (device_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    return app
