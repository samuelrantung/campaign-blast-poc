# WA-Blast: Flow Weakness Audit

## Legend

- 🔴 **Critical** — blocks correctness or production readiness fundamentally
- 🟠 **High** — significant gap that will cause real problems when building
- 🟡 **Medium** — not blocking but will hurt quality or extensibility
- 🟢 **Low** — minor, polish-level issues

---

## Stage 1: Data Ingestion

| #   | Weakness                                                                                                                                                                                            | Level     | Status      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ----------- |
| 1.1 | **No deduplication defined.** If the same customer or transaction appears twice (common in real datasets), the analysis will be skewed — double-counted frequency, inflated monetary value.         | 🟠 High   | ✅ Resolved |
| 1.2 | **Phone number is treated as a plain field.** No mention of what happens if it's missing, malformed, or not WhatsApp-registered. A blast to invalid numbers silently fails.                         | 🟠 High   | ✅ Resolved |
| 1.3 | **No handling of historical vs. new customers.** A customer with 1 year of history is scored the same as one with 1 week. RFM window doesn't account for customer age.                              | 🟡 Medium | ✅ Resolved |
| 1.4 | **Single dataset source assumed.** The flow mentions CSV/JSON but the schema is fixed. If the real dataset has different column names or date formats, the loader breaks with no graceful fallback. | 🟡 Medium | ✅ Resolved |

### Resolutions

**1.1 — Two-layer deduplication:**

- **Transaction deduplication** at ingest: deduplicate rows by `(customer_id, purchase_date, order_value)` — removes duplicate dataset rows before any analysis
- **Blast deduplication** at dispatch: `BLAST_COOLDOWN_DAYS` prevents re-blasting the same customer within the cooldown window
- **Promo deduplication**: log `promo_code` per customer in `blast_log.jsonl`; on the next eligible run, exclude any promo type already sent to that customer — so they never receive the same offer twice, even after cooldown expires

**1.2 — Phone number validation pipeline:**

1. Check field exists and is non-empty — skip customer if missing
2. Normalize to E.164 format (`+628xxx`) — skip if cannot be parsed
3. WhatsApp registration check is controlled by `WA_REGISTRATION_CHECK` config flag (default: `false`):
   - When `false`: skip the check entirely — assume all numbers are valid WhatsApp numbers
   - When `true` and `SENDER_MODE=meta`: call Meta Contacts API (`GET /v18.0/{phone_number_id}/contacts`) — skip customer if `status: invalid`
   - When `true` and `SENDER_MODE=mock`: skip the check (Meta API unavailable without credentials)
4. All skipped customers are logged with reason to `logs/skipped.jsonl`

**1.3 — Customer age via `created_at` + WhatsApp OTP assumption:**

- Add `created_at` as a required field in the CSV schema
- Customer age = `today - created_at`
- Customers with age < `MIN_CUSTOMER_AGE_DAYS` (default: 14) are excluded from RFM scoring entirely
- **Business assumption:** If the business uses WhatsApp OTP during customer registration, the phone number is already proven to be a valid WhatsApp-active number. In this case `WA_REGISTRATION_CHECK` should remain `false` permanently — the Meta Contacts API check is redundant and adds unnecessary latency and failure risk. This assumption must be explicitly confirmed per business before disabling the check.

**1.4 — Canonical CSV template approach:**

- Define a single canonical CSV schema with fixed column names, types, and required/optional flags
- Provide a downloadable `data/samples/template.csv` with headers and one example row
- At ingestion, validate that all required columns are present before processing any rows
- On failure: print a clear error listing exactly which columns are missing, and exit — do not partially process
- Users are responsible for mapping their own data to this schema; we do not attempt auto-mapping

---

## Stage 2: Churn Analysis

| #   | Weakness                                                                                                                                                                                                             | Level       |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ----------- |
| #   | Weakness                                                                                                                                                                                                             | Level       | Status      |
| --- | --------                                                                                                                                                                                                             | -----       | ------      |
| 2.1 | **RFM scoring method is undefined.** The doc says "scored 1–5" but doesn't specify how: equal-width bins? Percentile-based quintiles? This matters — equal-width on skewed spend data produces poor scores.          | 🔴 Critical | ✅ Resolved |
| 2.2 | **No definition of "combined score."** The doc says combine RFM + rules to rank urgency but never defines the combination formula. Is it sum? Weighted average? This is the core of the engine and it's a black box. | 🔴 Critical | ✅ Resolved |
| 2.3 | **Frequency Drop rule compares to "previous period" — period not defined.** What is the previous period? Last 30 days vs. prior 30 days? Last 3 months vs. prior 3 months? Undefined.                                | 🟠 High     | ✅ Resolved |
| 2.4 | **No cap on at-risk list size.** If 80% of customers score as at-risk, the system blasts all of them. There's no maximum batch size, cost guard, or sampling strategy.                                               | 🟠 High     | ✅ Resolved |
| 2.5 | **New customers will always look like churners.** A customer who signed up 5 days ago has a low Recency score and low Frequency — they'll be flagged as at-risk incorrectly. Need a minimum customer age filter.     | 🟠 High     | ✅ Resolved |
| 2.6 | **RFM doesn't account for business seasonality.** A customer who only buys during year-end sales will always look inactive 10 months of the year — false positive churn signal.                                      | 🟡 Medium   | ✅ Resolved |

### Resolutions

**2.1 — Versioned scoring strategy, simple start:**

- Current implementation: `ScoringStrategy v1.0` — percentile-based quintiles (1–5) per R, F, M dimension
- The scoring module is designed around a `ScoringStrategy` interface — new versions (v1.1, v2.0) are drop-in replacements, no other stage changes required
- Active version is set via config (`SCORING_VERSION`), defaulting to `v1.0`
- Future versions can adopt newer academic models or ML-based approaches without disrupting the pipeline

**2.2 — Combined score, simple start with upgrade path:**

- Current formula: `combined_score = R + F + M` (unweighted sum, range 3–15)
- Same `ScoringStrategy` interface governs the combination formula — upgrading to weighted sum or a different formula is a version bump, not a rewrite
- Thresholds that reference `combined_score` (e.g. `RFM_AT_RISK_THRESHOLD`) remain configurable regardless of version

**2.3 — All period settings are config-driven:**

- `RFM_WINDOW_DAYS` defines the full analysis lookback window
- Frequency Drop comparison period = two equal halves of `RFM_WINDOW_DAYS` (current half vs. prior half)
- Changing the period is a config value change only — no code change required

**2.4 — Configurable blast cap with priority sorting:**

- `MAX_BLAST_SIZE` controls the maximum number of customers per blast run (configurable, default: 500)
- When more customers qualify than the cap allows, the top N are selected by descending `combined_score`
- This ensures the highest-risk customers are always prioritized — budget is never wasted on lower-priority targets

**2.5 — Campaign Targeting Filters (new first-class concept):**

- Each blast run can define an optional set of **targeting filters** applied on top of the at-risk list
- Each blast run accepts an optional SQL WHERE clause applied against the at-risk customer list
- The at-risk list is loaded into an in-memory SQLite table; the filter runs as a SQL query
- Full SQL WHERE expressiveness: `AND`, `OR`, `NOT`, `IN`, `BETWEEN`, range comparisons, etc.
- Any column in the customer dataset is queryable — new CSV columns are automatically filterable
- If no filter is defined, all at-risk customers up to `MAX_BLAST_SIZE` are included
- The SQL input must be validated to allow WHERE conditions only (no INSERT, UPDATE, DROP, subqueries)

**2.6 — Seasonality reframed as opportunity, not noise:**

- A customer who only buys in December appearing on the at-risk list in March is not a false positive — it is a valid re-engagement opportunity
- The blast may succeed in converting them to purchase outside their habitual window, which is a positive outcome
- Seasonality adjustment (e.g. suppressing blasts to known seasonal buyers outside their season) is a future fine-tuning option, not a correctness requirement
- For now: seasonal customers stay in the at-risk pool and are treated the same as any other at-risk customer

---

## Stage 3: Promo Assignment

| #   | Weakness                                                                                                                                                                                  | Level       | Status      |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ----------- |
| 3.1 | **Still in the flow as a core stage**, not as a future add-on. You decided to decouple AI — this hasn't been updated yet. Stage 3 needs to be replaced with rule-based promo assignment.  | 🔴 Critical | ✅ Resolved |
| 3.2 | **No promo budget or cost control defined anywhere.** Nothing prevents generating a 50% discount for every customer. No maximum discount value, no total campaign cost cap.               | 🟠 High     | ✅ Resolved |
| 3.3 | **Promo code generation is unspecified.** Where do codes come from? Are they pre-created in your system? Randomly generated? If randomly generated, how are they validated at redemption? | 🟠 High     | ✅ Resolved |
| 3.4 | **No deduplication of promos.** If a customer was blasted last week and is still in the at-risk list this week, they'll get a second promo. No cooldown period is defined.                | 🟠 High     | ✅ Resolved |

### Resolutions

**3.1 — AI as optional per-campaign feature:**

- Stage 3 core is rule-based promo mapping — always runs, no external dependency
- Each campaign can set `ai_enabled: true/false` (default: `false`)
- When `ai_enabled=true`: Claude API is called to generate the promo instead of the rule table
- Output is always a `PromoOffer` object — Stages 4 and 5 are unaware of which strategy was used
- `ANTHROPIC_API_KEY` is only required when `ai_enabled=true`

**3.2 — Budget cap enforced at PromoOffer validation:**

- `MAX_DISCOUNT_PERCENT` config (default: `30`) — applies to all promo strategies (rule-based and AI)
- After any strategy produces a `PromoOffer`, a validation step checks the discount value against the cap
- If the generated promo exceeds the cap, it is clamped to the max value before proceeding
- This is a single enforcement point regardless of how many strategies are added in the future

**3.3 — Per-customer unique promo codes with SQLite table:**

- Each blast generates a unique code per customer (e.g. `WA-X7K2AB`) stored in a SQLite `promo_codes` table
- Codes are short, typeable, and use no ambiguous characters (no `0/O`, `1/I`)
- Our service owns validation and redemption — the business integrates via our API

**Promo code table schema:**

| Column             | Type        | Description                      |
| ------------------ | ----------- | -------------------------------- |
| `code`             | string (PK) | Unique code per customer         |
| `customer_id`      | string      | Customer this code was issued to |
| `promo_type`       | string      | e.g. `discount_30`, `bogo`       |
| `discount_percent` | float       | Actual discount value            |
| `issued_at`        | datetime    | When the blast was sent          |
| `expires_at`       | datetime    | `issued_at + PROMO_EXPIRY_DAYS`  |
| `is_active`        | bool        | Can be manually deactivated      |
| `is_redeemed`      | bool        | Whether it has been used         |
| `redeemed_at`      | datetime    | When it was redeemed             |

**Redemption flow (physical supermarket):**

1. Customer shows WhatsApp message with code to cashier
2. Cashier calls `GET /promo-codes/validate/{code}` — confirms valid
3. Cashier applies discount manually at POS
4. Cashier calls `POST /promo-codes/redeem/{code}` — marks `is_redeemed=true`
5. Customer deletes the WhatsApp message (informal trust step, acceptable for now)

**POS integration:** We provide the API and documentation. POS-side integration is the business's responsibility. The API is the contract.

**Known gap:** Between steps 2 (validate) and 4 (redeem) there is a race window where the same code could be validated at two registers before either marks it redeemed. Atomic validate-and-redeem in a single API call resolves this — deferred to a future improvement.

**3.4 — `is_sent` flag + customer blast status tracking:**

- Maintain a `customer_blast_status.json` file keyed by `customer_id`:
  ```json
  {
    "C001": {
      "last_sent_at": "2026-05-01T10:00:00Z",
      "sent_promo_codes": ["BACK30"]
    }
  }
  ```
- Before promo assignment: check `is_sent` = `last_sent_at` exists and is within `BLAST_COOLDOWN_DAYS` → skip customer
- Promo deduplication: exclude any promo codes already in `sent_promo_codes` for this customer
- After successful dispatch: update `last_sent_at` and append to `sent_promo_codes`
- This replaces scanning the full `blast_log.jsonl` for cooldown checks — O(1) lookup per customer

---

## Stage 4: Message Construction

| #   | Weakness                                                                                                                                                                                                                                                                     | Level     |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ----------- |
| #   | Weakness                                                                                                                                                                                                                                                                     | Level     | Status      |
| --- | --------                                                                                                                                                                                                                                                                     | -----     | ------      |
| 4.1 | **Template content doesn't match Meta's approval requirements.** The template as written is free-form prose. Meta requires templates to have a fixed structure with clearly marked variable slots (`{{1}}`, `{{2}}`). The current template format won't be approvable as-is. | 🟠 High   | ✅ Resolved |
| 4.2 | **No fallback if a template slot value is null/empty.** If `promo_code` is missing, the message renders with a blank slot. No validation guards against this.                                                                                                                | 🟡 Medium | ✅ Resolved |
| 4.3 | **Character limit validation is mentioned but no limits are specified.** WhatsApp template body max is 1024 characters. The doc says "validate" but doesn't say what to do on failure.                                                                                       | 🟡 Medium | ✅ Resolved |

### Resolutions

**4.1 — Simple template for POC:**

- Template format is plain text with named placeholders for readability — no Meta approval format required for POC since mock sender is used
- When switching to real Meta sender, the template must be reformatted with `{{1}}`, `{{2}}` slots and submitted for approval — this is a production migration step, not a POC concern

**4.2 — Missing slot value = skip message, log as failed:**

- Before construction, validate all required slot values are non-null and non-empty
- If any slot is missing: do not construct or send the message; write an entry to `logs/failed_messages.jsonl` with the customer ID, missing field name, and timestamp
- This ensures no malformed messages are ever dispatched

**4.3 — Pre-flight batch validation before any message is sent:**

- After constructing all messages for a blast run, run a validation pass over the entire batch before dispatching anything
- Each message is checked for: all slots filled, rendered length ≤ 1024 characters, promo code exists in DB and is active
- If any message fails validation: abort the entire blast, write all failures to `logs/failed_messages.jsonl` with customer ID, failure reason, and timestamp, return a full error report to the caller
- No messages are sent until every message in the batch passes — no partial blasts
- Operator fixes the issues and re-runs; clean separation between construction/validation and dispatch

---

## Stage 5: Message Dispatch

| #   | Weakness                                                                                         | Level       |
| --- | ------------------------------------------------------------------------------------------------ | ----------- | ----------- |
| #   | Weakness                                                                                         | Level       | Status      |
| --- | --------                                                                                         | -----       | ------      |
| 5.1 | **No opt-out / unsubscribe mechanism.** Legal requirement in most jurisdictions and Meta policy. | 🔴 Critical | ⏸ Deferred  |
| 5.2 | **Blast log is append-only JSONL with no indexing.** No fast cooldown lookup.                    | 🟡 Medium   | ✅ Resolved |
| 5.3 | **No distinction between API errors and business errors.**                                       | 🟡 Medium   | ✅ Resolved |

### Resolutions

**5.1 — Deferred, open questions documented:**

- Skipped for POC — no consent or opt-out mechanism implemented
- Must be resolved before any real customer data is used
- **Open questions that need business decisions before implementing:**
  - What counts as consent? Options: checkbox at registration, reply "YES" to an opt-in message, implicit (existing customer relationship)
  - How does a customer opt out? Options: reply "STOP" to any blast (Meta actually recommends this), a link in the message, contact customer service
  - Where is consent stored? Needs a `consent` boolean field in the customer schema, set by whatever registration/opt-in flow the business uses
  - Who is responsible for maintaining the opt-out list? Our service or the upstream CRM?
- Meta's own policy requires that customers can reply "STOP" to opt out — this ties into reply handling which is also out of scope

**5.2 — Blast log moved to SQLite:**

- `blast_log` becomes a table in the existing `wa_blast.db` SQLite database (same file as `promo_codes`)
- Enables fast indexed queries: cooldown check = `SELECT last_sent_at FROM blast_log WHERE customer_id = ?`
- Schema:

  | Column          | Type         | Description                   |
  | --------------- | ------------ | ----------------------------- |
  | `id`            | integer (PK) | Auto-increment                |
  | `customer_id`   | string       | Recipient                     |
  | `phone`         | string       | E.164 number used             |
  | `template_name` | string       | Template used                 |
  | `promo_code`    | string       | Code included in message      |
  | `status`        | string       | `sent`, `mocked`, `failed`    |
  | `error_code`    | string       | HTTP error code if failed     |
  | `error_reason`  | string       | Human-readable failure reason |
  | `sent_at`       | datetime     | Dispatch timestamp            |

**5.3 — Simple three-case error handling:**

| Error                       | HTTP Code     | Behavior                                                                                                       |
| --------------------------- | ------------- | -------------------------------------------------------------------------------------------------------------- |
| Invalid phone / bad request | 400           | Log as `failed` with reason, skip customer, continue blast                                                     |
| Rate limit hit              | 429           | Pause dispatch for `RATE_LIMIT_WAIT_SECONDS` (default: 60s), retry once, then log as `failed` if still failing |
| Meta server error / timeout | 500 / timeout | Log as `failed` with reason, skip customer, continue blast                                                     |

No complex retry chains for POC. One retry on rate limit only.

---

## Stage 6: API Layer

| #   | Weakness                                                                                                      | Level     | Status      |
| --- | ------------------------------------------------------------------------------------------------------------- | --------- | ----------- |
| 6.1 | **No authentication on the API.** Any caller can trigger a blast via `POST /blast/send`.                      | 🟠 High   | ⏸ Noted     |
| 6.2 | **`GET /customers/{id}/promo` still references AI generation.** Needs to reflect rule-based promo assignment. | 🟡 Medium | ✅ Resolved |
| 6.3 | **No pagination defined for `/customers/at-risk`.** Returns all results in one response.                      | 🟡 Medium | ✅ Resolved |

### Resolutions

**6.1 — API authentication noted for later:**

- No authentication implemented in POC — intentional
- Adding API key auth later is straightforward: one FastAPI middleware, one `API_KEY` config value
- Must be added before any external exposure beyond local development

**6.2 — `/customers/{id}/promo` revised:**

- Endpoint now runs rule-based promo assignment (Stage 3), not AI generation
- Returns the `PromoOffer` that would be assigned to this customer given their current RFM profile
- Useful for previewing what promo a specific customer would receive before triggering a blast

**6.3 — Standard list query features on all GET list endpoints:**
All `GET` endpoints returning lists support the following query parameters:

| Parameter    | Description                                            | Example                   |
| ------------ | ------------------------------------------------------ | ------------------------- |
| `limit`      | Max number of results to return                        | `?limit=50`               |
| `offset`     | Number of results to skip (for pagination)             | `?offset=100`             |
| `search`     | Filter by customer name or ID (partial match)          | `?search=john`            |
| `sort_by`    | Column to sort by                                      | `?sort_by=combined_score` |
| `order`      | Sort direction: `asc` or `desc`                        | `?order=desc`             |
| `risk_level` | Filter by risk level (where applicable)                | `?risk_level=HIGH`        |
| `since`      | Filter records after this datetime (for log endpoints) | `?since=2026-05-01`       |

Applies to: `/customers/at-risk`, `/blast/logs`

---

## General / Cross-Cutting

| #   | Weakness | Level | Status |
| --- | -------- | ----- | ------ |
| G.1 | **No feedback loop defined.** No process to measure if blasts actually reduced churn. | 🟠 High | ✅ Resolved |
| G.2 | **High-level flow diagram shows "AI Promo Generator"** — inconsistent with AI decoupling decision. | 🟡 Medium | ✅ Resolved |
| G.3 | **No defined trigger mechanism.** When does the pipeline run? | 🟡 Medium | ✅ Resolved |
| G.4 | **`ANTHROPIC_API_KEY` listed as required** even though AI is decoupled. | 🟢 Low | ✅ Resolved |

### Resolutions

**G.1 — Feedback loop via existing data, four levels:**

All four signals are available from data already in the system — no new infrastructure required.

| Level | Signal | How to measure | Data source |
|---|---|---|---|
| 1 | **Redemption rate** | % of issued promo codes redeemed per blast | `promo_codes` table — `is_redeemed` |
| 2 | **Re-engagement rate** | Customers who were at-risk after a blast but no longer appear at-risk in the next pipeline run (made a new purchase) | Compare blast history against next at-risk list |
| 3 | **Time-to-redeem** | Avg days between `issued_at` and `redeemed_at` per promo type | `promo_codes` table |
| 4 | **Promo type effectiveness** | Redemption rate broken down by `promo_type` and `risk_level` | `promo_codes` table joined with `blast_log` |

Levels 1–4 are all simple queries on existing tables. Start with level 1 and 2 — they cost nothing extra. Levels 3 and 4 feed directly into refining the promo mapping table in Stage 3.

A `GET /analytics/blast/{blast_id}` endpoint can expose these metrics per campaign run.

**G.2 — High-level flow diagram revised:**
- Replaced "AI Promo Generator" with "Promo Assignment" in FLOW.md

**G.3 — Manual trigger via API for POC:**
- Pipeline is triggered manually by calling `POST /blast/send`
- No scheduler or automation in POC — intentional
- Future options: cron job calling the API on a schedule, event-driven trigger from a CRM when a customer crosses a risk threshold, or a dedicated scheduler service

**G.4 — `ANTHROPIC_API_KEY` is optional:**
- Already resolved in config — key is only required when a campaign has `ai_enabled=true`
- No change needed
