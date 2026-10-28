"""Aritmética de horas hábiles: fines de semana, feriados, pausas y estados."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta

import pytest

from app.domain.sla import (
    AlwaysOnCalendar,
    BusinessHoursCalendar,
    Pause,
    SlaState,
    compute_due_at,
    elapsed_business_seconds,
    evaluate_sla,
    merge_pauses,
)
from app.services.sla_service import parse_sla_config
from tests.conftest import ART, art

HOUR = 3600
DAY = 9 * HOUR  # jornada de 9 a 18


@pytest.fixture
def cal() -> BusinessHoursCalendar:
    # Lunes 23 y martes 24/03/2026 son feriados
    return BusinessHoursCalendar(tz=ART, holidays=frozenset({date(2026, 3, 23), date(2026, 3, 24)}))


# ---------------------------------------------------------- business_seconds
class TestBusinessSeconds:
    def test_same_day_inside_hours(self, cal):
        assert cal.business_seconds(art(2026, 3, 11, 10), art(2026, 3, 11, 12, 30)) == 2.5 * HOUR

    def test_end_before_start_is_zero(self, cal):
        assert cal.business_seconds(art(2026, 3, 11, 12), art(2026, 3, 11, 10)) == 0

    def test_starts_before_opening_counts_from_nine(self, cal):
        assert cal.business_seconds(art(2026, 3, 11, 6), art(2026, 3, 11, 10)) == HOUR

    def test_ends_after_closing_counts_until_eighteen(self, cal):
        assert cal.business_seconds(art(2026, 3, 11, 17), art(2026, 3, 11, 22)) == HOUR

    def test_entirely_outside_hours(self, cal):
        assert cal.business_seconds(art(2026, 3, 11, 19), art(2026, 3, 12, 8, 59)) == 0

    def test_overnight(self, cal):
        # 17:00 mié → 10:00 jue = 1h + 1h
        assert cal.business_seconds(art(2026, 3, 11, 17), art(2026, 3, 12, 10)) == 2 * HOUR

    def test_weekend_is_skipped(self, cal):
        # viernes 17:00 → lunes 10:00 = 1h viernes + 1h lunes
        assert cal.business_seconds(art(2026, 3, 13, 17), art(2026, 3, 16, 10)) == 2 * HOUR

    def test_full_saturday_counts_nothing(self, cal):
        assert cal.business_seconds(art(2026, 3, 14, 0), art(2026, 3, 15, 23, 59)) == 0

    def test_holidays_are_skipped(self, cal):
        # viernes 20 17:00 → miércoles 25 10:00: sáb, dom, lun y mar feriados
        assert cal.business_seconds(art(2026, 3, 20, 17), art(2026, 3, 25, 10)) == 2 * HOUR

    def test_full_week(self, cal):
        assert cal.business_seconds(art(2026, 3, 9, 0), art(2026, 3, 16, 0)) == 5 * DAY

    def test_utc_inputs_are_converted_to_local_time(self, cal):
        # 13:00 UTC = 10:00 ART
        start = datetime(2026, 3, 11, 13, tzinfo=UTC)
        assert cal.business_seconds(start, start + timedelta(hours=1)) == HOUR

    def test_naive_datetimes_are_rejected(self, cal):
        with pytest.raises(ValueError):
            cal.business_seconds(datetime(2026, 3, 11, 10), art(2026, 3, 11, 11))


# ------------------------------------------------------- add_business_seconds
class TestAddBusinessSeconds:
    def test_same_day(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 11, 10), 2 * HOUR) == art(2026, 3, 11, 12)

    def test_rolls_to_next_day(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 11, 17), 2 * HOUR) == art(2026, 3, 12, 10)

    def test_friday_afternoon_rolls_to_monday(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 13, 17), 2 * HOUR) == art(2026, 3, 16, 10)

    def test_skips_holidays(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 20, 17), 2 * HOUR) == art(2026, 3, 25, 10)

    def test_start_on_weekend_begins_monday_opening(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 14, 15), 30 * 60) == art(2026, 3, 16, 9, 30)

    def test_start_before_opening(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 11, 7), HOUR) == art(2026, 3, 11, 10)

    def test_start_after_closing(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 11, 20), HOUR) == art(2026, 3, 12, 10)

    def test_exactly_until_closing_stays_same_day(self, cal):
        assert cal.add_business_seconds(art(2026, 3, 11, 9), DAY) == art(2026, 3, 11, 18)

    def test_multi_day_target(self, cal):
        # 27 h hábiles (P3) desde mié 10:00 = 3 jornadas → lun 10:00 (fin de semana en medio)
        assert cal.add_business_seconds(art(2026, 3, 11, 10), 27 * HOUR) == art(2026, 3, 16, 10)

    def test_zero_returns_start(self, cal):
        start = art(2026, 3, 14, 15)
        assert cal.add_business_seconds(start, 0) == start

    @pytest.mark.parametrize("seed", range(5))
    def test_round_trip_with_business_seconds(self, cal, seed):
        rng = random.Random(seed)
        for _ in range(40):
            start = art(2026, 3, 1) + timedelta(minutes=rng.randint(0, 60 * 24 * 40))
            amount = rng.randint(1, 60 * HOUR)
            end = cal.add_business_seconds(start, amount)
            assert cal.business_seconds(start, end) == pytest.approx(amount)


class TestCalendarConfig:
    def test_invalid_hours(self):
        with pytest.raises(ValueError):
            BusinessHoursCalendar(tz=ART, opens_at=time(18), closes_at=time(9))

    def test_needs_workdays(self):
        with pytest.raises(ValueError):
            BusinessHoursCalendar(tz=ART, workdays=frozenset())

    def test_yaml_config_loads_argentina_holidays(self):
        config = parse_sla_config(
            {
                "timezone": "America/Argentina/Buenos_Aires",
                "business_hours": {"start": "09:00", "end": "18:00", "workdays": [0, 1, 2, 3, 4]},
                "holidays": [date(2026, 4, 2), "2026-04-03"],
                "policies": {
                    p: {"first_response_minutes": 10, "resolution_minutes": 60}
                    for p in ("P1", "P2", "P3", "P4")
                },
            }
        )
        assert not config.calendar.is_business_day(date(2026, 4, 2))
        assert not config.calendar.is_business_day(date(2026, 4, 3))
        # Jueves 2 y viernes 3 de abril feriados: miércoles 17:00 + 2h → lunes 6, 10:00
        assert config.calendar.add_business_seconds(art(2026, 4, 1, 17), 2 * HOUR) == art(
            2026, 4, 6, 10
        )

    def test_missing_policy_is_an_error(self):
        with pytest.raises(ValueError, match="Faltan políticas"):
            parse_sla_config(
                {"policies": {"P1": {"first_response_minutes": 1, "resolution_minutes": 2}}}
            )

    def test_repo_yaml_is_valid(self, sla_config):
        assert set(sla_config.policies) == {"P1", "P2", "P3", "P4"}
        assert sla_config.policies["P1"].business_hours_only is False
        assert sla_config.warning_threshold == 0.75


def test_always_on_calendar_counts_every_second():
    cal = AlwaysOnCalendar()
    start = art(2026, 3, 14, 23)  # sábado a la noche
    assert cal.business_seconds(start, start + timedelta(hours=2)) == 2 * HOUR
    assert cal.add_business_seconds(start, 4 * HOUR) == start + timedelta(hours=4)


# --------------------------------------------------------------------- pausas
class TestPauses:
    def test_merge_overlapping_and_drops_empty(self):
        a = Pause(art(2026, 3, 11, 10), art(2026, 3, 11, 11))
        b = Pause(art(2026, 3, 11, 10, 30), art(2026, 3, 11, 12))
        empty = Pause(art(2026, 3, 11, 13), art(2026, 3, 11, 13))
        assert merge_pauses([b, empty, a]) == [Pause(art(2026, 3, 11, 10), art(2026, 3, 11, 12))]

    def test_open_pause_absorbs_later_ones(self):
        open_pause = Pause(art(2026, 3, 11, 10))
        later = Pause(art(2026, 3, 11, 12), art(2026, 3, 11, 13))
        assert merge_pauses([later, open_pause]) == [open_pause]

    def test_elapsed_discounts_pause(self, cal):
        pauses = [Pause(art(2026, 3, 11, 11), art(2026, 3, 11, 13))]
        elapsed = elapsed_business_seconds(cal, art(2026, 3, 11, 10), art(2026, 3, 11, 15), pauses)
        assert elapsed == 3 * HOUR

    def test_overlapping_pauses_not_discounted_twice(self, cal):
        pauses = [
            Pause(art(2026, 3, 11, 11), art(2026, 3, 11, 13)),
            Pause(art(2026, 3, 11, 12), art(2026, 3, 11, 14)),
        ]
        elapsed = elapsed_business_seconds(cal, art(2026, 3, 11, 10), art(2026, 3, 11, 15), pauses)
        assert elapsed == 2 * HOUR

    def test_pause_over_night_only_discounts_business_time(self, cal):
        # pausa mié 17:00 → jue 10:00 descuenta 2h hábiles
        pauses = [Pause(art(2026, 3, 11, 17), art(2026, 3, 12, 10))]
        elapsed = elapsed_business_seconds(cal, art(2026, 3, 11, 9), art(2026, 3, 12, 12), pauses)
        assert elapsed == (9 + 3 - 2) * HOUR

    def test_open_pause_freezes_elapsed(self, cal):
        pauses = [Pause(art(2026, 3, 11, 11))]
        elapsed = elapsed_business_seconds(cal, art(2026, 3, 11, 10), art(2026, 3, 13, 15), pauses)
        assert elapsed == HOUR

    def test_due_at_is_pushed_by_pause(self, cal):
        pauses = [Pause(art(2026, 3, 11, 11), art(2026, 3, 11, 14))]
        due = compute_due_at(cal, art(2026, 3, 11, 10), 4 * HOUR, pauses)
        assert due == art(2026, 3, 11, 17)

    def test_pause_after_due_does_not_move_due(self, cal):
        pauses = [Pause(art(2026, 3, 11, 15), art(2026, 3, 11, 17))]
        assert compute_due_at(cal, art(2026, 3, 11, 10), 2 * HOUR, pauses) == art(2026, 3, 11, 12)

    def test_due_unknown_while_paused(self, cal):
        pauses = [Pause(art(2026, 3, 11, 11))]
        assert compute_due_at(cal, art(2026, 3, 11, 10), 4 * HOUR, pauses) is None

    def test_pause_before_start_is_ignored(self, cal):
        pauses = [Pause(art(2026, 3, 10, 10), art(2026, 3, 10, 12))]
        assert compute_due_at(cal, art(2026, 3, 11, 10), HOUR, pauses) == art(2026, 3, 11, 11)


# --------------------------------------------------------------- evaluate_sla
class TestEvaluateSla:
    start = art(2026, 3, 11, 10)

    def test_running_green(self, cal):
        status = evaluate_sla(cal, self.start, 4 * HOUR, now=art(2026, 3, 11, 11))
        assert status.state == SlaState.EN_CURSO
        assert status.percent == 0.25
        assert status.remaining_seconds == 3 * HOUR
        assert status.due_at == art(2026, 3, 11, 14)

    def test_warning_at_75_percent(self, cal):
        status = evaluate_sla(cal, self.start, 4 * HOUR, now=art(2026, 3, 11, 13))
        assert status.state == SlaState.ADVERTENCIA

    def test_custom_threshold(self, cal):
        status = evaluate_sla(
            cal, self.start, 4 * HOUR, now=art(2026, 3, 11, 13), warning_threshold=0.9
        )
        assert status.state == SlaState.EN_CURSO

    def test_exactly_on_target_is_not_breached(self, cal):
        status = evaluate_sla(cal, self.start, 4 * HOUR, now=art(2026, 3, 11, 14))
        assert not status.breached

    def test_breached(self, cal):
        status = evaluate_sla(cal, self.start, 4 * HOUR, now=art(2026, 3, 11, 14, 1))
        assert status.state == SlaState.INCUMPLIDO
        assert status.breached
        assert status.remaining_seconds == -60

    def test_weekend_does_not_breach(self, cal):
        # viernes 17:00 con 2h de objetivo: el sábado sigue en 50%
        status = evaluate_sla(cal, art(2026, 3, 13, 17), 2 * HOUR, now=art(2026, 3, 14, 20))
        assert status.percent == 0.5
        assert status.state == SlaState.EN_CURSO

    def test_paused_state(self, cal):
        pauses = [Pause(art(2026, 3, 11, 11))]
        status = evaluate_sla(cal, self.start, 2 * HOUR, now=art(2026, 3, 12, 17), pauses=pauses)
        assert status.state == SlaState.PAUSADO
        assert status.paused
        assert status.due_at is None
        assert status.elapsed_seconds == HOUR

    def test_stopped_in_time(self, cal):
        status = evaluate_sla(
            cal, self.start, 4 * HOUR, now=art(2026, 3, 20, 10), stopped_at=art(2026, 3, 11, 12)
        )
        assert status.state == SlaState.CUMPLIDO
        assert status.stopped
        assert not status.breached

    def test_stopped_late(self, cal):
        status = evaluate_sla(
            cal, self.start, 4 * HOUR, now=art(2026, 3, 20, 10), stopped_at=art(2026, 3, 12, 12)
        )
        assert status.state == SlaState.INCUMPLIDO

    def test_target_must_be_positive(self, cal):
        with pytest.raises(ValueError):
            evaluate_sla(cal, self.start, 0, now=self.start)
