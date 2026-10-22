import math

def point_in_polygon(px, py, polygon):
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_intersect = x1 + (py - y1) / (y2 - y1) * (x2 - x1)
            if px < x_intersect:
                inside = not inside
    return inside


def distance_point_to_segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    ab_len_sq = abx * abx + aby * aby
    if ab_len_sq == 0:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / ab_len_sq))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(px - cx, py - cy), cx, cy


def closest_point_on_polygon(px, py, polygon):
    n = len(polygon)
    best_dist = math.inf
    best_point = polygon[0]
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        dist, cx, cy = distance_point_to_segment(px, py, ax, ay, bx, by)
        if dist < best_dist:
            best_dist = dist
            best_point = (cx, cy)
    return best_dist, best_point


def _ccw(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p):
    return (
        min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
        and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9
    )


def segments_intersect(p1, p2, p3, p4):
    d1 = _ccw(p3, p4, p1)
    d2 = _ccw(p3, p4, p2)
    d3 = _ccw(p1, p2, p3)
    d4 = _ccw(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    if d1 == 0 and _on_segment(p3, p4, p1):
        return True
    if d2 == 0 and _on_segment(p3, p4, p2):
        return True
    if d3 == 0 and _on_segment(p1, p2, p3):
        return True
    if d4 == 0 and _on_segment(p1, p2, p4):
        return True
    return False


def segment_intersects_polygon(p1, p2, polygon):
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        if segments_intersect(p1, p2, a, b):
            return True
    return False


def polygon_centroid(polygon):
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def polygon_bounding_radius(polygon, centroid):
    cx, cy = centroid
    return max(math.hypot(px - cx, py - cy) for px, py in polygon)
