# Praxis Prompt Template: ticket_routing

<!-- This file is the domain-specific section that gets embedded into the
     Orchestrator's rendered prompt. It replaces the "environment" section
     from Jiayi's atari57_prompt_template.txt.
     
     The four-part structure (hard constraints / stop rules / simplification /
     output contract) is maintained in orchestrator.py and stays identical
     across all domains. This file only describes the domain context. -->

## Domain: Ticket Routing

You are improving a **ticket routing policy** (`policy.py`).

The policy receives a raw support ticket dict and returns a routing decision:

```python
def evaluate(case: dict) -> dict:
    """
    Args:
        case: {
            "id": str,
            "subject": str,
            "body": str,
            "channel": "email" | "chat" | "phone",
            "customer_tier": "free" | "pro" | "enterprise",
            "created_at": ISO8601 str,
            "tags": list[str],
        }
    Returns:
        {
            "queue": str,          # target queue name
            "priority": 1|2|3|4,  # 1=urgent, 4=low
            "sla_hours": float,    # expected resolution time
            "auto_reply": str,     # optional auto-reply message (empty = none)
        }
    """
```

### Available MCP tools

| Tool | When to use |
|------|------------|
| `ticket_search` | Find tickets matching a pattern to build test cases |
| `ticket_get` | Fetch a specific ticket with full conversation |
| `ticket_annotate` | Record your policy's prediction on a ticket |
| `ticket_regression_cases` | Load the current regression set |
| `kpi_get metric_name=routing_accuracy` | Current routing accuracy KPI |
| `kpi_compare` | Before/after comparison across a date range |

### Scoring

Primary metric: `routing_accuracy` — fraction of tickets routed to correct queue
(as assessed by the regression set with human-labelled ground truth).

Secondary metrics tracked but not used for promotion decisions:
- `avg_sla_hours` (lower is better)
- `auto_reply_rate` (informational)

### Failure modes to watch

- Routing all tickets to `general` queue (a common degenerate policy)
- Priority inflation (everything priority=1 satisfies SLA but overwhelms agents)
- Empty `auto_reply` for simple FAQ tickets (missed cost-saving opportunity)
