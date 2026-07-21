import json, sys
sys.path.insert(0, ".")
from dam_scraper import parse_dam_table, build_dam_colors, compute_alert_color

# Realistic HTML table matching dams.kseb.in's actual 19-column structure,
# built from the real data you pasted (Idukki + Sengulam rows as test cases)
test_html = """
<table>
<tr>
  <th>Sl.No</th><th>Name of Reservoir</th><th>District</th><th>FRL (metre)</th>
  <th>Rule level (metre)</th><th>Water level on date (metre)</th>
  <th>Blue Alert level (metre)</th><th>Orange Alert level (metre)</th><th>Red Alert Level (metre)</th>
  <th>Live Storage (MCM)</th><th>% Storage</th><th>Inflow (MCM)</th>
  <th>Average Inflow (Cumecs)</th><th>Power House Discharge (MCM)</th>
  <th>Spill (MCM)</th><th>Current Spillway release (Cumecs)</th>
  <th>Total Outflow (MCM)</th><th>Rain fall (mm)</th><th>Remarks</th>
</tr>
<tr>
  <td>1</td><td>IDUKKI</td><td>IDK</td><td>2403.00 ft</td>
  <td>2377.95 ft</td><td>2327.52 ft</td>
  <td>2369.95</td><td>2373.33</td><td>2374.33</td>
  <td>413.19</td><td>28.31</td><td>5.84</td>
  <td>67.6</td><td>2.47</td>
  <td>0</td><td>&#8211;</td>
  <td>2.47</td><td>64.40</td><td></td>
</tr>
<tr>
  <td>18</td><td>SENGULAM</td><td>IDK</td><td>847.64</td>
  <td>&#8211;</td><td>846.80</td>
  <td>&#8211;</td><td>&#8211;</td><td>&#8211;</td>
  <td>0.19</td><td>48.46</td><td>0.78</td>
  <td>9.0</td><td>0.75</td>
  <td>0</td><td>&#8211;</td>
  <td>0.75</td><td>3.30</td><td></td>
</tr>
</table>
"""

data = parse_dam_table(test_html, "20.07.2026")
print(json.dumps(data, ensure_ascii=False, indent=2))

assert len(data["dams"]) == 2, f"Expected 2 dams parsed, got {len(data['dams'])}"

idukki = data["dams"][0]
assert idukki["name"] == "Idukki"
assert idukki["officialName"] == "IDUKKI"
assert idukki["district"] == "IDK"
assert idukki["FRL"] == "2403.00 ft"
assert idukki["latitude"] == 9.8436, f"Expected known coordinate lookup, got {idukki['latitude']}"
assert idukki["data"][0]["waterLevel"] == "2327.52 ft"
assert idukki["data"][0]["rainfall"] == "64.40"

sengulam = data["dams"][1]
assert sengulam["name"] == "Chenkulam"
assert sengulam["blueLevel"] == "", "Missing threshold should be empty string, not '–'"
assert sengulam["latitude"] == 10.010833

colors = build_dam_colors(data)
print("\nColors:", json.dumps(colors, ensure_ascii=False, indent=2))
assert colors["Idukki"] == "green", "Below all thresholds (missing/no red level matched in this test) -> green"
assert colors["Chenkulam"] == "green", "No thresholds at all -> green"

print("\n✅ ALL ASSERTIONS PASSED — parser correctly handles real column layout, missing dashes, coordinate lookup.")
