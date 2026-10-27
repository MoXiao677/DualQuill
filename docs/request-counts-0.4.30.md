# Request counts in 0.4.30

The chat status displays local request statistics: completed responses, network resends, completed actions, nonzero pending/failed/cancelled/unknown counts, and actual sends. These are local statistics and do not represent provider billing.

A response counts as complete only after the full transport text has been received and validated. This does not mean the resulting novel content passed review. Retries are still sent and may be billed by the provider. This change affects display only; it does not change retry behavior, transport, or author review policy.

Older records may lack outcome and resend data. An HTTP 200 header alone does not establish that the full response was received or validated; when available, it is shown as a historical HTTP 200 with completeness unrecorded. Missing request statistics show only the historical send count and state that effective responses and resends were not recorded. Effective response counts are never inferred from the legacy call count.
