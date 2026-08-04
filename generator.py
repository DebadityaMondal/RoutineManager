"""Routine generation engine with conflict-free scheduling and load balancing."""

import random
from dataclasses import dataclass, field


@dataclass
class TeacherData:
    name: str
    subjects: list[str] = field(default_factory=list)


@dataclass
class Period:
    subject: str
    teacher: str


@dataclass
class SchoolInputData:
    """Plain data class used by the generator (decoupled from DB models)."""
    subjects: list[str] = field(default_factory=list)
    teachers: list[TeacherData] = field(default_factory=list)
    class_keys: list[str] = field(default_factory=list)
    periods_per_day: int = 6
    days: list[str] = field(default_factory=lambda: [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"
    ])
    day_periods: dict[str, int] = field(default_factory=dict)
    first_period_subjects: list[str] = field(default_factory=list)
    class_subject_periods: dict[str, dict[str, int]] = field(default_factory=dict)
    class_teachers: dict[str, dict[str, str]] = field(default_factory=dict)
    max_teacher_periods_per_day: int = 0
    avoid_consecutive: bool = False
    # Class-specific periods per day: {class_key: periods}
    class_periods_per_day: dict[str, int] = field(default_factory=dict)
    # Min periods per teacher per day (soft): ensures each teacher gets at least this many
    # On short days (like Saturday), use min_teacher_periods_short_day
    min_teacher_periods_per_day: int = 2
    min_teacher_periods_short_day: int = 1
    short_day: str = "Saturday"

    def get_periods_for_day(self, day: str) -> int:
        """Get the schedule-level periods for a day."""
        return self.day_periods.get(day, self.periods_per_day)

    def get_periods_for_class_day(self, class_key: str, day: str) -> int:
        """Get effective periods for a class on a day (min of class config and day settings)."""
        day_setting = self.get_periods_for_day(day)
        class_setting = self.class_periods_per_day.get(class_key, 0)
        if class_setting > 0:
            return min(class_setting, day_setting)
        return day_setting

    def has_tiffin(self, day: str) -> bool:
        return self.get_periods_for_day(day) > 4


class RoutineGenerator:
    """Generates a class-wise weekly routine with load-balanced teacher assignments."""

    def __init__(self, data: SchoolInputData):
        self.data = data
        self.routine: dict[str, dict[str, list[Period | None]]] = {}
        self._build_subject_teacher_map()
        self._compute_ideal_loads()

    def _build_subject_teacher_map(self):
        self.subject_teachers: dict[str, list[TeacherData]] = {}
        for subject in self.data.subjects:
            self.subject_teachers[subject] = [
                t for t in self.data.teachers if subject in t.subjects
            ]

    def _compute_ideal_loads(self):
        """Compute target weekly load per teacher for balanced distribution."""
        total_slots = 0
        for day in self.data.days:
            for class_key in self.data.class_keys:
                total_slots += self.data.get_periods_for_class_day(class_key, day)

        num_teachers = len(self.data.teachers)
        if num_teachers > 0:
            self.ideal_weekly = total_slots / num_teachers
            self.ideal_daily = self.ideal_weekly / len(self.data.days) if self.data.days else 0
        else:
            self.ideal_weekly = 0
            self.ideal_daily = 0

    def generate(self, max_attempts: int = 500) -> bool:
        for _ in range(max_attempts):
            if self._try_generate():
                return True
        return False

    def _try_generate(self) -> bool:
        self.routine = {}
        # Running counters for efficient load tracking
        self.teacher_weekly_count: dict[str, int] = {t.name: 0 for t in self.data.teachers}
        self.teacher_daily_count: dict[str, dict[str, int]] = {
            t.name: {d: 0 for d in self.data.days} for t in self.data.teachers
        }

        for key in self.data.class_keys:
            self.routine[key] = {}
            for day in self.data.days:
                num_periods = self.data.get_periods_for_class_day(key, day)
                self.routine[key][day] = [None] * num_periods

        # Pre-assign class teachers to first period of every day
        if self.data.class_teachers:
            for day in self.data.days:
                teachers_used: set[str] = set()
                for class_key in self.data.class_keys:
                    ct = self.data.class_teachers.get(class_key)
                    if ct:
                        if ct["teacher"] in teachers_used:
                            return False
                        teachers_used.add(ct["teacher"])
                        self.routine[class_key][day][0] = Period(
                            subject=ct["subject"], teacher=ct["teacher"]
                        )
                        self.teacher_weekly_count[ct["teacher"]] += 1
                        self.teacher_daily_count[ct["teacher"]][day] += 1

        for day in self.data.days:
            num_periods = self.data.get_periods_for_day(day)
            for period_idx in range(num_periods):
                if not self._assign_slot(day, period_idx):
                    return False
        return True

    def _assign_slot(self, day: str, period_idx: int) -> bool:
        teachers_used: set[str] = set()

        for class_key in self.data.class_keys:
            # Skip if this class has fewer periods than period_idx
            if period_idx >= len(self.routine[class_key][day]):
                continue
            existing = self.routine[class_key][day][period_idx]
            if existing:
                teachers_used.add(existing.teacher)

        order = list(range(len(self.data.class_keys)))
        random.shuffle(order)

        for idx in order:
            class_key = self.data.class_keys[idx]
            # Skip if this class doesn't have this period
            if period_idx >= len(self.routine[class_key][day]):
                continue
            if self.routine[class_key][day][period_idx] is not None:
                continue
            if not self._assign_one(class_key, day, period_idx, teachers_used):
                return False
        return True

    def _assign_one(self, class_key: str, day: str, period_idx: int,
                    teachers_used: set[str]) -> bool:
        candidates = self._ranked_subjects(class_key, day)

        if period_idx == 0 and self.data.first_period_subjects:
            preferred = [s for s in candidates if s in self.data.first_period_subjects]
            non_preferred = [s for s in candidates if s not in self.data.first_period_subjects]
            random.shuffle(preferred)
            random.shuffle(non_preferred)
            candidates = preferred + non_preferred
        else:
            random.shuffle(candidates)
            weekly_count = self._weekly_subject_count(class_key)
            candidates.sort(key=lambda s: weekly_count.get(s, 0))

        for subject in candidates:
            available = [
                t for t in self.subject_teachers.get(subject, [])
                if t.name not in teachers_used
            ]
            if not available:
                continue

            teacher = self._select_best_teacher(available, class_key, day, period_idx)
            self.routine[class_key][day][period_idx] = Period(
                subject=subject, teacher=teacher.name
            )
            teachers_used.add(teacher.name)
            self.teacher_weekly_count[teacher.name] += 1
            self.teacher_daily_count[teacher.name][day] += 1
            return True
        return False

    def _select_best_teacher(self, available: list[TeacherData],
                             class_key: str, day: str, period_idx: int) -> TeacherData:
        """Select the best teacher using a scoring system for load balance."""
        if len(available) == 1:
            return available[0]

        # Determine min periods target for today
        if day.lower() == self.data.short_day.lower():
            min_target = self.data.min_teacher_periods_short_day
        else:
            min_target = self.data.min_teacher_periods_per_day

        scored: list[tuple[float, TeacherData]] = []

        for t in available:
            score = 0.0
            weekly = self.teacher_weekly_count[t.name]
            daily = self.teacher_daily_count[t.name][day]

            # Strong bonus for teachers below their minimum daily periods
            # This ensures everyone gets at least the minimum
            if daily < min_target:
                score -= 30  # big bonus (lower score = preferred)

            # Primary: weekly load deviation from ideal (lower is better)
            weekly_deviation = weekly - self.ideal_weekly
            score += weekly_deviation * 10

            # Secondary: daily load deviation (spread across days)
            daily_deviation = daily - self.ideal_daily
            score += daily_deviation * 5

            # Soft constraint: max periods per day
            if self.data.max_teacher_periods_per_day > 0:
                if daily >= self.data.max_teacher_periods_per_day:
                    score += 50

            # Soft constraint: avoid consecutive same teacher in same class
            if self.data.avoid_consecutive and period_idx > 0:
                prev = self.routine[class_key][day][period_idx - 1]
                if prev and prev.teacher == t.name:
                    score += 20

            # Small random tiebreaker to avoid deterministic bias
            score += random.uniform(0, 1)

            scored.append((score, t))

        # Sort ascending (lowest score = best candidate)
        scored.sort(key=lambda x: x[0])

        # Pick from the top candidates (within a small margin of the best)
        best_score = scored[0][0]
        top_candidates = [t for s, t in scored if s <= best_score + 3]

        return random.choice(top_candidates)

    def _ranked_subjects(self, class_key: str, day: str) -> list[str]:
        num_periods = self.data.get_periods_for_day(day)
        today_count: dict[str, int] = {}
        for period in self.routine[class_key][day]:
            if period:
                today_count[period.subject] = today_count.get(period.subject, 0) + 1

        max_per_day = max(2, num_periods // len(self.data.subjects) + 1)

        weekly_count = self._weekly_subject_count(class_key)
        class_limits = self.data.class_subject_periods.get(class_key, {})

        candidates = []
        for s in self.data.subjects:
            if class_limits and s in class_limits:
                if class_limits[s] == -1:
                    continue
            if today_count.get(s, 0) >= max_per_day:
                continue
            if not self.subject_teachers.get(s):
                continue
            if class_limits and s in class_limits and class_limits[s] > 0:
                if weekly_count.get(s, 0) >= class_limits[s]:
                    continue
            candidates.append(s)

        return candidates

    def _weekly_subject_count(self, class_key: str) -> dict[str, int]:
        count: dict[str, int] = {}
        for day in self.data.days:
            for period in self.routine[class_key][day]:
                if period:
                    count[period.subject] = count.get(period.subject, 0) + 1
        return count

    def get_routine_dict(self) -> dict:
        """Return routine as a plain dict (JSON-serializable)."""
        result = {}
        for class_key, schedule in self.routine.items():
            result[class_key] = {}
            for day, periods in schedule.items():
                result[class_key][day] = [
                    {"subject": p.subject, "teacher": p.teacher} if p else None
                    for p in periods
                ]
        return result
