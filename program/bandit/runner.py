"""Local learning, durable online pulls and bounded recovery."""

import uuid
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from server_pull import UncertainPullError

from .audit import OnlineLog
from .client import PacedClient, validate_settings
from .control import StopController, StopRequested
from .common import DEADLINE, MAX_PULLS, SERVER_URL, integer, normalize_result, server_address
from .models import UCBModel, make_model
from .storage import HistoryStore, driver_lock
from .tuning import TuningConfig, evaluate_isolated

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


def _resolve(store, client, log, max_retries, *, fresh=False, stop=None):
    request = store.pending
    attempt = 0
    while True:
        attempt += 1
        if stop:
            stop.check()
        log.write("pull_attempt", attempt=attempt, request=request)
        try:
            def before_send():
                if stop and stop.is_set():
                    if fresh and attempt == 1:
                        store._cancel_unsent(request['request_id'])
                    raise StopRequested()
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
            retry = max_retries is None or attempt <= max_retries
            log.write("pull_uncertain", attempt=attempt, request=request,
                      retry_scheduled=retry)
            if stop:
                stop.check()
            if not retry:
                raise
            client.wait_before_retry()
            if max_retries is None and attempt > 1:
                delay = min(30., 2. ** min(attempt-1, 5))
                if stop:
                    if stop.wait(delay):
                        raise StopRequested()
                else:
                    time.sleep(delay)


def _summary(model, store, *, online, budget, completed, reason, state=None, log_path=None):
    pending = store.pending
    return {"online": online, "model": model.name, "parameters": model.parameters,
            "requested_budget": budget, "completed_pulls": completed,
            "history_pulls": model.total_pulls, "history_signups": sum(model.signups),
            "next_arm": pending["arm"] if pending else model.select_arm(),
            "pending_request": pending, "stop_reason": reason,
            "server_status": state, "db_path": str(store.path),
            "log_path": str(log_path) if log_path else None, "arms": model.summary(),
            "tuning_state": store.tuning_state()}


def run_experiment(model="uniform", budget=None, *, online=False, db_path=DEFAULT_DB,
                   username=None, password=None, server_url=SERVER_URL,
                   interval=0.25, timeout=10.0, max_retries=2, log_path=None,
                   target_total=None, tuning=None, strict_history=False,
                   stop_event=None, handle_signals=True, progress=None, progress_every=1000):
    """Fit saved history; optionally complete at most `budget` real pulls.

    Recovery of an earlier pending request occupies one budget slot in this run.
    Offline mode never makes requests, creates outcomes, or truncates training.
    Exceptions stop the run; committed results and unresolved request IDs survive.
    """
    if budget is not None:
        integer(budget, "budget")
    if target_total is not None:
        integer(target_total, 'target_total', maximum=MAX_PULLS)
    if max_retries is not None:
        integer(max_retries, "max_retries")
    integer(progress_every, 'progress_every', minimum=1)
    if any(type(x) is not bool for x in (online, strict_history, handle_signals)):
        raise ValueError("Run switches must be booleans")
    if tuning is not None and not isinstance(tuning, TuningConfig):
        raise ValueError('tuning must be TuningConfig or None')
    validate_settings(interval, timeout)
    server_url = server_address(server_url)
    policy = make_model(model)
    if tuning is not None and not isinstance(policy, UCBModel):
        raise ValueError('Automatic tuning requires UCB')
    limit = budget if budget is not None else MAX_PULLS
    with driver_lock(db_path), HistoryStore(db_path) as store, StopController(stop_event, handle_signals) as stop:
        policy.fit_aggregates(store.aggregate())
        saved_tuning = store.tuning_state()
        if tuning is not None and saved_tuning and saved_tuning.get('config_key') == tuning.key():
            policy.exploration = UCBModel(round(2*saved_tuning['selected_multiplier']**2, 12)).exploration
        if not online or budget == 0:
            return _summary(policy, store, online=online, budget=budget, completed=0,
                            reason="offline" if not online else "zero_budget")
        if target_total is not None:
            pending = store.pending
            used = (store.last_pull+1) if store.last_pull is not None else 0
            if (pending and pending['expected_pull'] >= target_total) or (not pending and used >= target_total):
                return _summary(policy, store, online=True, budget=budget, completed=0, reason='target_reached')
        client = PacedClient(username, password, server_url, interval=interval, timeout=timeout)
        store.bind(username, server_url)
        log_path = (Path(log_path).expanduser().resolve() if log_path is not None
                    else store.path.with_suffix(".online.jsonl"))
        if log_path in (store.path, store.path.with_suffix(store.path.suffix + ".lock")):
            raise ValueError("Online log cannot overwrite the database or its lock")
        completed, state, reason = 0, None, "budget_complete"
        started = time.monotonic()
        def notify_progress():
            if progress:
                progress({'completed_pulls': completed, 'history_pulls': policy.total_pulls,
                          'history_signups': sum(policy.signups), 'parameters': policy.parameters,
                          'elapsed_seconds': time.monotonic()-started, 'server_status': state})

        def maybe_tune():
            nonlocal saved_tuning
            if tuning is None or not all(policy.counts):
                return
            if (saved_tuning and saved_tuning.get('config_key') == tuning.key()
                    and policy.total_pulls < saved_tuning['next_at']):
                return
            stop.check()
            remaining = min(state['MaxPulls'], target_total if target_total is not None else MAX_PULLS)-state['PullsUsed']
            baseline = round(math.sqrt(policy.exploration/2), 12)
            log.write('tuning_started', at_pull=policy.total_pulls, remaining=remaining, baseline=baseline)
            try:
                decision = evaluate_isolated(policy.summary(), remaining, baseline, tuning, stop)
            except StopRequested:
                raise
            except Exception as error:
                decision = {'selected_multiplier': baseline, 'reason': 'tuning_failed',
                            'error_type': type(error).__name__}
            stop.check()
            selected = UCBModel(round(2*decision['selected_multiplier']**2, 12)).exploration
            decision.update(at_pull=policy.total_pulls, next_at=policy.total_pulls+tuning.interval,
                            config_key=tuning.key())
            store.record_tuning(decision)
            saved_tuning = decision
            policy.exploration = selected
            log.write('tuning_completed', decision=decision)
        with OnlineLog(log_path, str(uuid.uuid4())) as log:
            log.write("run_started", model=policy.name, parameters=policy.parameters,
                      budget=budget, history_pulls=policy.total_pulls,
                      interval=interval, timeout=timeout, max_retries=max_retries)
            try:
                stop.check()
                if utc_now() >= DEADLINE and store.pending is None:
                    reason = "deadline_reached"
                else:
                    with client:
                        # Recovery must precede status/new-arm selection. Status may be
                        # ahead of the pending counter after an unacknowledged success.
                        if store.pending is not None:
                            client.wait_before_retry()
                            row = _resolve(store, client, log, max_retries, stop=stop)
                            policy.update(row)
                            completed += 1
                        if completed < limit:
                            stop.check()
                            state = _status(client, log)
                            if store.last_pull is not None and store.last_pull >= state["PullsUsed"]:
                                raise RuntimeError("Saved history is ahead of the server; check the group and data")
                            if strict_history and (policy.total_pulls != state['PullsUsed'] or
                                                   sum(policy.signups) != state['NetReward']):
                                raise RuntimeError('The server has pulls this database does not; reconcile saved history')
                            notify_progress()
                        while completed < limit:
                            stop.check()
                            if utc_now() >= DEADLINE:
                                reason = "deadline_reached"
                                break
                            if not state["Open"]:
                                reason = "server_closed"
                                break
                            if state["PullsUsed"] >= state["MaxPulls"]:
                                reason = "group_budget_exhausted"
                                break
                            if target_total is not None and state['PullsUsed'] >= target_total:
                                reason = 'target_reached'
                                break
                            maybe_tune()
                            stop.check()
                            if utc_now() >= DEADLINE:
                                reason = 'deadline_reached'
                                break
                            request = store.prepare(arm=policy.select_arm(), expected_pull=state["PullsUsed"],
                                                    model=policy.name, parameters=policy.parameters)
                            log.write("pull_prepared", request=request)
                            try:
                                row = _resolve(store, client, log, max_retries, fresh=True, stop=stop)
                            except _DeadlineReached:
                                reason = "deadline_reached"
                                break
                            policy.update(row)
                            completed += 1
                            state = {**state, "PullsUsed": row["Pull"] + 1, "NetReward": row["NetReward"]}
                            if completed % progress_every == 0:
                                notify_progress()
                log.write("run_finished", completed_pulls=completed, stop_reason=reason,
                          history_pulls=policy.total_pulls)
            except StopRequested:
                reason = 'manual_stop'
                log.write('run_finished', completed_pulls=completed, stop_reason=reason,
                          history_pulls=policy.total_pulls, pending_request=store.pending)
            except BaseException as error:
                # Do not persist remote exception messages, headers, or credentials.
                log.write("run_failed", error_type=type(error).__name__, completed_pulls=completed,
                          pending_request=store.pending)
                raise
        notify_progress()
        return _summary(policy, store, online=True, budget=budget, completed=completed,
                        reason=reason, state=state, log_path=log_path)
