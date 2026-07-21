import json, sys
sys.path.insert(0, ".")
from irrigation_dam_scraper import parse_irrigation_reservoirs, build_colors, compute_alert_color

# Exact real text extracted from https://sdma.kerala.gov.in/wp-content/uploads/2026/07/Irr-Site-4.pdf
real_text = """
1
Neyyar 
Thiruvananthapuram 
84.75 84.10 83.25 83.75 84.4 97.35 91.71 94% 11.65
4/4 spilway shutters opened @5 cm each, Outflow for drinking water.
2
Kallada 
Kollam 
115.82 100.93 113.74 114.81 115.45 504.92 219.30 41% 30.04 Outflow for power generation, URL - 106.68 m
3
Maniyar (Barrage)
Pathanamthitta 
34.62 29.26 8.80 7.78 36% _
4
Malankara 
Idukki 
42.00 37.52 40.70 41.00 41.30 37.00 20.28 49% 46.77
4/6 spillway shutter opened @60 cm each. Outflow for Drinking Water, Outflow for Power generation.
5
Bhoothathankettu (Barrage) 
Ernakulam 
34.95 30.50 169.79 - - 404.00
2/15 shutters opened @15 cm each. 2/15 shutters opened @200cm each.
6
Vazhani 
Thrissur 
62.48 51.01 60.98 61.48 61.88 18.12 5.21 22% 0.00
7
Chimoni 
Thrissur
76.40 64.25 74.9 75.4 75.9 151.55 72.00 47% 0.00
8
Peechi 
Thrissur 
79.25 70.18 78.00 78.30 78.60 94.95 20.71 21% 0.69 Outflow for Drinking Water
9
Siruvani (Inter state waters)
Palakkad 
878.50 869.89 25.6 12.87 31% 0.50
10
Kanjirappuzha 
Palakkad 
97.50 93.51 96.50 97.00 97.40 70.83 49.40 69% 0.40
11
Meenkara
Palakkad 
156.36 151.39 154.9 155.36 156.06 11.33 2.61 16% 0.00
12
Walayar 
Palakkad 
203.00 196.24 201.50 202.00 202.30 18.40 5.35 14% 0.00
13
Malampuzha 
Palakkad 
115.06 106.07 113.00 114.00 114.45 226.00 65.15 28% 1.24 Outflow for drinking water, URL - 111.15 m
14
Pothundy 
Palakkad 
108.20 96.35 106.71 107.21 107.59 50.91 16.69 22% 0.32 Outflow for drinking water
15
Chulliyar 
Palakkad 
154.08 144.25 152.50 153.08 153.70 13.70 2.25 10% 0.00
16
Mangalam 
Palakkad 
77.88 75.30 76.00 76.52 77.30 25.49 16.46 64% 0.00
17
Moolathara (Regulator)
Palakkad 
184.70 181.10 N/A - - 2.20
18
Kuttiyadi 
Kozhikode 
44.41 37.25 42.00 42.50 42.70 105.69 59.80 46% 27.00
4/4 spilway shutters are fully opened. Outflow for drinking water & power generation.
19
Karapuzha 
Wayanad 
763.00 757.05 761.00 761.50 762.00 76.50 34.60 42% 1.26 3/3 spillway shutter opened @10 cm each, Outflow for drinking water
20
Pazhassi (Barrage) 
Kannur 
26.52 18.89 49.08 5.32 10% 192.80
10/16 shutters opened @50 cm each. 5/16 shutters opened @20 cm each.
"""

data = parse_irrigation_reservoirs(real_text, "20.07.2026")
print(f"Parsed {len(data['reservoirs'])} reservoirs (expected 20)\n")
print(json.dumps(data, ensure_ascii=False, indent=2))
