from pathlib import Path

from pydantic import BaseModel


class CoveredSymbol(BaseModel):
    name: str
    file_path: Path
    line_start: int
    line_end: int
    covered_lines: int
    total_lines: int

    @property
    def coverage_pct(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return round(self.covered_lines / self.total_lines * 100, 1)


class TestFile(BaseModel):
    path: Path
    test_count: int = 0
    language: str = "unknown"


class CoverageResult(BaseModel):
    overall_pct: float
    covered_lines: int
    total_lines: int
    test_files: list[TestFile] = []
    symbols: list[CoveredSymbol] = []
    report_source: str = "unknown"


class TestMatch(BaseModel):
    function_name: str
    test_names: list[str] = []


class TestMatchReport(BaseModel):
    """Name-based mapping of test functions to the business function they
    most likely test — approximate (substring match on the TestXxx name
    with the "Test" prefix stripped), not derived from an actual coverage
    report. `unmatched_tests` are tests that didn't match any known public
    function by name (generic/integration tests, suite setup, etc.)."""
    matches: list[TestMatch] = []
    unmatched_tests: list[str] = []
    total_function_count: int = 0

    @property
    def covered_function_count(self) -> int:
        return len(self.matches)

    @property
    def coverage_pct(self) -> float:
        if self.total_function_count == 0:
            return 0.0
        return round(self.covered_function_count / self.total_function_count * 100, 1)
