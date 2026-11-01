"""Assignment constants and validation shared by models and persistence."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

ARMS = 24
VISITORS_PER_PULL = 100
MAX_PULLS = 1_000_000
SERVER_URL = "https://gp3-bandit-2026.onrender.com"
# 2026-11-15 23:59 in Singapore (UTC+08:00).
DEADLINE = datetime(2026, 11, 15, 15, 59, tzinfo=timezone.utc)


def integer(value, name, minimum=0, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("Invalid {}".format(name))
    return value


def server_address(value):
    if not isinstance(value, str):
        raise ValueError("Server must be an HTTPS base address")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.netloc or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise ValueError("Server must be an HTTPS base address without credentials or path")
    return value.rstrip("/")


def normalize_result(value):
    """Copy only the four documented fields; reject invalid observations."""
    if not isinstance(value, dict) or not {"Arm", "Reward", "NetReward", "Pull"} <= value.keys():
        raise ValueError("A result must contain Arm, Reward, NetReward and Pull")
    arm = value["Arm"]
    if isinstance(arm, str) and arm in {str(i) for i in range(ARMS)}:
        arm = int(arm)
    integer(arm, "arm", maximum=ARMS - 1)
    reward = integer(value["Reward"], "reward", maximum=VISITORS_PER_PULL)
    pull = integer(value["Pull"], "pull", maximum=MAX_PULLS - 1)
    total = integer(value["NetReward"], "net reward", minimum=reward,
                    maximum=(pull + 1) * VISITORS_PER_PULL)
    return {"Arm": str(arm), "Reward": reward, "NetReward": total, "Pull": pull}


def timestamp():
    return datetime.now(timezone.utc).isoformat()
