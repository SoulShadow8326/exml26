import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine.constants import (
    ARENA_SIZE,
    DEATH_HISTORY_TICKS,
    RESPAWN_DELAY_TICKS,
    RPC_TIMEOUT_S,
    TICK_DT,
)
from engine.flags import Flag, update_flags
from engine.map_gen import generate_map, generate_ramps
from engine.physics import (
    clamp_to_arena,
    resolve_ground,
    resolve_obstacle_collisions,
    resolve_ramp_collisions,
    resolve_sphere_collisions,
)
from engine.sphere import Sphere
from engine.telemetry import TelemetryRecorder
from engine.vision import audible_sonars, visible_enemies
from rpc.worker import ModelWorker


def _clean_unit(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(-1.0, min(1.0, number))


def _normalize_action(action):
    try:
        if not isinstance(action, (tuple, list)):
            return 0.0, 0.0, False, None
        if len(action) == 3:
            throttle, turn, jump = action
            return _clean_unit(throttle), _clean_unit(turn), jump, None
        if len(action) >= 4:
            throttle, turn, jump, sonar_val = action[:4]
            return _clean_unit(throttle), _clean_unit(turn), jump, sonar_val
        return 0.0, 0.0, False, None
    except Exception:
        return 0.0, 0.0, False, None


def _team_home(index, total):
    half = ARENA_SIZE / 2.0 - 10.0
    if total <= 1:
        return (-half, 0.0)
    angle = 2 * math.pi * index / total
    return (half * math.cos(angle), half * math.sin(angle))


class Game:
    def __init__(self, teams, spheres_per_team=3, seed=None, max_ticks=6000):
        if not teams:
            raise ValueError("teams must be a non-empty list")
        if spheres_per_team < 1:
            raise ValueError("spheres_per_team must be >= 1")
        names = [t.get("name") for t in teams]
        if any(not n for n in names):
            raise ValueError("every team needs a non-empty 'name'")
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate team names: {names}")
        for t in teams:
            if not t.get("model_path"):
                raise ValueError(f"team {t.get('name')!r} is missing 'model_path'")
            if not Path(t["model_path"]).is_file():
                raise FileNotFoundError(
                    f"team {t['name']!r}: model_path not found: {t['model_path']}"
                )
        self.teams = teams
        self.seed = seed
        self.max_ticks = max_ticks
        self.tick = 0
        self.score = {t["name"]: 0 for t in teams}

        homes = [_team_home(i, len(teams)) for i in range(len(teams))]
        self.spheres = []
        self.clients = {}
        sphere_id = 0
        for team, (hx, hy) in zip(teams, homes):
            for i in range(spheres_per_team):
                offset = (i - spheres_per_team / 2.0) * 3.0
                sphere = Sphere(sphere_id, team["name"], hx + offset, hy, player=i + 1)
                self.spheres.append(sphere)
                self.clients[sphere_id] = ModelWorker(
                    team["name"], team["model_path"], sphere_id=sphere_id)
                sphere_id += 1

        for client in self.clients.values():
            client.wait_ready()

        self.flags = [Flag(team["name"], hx, hy) for team, (hx, hy) in zip(teams, homes)]
        ramp_seed = None if seed is None else (seed + 0x9E37) & 0xFFFFFFFF
        self.obstacles = generate_map(homes, seed=seed)
        self.ramps = generate_ramps(self.obstacles, homes, seed=ramp_seed)
        if len(self.obstacles) < 24:
            print(f"warn: placed {len(self.obstacles)}/24 obstacles (seed={seed})")
        if len(self.ramps) < 12:
            print(f"warn: placed {len(self.ramps)}/12 ramps (seed={seed})")
        self.telemetry = TelemetryRecorder()
        self.telemetry.record_map(self.obstacles, self.flags, self.teams, self.max_ticks, self.ramps, seed=seed)
        self._pool = ThreadPoolExecutor(max_workers=max(4, len(self.spheres)))
        self._respawn_at = {}
        self._last_sonar = {}
        self._death_log = []

    def _recent_deaths(self):
        cutoff = self.tick - DEATH_HISTORY_TICKS
        return [m for m in self._death_log if m["tick"] >= cutoff]

    def _collect_sphere_action(self, sphere, all_alive, own_flag_state, other_flags_state, sonar_snapshot):
        worker = self.clients[sphere.id]
        recent_deaths = self._recent_deaths()
        mates = [s for s in all_alive if s.team == sphere.team and s.id != sphere.id]
        sonars = audible_sonars(sphere, all_alive, sonar_snapshot, self.obstacles)
        observation = {
            "tick": self.tick,
            "self": sphere.to_state_dict(),
            "visible_enemies": visible_enemies(sphere, all_alive, self.obstacles),
            "own_flag": own_flag_state,
            "other_flags": other_flags_state,
            "teammates": [s.to_state_dict() for s in mates],
            "score": dict(self.score),
            "sonar_receive": sonars,
            "sonar_recieve": sonars,
            "death_messages": [m for m in recent_deaths if m["team"] == sphere.team],
        }
        return worker.get_action(observation, RPC_TIMEOUT_S)

    def step(self):
        alive_spheres = [s for s in self.spheres if s.alive]
        flag_by_team = {f.team: f for f in self.flags}

        futures = {
            sphere.id: self._pool.submit(
                self._collect_sphere_action,
                sphere,
                alive_spheres,
                flag_by_team[sphere.team].to_state_dict(),
                [f.to_state_dict() for f in self.flags if f.team != sphere.team],
                dict(self._last_sonar),
            )
            for sphere in alive_spheres
        }
        by_id = {s.id: s for s in alive_spheres}
        for sid, future in futures.items():
            throttle, turn, jump, sonar_val = _normalize_action(future.result())
            sphere = by_id[sid]
            sphere.apply_action(throttle, turn, jump, sonar_val, TICK_DT)
            if sonar_val is not None:
                self._last_sonar[sphere.id] = sonar_val
            elif sphere.id in self._last_sonar:
                del self._last_sonar[sphere.id]

        for sphere in self.spheres:
            sphere.integrate(TICK_DT)

        clamp_to_arena(self.spheres)
        resolve_ramp_collisions(self.spheres, self.ramps)
        resolve_obstacle_collisions(self.spheres, self.obstacles)
        resolve_ground(self.spheres, self.ramps, self.obstacles)
        resolve_sphere_collisions(self.spheres)
        update_flags(self.flags, self.spheres, self.score)
        self._collect_deaths()
        self._process_respawns()
        alive_ids = {s.id for s in self.spheres if s.alive}
        for sid in list(self._last_sonar):
            if sid not in alive_ids:
                del self._last_sonar[sid]

        self.telemetry.record_tick(self.tick, self.spheres, self.flags, self.score, self._respawn_at, self._recent_deaths())
        self.tick += 1

    def _collect_deaths(self):
        for sphere in self.spheres:
            if sphere.alive or sphere.death_reported:
                continue
            sphere.death_reported = True
            self._death_log.append({
                "player": sphere.player,
                "team": sphere.team,
                "tick": self.tick,
                "x": sphere.death_x,
                "y": sphere.death_y,
                "reason": sphere.death_reason or "unknown",
            })
        del self._death_log[:-200]

    def _process_respawns(self):
        for sphere in self.spheres:
            if sphere.alive:
                continue
            if sphere.id not in self._respawn_at:
                self._respawn_at[sphere.id] = self.tick + RESPAWN_DELAY_TICKS
            elif self._respawn_at[sphere.id] <= self.tick:
                sphere.respawn()
                del self._respawn_at[sphere.id]

    def is_over(self):
        return self.tick >= self.max_ticks

    def run(self):
        try:
            while not self.is_over():
                start = time.monotonic()
                self.step()
                elapsed = time.monotonic() - start
                remaining = TICK_DT - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            self.telemetry.close()
            for client in self.clients.values():
                client.close()
            self._pool.shutdown()
