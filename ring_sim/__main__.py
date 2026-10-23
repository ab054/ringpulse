"""Command line for the ring simulator.

    python -m ring_sim generate                       rewrite fixtures/nights/*.json
    python -m ring_sim sync good_night                sync a fixture night to a running API
    python -m ring_sim sync good_night --drop 3,5     ... losing packets 3 and 5 (a partial sync)
    python -m ring_sim sync good_night --url http://localhost:8000
"""
import argparse

from ring_sim import faults
from ring_sim.generate import PROFILES, load_night, write_fixtures
from ring_sim.ring import RingSimulator


def sync(name: str, url: str, drop: list[int]) -> None:
    import httpx  # test tooling dependency, only needed for this command

    simulator = RingSimulator(load_night(name))
    packets = faults.drop_seqs(simulator.packets(), drop)
    with httpx.Client(base_url=url, timeout=10) as client:
        response = simulator.sync(client, packets)
        response.raise_for_status()
        body = response.json()
    print(
        f"{simulator.night_id}: {body['sync_status']}, {body['received_packets']}/{body['total_packets']} packets"
        + (f", missing {body['missing_packets']}" if body["missing_packets"] else "")
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m ring_sim", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("generate", help="rewrite fixtures/nights/*.json")

    sync_parser = commands.add_parser("sync", help="sync a fixture night to a running API")
    sync_parser.add_argument("night", choices=sorted(PROFILES))
    sync_parser.add_argument("--url", default="http://localhost:8000")
    sync_parser.add_argument("--drop", default="", help="comma-separated packet numbers to lose, e.g. 3,5")

    args = parser.parse_args()
    if args.command == "generate":
        write_fixtures()
    else:
        sync(args.night, args.url, [int(n) for n in args.drop.split(",") if n])


main()
