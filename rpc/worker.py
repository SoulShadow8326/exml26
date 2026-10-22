import importlib.util
import math
import multiprocessing as mp
import sys
import traceback

_ctx = mp.get_context("spawn")

IDLE_ACTION = (0.0, 0.0, False, None)
READY_TOKEN = "__model_ready__"
READY_TIMEOUT_S = 10.0


def _load_decide(model_path):
    spec = importlib.util.spec_from_file_location("team_model", model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load model at {model_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.decide


def _clean_unit(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(-1.0, min(1.0, number))


def _normalize(action):
    try:
        if not isinstance(action, (tuple, list)):
            return (0.0, 0.0, False, None)
        if len(action) == 3:
            throttle, turn, jump = action
            return (_clean_unit(throttle), _clean_unit(turn), jump, None)
        if len(action) >= 4:
            throttle, turn, jump, sonar = action[:4]
            return (_clean_unit(throttle), _clean_unit(turn), jump, sonar)
        return (0.0, 0.0, False, None)
    except Exception:
        return (0.0, 0.0, False, None)


def _worker_loop(model_path, conn):
    try:
        decide = _load_decide(model_path)
    except Exception:
        print(f"worker: failed to load {model_path}", file=sys.stderr)
        traceback.print_exc()
        decide = lambda observation: IDLE_ACTION

    try:
        conn.send((READY_TOKEN,))
    except (BrokenPipeError, OSError):
        return

    while True:
        try:
            observation = conn.recv()
        except EOFError:
            break
        if observation is None:
            break
        try:
            action = _normalize(decide(observation))
        except Exception:
            action = IDLE_ACTION
        try:
            conn.send(action)
        except (BrokenPipeError, OSError):
            break


class ModelWorker:
    def __init__(self, team, model_path, sphere_id=None):
        self.team = team
        self.model_path = model_path
        self.sphere_id = sphere_id
        self._process = None
        self._conn = None
        self._spawn()

    def _spawn(self):
        parent_conn, child_conn = _ctx.Pipe()
        process = _ctx.Process(target=_worker_loop, args=(self.model_path, child_conn), daemon=True)
        process.start()
        try:
            child_conn.close()
        except OSError:
            pass
        self._process = process
        self._conn = parent_conn
        self._ready = False

    def wait_ready(self, timeout=READY_TIMEOUT_S):
        if self._ready or self._conn is None:
            return self._ready
        if not self._conn.poll(timeout):
            return False
        try:
            message = self._conn.recv()
        except EOFError:
            return False
        self._ready = isinstance(message, tuple) and message and message[0] == READY_TOKEN
        return self._ready

    def _respawn(self):
        self.close()
        self._spawn()

    def get_action(self, observation, timeout):
        if not self.wait_ready():
            self._respawn()
            return IDLE_ACTION

        try:
            self._conn.send(observation)
        except (BrokenPipeError, OSError):
            self._respawn()
            return IDLE_ACTION

        if self._conn.poll(timeout):
            try:
                result = self._conn.recv()
            except EOFError:
                self._respawn()
                return IDLE_ACTION
            return _normalize(result)

        self._respawn()
        return IDLE_ACTION

    def close(self):
        if self._process is not None and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1)
            if self._process.is_alive():
                try:
                    self._process.kill()
                except Exception:
                    pass
                self._process.join(timeout=1)
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        self._process = None
        self._conn = None
