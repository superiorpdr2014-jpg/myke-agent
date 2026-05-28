# Myke Agent — SUPERIOR PDR

AI operations system for SUPERIOR PDR, integrating LINE/Telegram, Airtable CRM, Meta IG API, and TimeTree calendar.

---

## ECHO Server Integration — Airtable CRM Module

Hey Myke, I've built a Node.js module to fix the duplicate vehicle records issue in Airtable. Instead of calling the Airtable API directly, can you swap in this helper for the parts of ECHO that create customer, vehicle, and case records?

The file is `echo_airtable_crm.js` in this repo.

### Usage

```js
const crm = require('./echo_airtable_crm');

// Finds existing customer by LINE user ID, creates one if not found
const customer = await crm.findOrCreateCustomer({
  lineUserId: event.source.userId,
  lineName: profile.displayName,
  branch: 'branch name here'
});

// Finds existing vehicle by customer + brand + model, creates one if not found
const vehicle = await crm.findOrCreateVehicle(customer.id, {
  brand: 'Toyota',
  model: 'Camry',
  year: 2022,
  plate: 'ABC-1234'  // optional
});

// Creates a new case linked to both customer and vehicle
const newCase = await crm.createCase(customer.id, vehicle.id, {
  branch: 'branch name here',
  damage: 'damage description',
  priceRange: 'NT$3,000–5,000'
});
```

### Environment Variables

Make sure `AT_TOKEN` and `AT_BASE` are set in the server's `.env` file. The module reads them from `process.env` so no secrets need to be hardcoded.

```
AT_TOKEN=your_airtable_personal_access_token
AT_BASE=your_airtable_base_id
```

### What changes

The main change is that `findOrCreateVehicle` checks if the same brand + model already exists for that customer before creating a new record — that's what was causing the duplicates. Let me know if you need anything adjusted.

> **Note:** This module only touches Airtable record creation. It does not affect LINE webhook processing, OpenAI handling, branch detection, Telegram notifications, or the PostgreSQL database.

---

## Human Agent Quote Detection

When a human agent takes over and types a price quote, the module automatically:
1. Updates the customer's **服務進度** → `已報價`
2. Saves the quote to the case's **網路區間報價** field

### Usage

Call `handleAgentQuote` **only on outgoing agent messages**, never on incoming customer messages.

```js
const crm = require('./echo_airtable_crm');

// In your human-takeover message handler (agent-side only):
const result = await crm.handleAgentQuote(agentMessage, customerId, caseId);
if (result.detected) {
  console.log(`Quote saved: ${result.quote}`); // e.g. "NT$1500-NT$2500"
}
```

### Accepted quote formats

| Input | Saved as |
|-------|----------|
| `1500-2500` | NT$1500-NT$2500 |
| `$1500-$2500` | NT$1500-NT$2500 |
| `1500~2500` | NT$1500-NT$2500 |
| `$1500~$2500` | NT$1500-NT$2500 |
| `$2500` | NT$2500 |

### Rejected (will not trigger)

- Bare numbers: `800`, `1000`, `2500` — avoids false positives from car model numbers or customer messages
- Numbers typed by the customer — safe because this function is only called on agent-side messages

---

## Files

| File | Description |
|------|-------------|
| `dashboard.py` | Streamlit dashboard — Airtable CRM tables with auto-refresh |
| `mcp_server.py` | MCP server for Claude Desktop — CRM, IG stats, calendar tools |
| `echo_airtable_crm.js` | Node.js CRM module for ECHO server (find-or-create) |
| `airtable_dedup_vehicles.py` | One-time script to remove duplicate vehicle records |
| `airtable_link_vehicles.py` | One-time script to backfill case → vehicle links |
| `morning_report.py` | Daily morning report — TimeTree calendar + IG analytics |
| `ig_daily_report.py` | IG stats report via Meta Graph API |
