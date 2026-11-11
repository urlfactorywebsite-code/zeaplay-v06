"""Isolated deterministic entitlement tests; no ORM session or database."""

from datetime import date, datetime, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace as Row

import pytest

from backend.app.models import TaskPriorityEnum
from backend.app.services.subtask_rewards import POLICY, calculate

UTC = timezone.utc
POINTS = {"base": 30, "beforeDueBonus": 15, "overduePenalty": -15}
DATA = {"algorithm": POLICY, "bonus_enabled": True, "penalty_enabled": True}
TASK = Row(assigned_to_id="user", priority=TaskPriorityEnum.HIGH, team="Other")


def child(key, **values):
    return Row(
        **{
            "id": key,
            "point_policy_version": POLICY,
            "created_at": datetime(2026, 11, 2, tzinfo=UTC),
            "deleted_at": None,
            "completed": True,
            "planned_end_date": date(2026, 11, 2),
            "reward_timezone": "UTC",
            "actual_end_at": datetime(2026, 11, 2, 12, tzinfo=UTC),
            **values,
        }
    )


def run(rows, *, points=POINTS, data=DATA):
    return calculate(TASK, rows, points=points, policy_data=data, rule_revision=1)


@pytest.mark.parametrize("count", [1, 2, 3, 5, 100])
def test_capacity_and_earned_without_database(count):
    rows = [child(f"child-{i:03}") for i in range(count)]
    desired, inputs, ordinal, _ = run(list(reversed(rows)))
    assert sum(desired.values()) == (count - 1) * 45
    assert sum(v for key, v in desired.items() if key[2] == "BASE") == (count - 1) * 30
    assert not any(key[0] == rows[0].id for key in desired)
    assert ordinal[rows[0].id] == 1 and len(inputs) == count


def test_input_permutations_and_legacy_never_change_entitlement_or_output_order():
    rows = [
        child("c"),
        child("b"),
        child("a"),
        child("legacy", point_policy_version="legacy", created_at=None),
    ]
    expected = run(rows)
    for ordering in permutations(rows):
        actual = run(ordering)
        assert actual == expected
        assert list(actual[0]) == list(expected[0])
        assert list(actual[1]) == list(expected[1])
    assert "legacy" not in expected[1]


def test_deleted_first_and_completed_order_are_independent():
    rows = [
        child("a", deleted_at=datetime(2026, 11, 3, tzinfo=UTC)),
        child("b", completed=False),
        child("c"),
    ]
    desired, _, ordinal, _ = run(rows)
    assert ordinal == {"b": 1, "c": 2}
    assert desired == {("c", "user", "BASE"): 30, ("c", "user", "BONUS"): 15}


@pytest.mark.parametrize(
    "day,deadline",
    [
        (date(2026, 3, 8), datetime(2026, 3, 9, 3, 59, 59, 999999, UTC)),
        (date(2026, 11, 1), datetime(2026, 11, 2, 4, 59, 59, 999999, UTC)),
    ],
)
def test_dst_day_end_and_exact_boundary(day, deadline):
    rows = [
        child("a"),
        child(
            "b",
            planned_end_date=day,
            reward_timezone="America/New_York",
            actual_end_at=deadline,
        ),
    ]
    desired, inputs, _, _ = run(rows)
    assert desired[("b", "user", "BONUS")] == 15
    assert inputs["b"]["deadline"] == deadline.isoformat()
    rows[1].actual_end_at += timedelta(microseconds=1)
    desired, *_ = run(rows)
    assert desired[("b", "user", "PENALTY")] == -15


def test_penalty_can_exceed_base_and_zero_base_never_posts_bonus_or_penalty():
    rows = [child("a"), child("b", actual_end_at=datetime(2026, 11, 3, tzinfo=UTC))]
    desired, *_ = run(rows, points={**POINTS, "overduePenalty": -100})
    assert sum(desired.values()) == -70  # no invented balance or penalty cap
    assert run(rows, points={**POINTS, "base": 0})[0] == {}


def test_eligibility_flags_only_change_the_selected_component():
    rows = [child("a"), child("b")]
    assert run(rows, data={**DATA, "bonus_enabled": False})[0] == {
        ("b", "user", "BASE"): 30
    }
