// Fetches ERP rates from LTA DataMall and writes erp/erp-rates.json
// Runs inside GitHub Actions (Node 20+, no extra packages needed).
// Needs the DataMall key in the DATAMALL_KEY secret.
import { readFile, writeFile } from "node:fs/promises";

const KEY = process.env.DATAMALL_KEY;
if (!KEY) { console.error("DATAMALL_KEY is missing. Add it under Settings > Secrets and variables > Actions."); process.exit(1); }

const BASE = "https://datamall2.mytransport.sg/ltaodataservice/ERPRates";
const OUT = new URL("./erp-rates.json", import.meta.url);
const ZONES = new URL("./zones.json", import.meta.url);

async function fetchAll() {
  const rows = [];
  for (let skip = 0; skip < 100000; ) {
    const res = await fetch(`${BASE}?$skip=${skip}`, { headers: { AccountKey: KEY, accept: "application/json" } });
    if (!res.ok) throw new Error(`DataMall returned ${res.status} ${res.statusText}`);
    const page = (await res.json()).value || [];
    rows.push(...page);
    if (page.length === 0) break;
    skip += page.length; // DataMall pages can be 50 or 500 rows, so step by what came back
  }
  return rows;
}

const toMin = t => { const [h, m] = String(t || "").trim().split(":").map(Number); return h * 60 + (m || 0); };
const toHHMM = m => `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

function build(raw, zoneNames) {
  const today = new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10); // Singapore date
  // Group by zone > effective date
  const byZone = {};
  for (const r of raw) {
    const zone = String(r.ZoneID || "").trim();
    if (!zone) continue;
    const eff = String(r.EffectiveDate || "").slice(0, 10);
    (byZone[zone] ??= {})[eff] ??= [];
    byZone[zone][eff].push(r);
  }
  const gantries = [];
  const upcoming = [];
  for (const [zone, dates] of Object.entries(byZone)) {
    const sorted = Object.keys(dates).sort();
    const current = sorted.filter(d => d <= today).pop() ?? sorted[0];
    const future = sorted.filter(d => d > today);
    const meta = zoneNames[zone] || {};
    const entry = {
      zone,
      name: meta.name || `Gantry zone ${zone}`,
      road: meta.road || "Other",
      named: Boolean(meta.name),
      effective: current,
      rates: compress(dates[current]),
    };
    if (future.length) {
      entry.next = { effective: future[0], rates: compress(dates[future[0]]) };
      upcoming.push({ zone, name: entry.name, effective: future[0] });
    }
    gantries.push(entry);
  }
  gantries.sort((a, b) => a.road.localeCompare(b.road) || a.name.localeCompare(b.name));
  return { source: "LTA DataMall (ERP Rates)", checked: new Date().toISOString(), gantries, upcoming };
}

// Turn 5-minute rows into merged bands per vehicle type and day type, dropping $0 bands
function compress(rows) {
  const groups = {};
  for (const r of rows) {
    const amt = Math.round(parseFloat(r.ChargeAmount) * 100) / 100;
    const s = toMin(r.StartTime); let e = toMin(r.EndTime);
    if (Number.isNaN(s) || Number.isNaN(e) || Number.isNaN(amt)) continue;
    if (e <= s) e += 24 * 60;
    for (const vt of String(r.VehicleType || "All vehicles").split("/").map(v => v.trim()).filter(Boolean)) {
      const day = String(r.DayType || "Weekdays").trim();
      ((groups[vt] ??= {})[day] ??= []).push({ s, e, amt });
    }
  }
  const out = {};
  for (const [vt, days] of Object.entries(groups)) {
    out[vt] = {};
    for (const [day, list] of Object.entries(days)) {
      list.sort((a, b) => a.s - b.s);
      const bands = [];
      for (const b of list) {
        const last = bands[bands.length - 1];
        if (last && last.amt === b.amt && last.e === b.s) last.e = b.e;
        else bands.push({ ...b });
      }
      out[vt][day] = bands.filter(b => b.amt > 0).map(b => [toHHMM(b.s), toHHMM(b.e), b.amt]);
    }
  }
  return out;
}

const raw = await fetchAll();
if (raw.length === 0) { console.error("DataMall returned no rows. Keeping the old file."); process.exit(1); }
const zoneNames = JSON.parse(await readFile(ZONES, "utf8"));
const data = build(raw, zoneNames);

// Only rewrite the file when the rates themselves changed (ignore the timestamp)
let old = null;
try { old = JSON.parse(await readFile(OUT, "utf8")); } catch {}
const strip = d => JSON.stringify({ ...d, checked: undefined });
if (old && strip(old) === strip(data)) {
  console.log(`No rate changes (${raw.length} rows, ${data.gantries.length} zones).`);
  // still refresh the "last checked" date once a day
  old.checked = data.checked;
  await writeFile(OUT, JSON.stringify(old));
} else {
  await writeFile(OUT, JSON.stringify(data));
  console.log(`Updated: ${raw.length} rows, ${data.gantries.length} zones.`);
}
const unnamed = data.gantries.filter(g => !g.named).map(g => g.zone);
if (unnamed.length) console.log(`Zones without a name in zones.json: ${unnamed.join(", ")}`);
