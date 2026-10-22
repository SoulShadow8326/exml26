import json
import sys

from engine.game import Game


def load_teams(path="teams.json"):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(f"teams file not found: {path}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"invalid JSON in {path}: {e}")


def main():
    teams = load_teams()
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else None
    game = Game(teams, spheres_per_team=3, seed=seed)
    print(f"match started, telemetry file: {game.telemetry.file_path}")
    game.run()
    print(f"match over at tick {game.tick}, score: {game.score}")


if __name__ == "__main__":
    main()
