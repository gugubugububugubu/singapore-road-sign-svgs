"""Convert LTA's "1PCU ERP Rates Report" PDF (from LTA DataMall static datasets, ERP Rates.zip)
into erp-rates.json for the GetGo ERP embed.

Usage: python3 pdf-to-json.py <report.pdf> <output.json>
Needs: pip install pdfplumber

How it works: each rate table page has a row of gantry numbers under the column headings.
Every "$x.xx" value is matched to the column whose gantry number sits directly above it.
Column names and road groups come from the GANTRIES list below (copied from the PDF headings).
If LTA adds, removes or reorders a column, the script stops and says which one, so the
GANTRIES list can be updated instead of silently mislabelling rates.
"""
import json, re, sys
import pdfplumber

# (gantry numbers as printed in the PDF, display name, road group)
GANTRIES = [
    # Orchard Cordon and Rest of CBD (pages 1-2, weekday and Saturday columns)
    ("1", "Bugis-Marina Centre", "CBD and Orchard"),
    ("2", "Shenton Way-Chinatown", "CBD and Orchard"),
    ("3", "Orchard", "CBD and Orchard"),
    ("47,49", "YMCA Gantry and Fort Canning Tunnel Gantry", "CBD and Orchard"),
    ("48", "Handy Road Gantry", "CBD and Orchard"),
    ("61,62,64,69", "New Bridge Road, South Bridge Road, southbound Fullerton Road and southbound Bayfront Avenue", "CBD and Orchard"),
    ("60,63,66", "Eu Tong Sen Street at Central, northbound Fullerton Road and northbound Bayfront Avenue", "CBD and Orchard"),
    # Arterial roads (pages 3-4, weekdays)
    ("59", "Upper Boon Keng Road near Lorong 1 Geylang", "Arterial roads"),
    ("43,44", "Dunearn Road eastbound after Dunkirk Avenue", "Arterial roads"),
    ("58", "Geylang Bahru westbound after Geylang Bahru Terrace", "Arterial roads"),
    ("70", "Geylang Road westbound before Kallang River", "Arterial roads"),
    ("57", "Kallang Bahru from PIE", "Arterial roads"),
    ("40,71", "Bendemeer Road southbound after Woodsville Interchange, and Woodsville Tunnel", "Arterial roads"),
    ("39", "Thomson Road southbound after Toa Payoh Rise", "Arterial roads"),
    ("56", "Lorong 6 Toa Payoh from Braddell Road", "Arterial roads"),
    ("55", "Upper Bukit Timah Road southbound after Hume Avenue", "Arterial roads"),
    # Expressways (pages 3-4, weekdays)
    ("36", "AYE between Portsdown Road and Alexandra Road", "AYE"),
    ("52,53,74", "Citybound AYE after Jurong Town Hall, and Clementi Avenue 6 and Clementi Avenue 2 into AYE", "AYE"),
    ("41", "Tuas-bound AYE after North Buona Vista", "AYE"),
    ("54", "BKE between Dairy Farm Road and PIE", "BKE"),
    ("31,33,34", "CTE after Braddell Road, Serangoon Road and Balestier slip road", "CTE"),
    ("68", "CTE slip road to PIE (Changi) / Serangoon Road", "CTE"),
    ("35", "CTE between Ang Mo Kio Avenue 1 and Braddell Road", "CTE"),
    ("46,67", "CTE northbound between PIE and Braddell Road, and PIE to CTE northbound before Braddell Road", "CTE"),
    ("51", "CTE northbound between Jalan Bahagia and PIE", "CTE"),
    ("30", "ECP (city)", "ECP"),
    ("73", "ECP eastbound before KPE", "ECP"),
    ("80", "KPE slip road into citybound ECP", "KPE"),
    ("50", "KPE southbound after Defu Flyover", "KPE"),
    ("90,91", "MCE westbound before exits to Central Boulevard and Maxwell Road", "MCE"),
    ("92,93", "MCE eastbound after entry from Maxwell Road, and slip road after Marina Boulevard", "MCE"),
    ("32,45", "PIE after Kallang Bahru exit, and PIE slip road into Bendemeer Road", "PIE"),
    ("37,38", "PIE eastbound after Adam Road, and Mount Pleasant slip road into eastbound PIE", "PIE"),
    ("42", "PIE slip road into CTE", "PIE"),
    ("65", "PIE westbound before Eunos Link", "PIE"),
]
NAMES = {g[0]: g for g in GANTRIES}
TIME = re.compile(r"^(\d\d):(\d\d)$")
REFER = re.compile(r"^Refer #(\d)")

def fail(msg):
    sys.exit("STOPPED: " + msg)

def main(src, out):
    pdf = pdfplumber.open(src)
    text0 = pdf.pages[0].extract_text() or ""
    m = re.search(r"With Effect From (\d\d) (\w{3}) (\d{4})", text0)
    if not m: fail("couldn't find the 'With Effect From' date on page 1")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    effective = f"{m.group(3)}-{months.index(m.group(2))+1:02d}-{m.group(1)}"
    if "PASSENGER CARS, TAXIS AND LIGHT GOODS VEHICLES" not in text0:
        fail("page 1 isn't the passenger car base rate table")

    rates = {}  # gantry -> day -> list of (start, end, amount)
    multipliers = None
    refer = {}
    for pno, page in enumerate(pdf.pages, 1):
        words = page.extract_words(x_tolerance=1.5)
        txt = page.extract_text() or ""
        if "BASE ERP RATE TABLE" not in txt:
            # vehicle multipliers and "Refer #" location lists
            mm = {}
            for label, key in [("Motorcycles", "Motorcycles"), ("Passenger Cars/Light Goods Vehicles/Taxis", "Cars, taxis and light goods vehicles"),
                               ("Heavy Goods Vehicles/ Small Buses", "Heavy goods vehicles and small buses"), ("Very Heavy Goods Vehicles/ Big Buses", "Very heavy goods vehicles and big buses")]:
                r = re.search(re.escape(label) + r"\s+Base ERP Rate(?:\s*\*\s*([\d.]+))?", txt)
                if r: mm[key] = float(r.group(1) or 1)
            if mm: multipliers = mm
            cur = None
            for line in txt.splitlines():
                r = REFER.match(line.strip())
                if r: cur = r.group(1); refer[cur] = []; continue
                r = re.match(r"^\s*(\d+)\s+(.+)$", line)
                if cur and r: refer[cur].append({"no": int(r.group(1)), "location": r.group(2).strip()})
            continue
        if "With Effect From" in txt and m.group(0) not in txt:
            fail(f"page {pno} has a different effective date from page 1")
        # Column positions from the gantry-number row ("Refer to 1" counts as column "1")
        nums = [w for w in words if re.fullmatch(r"[\d,]+", w["text"]) and 100 < w["top"] < 200]
        rows = {}
        for w in nums: rows.setdefault(round(w["top"]), []).append(w)
        top, cols = max(rows.items(), key=lambda kv: len(kv[1]))
        cols.sort(key=lambda w: w["x0"])
        centres = []
        for w in cols:
            c = (w["x0"] + w["x1"]) / 2
            prev = [v for v in words if abs(v["top"] - w["top"]) < 1 and v["text"] == "to" and 0 < w["x0"] - v["x1"] < 6]
            if prev:  # "Refer to N": the value sits under the middle of the whole phrase
                refer_w = [v for v in words if abs(v["top"] - w["top"]) < 1 and v["text"] == "Refer" and 0 < prev[0]["x0"] - v["x1"] < 6]
                c = (refer_w[0]["x0"] + w["x1"]) / 2 if refer_w else c
            centres.append((c, w["text"]))
        # Weekday/Saturday split: the CBD table repeats its columns for Saturdays
        labels = [t for _, t in centres]
        half = len(labels) // 2
        days = ["Weekdays"] * len(labels)
        if len(labels) % 2 == 0 and labels[:half] == labels[half:]:
            days = ["Weekdays"] * half + ["Saturdays"] * half
        for t in labels:
            if t not in NAMES: fail(f"page {pno}: unknown gantry column '{t}'. Add it to GANTRIES.")
        # Rate rows
        times = [w for w in words if TIME.match(w["text"]) and w["x0"] < 80]
        bytop = {}
        for w in times: bytop.setdefault(round(w["top"]), []).append(w)
        for t, tw in bytop.items():
            tw.sort(key=lambda w: w["x0"])
            if len(tw) != 2: fail(f"page {pno}: odd time cell near y={t}")
            start, end = tw[0]["text"], tw[1]["text"]
            for w in words:
                if abs(w["top"] - tw[0]["top"]) < 2 and w["text"].startswith("$"):
                    c = (w["x0"] + w["x1"]) / 2
                    i = min(range(len(centres)), key=lambda k: abs(centres[k][0] - c))
                    if abs(centres[i][0] - c) > 4: fail(f"page {pno}: {w['text']} at {start} doesn't line up with a column")
                    amt = float(w["text"].replace("$", "").replace(",", ""))
                    rates.setdefault(labels[i], {}).setdefault(days[i], []).append((start, end, amt))

    if not multipliers: fail("couldn't find the vehicle type multipliers")
    # Merge 5-minute rows into bands
    def tomin(s): h, mi = s.split(":"); return int(h) * 60 + int(mi)
    gantries = []
    for gid, name, road in GANTRIES:
        g = {"id": gid, "nos": [int(x) for x in gid.split(",")], "name": name, "road": road, "rates": {}}
        if gid in ("1", "2", "3"):
            g["nos"] = [x["no"] for x in refer.get(gid, [])]
            g["locations"] = [x["location"] for x in refer.get(gid, [])]
        for day, rows in rates.get(gid, {}).items():
            rows.sort(key=lambda r: tomin(r[0]))
            bands = []
            for s, e, a in rows:
                if bands and bands[-1][2] == a and bands[-1][1] == s: bands[-1][1] = e
                else: bands.append([s, e, a])
            g["rates"][day] = bands
        gantries.append(g)
    data = {"source": "LTA DataMall, ERP Rates (1PCU ERP Rates Report)", "effective": effective,
            "converted": __import__("datetime").date.today().isoformat(), "multipliers": multipliers, "gantries": gantries}
    json.dump(data, open(out, "w"), separators=(",", ":"))
    charged = sum(1 for g in gantries if g["rates"])
    print(f"OK: effective {effective}, {len(gantries)} gantry groups, {charged} with charges, multipliers {multipliers}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
