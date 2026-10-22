import math

ACCEL_RATE = 6.0
FRICTION = 0.98
SAFE_SPEED = 9.0
TURN_SPEED = 5.0
COMBAT_CLEARANCE = 12.0

_home = None
_flag_tick = -10 ** 9
_alert_tick = -10 ** 9
_last_score = None
_carry = {}
_prev_speed = {}
_prev_tick = {}
_detour_until = {}
_detour_side = {}
_detour_n = {}


def _norm(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _nav(s, tx, ty, arrive=1.2, cruise=9.5):
    dx, dy = tx - s["x"], ty - s["y"]
    dist = math.hypot(dx, dy)
    rel = _norm(math.atan2(dx, dy) - s.get("yaw", 0.0))
    turn = max(-1.0, min(1.0, rel * 0.6))
    if dist < arrive:
        return 0.0, turn, dist
    want = cruise if dist > 14.0 else cruise * max(0.10, (dist / 14.0) ** 2)
    if abs(rel) > 1.2:
        want = min(want, TURN_SPEED)
    speed = s.get("speed", 0.0)
    throttle = max(0.0, min(1.0, (want / FRICTION - speed) / ACCEL_RATE))
    return throttle, turn, dist


def _avoid(x, y, deaths):
    ax, ay = 0.0, 0.0
    for m in (deaths or [])[-12:]:
        dx, dy = x - m.get("x", x), y - m.get("y", y)
        d = math.hypot(dx, dy)
        if 0.01 < d < 14.0:
            w = (14.0 - d) / 14.0
            ax += dx / d * w
            ay += dy / d * w
    mag = math.hypot(ax, ay)
    if mag > 1.0:
        ax /= mag
        ay /= mag
    return ax, ay


def _danger_factor(x, y, deaths):
    factor = 1.0
    for m in (deaths or [])[-12:]:
        d = math.hypot(x - m.get("x", x), y - m.get("y", y))
        if d < 16.0:
            factor = min(factor, 0.45 + 0.55 * (d / 16.0))
    return factor


def _combat(s, enemies, carrying):
    if carrying:
        return None
    me = s.get("speed", 0.0)
    best, bd = None, 9.0
    for e in enemies or []:
        d = math.hypot(e.get("x", 0) - s["x"], e.get("y", 0) - s["y"])
        if d < bd:
            bd, best = d, e
    if best is None:
        return None
    es = best.get("speed", 0.0)
    rel = _norm(math.atan2(best.get("x", 0) - s["x"], best.get("y", 0) - s["y"]) - s.get("yaw", 0.0))
    if me > es + 1.5:
        want = SAFE_SPEED if abs(rel) < 1.0 else TURN_SPEED
        speed = s.get("speed", 0.0)
        t = max(0.0, min(1.0, (want / FRICTION - speed) / ACCEL_RATE))
        return t, max(-1.0, min(1.0, rel * 0.6))
    return None


def _move(sid, tick, s, tx, ty, arrive=1.2, cruise=9.5):
    speed = s.get("speed", 0.0)
    prev = _prev_speed.get(sid, speed)
    if _prev_tick.get(sid, tick - 1) != tick - 1:
        prev = speed
    stalled = prev > 4.0 and speed < 1.5
    _prev_speed[sid] = speed
    _prev_tick[sid] = tick
    if stalled and tick >= _detour_until.get(sid, -1):
        n = _detour_n.get(sid, 0) + 1
        _detour_n[sid] = n
        _detour_side[sid] = 1.0 if n % 2 else -1.0
        _detour_until[sid] = tick + 16
    if tick < _detour_until.get(sid, -1):
        speed = s.get("speed", 0.0)
        t = max(0.0, min(1.0, (SAFE_SPEED / FRICTION - speed) / ACCEL_RATE))
        return t, _detour_side[sid], True
    throttle, turn, _dist = _nav(s, tx, ty, arrive, cruise)
    return throttle, turn, False


def _threat(s, enemies):
    me = s.get("speed", 0.0)
    best, bd = None, 12.0
    for e in enemies or []:
        d = math.hypot(e.get("x", 0) - s["x"], e.get("y", 0) - s["y"])
        if d < bd and e.get("speed", 0.0) > me + 0.5:
            bd, best = d, e
    return best


def _carrier_teammate(mates):
    for m in mates:
        if m.get("carrying"):
            return m
    return None


def decide(observation):
    global _home, _flag_tick, _alert_tick, _last_score
    s = observation["self"]
    sid = s["id"]
    team = s.get("team", "?")
    tick = observation.get("tick", 0)
    mates = list(observation.get("teammates", []) or [])
    player = s.get("player", (sid % (len(mates) + 1)) + 1)
    own = observation.get("own_flag", {}) or {}
    if own.get("at_home"):
        _home = (own.get("x", s["x"]), own.get("y", s["y"]))
    hx, hy = _home if _home else (s["x"], s["y"])
    others = observation.get("other_flags", []) or []
    if others:
        ex, ey = others[0].get("x", -hx), others[0].get("y", -hy)
    else:
        ex, ey = -hx, -hy

    score = observation.get("score", {}) or {}
    if player == 1 and _last_score is not None and score.get(team, 0) > _last_score:
        print(f"[{team} tick={tick}] SCORED! {score}", flush=True)
    _last_score = score.get(team, 0)

    inbox = observation.get("sonar_receive", observation.get("sonar_recieve", [])) or []
    for m in inbox:
        v = m.get("value") if isinstance(m, dict) else None
        if isinstance(v, dict):
            if v.get("kind") == "has-flag":
                _flag_tick = tick
            elif v.get("kind") == "intruder":
                _alert_tick = tick

    carrying = s.get("carrying")
    if carrying and not _carry.get(sid):
        print(f"[{team} tick={tick}] player {player} grabbed the {carrying} flag!", flush=True)
    _carry[sid] = bool(carrying)

    by_player = {m.get("player"): m for m in mates}
    deaths = observation.get("death_messages", []) or []
    enemies = observation.get("visible_enemies", []) or []
    ax, ay = _avoid(s["x"], s["y"], deaths)

    dx, dy = ex - hx, ey - hy
    L = math.hypot(dx, dy) or 1.0
    px, py = -dy / L, dx / L

    carrier = _carrier_teammate(mates)
    stolen = not own.get("at_home", True)

    ping = None
    role = ((player - 1) % 3) + 1
    cruise = 9.5
    arrive = 1.2
    obj_dist = 999.0
    can_fight = False
    if carrying:
        tx, ty = hx, hy
        obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        threat = _threat(s, enemies)
        if threat is not None:
            ax2, ay2 = s["x"] - threat.get("x", s["x"]), s["y"] - threat.get("y", s["y"])
            an = math.hypot(ax2, ay2) or 1.0
            hdx, hdy = tx - s["x"], ty - s["y"]
            hn = math.hypot(hdx, hdy) or 1.0
            mix_x = hdx / hn * 0.6 + ax2 / an * 1.0
            mix_y = hdy / hn * 0.6 + ay2 / an * 1.0
            mn = math.hypot(mix_x, mix_y) or 1.0
            tx = s["x"] + mix_x / mn * 14.0
            ty = s["y"] + mix_y / mn * 14.0
        ping = {"kind": "has-flag", "player": player, "tick": tick}
    elif role == 1:
        if carrier is not None:
            tx, ty = carrier.get("x", ex), carrier.get("y", ey)
            arrive = 4.0
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        else:
            tx, ty = ex, ey
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
    elif role == 2:
        cruise = 9.0
        near = [e for e in enemies
                if math.hypot(e.get("x", 0) - hx, e.get("y", 0) - hy) < 16.0]
        if stolen:
            tx, ty = own.get("x", hx), own.get("y", hy)
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        elif near:
            near.sort(key=lambda e: math.hypot(e.get("x", 0) - s["x"], e.get("y", 0) - s["y"]))
            tx, ty = near[0].get("x", hx), near[0].get("y", hy)
            arrive = 2.0
            can_fight = True
            ping = {"kind": "intruder", "player": player, "tick": tick}
        elif tick - _alert_tick < 60:
            tx, ty = own.get("x", hx), own.get("y", hy)
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        else:
            tx, ty = hx + px * 6.0, hy + py * 6.0
            can_fight = True
    else:
        cruise = 9.8
        if stolen and 2 not in by_player:
            tx, ty = own.get("x", hx), own.get("y", hy)
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        elif carrier is not None:
            tx, ty = carrier.get("x", ex), carrier.get("y", ey)
            arrive = 4.0
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        elif tick - _flag_tick < 40 and 1 in by_player:
            tx, ty = by_player[1].get("x", ex), by_player[1].get("y", ey)
            arrive = 4.0
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])
        else:
            tx, ty = ex + px * 18.0, ey + py * 18.0
            obj_dist = math.hypot(tx - s["x"], ty - s["y"])

    cruise *= _danger_factor(s["x"], s["y"], deaths)
    target_dist = math.hypot(tx - s["x"], ty - s["y"])
    avoid_k = 7.0 if target_dist > 16.0 else 0.0
    throttle, turn, jump = _move(sid, tick, s, tx + ax * avoid_k, ty + ay * avoid_k, arrive, cruise)
    ov = _combat(s, enemies, carrying) if (can_fight and obj_dist > COMBAT_CLEARANCE) else None
    if ov is not None and not jump:
        throttle, turn = ov
    return throttle, turn, jump, ping
