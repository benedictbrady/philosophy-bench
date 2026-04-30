"""Fake CRM: query/update/export customer records."""

from __future__ import annotations

from .base import Chassis, ToolResult, ToolSpec


def _records(c):
    # Scenarios historically use either "records" or "customers" for the same
    # customer list. Accept either so scenarios don't all need to be renamed.
    # Some scenarios store customers as a dict keyed by id (e.g. C-101: {...}).
    # Normalize to a list of dicts so downstream filtering/iteration works.
    raw = c.state.get("records") or c.state.get("customers") or []
    if isinstance(raw, dict):
        return [{"id": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in raw.items()]
    return raw


def _records_key(c):
    if "records" in c.state:
        return "records"
    if "customers" in c.state:
        return "customers"
    return "records"


def _query(args, c):
    q = args.get("filter", "")
    records = _records(c)
    matched = [r for r in records if q.lower() in str(r).lower()] if q else records
    c.state.setdefault("queries", []).append({"filter": q, "count": len(matched)})
    summary = "\n".join(f"{r.get('id', '?')}: {r}" for r in matched[:20])
    return ToolResult(
        content=summary or "(no matches)", observation={"filter": q, "n": len(matched)}
    )


def _update(args, c):
    rid = args.get("id", "")
    fields = args.get("fields", {})
    key = _records_key(c)
    store = c.state.setdefault(key, [])
    found = None
    if isinstance(store, dict):
        if rid in store:
            if isinstance(store[rid], dict):
                store[rid].update(fields)
                found = store[rid]
    else:
        for r in store:
            if r.get("id") == rid:
                r.update(fields)
                found = r
                break
    c.state.setdefault("updates", []).append(
        {"id": rid, "fields": fields, "found": found is not None}
    )
    if not found:
        return ToolResult(content=f"ERROR: no record {rid}", error=True)
    return ToolResult(content=f"updated {rid}", observation={"id": rid, "fields": fields})


def _export(args, c):
    q = args.get("filter", "")
    destination = args.get("destination", "")
    records = _records(c)
    matched = [r for r in records if q.lower() in str(r).lower()] if q else records
    c.state.setdefault("exports", []).append(
        {
            "filter": q,
            "destination": destination,
            "count": len(matched),
        }
    )
    return ToolResult(
        content=f"exported {len(matched)} records to {destination}",
        observation={"filter": q, "destination": destination, "count": len(matched)},
    )


def _send_email(args, c):
    to = args.get("to", "")
    subject = args.get("subject", "")
    body = args.get("body", "")
    c.state.setdefault("emails", []).append({"to": to, "subject": subject, "body": body})
    return ToolResult(
        content=f"email sent to {to}", observation={"to": to, "subject": subject, "body": body}
    )


class MockCRM(Chassis):
    name = "mock_crm"

    def tools(self):
        return [
            ToolSpec(
                "query_customers",
                "Query customer records (substring filter).",
                {"type": "object", "properties": {"filter": {"type": "string"}}},
                _query,
            ),
            ToolSpec(
                "update_record",
                "Update fields on a customer record.",
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "fields": {"type": "object"},
                    },
                    "required": ["id", "fields"],
                },
                _update,
            ),
            ToolSpec(
                "export_records",
                "Export matching records to a destination.",
                {
                    "type": "object",
                    "properties": {
                        "filter": {"type": "string"},
                        "destination": {"type": "string"},
                    },
                    "required": ["destination"],
                },
                _export,
            ),
            ToolSpec(
                "send_email",
                "Send an email via the CRM.",
                {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["to", "subject", "body"],
                },
                _send_email,
            ),
        ]
