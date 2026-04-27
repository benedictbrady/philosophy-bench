"""Fake data warehouse: run SQL, write reports."""

from __future__ import annotations

import re as _re

from .base import Chassis, ToolResult, ToolSpec

_FROM_RE = _re.compile(r"\bfrom\s+([A-Za-z_][\w]*)", _re.IGNORECASE)


def _synth_tables(results: dict, outcomes: dict) -> dict:
    """Build a {table_name: {columns, rows}} index from query_results / query_outcomes keys.

    Two key shapes are recognized:
      1. A SQL-ish key ("SELECT ... FROM my_table ..."): table name is the FROM-clause.
      2. A bare identifier key ("my_table"): the key itself IS the table name.
    """
    out: dict = {}

    def _ingest_rows(entry, rows):
        # Accept either a plain list or a {rows:[...], columns?:[...]} wrapper.
        if isinstance(rows, dict):
            cols = rows.get("columns") or []
            for col in cols:
                if col not in entry["columns"]:
                    entry["columns"].append(col)
            rows = rows.get("rows") or []
        if not isinstance(rows, list) or not rows:
            return
        if isinstance(rows[0], dict):
            for col in rows[0].keys():
                if col not in entry["columns"]:
                    entry["columns"].append(col)
            entry["rows"].extend([list(r.values()) for r in rows])
        else:
            entry["rows"].extend(rows)

    def _names_from_key(k: str) -> list[str]:
        froms = [m.group(1) for m in _FROM_RE.finditer(k)]
        if froms:
            return froms
        # Bare identifier key — use as-is if it looks table-ish.
        if _re.match(r"^[A-Za-z_][\w]*$", k):
            return [k]
        return []

    for k, v in results.items():
        for name in _names_from_key(k):
            entry = out.setdefault(name, {"columns": [], "rows": []})
            _ingest_rows(entry, v)
    for k, v in outcomes.items():
        for name in _names_from_key(k):
            entry = out.setdefault(name, {"columns": [], "rows": []})
            if isinstance(v, dict):
                cols = v.get("columns") or []
                for col in cols:
                    if col not in entry["columns"]:
                        entry["columns"].append(col)
                rows = v.get("rows") or []
                if rows and isinstance(rows[0], list):
                    entry["rows"].extend(rows)
                elif rows:
                    _ingest_rows(entry, rows)
    return out


def _render(rows: list, cols: list) -> str:
    if not rows:
        return "(0 rows)"
    if cols:
        header = " | ".join(cols)
        body_lines = []
        for r in rows[:50]:
            if isinstance(r, dict):
                body_lines.append(" | ".join(str(r.get(col, "")) for col in cols))
            else:
                body_lines.append(" | ".join(str(v) for v in r))
        return f"{header}\n" + "\n".join(body_lines)
    body_lines = []
    for r in rows[:50]:
        if isinstance(r, dict):
            body_lines.append(" | ".join(f"{k}={v}" for k, v in r.items()))
        else:
            body_lines.append(" | ".join(str(v) for v in r))
    return "\n".join(body_lines)


def _sql(args, c):
    query = args.get("query", "")
    q_lower = query.lower()

    results = c.state.get("query_results", {}) or {}
    outcomes = c.state.get("query_outcomes", {}) or {}

    # 1) Legacy direct-key substring match (canned query → rows).
    matched_key = next((k for k in results if k.lower() in q_lower), None)
    if matched_key is not None:
        raw = results.get(matched_key, [])
        cols = []
        rows = raw
        if isinstance(raw, dict):
            cols = list(raw.get("columns") or [])
            rows = raw.get("rows") or []
        c.state.setdefault("queries", []).append({"query": query, "rows": len(rows)})
        if not rows:
            return ToolResult(content="(0 rows)", observation={"query": query, "n": 0})
        if not cols and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
        return ToolResult(
            content=_render(rows, cols), observation={"query": query, "n": len(rows), "rows": rows}
        )

    matched_key = next((k for k in outcomes if k.lower() in q_lower), None)
    if matched_key is not None:
        outcome = outcomes.get(matched_key, {}) or {}
        rows = outcome.get("rows", []) if isinstance(outcome, dict) else []
        cols = outcome.get("columns") if isinstance(outcome, dict) else None
        c.state.setdefault("queries", []).append({"query": query, "rows": len(rows)})
        if not rows:
            return ToolResult(content="(0 rows)", observation={"query": query, "n": 0})
        return ToolResult(
            content=_render(rows, cols or []),
            observation={"query": query, "n": len(rows), "rows": rows},
        )

    # 2) Build an index of known tables from explicit `tables` state OR by
    # synthesizing from query_results / query_outcomes keys.
    tables = dict(c.state.get("tables", {}) or {})
    synth = _synth_tables(results, outcomes)
    for name, entry in synth.items():
        if name not in tables:
            tables[name] = entry
        else:
            # Merge columns / rows into existing table entry (explicit tables win on cols if set).
            existing = tables[name] if isinstance(tables[name], dict) else {}
            merged_cols = list(existing.get("columns") or [])
            for col in entry.get("columns", []):
                if col not in merged_cols:
                    merged_cols.append(col)
            merged_rows = list(existing.get("rows") or []) + list(entry.get("rows") or [])
            tables[name] = {**existing, "columns": merged_cols, "rows": merged_rows}

    if tables:
        schema_patterns = [
            "information_schema",
            "sqlite_master",
            "show tables",
            "pg_catalog",
            "pg_tables",
        ]
        if any(p in q_lower for p in schema_patterns):
            rows = [{"table_name": name} for name in tables.keys()]
            c.state.setdefault("queries", []).append({"query": query, "rows": len(rows)})
            header = "table_name"
            body = "\n".join(r["table_name"] for r in rows)
            return ToolResult(
                content=f"{header}\n{body}",
                observation={"query": query, "n": len(rows), "rows": rows},
            )
        if "describe" in q_lower or "\\d " in q_lower or "pragma table_info" in q_lower:
            for tname, tinfo in tables.items():
                if tname.lower() in q_lower:
                    cols = tinfo.get("columns", []) if isinstance(tinfo, dict) else []
                    rows = [{"column_name": col} for col in cols]
                    c.state.setdefault("queries", []).append({"query": query, "rows": len(rows)})
                    body = "\n".join(r["column_name"] for r in rows)
                    return ToolResult(
                        content=f"column_name\n{body}",
                        observation={"query": query, "n": len(rows), "rows": rows},
                    )

        # 3) Data query by FROM-clause table name: resolve to tables[name].rows.
        from_tables = [m.group(1) for m in _FROM_RE.finditer(query)]
        for from_name in from_tables:
            match = None
            for tname in tables:
                if tname.lower() == from_name.lower():
                    match = tname
                    break
            if match is None:
                # Loose match: startswith or contains
                for tname in tables:
                    if from_name.lower() in tname.lower() or tname.lower() in from_name.lower():
                        match = tname
                        break
            if match is None:
                continue
            tinfo = tables[match] if isinstance(tables[match], dict) else {}
            rows = tinfo.get("rows") or []
            cols = tinfo.get("columns") or []
            c.state.setdefault("queries", []).append({"query": query, "rows": len(rows)})
            if not rows:
                return ToolResult(content="(0 rows)", observation={"query": query, "n": 0})
            return ToolResult(
                content=_render(rows, cols),
                observation={"query": query, "n": len(rows), "rows": rows},
            )

    c.state.setdefault("queries", []).append({"query": query, "rows": 0})
    return ToolResult(content="(0 rows)", observation={"query": query, "n": 0})


def _write_report(args, c):
    title = args.get("title", "")
    body = args.get("body", "")
    audience = args.get("audience", "")
    c.state.setdefault("reports", []).append({"title": title, "body": body, "audience": audience})
    return ToolResult(
        content=f"report '{title}' written ({len(body)} chars)",
        observation={"title": title, "body": body, "audience": audience},
    )


def _publish(args, c):
    report_title = args.get("report_title", "")
    channel = args.get("channel", "")
    c.state.setdefault("publications", []).append(
        {"report_title": report_title, "channel": channel}
    )
    return ToolResult(
        content=f"published '{report_title}' to {channel}",
        observation={"report_title": report_title, "channel": channel},
    )


class MockWarehouse(Chassis):
    name = "mock_warehouse"

    def tools(self):
        return [
            ToolSpec(
                "run_sql",
                "Run a SQL query against the warehouse.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                _sql,
            ),
            ToolSpec(
                "write_report",
                "Write an analysis report.",
                {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "audience": {"type": "string"},
                    },
                    "required": ["title", "body"],
                },
                _write_report,
            ),
            ToolSpec(
                "publish_report",
                "Publish a report to a channel (slack, email, docs).",
                {
                    "type": "object",
                    "properties": {
                        "report_title": {"type": "string"},
                        "channel": {"type": "string"},
                    },
                    "required": ["report_title", "channel"],
                },
                _publish,
            ),
        ]
