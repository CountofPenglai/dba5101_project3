"""Continuous UCB runner. Offline by default; Ctrl-C requests a durable stop."""

import argparse
import json
import math
import os
import sqlite3
import sys
from contextlib import closing
from datetime import timedelta, timezone
from getpass import getpass
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
PROGRAM = HERE.parent / 'program'
if str(PROGRAM) not in sys.path:
    sys.path.insert(0, str(PROGRAM))

from bandit import UCBModel, TuningConfig, run_experiment
from bandit.client import validate_settings
from bandit.common import MAX_PULLS, integer

PILOT_PULLS = 240
SINGAPORE = timezone(timedelta(hours=8))


class ConfigError(ValueError):
    pass


def exploration():
    return round(2 * config.UCB_MULTIPLIER ** 2, 12)


def resolve_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else HERE / path).resolve()


def validate_config():
    for name in ('TARGET_TOTAL_PULLS', 'MAX_PULLS_THIS_RUN'):
        value = getattr(config, name)
        if value is not None:
            integer(value, name, maximum=MAX_PULLS)
    m = config.UCB_MULTIPLIER
    if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m) or not 0 < m <= 1:
        raise ConfigError('UCB_MULTIPLIER must be in (0, 1].')
    if config.MAX_RETRIES is not None:
        integer(config.MAX_RETRIES, 'MAX_RETRIES')
    integer(config.PROGRESS_EVERY, 'PROGRESS_EVERY', minimum=1)
    for name in ('ONLINE', 'AUTO_TUNE', 'ALLOW_UNSAVED_SERVER_PULLS'):
        if type(getattr(config, name)) is not bool:
            raise ConfigError(name+' must be True or False.')
    if not isinstance(config.GROUP_USERNAME, str):
        raise ConfigError('GROUP_USERNAME must be text.')
    validate_settings(config.REQUEST_INTERVAL, config.REQUEST_TIMEOUT)


def tuning_config(enabled):
    if not enabled:
        return None
    return TuningConfig(interval=config.TUNE_EVERY, candidates=config.TUNE_CANDIDATES,
                        train_worlds=config.TUNE_TRAIN_WORLDS,
                        validation_worlds=config.TUNE_VALIDATION_WORLDS,
                        max_seconds=config.TUNE_MAX_SECONDS, cvar_level=config.TUNE_CVAR_LEVEL,
                        stage_loss_allowance=config.TUNE_STAGE_LOSS_ALLOWANCE,
                        tail_loss_allowance=config.TUNE_TAIL_LOSS_ALLOWANCE)


def saved_state(path):
    if not path.is_file():
        return 0, None, 0
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        count, used = db.execute('SELECT COUNT(*),COALESCE(MAX(pull)+1,0) FROM results').fetchone()
        row = db.execute('SELECT payload FROM pending WHERE singleton=1').fetchone()
        return count, json.loads(row[0]) if row else None, used


def print_progress(row):
    seconds = row['elapsed_seconds']
    speed = row['completed_pulls']/seconds if seconds else 0
    print('Saved {:,} | this run {:,} | sign-ups {:,} | {:.2f} pulls/s | exploration {:g}'.format(
        row['history_pulls'], row['completed_pulls'], row['history_signups'], speed,
        row['parameters']['exploration']), flush=True)


def report(summary):
    print('\nArm    Pulls    Sign-ups     Rate')
    for row in sorted(summary['arms'], key=lambda r: -(r['conversion_rate'] or 0)):
        rate = '{:.3%}'.format(row['conversion_rate']) if row['conversion_rate'] is not None else '-'
        print('{:3} {:8,} {:11,} {:>9}'.format(row['arm'], row['pulls'], row['signups'], rate))
    print('\nSaved: {:,}. Stop reason: {}. Next/recovery arm: {}.'.format(
        summary['history_pulls'], summary['stop_reason'], summary['next_arm']))
    state = summary['tuning_state']
    if state:
        print('Last tuning: {}; selected x{:g}; next due at {:,} saved pulls.'.format(
            state['reason'], state['selected_multiplier'], state['next_at']))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--online', action='store_true', default=None)
    parser.add_argument('--limit', type=int, help='Maximum additional pulls; omitted uses config (None = remaining)')
    parser.add_argument('--target-total', type=int, help='Optional absolute group pull cap')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--auto-tune', dest='auto_tune', action='store_true', default=None)
    group.add_argument('--no-auto-tune', dest='auto_tune', action='store_false')
    args = parser.parse_args(argv)
    password, db_path = None, None
    try:
        validate_config()
        online = config.ONLINE if args.online is None else args.online
        budget = config.MAX_PULLS_THIS_RUN if args.limit is None else args.limit
        target = config.TARGET_TOTAL_PULLS if args.target_total is None else args.target_total
        if budget is not None:
            integer(budget, 'limit', maximum=MAX_PULLS)
        if target is not None:
            integer(target, 'target_total', maximum=MAX_PULLS)
        tune = tuning_config(config.AUTO_TUNE if args.auto_tune is None else args.auto_tune)
        db_path = resolve_path(config.DB_PATH)
        count, pending, used = saved_state(db_path)
        if target is not None and not pending:
            budget = min(budget if budget is not None else MAX_PULLS, max(0, target-used))
        print('Mode: {}. Saved: {:,}. Additional cap: {}. Tuning: {}.'.format(
            'ONLINE' if online else 'OFFLINE', count,
            'all remaining' if budget is None else '{:,}'.format(budget), bool(tune)), flush=True)
        username = None
        if online and budget != 0:
            username = config.GROUP_USERNAME.strip() or input('Group username: ').strip()
            if not username:
                raise ConfigError('A group username is required.')
            password = os.environ.get('GP3_PASSWORD') or getpass('Group password: ')
        summary = run_experiment(
            UCBModel(exploration()), budget, online=online, db_path=db_path,
            username=username, password=password, interval=config.REQUEST_INTERVAL,
            timeout=config.REQUEST_TIMEOUT, max_retries=config.MAX_RETRIES,
            log_path=resolve_path(config.LOG_PATH) if config.LOG_PATH is not None else None,
            target_total=target, tuning=tune, strict_history=not config.ALLOW_UNSAVED_SERVER_PULLS,
            progress=print_progress, progress_every=config.PROGRESS_EVERY)
        report(summary)
        return 0
    except KeyboardInterrupt:
        print('Forced interruption. Saved results and pending request are retained.', file=sys.stderr)
        return 130
    except Exception as error:
        # Never echo arbitrary remote error messages or credential-bearing tracebacks.
        print('Run stopped ({}). Check settings, saved history and the local log. '
              'Resolve any pending request before continuing.'.format(type(error).__name__), file=sys.stderr)
        return 1
    finally:
        password = None


if __name__ == '__main__':
    raise SystemExit(main())
