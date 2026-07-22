"""Routine generation engine with conflict-free scheduling."""

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
    # Optional: class-wise subject period limits
    # {class_key: {subject_name: periods_per_week}}
    class_subject_periods: dict[str, dict[str, int]] = field(default_factory=dict)
    # Optional: class teacher mapping
    # {class_key: {"teacher": name, "subject": name}}
    class_teachers: dict[str, dict[str, str]] = field(default_factory=dict)
    # Optional: max periods a teacher can take per day (0 = no limit)
    max_teacher_periods_per_day: int = 0
    # Optional: try to avoid same teacher in consecutive periods for a class
    avoid_consecutive: bool = False

    def get_periods_for_day(self, day: str) -> int:
        return self.day_periods.get(day, self.periods_per_day)

    def has_tiffin(self, day: str) -> bool:
        return self.get_periods_for_day(day) > 4


class RoutineGenerator:
    """Generates a class-wise weekly routine ensuring no teacher conflicts."""

    def __init__(self, data: SchoolInputData):
        self.data = data
        self.routine: dict[str, dict[str, list[Period | None]]] = {}
        self._build_subject_teacher_map()

    def _build_subject_teacher_map(self):
        self.subject_teachers: dict[str, list[TeacherData]] = {}
        for subject in self.data.subjects:
            self.subject_teachers[subject] = [
                t for t in self.data.teachers if subject in t.subjects
            ]

    def generate(self, max_attempts: int = 500) -> bool:
        for _ in range(max_attempts):
            if self._try_generate():
                return True
        return False

    def _try_generate(self) -> bool:
        self.routine = {}
        for key in self.data.class_keys:
            self.routine[key] = {}
            for day in self.data.days:
                num_periods = self.data.get_periods_for_day(day)
                self.routine[key][day] = [None] * num_periods

        # Pre-assign class teachers to first period of every day
        if self.data.class_teachers:
            for day in self.data.days:
                # Check for teacher conflicts in first period across classes
                teachers_used: set[str] = set()
                for class_key in self.data.class_keys:
                    ct = self.data.class_teachers.get(class_key)
                    if ct:
                        if ct["teacher"] in teachers_used:
                            # Conflict: same teacher is class teacher for multiple classes
                            return False
                        teachers_used.add(ct["teacher"])
                        self.routine[class_key][day][0] = Period(
                            subject=ct["subject"], teacher=ct["teacher"]
                        )

        for day in self.data.days:
            num_periods = self.data.get_periods_for_day(day)
            for period_idx in range(num_periods):
                if not self._assign_slot(day, period_idx):
                    return False
        return True

    def _assign_slot(self, day: str, period_idx: int) -> bool:
        teachers_used: set[str] = set()

        # Collect teachers already assigned in this slot (e.g. class teachers)
        for class_key in self.data.class_keys:
            existing = self.routine[class_key][day][period_idx]
            if existing:
                teachers_used.add(existing.teacher)

        order = list(range(len(self.data.class_keys)))
        random.shuffle(order)

        for idx in order:
            class_key = self.data.class_keys[idx]
            # Skip if already assigned (class teacher pre-assignment)
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

            # Apply soft constraints: prefer teachers that satisfy them
            preferred_teachers = self._filter_soft_constraints(
                available, class_key, day, period_idx
            )

            # Use preferred if any exist, otherwise fall back to all available (soft = flexible)
            pick_from = preferred_teachers if preferred_teachers else available
            teacher = random.choice(pick_from)
            self.routine[class_key][day][period_idx] = Period(
                subject=subject, teacher=teacher.name
            )
            teachers_used.add(teacher.name)
            return True
        return False

    def _filter_soft_constraints(self, available: list[TeacherData],
                                 class_key: str, day: str, period_idx: int) -> list[TeacherData]:
        """Filter teachers by soft constraints. Returns subset that passes all; if none pass, caller uses full list."""
        result = available

        # Soft constraint 1: max periods per day
        if self.data.max_teacher_periods_per_day > 0:
            daily_counts = self._teacher_daily_count(day)
            limit = self.data.max_teacher_periods_per_day
            result = [t for t in result if daily_counts.get(t.name, 0) < limit]
            if not result:
                result = available  # ignore if too restrictive

        # Soft constraint 2: avoid consecutive periods for same teacher in same class
        if self.data.avoid_consecutive and period_idx > 0:
            prev_period = self.routine[class_key][day][period_idx - 1]
            if prev_period:
                prev_teacher = prev_period.teacher
                non_consecutive = [t for t in result if t.name != prev_teacher]
                if non_consecutive:
                    result = non_consecutive
                # If all are the same as previous, allow it (soft constraint)

        return result

    def _teacher_daily_count(self, day: str) -> dict[str, int]:
        """Count how many periods each teacher has on a given day across all classes."""
        count: dict[str, int] = {}
        for class_key in self.data.class_keys:
            for period in self.routine[class_key][day]:
                if period:
                    count[period.teacher] = count.get(period.teacher, 0) + 1
        return count

    def _ranked_subjects(self, class_key: str, day: str) -> list[str]:
        num_periods = self.data.get_periods_for_day(day)
        today_count: dict[str, int] = {}
        for period in self.routine[class_key][day]:
            if period:
                today_count[period.subject] = today_count.get(period.subject, 0) + 1

        max_per_day = max(2, num_periods // len(self.data.subjects) + 1)

        weekly_count = self._weekly_subject_count(class_key)

        # Get class-specific subject limits if configured
        class_limits = self.data.class_subject_periods.get(class_key, {})

        candidates = []
        for s in self.data.subjects:
            # Skip if marked as not applicable (-1) for this class
            if class_limits and s in class_limits:
                if class_limits[s] == -1:
                    continue
            # Skip if already hit daily max
            if today_count.get(s, 0) >= max_per_day:
                continue
            # Skip if no teacher available
            if not self.subject_teachers.get(s):
                continue
            # Skip if weekly limit reached for this class+subject
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
