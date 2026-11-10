"""Spreadsheet formula gate (§11).

Every generated workbook passes this gate before it ships: parenthesis
balance, a parse of every formula, and canonical single-sheet ranges.  The
gate exists because a shipped workbook once failed on one extra parenthesis
in 101 formulas and 200 non-canonical double-sheet ranges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

CELL_RE = re.compile(r"^\$?[A-Za-z]{1,3}\$?\d+$")
NAME_START = re.compile(r"[A-Za-z_\\]")
NAME_CHAR = re.compile(r"[A-Za-z0-9_.\\$]")


class FormulaError(ValueError):
    pass


@dataclass
class Token:
    kind: str
    value: str
    sheet: str | None = None
    pos: int = 0

    def __repr__(self):
        return f"{self.kind}({self.value!r})"


def _read_sheet(text: str, i: int) -> tuple[str, int]:
    """Read a sheet name at i.  Returns (name, next index)."""
    if text[i] == "'":
        j = i + 1
        out = []
        while j < len(text):
            if text[j] == "'":
                if j + 1 < len(text) and text[j + 1] == "'":
                    out.append("'")
                    j += 2
                    continue
                return "".join(out), j + 1
            out.append(text[j])
            j += 1
        raise FormulaError(f"unterminated sheet name at {i}")
    j = i
    while j < len(text) and (text[j].isalnum() or text[j] in "_. "):
        j += 1
    return text[i:j].strip(), j


def tokenize(formula: str) -> list[Token]:
    text = formula.strip()
    text = text.removeprefix("=")
    if not text:
        raise FormulaError("empty formula")
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise FormulaError(f"unterminated string at {i}")
            tokens.append(Token("STR", text[i : j + 1], pos=i))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            while j < n and (text[j].isdigit() or text[j] in ".eE+-"):
                if text[j] in "+-" and (j == i or text[j - 1] not in "eE"):
                    break
                j += 1
            tokens.append(Token("NUM", text[i:j], pos=i))
            i = j
            continue
        if ch == "'" or NAME_START.match(ch) or ch == "$":
            sheet = None
            start = i
            if ch == "'":
                sheet, i = _read_sheet(text, i)
                if i >= n or text[i] != "!":
                    raise FormulaError(f"sheet name without '!' at {start}")
                i += 1
                if i >= n:
                    raise FormulaError("formula ends after sheet name")
                start = i
            # read a name or a cell reference
            j = i
            if text[j] == "$":
                j += 1
            if j < n and text[j].isalpha():
                k = j
                while k < n and (text[k].isalnum() or text[k] in "_.$"):
                    k += 1
                word = text[i:k]
                if k < n and text[k] == "!":
                    sheet2, i = _read_sheet(text, k + 1)
                    if sheet is not None:
                        raise FormulaError("nested sheet qualifier")
                    sheet = sheet2
                    if i >= n:
                        raise FormulaError("formula ends after sheet name")
                    start = i
                    j = i
                    if text[j] == "$":
                        j += 1
                    k = j
                    while k < n and (text[k].isalnum() or text[k] in "_.$"):
                        k += 1
                    word = text[i:k]
                if k < n and text[k] == "(" and sheet is None:
                    tokens.append(Token("FUNC", word.upper(), pos=start))
                    i = k
                    continue
                if CELL_RE.match(word):
                    tokens.append(Token("REF", word, sheet=sheet, pos=start))
                elif sheet is not None:
                    raise FormulaError(f"sheet-qualified token {word!r} is not a cell reference")
                else:
                    tokens.append(Token("NAME", word, pos=start))
                i = k
                continue
            raise FormulaError(f"unexpected character {ch!r} at {i}")
        if ch in "()+-*/^&=<>%,:{}":
            two = text[i : i + 2]
            if two in ("<>", "<=", ">="):
                tokens.append(Token("OP", two, pos=i))
                i += 2
            else:
                tokens.append(Token("OP" if ch in "+-*/^&=<>%" else ch, ch, pos=i))
                i += 1
            continue
        raise FormulaError(f"unexpected character {ch!r} at {i}")
    return tokens


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0
        self.refs: list[Token] = []

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self, kind: str | None = None, value: str | None = None) -> Token:
        tok = self.peek()
        if tok is None:
            raise FormulaError("unexpected end of formula")
        if kind and tok.kind != kind:
            raise FormulaError(f"expected {kind}, got {tok.kind} {tok.value!r} at {tok.pos}")
        if value and tok.value != value:
            raise FormulaError(f"expected {value!r}, got {tok.value!r} at {tok.pos}")
        self.i += 1
        return tok

    def at(self, kind: str, value: str | None = None) -> bool:
        tok = self.peek()
        return tok is not None and tok.kind == kind and (value is None or tok.value == value)

    def parse(self) -> list[Token]:
        self.expr()
        if self.peek() is not None:
            tok = self.peek()
            raise FormulaError(f"trailing token {tok.value!r} at {tok.pos}")
        return self.refs

    def expr(self):
        self.comparison()

    def comparison(self):
        self.concat()
        while self.at("OP") and self.peek().value in ("=", "<>", "<", ">", "<=", ">="):
            self.take()
            self.concat()

    def concat(self):
        self.additive()
        while self.at("OP", "&"):
            self.take()
            self.additive()

    def additive(self):
        self.term()
        while self.at("OP") and self.peek().value in ("+", "-"):
            self.take()
            self.term()

    def term(self):
        self.power()
        while self.at("OP") and self.peek().value in ("*", "/"):
            self.take()
            self.power()

    def power(self):
        self.unary()
        while self.at("OP", "^"):
            self.take()
            self.unary()

    def unary(self):
        if self.at("OP") and self.peek().value in ("+", "-"):
            self.take()
            self.unary()
            return
        self.postfix()

    def postfix(self):
        self.primary()
        while self.at("OP", "%"):
            self.take()

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise FormulaError("unexpected end of formula")
        if tok.kind == "NUM":
            self.take()
            return
        if tok.kind == "STR":
            self.take()
            return
        if tok.kind == "NAME":
            self.take()
            return
        if tok.kind == "REF":
            self.take()
            self.refs.append(tok)
            self._range(tok)
            return
        if tok.kind == "FUNC":
            self.take()
            self.take("(")
            if not self.at(")"):
                self.expr()
                while self.at(","):
                    self.take()
                    self.expr()
            self.take(")")
            return
        if tok.kind == "(":
            self.take()
            self.expr()
            self.take(")")
            return
        if tok.kind == "{":
            self.take()
            while True:
                self.expr()
                if self.at(",") or self.at(";"):
                    self.take()
                    continue
                break
            self.take("}")
            return
        raise FormulaError(f"unexpected token {tok.value!r} at {tok.pos}")

    def _range(self, first: Token):
        if not self.at(":"):
            return
        self.take(":")
        second = self.take("REF")
        self.refs.append(second)
        if first.sheet and second.sheet and first.sheet != second.sheet:
            raise FormulaError(
                f"range spans two sheets: {first.sheet}!{first.value}:{second.sheet}!{second.value}"
            )
        # Normalise the sheet onto both ends for the caller.
        sheet = first.sheet or second.sheet
        first.sheet = sheet
        second.sheet = sheet


def check_formula(formula: str) -> list[str]:
    """Return a list of problems; empty means the formula passed."""
    try:
        tokens = tokenize(formula)
    except FormulaError as exc:
        return [str(exc)]
    if sum(1 for t in tokens if t.kind == "(") != sum(1 for t in tokens if t.kind == ")"):
        return ["parentheses are unbalanced"]
    try:
        Parser(tokens).parse()
    except FormulaError as exc:
        return [str(exc)]
    return []


def gate_workbook(path: str | Path) -> dict:
    """Check every formula cell in a workbook (§11)."""
    path = Path(path)
    wb = load_workbook(path, data_only=False)
    errors = []
    checked = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if isinstance(value, str) and value.startswith("="):
                    checked += 1
                    problems = check_formula(value)
                    for problem in problems:
                        errors.append(
                            {"sheet": ws.title, "cell": cell.coordinate, "formula": value, "problem": problem}
                        )
    return {
        "file": str(path),
        "formulas": checked,
        "errors": errors,
        "ok": not errors,
    }
