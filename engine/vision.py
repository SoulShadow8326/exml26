import math

from engine.constants import VISION_HALF_ANGLE_DEG, VISION_RANGE, SONAR_RANGE
from engine.geometry import segment_intersects_polygon

VISION_HALF_ANGLE = math.radians(VISION_HALF_ANGLE_DEG)


def _normalize_angle(angle):
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def _blocked(sphere, other, obstacles):
    for obstacle in obstacles:
        if obstacle.height <= min(sphere.z, other.z):
            continue
        if segment_intersects_polygon((sphere.x, sphere.y), (other.x, other.y), obstacle.points):
            return True
    return False


def visible_enemies(sphere, others, obstacles):
    visible = []
    for other in others:
        if other.team == sphere.team or not other.alive:
            continue

        dx, dy = other.x - sphere.x, other.y - sphere.y
        dist = math.hypot(dx, dy)
        if dist == 0 or dist > VISION_RANGE:
            continue
        angle_to = math.atan2(dx, dy)
        relative = _normalize_angle(angle_to - sphere.yaw)
        if abs(relative) > VISION_HALF_ANGLE:
            continue
        if _blocked(sphere, other, obstacles):
            continue

        visible.append(other.to_state_dict())
    return visible


def sonar_recipients(sender, all_spheres, obstacles):
    recipients = []
    for sphere in all_spheres:
        if not sphere.alive or sphere.id == sender.id:
            continue
        if sphere.team != sender.team:
            continue
        dx, dy = sphere.x - sender.x, sphere.y - sender.y
        dist = math.hypot(dx, dy)
        if dist > SONAR_RANGE:
            continue
        if _blocked(sender, sphere, obstacles):
            continue
        recipients.append(sphere.to_state_dict())
    return recipients


def audible_sonars(receiver, all_spheres, last_sonar, obstacles):
    if not receiver.alive:
        return []
    heard = []
    by_id = {s.id: s for s in all_spheres}
    for sender_id, value in (last_sonar or {}).items():
        if value is None:
            continue
        if sender_id == receiver.id:
            continue
        sender = by_id.get(sender_id)
        if sender is None or not sender.alive:
            continue
        if sender.team != receiver.team:
            continue
        dist = math.hypot(sender.x - receiver.x, sender.y - receiver.y)
        if dist > SONAR_RANGE:
            continue
        if _blocked(sender, receiver, obstacles):
            continue
        heard.append({"from_id": sender_id, "from_player": sender.player, "value": value})
    return heard
