Hackerrank-Orchestrate-september26-Buy-or-Wait
# Buy or Wait? — Financial Decision Agent

A deterministic financial-decision agent for the **HackerRank Orchestrate September 2026** challenge. The system evaluates whether a user can safely make a requested purchase **now, with an accepted payment plan, later, or not at all**, while preserving the user's required minimum account balance.

The solution combines transaction history, future scheduled events, recurring expenses, salary and message-based updates, payment preferences, exchange rates, and linked receipt/invoice images into a single cash-flow decision pipeline.

---

## 1. Problem Overview

For each purchase request, the agent must answer a practical question:

> **"Can this purchase be made without putting the user's finances below their required safety margin, and what is the best allowed way to pay for it?"**

The output captures both the numerical safety decision and the reasoning behind it.

The four supported affordability states are:

- `affordable_now` — the full requested amount is safe today and the user accepts `full_payment`.
- `affordable_with_plan` — the purchase is achievable through a valid, user-accepted payment plan.
- `affordable_later` — the full purchase is not safe now, but becomes safe on a future date.
- `not_affordable` — no valid current plan and no future date in the forecast makes the purchase safe.

Recommended payment methods are restricted to the challenge vocabulary:

`full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`

---

## 2. Solution Approach

The implementation follows a **forecast → safety calculation → payment-plan validation → decision** pipeline.

### Step 1 — Load and normalize the financial data

The agent reads the challenge datasets and normalizes:

- dates
- numeric amounts
- currencies
- event status
- event direction
- categories and descriptions
- linked event identifiers

This creates a consistent representation before any financial reasoning is performed.

### Step 2 — Recover missing transaction amounts from images

Some financial events may not contain an amount directly in the CSV data. The solution uses the mapping in `images.csv` to locate the corresponding image under `dataset/media/images/` and applies **Tesseract OCR** to extract a monetary value.

The extraction logic first looks for values near financial keywords such as `total`, `amount`, `paid`, `price`, `due`, `net`, and `payment`, then falls back to numeric candidates when necessary.

This prevents image-linked financial evidence from being ignored simply because the CSV amount field is blank.

### Step 3 — Incorporate message-derived financial updates

Messages can provide information that is not yet represented completely in the event table. The agent interprets relevant linked messages for cases such as:

- pending refunds or credits
- completed credits
- failed debits
- investment-related updates
- salary information and salary changes
- arrears or delayed income
- employment-ending information
- payroll-date changes
- other future income signals that affect cash flow

Uncertain or unapproved bonus/commission information is not treated as guaranteed income.

### Step 4 — Convert event amounts into the user's home currency

The user's profile defines the home currency used for decision-making. When an event is denominated in another currency, the dated rates in `exchange_rates.csv` are used.

The conversion logic prefers the latest applicable direct rate on or before the relevant event date and can use the inverse rate when necessary.

### Step 5 — Build a future cash-flow forecast

For each request date, the agent creates a daily forecast window and combines:

- known future credits
- known future debits
- pending debit reservations
- recurring expenses inferred from historical transactions
- expected salary income
- message-derived future financial changes

Events that are failed, cancelled, unusable, unrealized, or otherwise not valid for guaranteed cash-flow purposes are excluded from the spendable forecast.

Recurring activity is inferred conservatively from historical patterns. Refunds, investments, transfers, and salary events are treated differently from ordinary recurring expenses so they do not distort recurring-spend estimates.

### Step 6 — Calculate the safe amount available today

The key safety rule is:

```text
safe_amount = min(requested_amount,
                  max(0, worst_future_balance - minimum_required_balance))
```

In other words, the agent does not simply ask whether the account has enough money **today**. It checks the future cash-flow trajectory and protects the user's configured minimum balance.

The result is capped to the requested purchase amount and never becomes negative.

### Step 7 — Find the earliest safe date for full payment

The forecast is scanned to find the earliest date on which paying the **entire requested amount as a single payment** would still leave the account at or above the required minimum balance throughout the remaining forecast horizon.

This produces `earliest_date_for_full_payment` when such a date exists.

### Step 8 — Validate the user's payment options

The agent reads the payment options associated with the request and filters them using the user's accepted payment methods and installment constraints.

A candidate plan is accepted only when it satisfies all relevant constraints, including:

- user acceptance of the payment method
- installment limits
- supplied payment amounts
- payment chronology
- desired completion date
- full-payment amount consistency
- projected balance safety for every payment

The selected option is the valid plan with the lowest total payable amount, with additional tie-breaking based on payment count and first payment date.

### Step 9 — Handle partial payment when explicitly supported

A partial-payment option is considered only when:

- the request allows partial payment,
- the user accepts `partial_payment`,
- some but not all of the requested amount is currently safe, and
- the full amount becomes safe by an acceptable completion date.

The generated partial-payment schedule uses exactly two payments:

1. the amount that is safe today, and
2. the remaining balance on the earliest safe full-payment date.

### Step 10 — Produce the final decision

The final status is derived from the safe amount, the best valid payment option, and the earliest safe full-payment date.

The decision explanation is generated directly from these computed values so that the explanation remains consistent with the numerical decision.

---

## 3. Output Contract

The program creates `output.csv` in the repository root with these columns **in exactly this order**:

```text
request_id,
amount_safe_to_pay,
affordability_status,
recommended_payment_method,
payment_plan,
earliest_date_for_full_payment,
spending_changes_needed,
decision_explanation
```

### Column meanings

| Column | Meaning |
|---|---|
| `request_id` | Unique identifier of the purchase request. |
| `amount_safe_to_pay` | Maximum amount that can safely be paid now without violating the minimum-balance rule. |
| `affordability_status` | One of `affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable`. |
| `recommended_payment_method` | Selected method from the challenge vocabulary. |
| `payment_plan` | Chronological plan in `YYYY-MM-DD:amount\|...` format, or `none`. |
| `earliest_date_for_full_payment` | Earliest conservative date on which the full purchase is safe as one payment, or `none` when unavailable. |
| `spending_changes_needed` | `none` or permitted spending-change actions when applicable. |
| `decision_explanation` | Human-readable explanation of the computed decision. |

All monetary values are expressed in the user's **home currency**.

---

## 4. Dataset Usage

The solution uses the challenge data files as follows:

```text
financial_profiles.csv         User balance, minimum balance and preferences
financial_events.csv           Historical and scheduled financial events
requests.csv                   Purchase requests to evaluate
request_payment_options.csv    Allowed payment options for each request
messages.csv                   Additional financial context and future updates
images.csv                     Links events to supporting images
exchange_rates.csv             Dated currency conversion rates
```

Image evidence is loaded from:

```text
 dataset/media/images/
```

The optional `sample_requests.csv` file is used as a reference/test dataset and is **not** treated as the production request set.

---

## 5. Project Structure

The submission package is organized so that the executable solution and documentation are easy to inspect:

```text
.
├── code/
│   └── main.py
├── evaluation/
│   └── usage_report.md
├── dataset/
│   ├── financial_profiles.csv
│   ├── financial_events.csv
│   ├── requests.csv
│   ├── request_payment_options.csv
│   ├── messages.csv
│   ├── images.csv
│   ├── exchange_rates.csv
│   └── media/
│       └── images/
├── README.md
└── ...submission/support files as provided by the challenge...
```

`output.csv` is generated in the repository root when the program runs.

---

## 6. Requirements

The solution is implemented in Python and uses:

- **Python**
- `pandas` for tabular data processing
- `Pillow` for image loading
- `pytesseract` for OCR
- **Tesseract OCR** installed on the system

Install the Python dependencies with:

```bash
pip install pandas pillow pytesseract
```

Tesseract OCR must also be installed and available to `pytesseract` through the system PATH.

The solution does not require an external web API, cloud database, or internet connection for the core decision process.

---

## 7. How to Run

From the repository root:

```bash
py .\code\main.py
```

The program reads the datasets from `dataset/` and writes:

```text
output.csv
```

to the repository root.

For environments where `python` is the normal launcher, the equivalent command is:

```bash
python code/main.py
```

---

## 8. Design Principles

### Safety before spendability

The agent does not treat the current account balance as the only measure of affordability. Future cash-flow obligations are considered and the user's minimum required balance is protected.

### Evidence-aware forecasting

Important financial evidence may come from transactions, messages, exchange rates, or linked images. The system therefore combines multiple evidence sources instead of relying on a single CSV field.

### Conservative treatment of uncertain income

Future income that is not sufficiently confirmed is not automatically converted into guaranteed spending capacity.

### User preference enforcement

A payment plan is not recommended merely because it is mathematically possible. The payment method must also be accepted by the user and must satisfy the request's supplied constraints.

### Exact output contract

The final CSV preserves the required column names, order, status vocabulary, payment-method vocabulary, chronological payment-plan representation, and home-currency convention.

---

## 9. Important Decision Rules

### Affordable now

`affordable_now` requires all of the following:

1. the full requested amount is safe today;
2. a valid `full_payment` option exists; and
3. the user accepts `full_payment`.

### Affordable with plan

`affordable_with_plan` is used when the purchase cannot be treated as a safe full payment today, but a valid accepted payment plan passes the cash-flow safety checks and completion constraints.

### Affordable later

`affordable_later` is used when no valid current payment plan is available but a future date exists on which the full amount can safely be paid.

### Not affordable

`not_affordable` is used when neither a valid current plan nor a safe future full-payment date is available within the forecast logic.

---

## 10. Validation and Quality Checks

During development, the solution was checked against structural and semantic requirements including:

- exact eight-column output schema
- duplicate `request_id` detection
- null-value checks
- affordability-status/payment-method consistency
- payment-plan syntax and chronology
- safe-amount bounds (`0 <= safe <= requested`)
- full-payment amount consistency
- home-currency calculations
- image-based amount recovery
- message-based event updates
- exchange-rate handling
- installment completion constraints
- future balance safety relative to the minimum required balance

A representative final validation pass produced a **250-row output with all required eight columns and no duplicate request IDs or null output fields**.

The observed final status distribution in that validation run was:

```text
68  affordable_now
70  affordable_with_plan
66  affordable_later
46  not_affordable
```

These counts describe the development validation run and are not hard-coded into the solution.

---

## 11. Submission Contents

For the challenge upload flow, the solution ZIP should contain at minimum:

```text
code/main.py
README.md
evaluation/usage_report.md
```

The generated `output.csv` is submitted through the challenge's separate output step when required, and the chat transcript is submitted through the transcript step.

The development `log.txt` remains an append-only record of the work performed during the session.

---

## 12. Limitations and Scope

This project is a challenge-specific financial decision engine, not a real-world financial advisory service.

Forecast quality depends on the evidence present in the supplied datasets. Recurring patterns are inferred from historical data, OCR can fail on poor-quality images, and future financial events are handled according to the challenge's available signals and deterministic rules.

The system is intentionally designed to make a **safe, reproducible decision from the provided dataset**, rather than inventing unavailable financial information.

---

## 13. Final Deliverable

The intended execution flow is:

```text
Input datasets
      │
      ▼
Data normalization
      │
      ├── Image OCR recovery
      ├── Message-derived updates
      └── Currency conversion
      │
      ▼
Future cash-flow forecast
      │
      ▼
Safe amount + earliest safe date
      │
      ▼
Payment-option validation
      │
      ▼
Affordability decision
      │
      ▼
output.csv
```

The result is a deterministic **"Buy or Wait?"** decision for every purchase request, with the financial safety constraint and supported payment choices explicitly represented in the final output.
