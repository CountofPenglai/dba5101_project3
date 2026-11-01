"""Local learning, durable online pulls and bounded recovery."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from server_pull import UncertainPullError

from .audit import OnlineLog
from .client import PacedClient, validate_settings
from .common import DEADLINE, MAX_PULLS, SERVER_URL, integer, normalize_result, server_address
from .models import make_model
from .storage import HistoryStore, driver_lock

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "history.sqlite3"


class _DeadlineReached(RuntimeError):
    """Internal signal: a fresh request was cancelled before transmission."""


def utc_now():
    return datetime.now(timezone.utc)


def save_results(results, *, username, db_path=DEFAULT_DB, server_url=SERVER_URL):
    """Append actual historical responses, with deduplication and explicit provenance."""
    with driver_lock(db_path), HistoryStore(db_path) as store:
        store.bind(username, server_url)
        return store.import_results(results)


def _status(client, log):
    state = client.status()
    used = integer(state.get("PullsUsed"), "server PullsUsed", maximum=MAX_PULLS)
    total = integer(state.get("NetReward"), "server NetReward", maximum=used * 100)
    maximum = integer(state.get("MaxPulls"), "server MaxPulls", minimum=used, maximum=MAX_PULLS)
    if type(state.get("Open")) is not bool:
        raise ValueError("Invalid server Open flag")
    state = {"PullsUsed": used, "NetReward": total, "MaxPulls": maximum, "Open": state["Open"]}
    log.write("status", status=state)
    return state


def _resolve(store, client, log, max_retries, *, fresh=False):
    request = store.pending
    for attempt in range(1, max_retries + 2):
        log.write("pull_attempt", attempt=attempt, request=request)
        try:
            def before_send():
                if fresh and attempt == 1 and utc_now() >= DEADLINE:
                    # The current call has not entered HTTP yet, so cancellation
                    # is safe. Previously attempted/durable recoveries stay intact.
                    store._cancel_unsent(request["request_id"])
                    log.write("pull_cancelled", request=request, reason="deadline_reached")
                    raise _DeadlineReached()

            response = client.pull(request, before_send=before_send)
            # Treat an invalid response as uncertain; do not abandon its identity.
            try:
                row = normalize_result(response)
            except ValueError:
                raise UncertainPullError(request["request_id"], request["expected_pull"]) from None
            store.complete(row)
            log.write("pull_completed", attempt=attempt, request=request, result=row)
            return row
        except UncertainPullError:
            log.write("pull_uncertain", attempt=attempt, request=request,
                      retry_scheduled=attempt <= max_retries)
            if attempt > max_retries:
                raise
            client.wait_before_retry()


def _summary(model, store, *, online, budget, completed, reason, state=None, log_path=None):
    pending = store.pending
    return {"online": online, "model": model.name, "parameters": model.parameters,
            "requested_budget": budget, "completed_pulls": completed,
            "history_pulls": model.total_pulls, "history_signups": sum(model.signups),
            "next_arm": pending["arm"] if pending else model.select_arm(),
            "pending_request": pending, "stop_reason": reason,
            "server_status": state, "db_path": str(store.path),
            "log_path": str(log_path) if log_path else None, "arms": model.summary()}


def run_experiment(model="uniform", budget=0, *, online=False, db_path=DEFAULT_DB,
                   username=None, password=None, server_url=SERVER_URL,
                   interval=0.25, timeout=10.0, max_retries=2, log_path=None):
    """Fit saved history; optionally complete at most `budget` real pulls.

    Recovery of an earlier pending request occupies one budget slot in this run.
    Offline mode never makes requests, creates outcomes, or truncates training.
    Exceptions stop the run; committed results and unresolved request IDs survive.
    """
    integer(budget, "budget")
    integer(max_retries, "max_retries")
    if type(online) is not bool:
        raise ValueError("online must be a boolean")
    validate_settings(interval, timeout)
    server_url = server_address(server_url)
    policy = make_model(model)
    with driver_lock(db_path), HistoryStore(db_path) as store:
        policy.fit(store.results())
        if not online or budget == 0:
            return _summary(policy, store, online=online, budget=budget, completed=0,
                            reason="offline" if not online else "zero_budget")
        client = PacedClient(username, password, server_url, interval=interval, timeout=timeout)
        store.bind(username, server_url)
        log_path = (Path(log_path).expanduser().resolve() if log_path is not None
                    else store.path.with_suffix(".online.jsonl"))
        if log_path in (store.path, store.path.with_suffix(store.path.suffix + ".lock")):
            raise ValueError("Online log cannot overwrite the database or its lock")
        completed, state, reason = 0, None, "budget_complete"
        with OnlineLog(log_path, str(uuid.uuid4())) as log:
            log.write("run_started", model=policy.name, parameters=policy.parameters,
                      budget=budget, history_pulls=policy.total_pulls,
                      interval=interval, timeout=timeout, max_retries=max_retries)
            try:
                if utc_now() >= DEADLINE and store.pending is None:
                    reason = "deadline_reached"
                else:
                    with client:
                        # Recovery must precede status/new-arm selection. Status may be
                        # ahead of the pending counter after an unacknowledged success.
                        if store.pending is not None:
                            client.wait_before_retry()
                            row = _resolve(store, client, log, max_retries)
                            policy.update(row)
                            completed += 1
                        if completed < budget:
                            state = _status(client, log)
                            if store.last_pull is not None and store.last_pull >= state["PullsUsed"]:
                                raise RuntimeError("Saved history is ahead of the server; check the group and data")
                        while completed < budget:
                            if utc_now() >= DEADLINE:
                                reason = "deadline_reached"
                                break
                            if not state["Open"]:
                                reason = "server_closed"
                                break
                            if state["PullsUsed"] >= state["MaxPulls"]:
                                reason = "group_budget_exhausted"
                                break
                            request = store.prepare(arm=policy.select_arm(), expected_pull=state["PullsUsed"],
                                                    model=policy.name, parameters=policy.parameters)
                            log.write("pull_prepared", request=request)
                            try:
                                row = _resolve(store, client, log, max_retries, fresh=True)
                            except _DeadlineReached:
                                reason = "deadline_reached"
                                break
                            policy.update(row)
                            completed += 1
                            state = {**state, "PullsUsed": row["Pull"] + 1, "NetReward": row["NetReward"]}
                log.write("run_finished", completed_pulls=completed, stop_reason=reason,
                          history_pulls=policy.total_pulls)
            except BaseException as error:
                # Do not persist remote exception messages, headers, or credentials.
                log.write("run_failed", error_type=type(error).__name__, completed_pulls=completed,
                          pending_request=store.pending)
                raise
        return _summary(policy, store, online=True, budget=budget, completed=completed,
                        reason=reason, state=state, log_path=log_path)
