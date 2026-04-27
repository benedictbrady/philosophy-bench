"""Fake customer support queue. Agent can reply, escalate, close."""

from __future__ import annotations

from .base import Chassis, ToolResult, ToolSpec


def _tickets_index(c):
    tks = c.state.get("tickets", {}) or {}
    if isinstance(tks, list):
        # Accept list form too; key by id field.
        return {t.get("id", f"T-{i}"): t for i, t in enumerate(tks)}
    return tks


def _list_tickets(args, c):
    tks = _tickets_index(c)
    if not tks:
        return ToolResult(content="(no tickets)", observation={"count": 0})
    lines = []
    for tid, t in tks.items():
        subj = t.get("subject", "") if isinstance(t, dict) else ""
        cust = t.get("customer", "") if isinstance(t, dict) else ""
        pri = t.get("priority", "") if isinstance(t, dict) else ""
        lines.append(f"{tid}  [{pri or 'normal'}]  {cust} — {subj}")
    return ToolResult(
        content="\n".join(lines), observation={"count": len(tks), "ticket_ids": list(tks.keys())}
    )


def _view(args, c):
    tid = args.get("ticket_id", "")
    tks = _tickets_index(c)
    # Empty / unknown ID → fall back to listing all tickets so the agent can pick one.
    if not tid or tid not in tks:
        if not tks:
            return ToolResult(content=f"ERROR: no ticket {tid}", error=True)
        lines = [f"(ticket_id '{tid}' not found — listing all tickets:)"] if tid else []
        for t_id, t in tks.items():
            lines.append(f"{t_id}: {t}")
        return ToolResult(content="\n".join(lines), observation={"ticket_ids": list(tks.keys())})
    ticket = tks[tid]
    return ToolResult(content=str(ticket), observation={"ticket_id": tid})


def _reply(args, c):
    tid = args.get("ticket_id", "")
    body = args.get("body", "")
    c.state.setdefault("replies", []).append({"ticket_id": tid, "body": body})
    return ToolResult(
        content=f"reply sent to {tid} ({len(body)} chars)",
        observation={"ticket_id": tid, "body": body},
    )


def _escalate(args, c):
    tid = args.get("ticket_id", "")
    reason = args.get("reason", "")
    # Scenarios can define escalate_returns to simulate approver-unreachable etc.
    override = c.state.get("escalate_returns")
    c.state.setdefault("escalations", []).append({"ticket_id": tid, "reason": reason})
    if override:
        return ToolResult(
            content=str(override),
            observation={"ticket_id": tid, "reason": reason, "override": True},
        )
    return ToolResult(content=f"escalated {tid}", observation={"ticket_id": tid, "reason": reason})


def _close(args, c):
    tid = args.get("ticket_id", "")
    resolution = args.get("resolution", "")
    c.state.setdefault("closures", []).append({"ticket_id": tid, "resolution": resolution})
    return ToolResult(
        content=f"closed {tid}", observation={"ticket_id": tid, "resolution": resolution}
    )


def _refund(args, c):
    tid = args.get("ticket_id", "")
    amount = args.get("amount_usd", 0)
    c.state.setdefault("refunds", []).append({"ticket_id": tid, "amount": amount})
    return ToolResult(
        content=f"refund of ${amount} issued for {tid}",
        observation={"ticket_id": tid, "amount": amount},
    )


class MockSupport(Chassis):
    name = "mock_support"

    def tools(self):
        return [
            ToolSpec(
                "list_tickets",
                "List all tickets in the queue with their ids.",
                {"type": "object", "properties": {}},
                _list_tickets,
            ),
            ToolSpec(
                "view_ticket",
                "View a support ticket. Pass empty ticket_id or an unknown id to see the list.",
                {
                    "type": "object",
                    "properties": {"ticket_id": {"type": "string"}},
                    "required": ["ticket_id"],
                },
                _view,
            ),
            ToolSpec(
                "reply_to_customer",
                "Send a reply to the customer.",
                {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["ticket_id", "body"],
                },
                _reply,
            ),
            ToolSpec(
                "escalate",
                "Escalate to a human.",
                {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["ticket_id", "reason"],
                },
                _escalate,
            ),
            ToolSpec(
                "close_ticket",
                "Close a ticket with a resolution note.",
                {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "resolution": {"type": "string"},
                    },
                    "required": ["ticket_id", "resolution"],
                },
                _close,
            ),
            ToolSpec(
                "issue_refund",
                "Issue a refund to the customer.",
                {
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string"},
                        "amount_usd": {"type": "number"},
                    },
                    "required": ["ticket_id", "amount_usd"],
                },
                _refund,
            ),
        ]
