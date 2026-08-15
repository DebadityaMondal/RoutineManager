
generator.py
Here's the complete routine generation logic, broken down into layers:

Routine Generation Logic — Full Breakdown
1. Inputs (SchoolInputData)
Input	Purpose
subjects	List of all subject names
teachers	List of teachers with their teachable subjects
class_keys	List of classes like "Class 6 - A"
periods_per_day	Default periods (e.g., 6)
days	Working days list
day_periods	Override periods per specific day (e.g., Saturday: 4)
class_periods_per_day	Override periods per class (uses min(class, day))
first_period_subjects	Subjects preferred for period 1
class_subject_periods	Per-class weekly limits per subject; -1 = subject excluded
class_teachers	Class teacher → forces their subject in period 1 every day
max_teacher_periods_per_day	Soft max periods for one teacher in a day
avoid_consecutive	Soft: avoid same teacher back-to-back in a class
min_teacher_periods_per_day	Soft minimum per teacher (default 2)
min_teacher_periods_short_day	Minimum on short day (default 1)
short_day	Which day is short (default "Saturday")
2. Initialization
_build_subject_teacher_map()  →  {subject: [teachers who can teach it]}
_compute_ideal_loads()        →  ideal_weekly = total_slots / num_teachers
                                  ideal_daily  = ideal_weekly / num_days
3. Generation Flow (_try_generate)
1. Create empty routine grid (class × day × periods)
   - Each class gets its own period count per day: min(class_config, day_setting)

2. Pre-assign class teachers to Period 1 of every day
   - Hard fail if two class teachers conflict in same slot

3. For each day → for each period index:
   - Call _assign_slot(day, period_idx)
   - If any slot fails → retry entire generation (up to 500 attempts)
4. Slot Assignment (_assign_slot)
1. Collect teachers already busy in this time slot (across all classes)
2. Shuffle class order (randomize to avoid bias)
3. For each class needing this period:
   - Skip if already assigned (class teacher) or class doesn't have this period
   - Call _assign_one(class, day, period_idx, teachers_used)
5. Single Period Assignment (_assign_one)
1. Get candidate SUBJECTS for this class today:
   - Exclude N/A subjects (class_subject_periods == -1)
   - Exclude subjects at daily max
   - Exclude subjects at weekly limit
   - Sort by least-assigned-this-week (balance subjects)
   - For period 0: prefer first_period_subjects

2. Track today's teacher+subject combos for this class

3. For each candidate subject:
   a. Find available teachers (not busy in this slot across classes)
   b. HARD CONSTRAINT: remove teachers who already teach THIS subject
      in THIS class today (no same teacher+subject repeat)
   c. Call _select_best_teacher() on the filtered pool
   d. Assign and update counters
6. Teacher Selection Scoring (_select_best_teacher)
Each candidate teacher gets a score (lower = better):

Factor	Score Impact	Type
Below min daily periods	-30	Soft bonus
Weekly load above ideal	+10 per period above	Balance
Daily load above ideal	+5 per period above	Balance
Exceeds max_teacher_periods_per_day	+50	Soft penalty
Consecutive with previous period in class	+20	Soft penalty
Already appeared in this class today	+15	Soft penalty
Random tiebreaker	0 to 1	Anti-bias
Final pick: Sort by score, take candidates within 3 points of the best, randomly choose from them.

7. Constraint Summary
Constraint	Hard/Soft	Effect
No teacher in two classes at same time	Hard	Guaranteed
Same teacher+subject can't repeat in same class same day	Hard (fallback if impossible)	Almost always enforced
Class teacher gets period 1	Hard	Guaranteed
Subject excluded (N/A = -1)	Hard	Never assigned
Weekly subject limit per class	Hard	Capped
Load balancing (equal distribution)	Soft	Best-effort via scoring
Max teacher periods per day	Soft	Penalty-based
Avoid consecutive same teacher	Soft	Penalty-based
Min teacher periods per day (2 regular / 1 Saturday)	Soft	Bonus-based
Prefer different teachers in same class daily	Soft	Penalty-based
First period subject preference	Soft	Ordering-based
8. Retry Logic
If any slot can't be filled (all teachers busy, no valid subjects), the entire attempt fails and a new one starts from scratch with different random orderings. Up to 500 attempts. This randomized-restart approach handles edge cases that a single greedy pass might get stuck on.