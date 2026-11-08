"""The benchmark: small, self-contained bugs for the agent to fix.

Each task is a tiny repository (source + visible tests), a bug report, a set of
HIDDEN tests and a reference fix.

- The agent sees only the visible tests.
- After the agent has finished, the hidden tests are added and run. A fix that
  passes the visible tests but fails the hidden ones is counted as an INCORRECT
  fix: it fooled the tests the agent could see, but the bug is not really fixed.
- The reference fix is never shown to the agent. It is used by `codefix bench-check`
  to prove each task is valid: the bug is real, and a correct fix passes every test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Task:
    id: str
    difficulty: str          # easy | medium | hard
    issue: str               # the bug report the agent receives
    files: dict[str, str]    # visible repo: path -> content
    hidden_tests: str        # content of tests/test_hidden.py, added after the agent finishes
    fix_file: str            # reference fix (never shown to the agent)
    fix_function: str
    fix_code: str
    note: str = ""           # what makes this task interesting


TASKS: list[Task] = [
    # ------------------------------------------------------------------ easy
    Task(
        id="average_empty",
        difficulty="easy",
        issue="average([]) crashes with ZeroDivisionError. It should return 0 for an empty list.",
        files={
            "stats.py": '''def average(values):
    """Return the mean of a list of numbers. An empty list returns 0."""
    return sum(values) / len(values)
''',
            "tests/test_stats.py": '''from stats import average


def test_average():
    assert average([2, 4]) == 3


def test_average_empty():
    assert average([]) == 0
''',
        },
        hidden_tests='''from stats import average


def test_single_value():
    assert average([5]) == 5


def test_fractional_mean():
    assert average([1, 2, 3, 4]) == 2.5
''',
        fix_file="stats.py",
        fix_function="average",
        fix_code='''def average(values):
    """Return the mean of a list of numbers. An empty list returns 0."""
    if not values:
        return 0
    return sum(values) / len(values)
''',
        note="Missing guard for an empty input.",
    ),
    Task(
        id="clamp_order",
        difficulty="easy",
        issue="clamp(5, 0, 10) returns 10. A value already inside the range should come back unchanged.",
        files={
            "limits.py": '''def clamp(value, low, high):
    """Limit value to the range [low, high]."""
    return max(high, min(low, value))
''',
            "tests/test_limits.py": '''from limits import clamp


def test_inside_range():
    assert clamp(5, 0, 10) == 5


def test_below_range():
    assert clamp(-5, 0, 10) == 0


def test_above_range():
    assert clamp(15, 0, 10) == 10
''',
        },
        hidden_tests='''from limits import clamp


def test_edges():
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10


def test_floats():
    assert clamp(3.5, 1, 2) == 2
''',
        fix_file="limits.py",
        fix_function="clamp",
        fix_code='''def clamp(value, low, high):
    """Limit value to the range [low, high]."""
    return max(low, min(high, value))
''',
        note="min and max arguments swapped.",
    ),
    Task(
        id="range_inclusive",
        difficulty="easy",
        issue="numbers_between(1, 3) returns [1, 2]. The end value 3 is missing.",
        files={
            "ranges.py": '''def numbers_between(start, end):
    """Return the list of integers from start to end, including both ends."""
    return list(range(start, end))
''',
            "tests/test_ranges.py": '''from ranges import numbers_between


def test_includes_end():
    assert numbers_between(1, 3) == [1, 2, 3]
''',
        },
        hidden_tests='''from ranges import numbers_between


def test_single_number():
    assert numbers_between(5, 5) == [5]


def test_negative_start():
    assert numbers_between(-1, 1) == [-1, 0, 1]
''',
        fix_file="ranges.py",
        fix_function="numbers_between",
        fix_code='''def numbers_between(start, end):
    """Return the list of integers from start to end, including both ends."""
    return list(range(start, end + 1))
''',
        note="Classic off-by-one with range().",
    ),
    Task(
        id="split_bill",
        difficulty="easy",
        issue="split_bill(100, 3) gives 33.0 instead of 33.33.",
        files={
            "bills.py": '''def split_bill(total, people):
    """Split a bill evenly. Returns each person's share rounded to 2 decimals."""
    return round(total // people, 2)
''',
            "tests/test_bills.py": '''from bills import split_bill


def test_uneven_split():
    assert split_bill(100, 3) == 33.33


def test_even_split():
    assert split_bill(90, 3) == 30
''',
        },
        hidden_tests='''from bills import split_bill


def test_small_amounts():
    assert split_bill(10, 4) == 2.5
    assert split_bill(0.99, 3) == 0.33
''',
        fix_file="bills.py",
        fix_function="split_bill",
        fix_code='''def split_bill(total, people):
    """Split a bill evenly. Returns each person's share rounded to 2 decimals."""
    return round(total / people, 2)
''',
        note="Floor division (//) instead of true division (/).",
    ),
    Task(
        id="find_first",
        difficulty="easy",
        issue="find_first(['a', 'b'], 'a') returns -1 even though 'a' is in the list.",
        files={
            "search.py": '''def find_first(items, target):
    """Return the position of the first occurrence of target in items, or -1."""
    for i in range(1, len(items)):
        if items[i] == target:
            return i
    return -1
''',
            "tests/test_search.py": '''from search import find_first


def test_first_item():
    assert find_first(["a", "b"], "a") == 0


def test_missing():
    assert find_first(["a", "b"], "z") == -1
''',
        },
        hidden_tests='''from search import find_first


def test_empty():
    assert find_first([], "x") == -1


def test_first_of_duplicates():
    assert find_first(["x", "y", "x"], "x") == 0


def test_last_item():
    assert find_first(["a", "b"], "b") == 1
''',
        fix_file="search.py",
        fix_function="find_first",
        fix_code='''def find_first(items, target):
    """Return the position of the first occurrence of target in items, or -1."""
    for i in range(len(items)):
        if items[i] == target:
            return i
    return -1
''',
        note="Loop starts at 1 and skips the first element.",
    ),
    # ---------------------------------------------------------------- medium
    Task(
        id="leap_year",
        difficulty="medium",
        issue="is_leap_year(2000) returns False, but 2000 was a leap year.",
        files={
            "dates.py": '''def is_leap_year(year):
    """Gregorian calendar leap year rule."""
    return year % 4 == 0 and year % 100 != 0
''',
            "tests/test_dates.py": '''from dates import is_leap_year


def test_ordinary_leap_year():
    assert is_leap_year(2024) is True


def test_ordinary_year():
    assert is_leap_year(2023) is False


def test_year_2000():
    assert is_leap_year(2000) is True
''',
        },
        hidden_tests='''from dates import is_leap_year


def test_century_rules():
    assert is_leap_year(1900) is False
    assert is_leap_year(2100) is False
    assert is_leap_year(2400) is True
''',
        fix_file="dates.py",
        fix_function="is_leap_year",
        fix_code='''def is_leap_year(year):
    """Gregorian calendar leap year rule."""
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
''',
        note="Incomplete rule. A fix like `or year == 2000` passes the visible tests but not the hidden ones.",
    ),
    Task(
        id="mutable_default",
        difficulty="medium",
        issue="add_tag('a') followed by add_tag('b') returns ['a', 'b'] on the second call. Each call without a list should start from an empty list.",
        files={
            "tags.py": '''def add_tag(tag, tags=[]):
    """Return a new list containing the existing tags plus `tag`."""
    tags.append(tag)
    return tags
''',
            "tests/test_tags.py": '''from tags import add_tag


def test_calls_do_not_share_state():
    assert add_tag("a") == ["a"]
    assert add_tag("b") == ["b"]


def test_with_existing_tags():
    assert add_tag("x", ["y"]) == ["y", "x"]
''',
        },
        hidden_tests='''from tags import add_tag


def test_input_list_is_not_changed():
    original = ["y"]
    add_tag("x", original)
    assert original == ["y"]
''',
        fix_file="tags.py",
        fix_function="add_tag",
        fix_code='''def add_tag(tag, tags=None):
    """Return a new list containing the existing tags plus `tag`."""
    return list(tags or []) + [tag]
''',
        note="Mutable default argument. The docstring promises a NEW list; the hidden test checks that.",
    ),
    Task(
        id="initials_spaces",
        difficulty="medium",
        issue="initials('ada  lovelace') crashes with IndexError when there are two spaces between the words.",
        files={
            "names.py": '''def initials(full_name):
    """Return the initials of a name in upper case, e.g. "ada lovelace" -> "AL"."""
    return "".join(part[0] for part in full_name.split(" ")).upper()
''',
            "tests/test_names.py": '''from names import initials


def test_simple():
    assert initials("ada lovelace") == "AL"


def test_double_space():
    assert initials("ada  lovelace") == "AL"
''',
        },
        hidden_tests='''from names import initials


def test_leading_and_trailing_spaces():
    assert initials(" grace hopper ") == "GH"


def test_three_names():
    assert initials("alan mathison turing") == "AMT"
''',
        fix_file="names.py",
        fix_function="initials",
        fix_code='''def initials(full_name):
    """Return the initials of a name in upper case, e.g. "ada lovelace" -> "AL"."""
    return "".join(part[0] for part in full_name.split()).upper()
''',
        note="split(' ') produces empty strings.",
    ),
    Task(
        id="withdraw_full_balance",
        difficulty="medium",
        issue="With 100 in the account, withdraw(100) raises 'insufficient funds'. Taking out the whole balance should be allowed.",
        files={
            "bank.py": '''class Account:
    def __init__(self, balance=0):
        self.balance = balance

    def deposit(self, amount):
        """Add money. Raise ValueError for amounts that are not positive."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        self.balance += amount

    def withdraw(self, amount):
        """Take money out. Raise ValueError if the balance would become negative."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        if amount >= self.balance:
            raise ValueError("insufficient funds")
        self.balance -= amount
''',
            "tests/test_bank.py": '''import pytest

from bank import Account


def test_withdraw_whole_balance():
    acct = Account(100)
    acct.withdraw(100)
    assert acct.balance == 0


def test_overdraft_refused():
    acct = Account(100)
    with pytest.raises(ValueError):
        acct.withdraw(150)


def test_deposit():
    acct = Account()
    acct.deposit(20)
    assert acct.balance == 20
''',
        },
        hidden_tests='''import pytest

from bank import Account


def test_partial_withdraw():
    acct = Account(100)
    acct.withdraw(30)
    assert acct.balance == 70


def test_just_over_balance_refused():
    acct = Account(100)
    with pytest.raises(ValueError):
        acct.withdraw(100.01)
''',
        fix_file="bank.py",
        fix_function="Account.withdraw",
        fix_code='''def withdraw(self, amount):
    """Take money out. Raise ValueError if the balance would become negative."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    if amount > self.balance:
        raise ValueError("insufficient funds")
    self.balance -= amount
''',
        note="A method inside a class: the patch must be re-indented.",
    ),
    Task(
        id="sort_by_age",
        difficulty="medium",
        issue="sort_by_age puts people in alphabetical order by name instead of ordering them by age.",
        files={
            "people.py": '''def sort_by_age(people):
    """Return people sorted from youngest to oldest. Each person is a dict with "name" and "age"."""
    return sorted(people, key=lambda p: p["name"])
''',
            "tests/test_people.py": '''from people import sort_by_age


def test_sorted_by_age():
    people = [{"name": "ann", "age": 40}, {"name": "bob", "age": 25}]
    assert [p["name"] for p in sort_by_age(people)] == ["bob", "ann"]
''',
        },
        hidden_tests='''from people import sort_by_age


def test_ties_keep_original_order():
    people = [{"name": "zoe", "age": 30}, {"name": "amy", "age": 30}, {"name": "kid", "age": 5}]
    assert [p["name"] for p in sort_by_age(people)] == ["kid", "zoe", "amy"]


def test_input_not_changed():
    people = [{"name": "ann", "age": 40}, {"name": "bob", "age": 25}]
    sort_by_age(people)
    assert people[0]["name"] == "ann"
''',
        fix_file="people.py",
        fix_function="sort_by_age",
        fix_code='''def sort_by_age(people):
    """Return people sorted from youngest to oldest. Each person is a dict with "name" and "age"."""
    return sorted(people, key=lambda p: p["age"])
''',
        note="Wrong sort key. Hidden tests check ties and that the input is not modified.",
    ),
    Task(
        id="count_words_case",
        difficulty="medium",
        issue="count_words('The the THE') returns three separate entries. It should return {'the': 3}.",
        files={
            "words.py": '''def count_words(text):
    """Count how often each word appears, ignoring case. Returns a dict of lowercase words."""
    counts = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    return counts
''',
            "tests/test_words.py": '''from words import count_words


def test_ignores_case():
    assert count_words("The the THE") == {"the": 3}
''',
        },
        hidden_tests='''from words import count_words


def test_empty_text():
    assert count_words("") == {}


def test_mixed():
    assert count_words("a B a b c") == {"a": 2, "b": 2, "c": 1}
''',
        fix_file="words.py",
        fix_function="count_words",
        fix_code='''def count_words(text):
    """Count how often each word appears, ignoring case. Returns a dict of lowercase words."""
    counts = {}
    for word in text.split():
        word = word.lower()
        counts[word] = counts.get(word, 0) + 1
    return counts
''',
        note="Case normalisation missing.",
    ),
    Task(
        id="factorial_zero",
        difficulty="medium",
        issue="factorial(0) crashes with RecursionError. It should return 1.",
        files={
            "maths.py": '''def factorial(n):
    """Return n! for n >= 0."""
    if n == 1:
        return 1
    return n * factorial(n - 1)
''',
            "tests/test_maths.py": '''from maths import factorial


def test_zero():
    assert factorial(0) == 1


def test_five():
    assert factorial(5) == 120
''',
        },
        hidden_tests='''from maths import factorial


def test_one():
    assert factorial(1) == 1


def test_ten():
    assert factorial(10) == 3628800
''',
        fix_file="maths.py",
        fix_function="factorial",
        fix_code='''def factorial(n):
    """Return n! for n >= 0."""
    if n == 0:
        return 1
    return n * factorial(n - 1)
''',
        note="Wrong base case for recursion.",
    ),
    # ------------------------------------------------------------------ hard
    Task(
        id="running_total_vague",
        difficulty="hard",
        issue="The running totals report is shifted by one. For sales of 5, 3 and 2 it shows 0, 5, 8 but it should show 5, 8, 10.",
        files={
            "report.py": '''def format_money(amount):
    return f"{amount:,.2f}"


def top_n(items, n):
    return sorted(items, reverse=True)[:n]


def process(data):
    result = []
    total = 0
    for x in data:
        result.append(total)
        total += x
    return result
''',
            "tests/test_report.py": '''from report import format_money, process, top_n


def test_format_money():
    assert format_money(1234.5) == "1,234.50"


def test_top_n():
    assert top_n([3, 9, 1, 7], 2) == [9, 7]


def test_process():
    assert process([5, 3, 2]) == [5, 8, 10]
''',
        },
        hidden_tests='''from report import process


def test_empty():
    assert process([]) == []


def test_single_and_negative():
    assert process([1]) == [1]
    assert process([-1, 1]) == [-1, 0]
''',
        fix_file="report.py",
        fix_function="process",
        fix_code='''def process(data):
    result = []
    total = 0
    for x in data:
        total += x
        result.append(total)
    return result
''',
        note="No docstrings and a vague report: keyword search cannot find the function.",
    ),
    Task(
        id="price_helper",
        difficulty="hard",
        issue="order_total(['£1,234.50', '£5.00']) raises ValueError: could not convert string to float.",
        files={
            "prices.py": '''def parse_price(text):
    """Turn a price like "£1,234.50" into the number 1234.5."""
    return float(text.replace("£", "").replace(",", "."))


def order_total(price_texts):
    """Add up a list of prices like "£1,234.50"."""
    return round(sum(parse_price(t) for t in price_texts), 2)
''',
            "tests/test_prices.py": '''from prices import order_total, parse_price


def test_order_total_with_thousands():
    assert order_total(["£1,234.50", "£5.00"]) == 1239.5


def test_simple_price():
    assert parse_price("£5.00") == 5.0
''',
        },
        hidden_tests='''from prices import order_total, parse_price


def test_parse_thousands():
    assert parse_price("£2,000") == 2000.0
    assert parse_price("£1,234.50") == 1234.5


def test_total_of_simple_prices():
    assert order_total(["£1.10", "£2.20"]) == 3.3
''',
        fix_file="prices.py",
        fix_function="parse_price",
        fix_code='''def parse_price(text):
    """Turn a price like "£1,234.50" into the number 1234.5."""
    return float(text.replace("£", "").replace(",", ""))
''',
        note="The symptom appears in order_total but the bug is in the helper parse_price.",
    ),
    Task(
        id="median_two_bugs",
        difficulty="hard",
        issue="median([4, 1, 3, 2]) returns 3. For an even number of values it should be the average of the two middle values, 2.5.",
        files={
            "median.py": '''def median(values):
    """Return the median of a list of numbers. The input list is not modified."""
    values.sort()
    mid = len(values) // 2
    return values[mid]
''',
            "tests/test_median.py": '''from median import median


def test_odd_length():
    assert median([3, 1, 2]) == 2


def test_even_length():
    assert median([4, 1, 3, 2]) == 2.5
''',
        },
        hidden_tests='''from median import median


def test_input_not_modified():
    values = [3, 1, 2]
    median(values)
    assert values == [3, 1, 2]


def test_single_value():
    assert median([5]) == 5
''',
        fix_file="median.py",
        fix_function="median",
        fix_code='''def median(values):
    """Return the median of a list of numbers. The input list is not modified."""
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 0:
        return (ordered[mid - 1] + ordered[mid]) / 2
    return ordered[mid]
''',
        note="Two bugs, only one reported. The second (sorting the input in place) is only caught by a hidden test.",
    ),
]


def get_task(task_id: str) -> Task:
    for task in TASKS:
        if task.id == task_id:
            return task
    raise KeyError(f"No task called {task_id!r}")