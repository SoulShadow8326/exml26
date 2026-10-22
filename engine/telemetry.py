import json
import time
from pathlib import Path

from engine.constants import ARENA_SIZE, GRAVITY, JUMP_SPEED, SPHERE_RADIUS, TICK_RATE

MAX_JUMP_HEIGHT = (JUMP_SPEED ** 2) / (2 * -GRAVITY)


def build_map_frame(match_id, obstacles, flags, teams, max_ticks, ramps=None, seed=None):
    return {
        "type": "map",
        "match_id": match_id,
        "arena_size": ARENA_SIZE,
        "tick_rate": TICK_RATE,
        "sphere_radius": SPHERE_RADIUS,
        "max_jump_height": MAX_JUMP_HEIGHT,
        "max_ticks": max_ticks,
        "seed": seed,
        "teams": [{"name": t["name"], "color": t.get("color", "#ffffff")} for t in teams],
        "obstacles": [
            {"points": o.points, "height": o.height}
            for o in obstacles
        ],
        "ramps": [r.to_state_dict() for r in (ramps or [])],
        "flags": [f.to_state_dict() for f in flags],
    }


def build_tick_frame(match_id, tick, spheres, flags, score, respawn_at, deaths=None, now=None):
    return {
        "type": "tick",
        "match_id": match_id,
        "tick": tick,
        "time": now if now is not None else time.time(),
        "spheres": [
            {
                **s.to_state_dict(),
                "respawn_in": (respawn_at[s.id] - tick) if s.id in respawn_at else None,
            }
            for s in spheres
        ],
        "flags": [f.to_state_dict() for f in flags],
        "score": score,
        "deaths": list(deaths) if deaths else [],
    }


class TelemetryRecorder:
    def __init__(self, out_dir="data/telemetry", match_id=None):
        self.match_id = match_id or str(time.time_ns())
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        self.file_path = out_path / f"{self.match_id}.jsonl"
        self._fh = open(self.file_path, "x", buffering=1)

    def record_map(self, obstacles, flags, teams, max_ticks, ramps=None, seed=None):
        frame = build_map_frame(self.match_id, obstacles, flags, teams, max_ticks, ramps, seed)
        self._fh.write(json.dumps(frame) + "\n")

    def record_tick(self, tick, spheres, flags, score, respawn_at, deaths=None):
        frame = build_tick_frame(self.match_id, tick, spheres, flags, score, respawn_at, deaths)
        self._fh.write(json.dumps(frame) + "\n")

    def close(self):
        self._fh.close()
