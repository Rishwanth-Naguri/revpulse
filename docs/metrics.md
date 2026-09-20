# RevPulse Metric Definitions & SQL Formulations

This document specifies the exact accounting rules, formulas, and SQL definitions used throughout RevPulse.

---

## 1. Monetary Storage & Currencies
- **Minor Units**: All amounts are stored as integer minor units (`BIGINT` cents). For example, `$49.00/mo` is stored as `4900`.
- **Currency Isolation**: MVP uses a single reporting currency per organization (default `usd`). Multi-currency normalization (converting foreign currency amounts via exchange rate feeds) is flagged as a future roadmap item.

---

## 2. Monthly Recurring Revenue (MRR) Normalization

MRR normalizes subscription intervals into standard 30-day / 1-month units:

| Interval | Interval Count | Normalization Formula |
|---|---|---|
| `month` | 1 | `amount_cents * quantity` |
| `year` | 1 | `(amount_cents * quantity) / 12` |
| `quarter` | 1 (or 3 mo) | `(amount_cents * quantity) / 3` |
| `week` | 1 | `(amount_cents * quantity * 52) / 12` |

### Edge Case Handling:
1. **Trialing Subscriptions**: If `status = 'trialing'`, `mrr_cents = 0`.
2. **Canceled / Incomplete / Unpaid**: If `status IN ('canceled', 'incomplete', 'incomplete_expired', 'unpaid')`, `mrr_cents = 0`.
3. **Past Due**: Subscriptions in `past_due` status still contribute to nominal MRR until canceled, but are flagged under **At-Risk Revenue**.
4. **Annualized Run Rate (ARR)**:
   $$\text{ARR} = \text{MRR} \times 12$$

---

## 3. MRR Movements & Classification Logic

For each subscription $s$ and day $T$, let:
- $P_s = \text{MRR on day } T-1$ (Prior MRR)
- $C_s = \text{MRR on day } T$ (Current MRR)

| Condition | Movement Type | Movement Amount |
|---|---|---|
| $P_s = 0$ AND $C_s > 0$ AND no previous subscription history for customer | **`new`** | $C_s$ |
| $P_s = 0$ AND $C_s > 0$ AND customer had previous churned subscription | **`reactivation`** | $C_s$ |
| $C_s > P_s > 0$ | **`expansion`** | $C_s - P_s$ |
| $P_s > C_s > 0$ | **`contraction`** | $P_s - C_s$ |
| $P_s > 0$ AND $C_s = 0$ | **`churn`** | $P_s$ |

$$\text{Net New MRR} = \text{New} + \text{Reactivation} + \text{Expansion} - \text{Contraction} - \text{Churn}$$

---

## 4. SaaS KPI Metrics

### 1. Logo Churn %
$$\text{Logo Churn Rate} = \frac{\text{Customers Churned in Period}}{\text{Active Customers at Start of Period}} \times 100$$

### 2. Revenue Churn %
$$\text{Gross Revenue Churn Rate} = \frac{\text{Churned MRR} + \text{Contraction MRR}}{\text{MRR at Start of Period}} \times 100$$

### 3. Net Revenue Retention (NRR) %
$$\text{NRR} = \frac{\text{Starting MRR} + \text{Expansion} - \text{Contraction} - \text{Churn}}{\text{Starting MRR}} \times 100$$

### 4. Average Revenue Per Account (ARPA)
$$\text{ARPA} = \frac{\text{Total MRR}}{\text{Active Customers Count}}$$

### 5. Simple Customer Lifetime Value (LTV)
$$\text{LTV} = \frac{\text{ARPA}}{\text{Monthly Logo Churn Rate}}$$

---

## 5. Cohort Retention Matrix
Customers are grouped into monthly cohorts based on `date_trunc('month', created_at)`.
- **Cohort Month ($M_0$)**: The month the customer signed up.
- **Period ($n$)**: The number of elapsed months ($0, 1, 2, \dots$).
- **Retained Customers**: Distinct customers with active MRR > 0 in month $M_0 + n$.
- **Retention Rate %**: $\frac{\text{Retained Customers in } M_0+n}{\text{Total Customers in Cohort } M_0} \times 100$.

---

## 6. At-Risk Revenue
Revenue is classified as at-risk if:
1. An invoice is in `open` or `uncollectible` status past its due date (`period_end < CURRENT_TIMESTAMP`).
2. The customer's `delinquent` flag is `true`.
3. The subscription status is `past_due`.
Total At-Risk Revenue = sum of outstanding `amount_due_cents` on past-due invoices + current MRR of `past_due` subscriptions.
