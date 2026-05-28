/**
 * echo_airtable_crm.js
 * Drop into ECHO server and require() where Airtable records are created.
 * Handles find-or-create for customers, vehicles, and cases — no more duplicates.
 *
 * Usage in ECHO:
 *   const crm = require('./echo_airtable_crm');
 *
 *   // When a LINE message comes in:
 *   const customer = await crm.findOrCreateCustomer({ lineUserId, lineName, phone, branch });
 *   const vehicle  = await crm.findOrCreateVehicle(customer.id, { brand, model, year, plate });
 *   const caseRec  = await crm.createCase(customer.id, vehicle.id, { branch, damage, priceRange });
 */

const axios = require('axios');

// ── Config ──────────────────────────────────────────────────────
const AT_TOKEN  = process.env.AT_TOKEN;   // set in ECHO server .env
const AT_BASE   = process.env.AT_BASE;    // set in ECHO server .env
if (!AT_TOKEN || !AT_BASE) throw new Error('AT_TOKEN and AT_BASE must be set in environment variables');
const AT_API    = `https://api.airtable.com/v0/${AT_BASE}`;

const TABLES = {
  customer: 'tblyppP7rIazjfo1o',
  vehicle:  'tblck9rVDwxf3oeoE',
  case:     'tblKQfzgfLg8AYiuQ',
};

const headers = {
  Authorization: `Bearer ${AT_TOKEN}`,
  'Content-Type': 'application/json',
};

// ── Low-level helpers ────────────────────────────────────────────
async function atGet(table, params) {
  const res = await axios.get(`${AT_API}/${TABLES[table]}`, { headers, params });
  return res.data;
}

async function atPost(table, fields) {
  const res = await axios.post(`${AT_API}/${TABLES[table]}`, { fields }, { headers });
  return res.data;
}

async function atPatch(table, recordId, fields) {
  const res = await axios.patch(`${AT_API}/${TABLES[table]}/${recordId}`, { fields }, { headers });
  return res.data;
}

// ── Customer: find by LINE user ID, create if not found ──────────
/**
 * @param {Object} info
 * @param {string} info.lineUserId  - LINE user ID (Uxxxxxxxx)
 * @param {string} [info.lineName]  - LINE display name
 * @param {string} [info.phone]     - customer phone
 * @param {string} [info.branch]    - assigned branch (指定分店)
 * @returns {{ id: string, created: boolean, fields: Object }}
 */
async function findOrCreateCustomer({ lineUserId, lineName = '', phone = '', branch = '' }) {
  const formula = `{LINE用戶ID}='${lineUserId}'`;
  const data = await atGet('customer', { filterByFormula: formula, maxRecords: 1 });

  if (data.records && data.records.length > 0) {
    const rec = data.records[0];
    // Update name/phone/branch if changed
    const updates = {};
    if (lineName && lineName !== rec.fields['客戶LINE名稱']) updates['客戶LINE名稱'] = lineName;
    if (phone    && phone    !== rec.fields['客戶電話'])    updates['客戶電話']    = phone;
    if (branch   && branch   !== rec.fields['指定分店'])    updates['指定分店']    = branch;
    if (Object.keys(updates).length > 0) {
      updates['最後更新時間'] = new Date().toISOString();
      await atPatch('customer', rec.id, updates);
    }
    return { id: rec.id, created: false, fields: { ...rec.fields, ...updates } };
  }

  // Not found → create
  const fields = { 'LINE用戶ID': lineUserId, '最後更新時間': new Date().toISOString() };
  if (lineName) fields['客戶LINE名稱'] = lineName;
  if (phone)    fields['客戶電話']    = phone;
  if (branch)   fields['指定分店']    = branch;
  const created = await atPost('customer', fields);
  return { id: created.id, created: true, fields: created.fields };
}

// ── Vehicle: find by customer + brand + model, create if not found ─
/**
 * @param {string} customerId       - Airtable customer record ID
 * @param {Object} info
 * @param {string} info.brand       - car brand (廠牌), e.g. "Toyota"
 * @param {string} info.model       - car model (型號), e.g. "Camry"
 * @param {number} [info.year]      - manufacture year
 * @param {string} [info.plate]     - license plate
 * @returns {{ id: string, created: boolean, fields: Object }}
 */
async function findOrCreateVehicle(customerId, { brand, model, year = 0, plate = '' }) {
  // Filter by brand + model only — ARRAYJOIN returns display names not IDs,
  // so we can't use it to match customerId. Instead we filter in JS after fetch.
  const formula = `AND({廠牌}='${brand}',{型號}='${model}')`;
  const data = await atGet('vehicle', { filterByFormula: formula, maxRecords: 100 });

  const match = (data.records || []).find(rec =>
    (rec.fields['所屬客戶'] || []).includes(customerId)
  );

  if (match) {
    if (plate && !match.fields['車牌號碼']) {
      await atPatch('vehicle', match.id, { '車牌號碼': plate });
    }
    return { id: match.id, created: false, fields: match.fields };
  }

  // Not found → create
  const fields = { '所屬客戶': [customerId], '廠牌': brand, '型號': model };
  if (year)  fields['年分']     = year;
  if (plate) fields['車牌號碼'] = plate;
  const created = await atPost('vehicle', fields);
  return { id: created.id, created: true, fields: created.fields };
}

// ── Case: always create new, linked to customer + vehicle ─────────
/**
 * @param {string} customerId       - Airtable customer record ID
 * @param {string} vehicleId        - Airtable vehicle record ID (can be null)
 * @param {Object} info
 * @param {string} [info.branch]    - service branch (指定分店)
 * @param {string} [info.damage]    - damage description (損傷說明)
 * @param {string} [info.priceRange] - online price range (網路區間報價)
 * @returns {{ id: string, caseNumber: number, fields: Object }}
 */
async function createCase(customerId, vehicleId, { branch = '', damage = '', priceRange = '' } = {}) {
  const fields = { '所屬客戶': [customerId] };
  if (vehicleId)   fields['所屬車輛']   = [vehicleId];
  if (branch)      fields['指定分店']   = branch;
  if (damage)      fields['損傷說明']   = damage;
  if (priceRange)  fields['網路區間報價'] = priceRange;

  const created = await atPost('case', fields);
  return {
    id: created.id,
    caseNumber: created.fields?.['案件編號'] || null,
    fields: created.fields,
  };
}

// ── Update customer service status ────────────────────────────────
/**
 * @param {string} customerId
 * @param {string} status  - 諮詢中 | 已派單 | 已報價 | 已預約 | 未成交
 */
async function updateCustomerStatus(customerId, status) {
  return atPatch('customer', customerId, {
    '服務進度': status,
    '最後更新時間': new Date().toISOString(),
  });
}

// ── Update case status ────────────────────────────────────────────
/**
 * @param {string} caseId
 * @param {string} status  - 已預約 | 保險處理中 | 維修中 | 交車完成 | 已結案
 * @param {Object} [extra] - { quote, damage }
 */
async function updateCaseStatus(caseId, status, { quote = null, damage = null } = {}) {
  const fields = { '案件狀態': status };
  if (quote)  fields['實際到店報價'] = quote;
  if (damage) fields['損傷說明']     = damage;
  return atPatch('case', caseId, fields);
}

// ── Quote detection & save ────────────────────────────────────
/**
 * Extracts a price quote from agent-typed text.
 * Accepted formats (agent side only — never call this on customer messages):
 *   Range : 1500-2500  $1500-$2500  1500~2500  $1500~$2500  NT$1500-NT$2500
 *   Single: $2500  NT$2500   ← must have currency symbol to avoid false positives
 * Rejected: bare numbers like 800, 1000, 2022 (car model/year noise)
 *
 * @param {string} text
 * @returns {string|null}  normalised quote string, e.g. "NT$1500-NT$2500", or null
 */
function extractQuote(text) {
  // Range pattern: optional NT$|$ + 3-6 digits + [-~] + optional NT$|$ + 3-6 digits
  const rangeRe = /(?:NT\$|\$)?(\d{3,6})\s*[-~]\s*(?:NT\$|\$)?(\d{3,6})/;
  // Single pattern: must be preceded by NT$ or $ to avoid bare-number false positives
  const singleRe = /(?:NT\$|\$)(\d{3,6})/;

  const rangeMatch = text.match(rangeRe);
  if (rangeMatch) {
    return `NT$${rangeMatch[1]}-NT$${rangeMatch[2]}`;
  }
  const singleMatch = text.match(singleRe);
  if (singleMatch) {
    return `NT$${singleMatch[1]}`;
  }
  return null;
}

/**
 * Call this when a human agent sends a message (NOT on customer messages).
 * If the message contains a valid quote, updates:
 *   - Customer 服務進度 → 已報價
 *   - Case 網路區間報價 → extracted quote
 *
 * @param {string} agentText   - the message the human agent typed
 * @param {string} customerId  - Airtable customer record ID
 * @param {string} caseId      - Airtable case record ID
 * @returns {{ detected: boolean, quote: string|null }}
 */
async function handleAgentQuote(agentText, customerId, caseId) {
  const quote = extractQuote(agentText);
  if (!quote) return { detected: false, quote: null };

  await Promise.all([
    updateCustomerStatus(customerId, '已報價'),
    atPatch('case', caseId, { '網路區間報價': quote }),
  ]);

  return { detected: true, quote };
}

module.exports = {
  findOrCreateCustomer,
  findOrCreateVehicle,
  createCase,
  updateCustomerStatus,
  updateCaseStatus,
  extractQuote,
  handleAgentQuote,
};
