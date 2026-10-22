import math

from engine.constants import FLAG_CAPTURE_RADIUS


class Flag:
    def __init__(self, team, home_x, home_y):
        self.team = team
        self.home_x = home_x
        self.home_y = home_y
        self.x = home_x
        self.y = home_y
        self.carrier = None

    def drop(self):
        self.carrier = None
        self.x = self.home_x
        self.y = self.home_y

    def to_state_dict(self):
        return {
            "team": self.team,
            "x": self.x,
            "y": self.y,
            "carried_by": self.carrier.id if self.carrier else -1,
            "at_home": self.carrier is None and self.x == self.home_x and self.y == self.home_y,
        }


def update_flags(flags, spheres, score):
    by_team = {}
    for flag in flags:
        if flag.carrier is not None:
            flag.x = flag.carrier.x
            flag.y = flag.carrier.y
        by_team[flag.team] = flag

    for sphere in spheres:
        if not sphere.alive:
            continue

        if sphere.carrying_flag is not None:
            home_flag = by_team.get(sphere.team)
            if home_flag is not None:
                dist = math.hypot(sphere.x - home_flag.home_x, sphere.y - home_flag.home_y)
                if dist <= FLAG_CAPTURE_RADIUS:
                    score[sphere.team] = score.get(sphere.team, 0) + 1
                    sphere.carrying_flag.drop()
                    sphere.carrying_flag = None
            continue

        for flag in flags:
            if flag.team == sphere.team or flag.carrier is not None:
                continue
            dist = math.hypot(sphere.x - flag.x, sphere.y - flag.y)
            if dist <= FLAG_CAPTURE_RADIUS:
                flag.carrier = sphere
                sphere.carrying_flag = flag
                break
