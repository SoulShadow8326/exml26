import math
import random

from engine.constants import (
    ARENA_SIZE,
    OBSTACLE_COUNT,
    OBSTACLE_MAX_HEIGHT,
    OBSTACLE_MAX_POINTS,
    OBSTACLE_MAX_RADIUS,
    OBSTACLE_MIN_HEIGHT,
    OBSTACLE_MIN_POINTS,
    OBSTACLE_MIN_RADIUS,
    OBSTACLE_MIN_SPACING,
    RAMP_LENGTH_MAX,
    RAMP_LENGTH_MIN,
    RAMP_MAX_COUNT,
    RAMP_OVERLAP,
    RAMP_RING_COUNT,
    RAMP_WIDTH_MAX,
    RAMP_WIDTH_MIN,
    SPAWN_EXCLUSION_RADIUS,
)
from engine.geometry import (
    closest_point_on_polygon,
    point_in_polygon,
    polygon_bounding_radius,
    polygon_centroid,
    segments_intersect,
)


def _rect_edges(corners):
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


def _rects_overlap(a, b):
    for px, py in a:
        if point_in_polygon(px, py, b):
            return True
    for px, py in b:
        if point_in_polygon(px, py, a):
            return True
    for p1, p2 in _rect_edges(a):
        for p3, p4 in _rect_edges(b):
            if segments_intersect(p1, p2, p3, p4):
                return True
    return False


def _rect_hits_obstacle(corners, obstacles, target):
    for ob in obstacles:
        if ob is target:
            continue
        for px, py in corners:
            if point_in_polygon(px, py, ob.points):
                return True
        for p1, p2 in _rect_edges(corners):
            n = len(ob.points)
            for i in range(n):
                if segments_intersect(p1, p2, ob.points[i], ob.points[(i + 1) % n]):
                    return True
    return False


class Obstacle:
    def __init__(self, points, height):
        self.points = points
        self.height = height
        self.centroid = polygon_centroid(points)
        self.bounding_radius = polygon_bounding_radius(points, self.centroid)


class Ramp:
    def __init__(self, cx, cy, dx, dy, length, width, height):
        norm = math.hypot(dx, dy) or 1.0
        self.cx = cx
        self.cy = cy
        self.dx = dx / norm
        self.dy = dy / norm
        self.length = length
        self.width = width
        self.height = height

    def height_at(self, x, y):
        rx, ry = x - self.cx, y - self.cy
        along = rx * self.dx + ry * self.dy
        side = rx * -self.dy + ry * self.dx
        if abs(along) > self.length / 2.0 or abs(side) > self.width / 2.0:
            return None
        return (along + self.length / 2.0) / self.length * self.height

    def corners(self):
        ax, ay = self.dx * self.length / 2.0, self.dy * self.length / 2.0
        sx, sy = -self.dy * self.width / 2.0, self.dx * self.width / 2.0
        return [
            (self.cx - ax - sx, self.cy - ay - sy),
            (self.cx - ax + sx, self.cy - ay + sy),
            (self.cx + ax + sx, self.cy + ay + sy),
            (self.cx + ax - sx, self.cy + ay - sy),
        ]

    def solid_edges(self):
        ll, lr, hr, hl = self.corners()
        return [(ll, hl), (lr, hr), (hl, hr)]

    def surface_at_along(self, along):
        t = min(1.0, max(0.0, (along + self.length / 2.0) / self.length))
        return t * self.height

    def to_state_dict(self):
        return {
            "cx": self.cx,
            "cy": self.cy,
            "dx": self.dx,
            "dy": self.dy,
            "length": self.length,
            "width": self.width,
            "height": self.height,
        }


def _make_polygon(rng, cx, cy):
    n_points = rng.randint(OBSTACLE_MIN_POINTS, OBSTACLE_MAX_POINTS)
    base_radius = rng.uniform(OBSTACLE_MIN_RADIUS, OBSTACLE_MAX_RADIUS)
    step = 2 * math.pi / n_points
    points = []
    for i in range(n_points):
        angle = i * step + rng.uniform(-step * 0.2, step * 0.2)
        r = base_radius * rng.uniform(0.6, 1.0)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _too_close(cx, cy, bounding_radius, placed, exclusion_zones):
    for ex, ey, eradius in exclusion_zones:
        dist = math.hypot(cx - ex, cy - ey)
        if dist < eradius + bounding_radius:
            return True
    for other in placed:
        dist = math.hypot(cx - other.centroid[0], cy - other.centroid[1])
        if dist < bounding_radius + other.bounding_radius + OBSTACLE_MIN_SPACING:
            return True
    return False


def _radial_density_weight(r):
    return min(1.0, 0.25 + 0.75 * r)


def generate_map(spawn_points, seed=None):
    rng = random.Random(seed)
    half = ARENA_SIZE / 2.0
    exclusion_zones = [(sx, sy, SPAWN_EXCLUSION_RADIUS) for sx, sy in spawn_points]

    obstacles = []
    attempts = 0
    max_attempts = OBSTACLE_COUNT * 40
    while len(obstacles) < OBSTACLE_COUNT and attempts < max_attempts:
        attempts += 1
        cx = rng.uniform(-half + OBSTACLE_MAX_RADIUS, half - OBSTACLE_MAX_RADIUS)
        cy = rng.uniform(-half + OBSTACLE_MAX_RADIUS, half - OBSTACLE_MAX_RADIUS)
        r = math.hypot(cx, cy) / half
        if rng.random() > _radial_density_weight(r):
            continue
        points = _make_polygon(rng, cx, cy)
        centroid = polygon_centroid(points)
        bounding_radius = polygon_bounding_radius(points, centroid)
        if _too_close(centroid[0], centroid[1], bounding_radius, obstacles, exclusion_zones):
            continue
        height_ceiling = OBSTACLE_MIN_HEIGHT + (OBSTACLE_MAX_HEIGHT - OBSTACLE_MIN_HEIGHT) * min(1.0, max(0.15, r))
        height = rng.uniform(OBSTACLE_MIN_HEIGHT, height_ceiling)
        obstacles.append(Obstacle(points, height))

    return obstacles


def _ramp_fits(low_point, high_point, corners, obstacles, target, exclusion_zones, placed_ramps=()):
    half = ARENA_SIZE / 2.0 - 1.0
    for px, py in corners:
        if abs(px) > half or abs(py) > half:
            return False

    for ob in obstacles:
        if ob is target:
            continue
        if point_in_polygon(low_point[0], low_point[1], ob.points):
            return False
        if point_in_polygon(high_point[0], high_point[1], ob.points):
            return False
        dist_low, _ = closest_point_on_polygon(low_point[0], low_point[1], ob.points)
        if dist_low < 0.5:
            return False
        dist_high, _ = closest_point_on_polygon(high_point[0], high_point[1], ob.points)
        if dist_high < 0.5:
            return False

    if _rect_hits_obstacle(corners, obstacles, target):
        return False

    for other in placed_ramps:
        if _rects_overlap(corners, other.corners()):
            return False

    for ex, ey, eradius in exclusion_zones:
        if math.hypot(low_point[0] - ex, low_point[1] - ey) < eradius:
            return False
    return True


def _edge_outward_normal(ob, edge_index):
    ax, ay = ob.points[edge_index]
    bx, by = ob.points[(edge_index + 1) % len(ob.points)]
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    ex, ey = bx - ax, by - ay
    elen = math.hypot(ex, ey)
    if elen < 1.0:
        return None

    nx, ny = ey / elen, -ex / elen
    if nx * (mx - ob.centroid[0]) + ny * (my - ob.centroid[1]) < 0:
        nx, ny = -nx, -ny

    return mx, my, nx, ny, elen


def _angle_gap(angle_a, angle_b):
    gap = (angle_a - angle_b) % (2 * math.pi)
    return gap - 2 * math.pi if gap > math.pi else gap


def _build_ramp_on_edge(ob, edge_index, obstacles, exclusion_zones, rng, placed_ramps=()):
    normal = _edge_outward_normal(ob, edge_index)
    if normal is None:
        return None
    mx, my, nx, ny, elen = normal

    length = rng.uniform(RAMP_LENGTH_MIN, RAMP_LENGTH_MAX)
    width = min(rng.uniform(RAMP_WIDTH_MIN, RAMP_WIDTH_MAX), elen)
    dx, dy = -nx, -ny

    hx, hy = mx - nx * RAMP_OVERLAP, my - ny * RAMP_OVERLAP
    cx, cy = hx - dx * length / 2.0, hy - dy * length / 2.0
    lx, ly = hx - dx * length, hy - dy * length

    candidate = Ramp(cx, cy, dx, dy, length, width, ob.height)
    if not _ramp_fits((lx, ly), (hx, hy), candidate.corners(), obstacles, ob, exclusion_zones, placed_ramps):
        return None
    return candidate


def _ring_index(ob, half, rings):
    r = min(1.0, math.hypot(ob.centroid[0], ob.centroid[1]) / half)
    return min(rings - 1, int(r * rings))


def generate_ramps(obstacles, spawn_points, seed=None, count=RAMP_MAX_COUNT, rings=RAMP_RING_COUNT):
    rng = random.Random(seed)
    exclusion_zones = [(sx, sy, SPAWN_EXCLUSION_RADIUS) for sx, sy in spawn_points]
    half = ARENA_SIZE / 2.0

    remaining = list(obstacles)
    rng.shuffle(remaining)
    by_ring = [[ob for ob in remaining if _ring_index(ob, half, rings) == ring] for ring in range(rings)]

    ramps = []
    slots_per_ring = max(1, count // rings)
    for ring_obstacles in by_ring:
        for slot in range(slots_per_ring):
            if len(ramps) >= count or not ring_obstacles:
                break
            slot_angle = 2 * math.pi * slot / slots_per_ring
            tangent_dx, tangent_dy = -math.sin(slot_angle), math.cos(slot_angle)

            ring_obstacles.sort(key=lambda ob: abs(_angle_gap(math.atan2(ob.centroid[1], ob.centroid[0]), slot_angle)))

            chosen_ramp = None
            chosen_obstacle = None
            for ob in ring_obstacles[: max(3, len(ring_obstacles) // 4)]:
                normals = [(i, _edge_outward_normal(ob, i)) for i in range(len(ob.points))]
                normals = [(i, n) for i, n in normals if n is not None]
                normals.sort(key=lambda item: -abs(item[1][2] * tangent_dx + item[1][3] * tangent_dy))

                for edge_index, _ in normals:
                    ramp = _build_ramp_on_edge(ob, edge_index, obstacles, exclusion_zones, rng, tuple(ramps))
                    if ramp is not None:
                        chosen_ramp, chosen_obstacle = ramp, ob
                        break
                if chosen_ramp is not None:
                    break

            if chosen_ramp is None:
                continue
            ramps.append(chosen_ramp)
            ring_obstacles.remove(chosen_obstacle)
    return ramps
