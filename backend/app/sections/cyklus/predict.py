"""Cycle arithmetic - pure functions, no database (FamilyLog 0.3.0).

The calendar method, as period apps use it:

* cycle length   = days from one period's start to the next; the mean of the
                   last six plausible cycles (15-60 days), else her own
                   setting, else 28.
* period length  = the mean of her last six finished periods (1-10 days),
                   else her setting, else 5.
* ovulation      = 14 days before the next period (the luteal phase is the
                   steady part of a cycle); fertile window = five days before
                   ovulation to one day after.
* PMS days       = the last five days before the next period.

It is an estimate from the calendar, never contraception - the page says so.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_CYCLE = 28
DEFAULT_PERIOD = 5
LUTEAL = 14
PMS_DAYS = 5
MAX_OPEN = 10             # an un-ended period counts at most this many days
HISTORY = 6               # cycles the averages look at
STALE_DAYS = 75           # no period logged for this long: no forecast
MIN_CYCLE, MAX_CYCLE = 15, 60

PHASES = ("menstruation", "follicular", "fertile", "ovulation", "luteal", "pms")


@dataclass(frozen=True)
class Period:
    start: date
    end: date | None = None          # None = not ended yet


def _mean(xs: list[int]) -> int:
    return int(round(statistics.mean(xs)))


def lengths(periods: list[Period]) -> list[int]:
    """Plausible cycle lengths, oldest first."""
    starts = sorted(p.start for p in periods)
    return [d for d in ((b - a).days for a, b in zip(starts, starts[1:])) if MIN_CYCLE <= d <= MAX_CYCLE]


def averages(periods: list[Period], cycle_setting: int | None = None,
             period_setting: int | None = None) -> dict:
    cl = lengths(periods)[-HISTORY:]
    if len(cl) >= 2 or (cl and not cycle_setting):
        cycle, cycle_src = _mean(cl), "målt"
    elif cycle_setting:
        cycle, cycle_src = cycle_setting, "indstilling"
    else:
        cycle, cycle_src = DEFAULT_CYCLE, "standard"
    pl = [(p.end - p.start).days + 1 for p in sorted(periods, key=lambda p: p.start) if p.end]
    pl = [d for d in pl if 1 <= d <= MAX_OPEN][-HISTORY:]
    if pl:
        period = _mean(pl)
    else:
        period = period_setting or DEFAULT_PERIOD
    period = max(1, min(period, cycle - LUTEAL - 1, MAX_OPEN))
    return {"cycle": cycle, "cycleSource": cycle_src, "period": period,
            "cyclesMeasured": len(cl), "spread": (max(cl) - min(cl)) if len(cl) >= 2 else None,
            "regular": (max(cl) - min(cl) <= 7) if len(cl) >= 3 else None,
            "history": cl}


def ovulation_day(cycle: int, period: int) -> int:
    """Cycle day of ovulation (day 15 in a 28-day cycle), never inside the period."""
    return max(cycle - LUTEAL + 1, period + 2)


def phase_of(cd: int, cycle: int, period: int, bleeding: bool | None = None) -> str:
    """The phase of cycle day `cd` (1 = first period day) in a cycle of
    `cycle` days. Past the expected end (a late period) counts as PMS.
    `bleeding` overrides the menstruation guess when known."""
    ov = ovulation_day(cycle, period)
    if bleeding is True and cd <= MAX_OPEN:
        return "menstruation"
    if cd <= period and bleeding is not False:
        return "menstruation"
    if cd == ov:
        return "ovulation"
    if ov - 5 <= cd <= ov + 1:
        return "fertile"
    if cd > cycle - PMS_DAYS:
        return "pms"
    if cd > ov + 1:
        return "luteal"
    return "follicular"


def period_days(periods: list[Period], period_len: int, today: date,
                flow_days: set[date] | None = None) -> set[date]:
    """The days she bled, as far as the log says: each period from its start
    to its end; an un-ended one to her usual length or the last day she
    logged flow (at most MAX_OPEN), never past today or the next start."""
    flow_days = flow_days or set()
    out: set[date] = set()
    ps = sorted(periods, key=lambda p: p.start)
    for i, p in enumerate(ps):
        nxt = ps[i + 1].start if i + 1 < len(ps) else None
        if p.end:
            end = p.end
        else:
            end = p.start + timedelta(days=period_len - 1)
            later = [d for d in flow_days if p.start <= d <= p.start + timedelta(days=MAX_OPEN - 1)]
            if later:
                end = max(end, max(later))
        if nxt:
            end = min(end, nxt - timedelta(days=1))
        end = min(end, today)
        d = p.start
        while d <= end:
            out.add(d)
            d += timedelta(days=1)
    return out


def status(periods: list[Period], today: date, cycle_setting: int | None = None,
           period_setting: int | None = None, flow_days: set[date] | None = None) -> dict:
    """Where she is today and what comes next."""
    avg = averages(periods, cycle_setting, period_setting)
    out = {"averages": avg, "empty": not periods}
    past = sorted((p for p in periods if p.start <= today), key=lambda p: p.start)
    if not past:
        return out
    L, P = avg["cycle"], avg["period"]
    last = past[-1]
    if (today - last.start).days >= max(2 * L, STALE_DAYS):
        # Nothing logged for months: no guessing a "150 days late".
        out.update({"stale": True, "lastStart": last.start.isoformat()})
        return out
    bled = period_days(periods, P, today, flow_days)
    in_period = today in bled
    cd = (today - last.start).days + 1
    next_start = last.start + timedelta(days=L)
    late = max(0, (today - next_start).days) if not in_period else 0
    # A late period is expected any day now: from tomorrow.
    expected = next_start if next_start >= today else today + timedelta(days=1)
    ov = last.start + timedelta(days=ovulation_day(L, P) - 1)
    if ov + timedelta(days=1) < today and not in_period:
        # This cycle's window is behind her: show the next cycle's.
        ov = expected + timedelta(days=ovulation_day(L, P) - 1)
    fertile_from, fertile_to = ov - timedelta(days=5), ov + timedelta(days=1)
    phase = "menstruation" if in_period else phase_of(cd, L, P, bleeding=False)
    period_day = (today - last.start).days + 1 if in_period else None
    out.update({
        "lastStart": last.start.isoformat(), "lastOpen": last.end is None,
        "cycleDay": cd, "phase": phase, "inPeriod": in_period, "periodDay": period_day,
        "nextStart": expected.isoformat(), "daysUntilNext": (expected - today).days,
        "late": late,
        "ovulation": ov.isoformat(), "fertileFrom": fertile_from.isoformat(),
        "fertileTo": fertile_to.isoformat(),
        "fertileToday": fertile_from <= today <= fertile_to,
        "daysUntilFertile": (fertile_from - today).days if today < fertile_from else 0,
        # "Is it over?" - an un-ended period past her usual length.
        "askEnded": last.end is None and not in_period and cd <= MAX_OPEN + 3,
    })
    return out


def day_kinds(periods: list[Period], frm: date, to: date, today: date,
              cycle_setting: int | None = None, period_setting: int | None = None,
              flow_days: set[date] | None = None) -> dict[date, str]:
    """A mark per day for the calendar and the week strip: 'period' (logged),
    'predicted' (a coming period), 'fertile', 'ovulation', 'pms' or ''.
    Past days follow the log; days from today on follow the prediction."""
    avg = averages(periods, cycle_setting, period_setting)
    L, P = avg["cycle"], avg["period"]
    bled = period_days(periods, P, today, flow_days)
    started = sorted((p for p in periods if p.start <= today), key=lambda p: p.start)
    starts = [p.start for p in started]
    last_end = started[-1].end if started else None
    st = status(periods, today, cycle_setting, period_setting, flow_days)
    out: dict[date, str] = {}
    d = frm
    while d <= to:
        kind = ""
        if d in bled:
            kind = "period"
        elif starts and d >= starts[0]:
            if d <= today:
                prev = max(s for s in starts if s <= d)
                nxt = [s for s in starts if s > d]
                length = (nxt[0] - prev).days if nxt and MIN_CYCLE <= (nxt[0] - prev).days <= MAX_CYCLE else L
                ph = phase_of((d - prev).days + 1, length, P, bleeding=False)
                kind = {"fertile": "fertile", "ovulation": "ovulation"}.get(ph, "")
                if d == today and ph == "pms" and not st.get("stale"):
                    kind = "pms"
            elif st.get("stale"):
                kind = ""
            else:
                anchor = date.fromisoformat(st["nextStart"])
                if d < anchor:
                    # The rest of a period still going is expected too; not
                    # once she has said it ended.
                    ended = last_end is not None and d > last_end
                    ph = phase_of((d - date.fromisoformat(st["lastStart"])).days + 1, L, P,
                                  bleeding=False if ended else None)
                    if st.get("late"):
                        ph = "pms"
                else:
                    k = (d - anchor).days // L
                    cd = (d - (anchor + timedelta(days=k * L))).days + 1
                    ph = phase_of(cd, L, P)
                kind = {"menstruation": "predicted", "fertile": "fertile", "ovulation": "ovulation",
                        "pms": "pms"}.get(ph, "")
        out[d] = kind
        d += timedelta(days=1)
    return out


def phase_by_day(periods: list[Period], days: list[date], today: date,
                 cycle_setting: int | None = None, period_setting: int | None = None,
                 flow_days: set[date] | None = None) -> dict[date, str]:
    """The phase each past day was in, for her patterns: by the cycle the day
    belonged to (its real length when the next start is logged)."""
    avg = averages(periods, cycle_setting, period_setting)
    L, P = avg["cycle"], avg["period"]
    bled = period_days(periods, P, today, flow_days)
    starts = sorted(p.start for p in periods if p.start <= today)
    out: dict[date, str] = {}
    for d in days:
        prev = [s for s in starts if s <= d]
        if not prev or d > today:
            continue
        p0 = prev[-1]
        nxt = [s for s in starts if s > d]
        length = (nxt[0] - p0).days if nxt else L
        if not MIN_CYCLE <= length <= MAX_CYCLE:
            continue                                    # a gap in the log, not a cycle
        cd = (d - p0).days + 1
        out[d] = "menstruation" if d in bled else phase_of(cd, length, P, bleeding=False)
    return out
