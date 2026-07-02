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
