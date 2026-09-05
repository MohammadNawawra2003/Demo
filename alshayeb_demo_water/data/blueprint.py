"""The numbers from Document A, in one place.

Transcribed from the blueprint rather than scattered through XML, so that a
reviewer can diff this file against Document A §5 to §9 and §12 and see the
whole company at once. Every figure here is load-bearing somewhere: the water
balance in §7, the transfer price in §6, and the seeded conditions in §13 all
depend on these exact values.
"""

# -- §2 identity ----------------------------------------------------------
CURRENCY = 'SAR'
COUNTRY = 'SA'

# -- §3 the three companies -----------------------------------------------
COMPANIES = [
    ('parent', 'Naqaa Group', None),
    ('c1', 'Naqaa Water Manufacturing Co.', 'parent'),
    ('c2', 'Naqaa Distribution Co.', 'parent'),
    ('c3', 'Naqaa Retail & Delivery Co.', 'parent'),   # dormant in Phase 1
]

# -- §4 warehouses ---------------------------------------------------------
#   code, name, company
WAREHOUSES = [
    ('RM', 'Raw Material Store', 'c1'),
    ('WIP', 'Production Floor', 'c1'),
    ('FG', 'Finished Goods', 'c1'),
    ('QH', 'Quality Hold', 'c1'),
    ('SP', 'Spare Parts & Consumables', 'c1'),
    ('SCRP', 'Scrap', 'c1'),
    ('DCJZN', 'Jazan Distribution Centre', 'c2'),
    ('BRABH', 'Abha Branch', 'c2'),
    ('BRKHM', 'Khamis Mushait Branch', 'c2'),
    ('BRJED', 'Jeddah Branch', 'c2'),
]

# -- §5.1 finished goods ---------------------------------------------------
#   code, name, units/carton, litres/unit, cartons/yr, trade price SAR/ctn, line
FINISHED_GOODS = [
    ('FG-200',   'Naqaa 200 ml',  48, 0.200, 1_200_000,  7.50, 'L1'),
    ('FG-330',   'Naqaa 330 ml',  40, 0.330, 3_500_000,  8.00, 'L1'),
    ('FG-600',   'Naqaa 600 ml',  24, 0.600, 3_000_000,  6.50, 'L2'),
    ('FG-1500',  'Naqaa 1.5 L',   12, 1.500, 2_600_000,  9.00, 'L3'),
    ('FG-5000',  'Naqaa 5 L',      4, 5.000, 1_500_000, 10.00, 'L3'),
    ('FG-12000', 'Naqaa 12 L',     2, 12.00,   900_000, 12.00, 'L4'),
]

#: §6. Net product water × this = the water a BoM consumes. Covers bottle rinse,
#: filler and line CIP, and changeover flush. A BoM consuming exactly the net
#: product volume would imply a plant with no rinse and no CIP, and would make
#: the §7 water balance impossible.
PROCESS_WATER_FACTOR = 1.20

#: §6. Transfer price is cost-plus, per SKU, and the markup table is withheld
#: from C2. Version 1.0 carried 5.76 for FG-330, a 12.5% markup outside the
#: §3 band; 5.86 is the corrected figure.
TRANSFER_PRICE = {
    'FG-200': 4.30, 'FG-330': 5.86, 'FG-600': 4.55,
    'FG-1500': 6.40, 'FG-5000': 7.10, 'FG-12000': 8.60,
}

# -- §5.2 packaging, all purchased -----------------------------------------
#   code, name, uom, unit cost SAR, lead days, lot tracked
BOTTLES = [
    ('PK-BTL-200',   'Empty PET bottle 200 ml',  'Units', 0.042, 18, True),
    ('PK-BTL-330',   'Empty PET bottle 330 ml',  'Units', 0.055, 18, True),
    ('PK-BTL-600',   'Empty PET bottle 600 ml',  'Units', 0.078, 18, True),
    ('PK-BTL-1500',  'Empty PET bottle 1.5 L',   'Units', 0.135, 21, True),
    ('PK-BTL-5000',  'Empty PET bottle 5 L',     'Units', 0.520, 25, True),
    ('PK-BTL-12000', 'Empty PET jerry can 12 L', 'Units', 1.850, 30, True),
]
CLOSURES = [
    ('PK-CAP-S', 'Cap 29/25 PCO (small formats)', 'Units', 0.022, 21, True),
    ('PK-CAP-L', 'Cap 48 mm (5 L, 12 L)',         'Units', 0.075, 21, True),
]
LABELS = [
    ('PK-LBL-200',   'BOPP label 200 ml',  'Units', 0.010, 12, True),
    ('PK-LBL-330',   'BOPP label 330 ml',  'Units', 0.012, 12, True),
    ('PK-LBL-600',   'BOPP label 600 ml',  'Units', 0.014, 12, True),
    ('PK-LBL-1500',  'BOPP label 1.5 L',   'Units', 0.018, 12, True),
    ('PK-LBL-5000',  'BOPP label 5 L',     'Units', 0.021, 12, True),
    ('PK-LBL-12000', 'BOPP label 12 L',    'Units', 0.024, 12, True),
]
CARTONS = [
    ('PK-CTN-200',   'Carton 200 ml x48', 'Units', 0.42, 8, False),
    ('PK-CTN-330',   'Carton 330 ml x40', 'Units', 0.46, 8, False),
    ('PK-CTN-600',   'Carton 600 ml x24', 'Units', 0.52, 8, False),
    ('PK-CTN-1500',  'Carton 1.5 L x12',  'Units', 0.68, 8, False),
    ('PK-CTN-5000',  'Tray 5 L x4',       'Units', 0.90, 8, False),
    ('PK-CTN-12000', 'Tray 12 L x2',      'Units', 1.10, 8, False),
]
FILMS = [
    ('PK-FILM-SHR', 'Shrink film', 'kg', 6.50, 14, False),
    ('PK-FILM-STR', 'Stretch wrap', 'kg', 5.80, 14, False),
]
PALLETS = [('PK-PAL', 'Pallet', 'Units', 22.00, 10, False)]

#: §6. Shrink film per carton, in kg.
FILM_PER_CARTON = {
    'FG-200': 0.038, 'FG-330': 0.045, 'FG-600': 0.052,
    'FG-1500': 0.061, 'FG-5000': 0.070, 'FG-12000': 0.085,
}

#: Which closure each format takes.
CAP_FOR = {
    'FG-200': 'PK-CAP-S', 'FG-330': 'PK-CAP-S', 'FG-600': 'PK-CAP-S',
    'FG-1500': 'PK-CAP-S', 'FG-5000': 'PK-CAP-L', 'FG-12000': 'PK-CAP-L',
}

#: §6 scrap percentages, per component role.
SCRAP_PCT = {'bottle': 0.5, 'cap': 0.3, 'label': 1.5, 'film': 2.0, 'carton': 0.5}

# -- §5.3 process materials -------------------------------------------------
#   code, name, uom, tracked, purchasable
PROCESS_MATERIALS = [
    ('PR-WATER-RAW', 'Raw feed water (well)', 'Litre', False, False),
    ('PR-WATER-TRT', 'Treated water',         'Litre', True,  False),
    ('PR-ANTISCAL',  'RO antiscalant',        'kg',    False, True),
    ('PR-SANIT',     'Sanitiser / CIP chemicals', 'Litre', False, True),
]
SPARES = [
    ('SP-MEMB-RO', 'RO membrane',         'Units', 4200.0, 60),
    ('SP-LAMP-UV', 'UV lamp',             'Units',  380.0, 45),
    ('SP-OZONE',   'Ozone generator part', 'Units', 1750.0, 90),
]

# -- §7 work centres --------------------------------------------------------
#   code, name, formats, capacity note
WORK_CENTRES = [
    ('L1', 'Small PET Line A', 'small'),
    ('L2', 'Small PET Line B', 'small'),
    ('L3', 'Large PET Line',   'large'),
    ('L4', 'Jerry Can Line',   'jerry'),
    ('WT', 'Water Treatment',  'water'),
]
#: §6 sizing. Raised from 640 in v1.0: the original plant could not physically
#: make its stated 199.3M L/yr and was 147% oversubscribed at the July peak.
WT_FEED_M3_DAY = 900
WT_PRODUCT_M3_DAY = 765
WT_RUN_DAYS = 350

# -- §8.3 quality control points -------------------------------------------
#   code, title, spec note, triggers recall
QUALITY_POINTS = [
    ('QCP-01', 'Raw feed water',            'TDS, bromide, micro',        False),
    ('QCP-02', 'Post-RO conductivity / TDS', 'TDS 80-150 mg/L',           False),
    ('QCP-03', 'Post-ozone bromate',        'Bromate <= 10 ppb (GSO 1025)', True),
    ('QCP-04', 'Incoming empty bottles',    'Visual, dimensional, cert',  True),
    ('QCP-05', 'Incoming caps',             'Torque, seal integrity',     True),
    ('QCP-06', 'Fill volume',               '+/-2% nominal',              False),
    ('QCP-07', 'Cap torque / seal',         '12-18 in-lb',                False),
    ('QCP-08', 'Finished lot micro',        'TPC, coliform, Pseudomonas', True),
    ('QCP-09', 'Retention sample',          'Archive 15 months',          False),
    ('QCP-10', 'Date code & label verify',  'Legibility, correctness',    True),
]
BROMATE_LIMIT_PPB = 10          # §8.1 GSO 1025

# -- §9 suppliers -----------------------------------------------------------
#   code, name, city, lead days, note
SUPPLIERS = [
    ('SUP-JPI',  'Jeddah Plastic Industries', 'Jeddah', 18, 'Primary bottles, 60% share'),
    ('SUP-RPC',  'Riyadh PET Co.',            'Riyadh', 21, 'Secondary, higher freight'),
    ('SUP-JZP',  'Jazan Packaging Est.',      'Jazan',  14, 'Local, capacity-limited'),
    ('SUP-GCC',  'Gulf Closures Co.',         'Dammam', 21, 'Caps, primary'),
    ('SUP-NCI',  'Ningbo Cap Industry',       'Ningbo', 55, 'Import, cheaper, MOQ 5M'),
    ('SUP-APH',  'Asir Printing House',       'Abha',   12, 'Labels, sole source per SKU'),
    ('SUP-SCG',  'Southern Corrugated',       'Jazan',   8, 'Cartons, local'),
    ('SUP-GFT',  'Gulf Films Trading',        'Jeddah', 14, 'Shrink and stretch film'),
    ('SUP-AWP',  'Al-Wafa Pallets',           'Jazan',  10, 'Pallets'),
    ('SUP-ATS',  'AquaTech Systems',          'Riyadh', 60, 'Membranes, UV lamps, ozone'),
    ('SUP-CGF',  'ChemGulf',                  'Dammam', 20, 'Antiscalant, CIP chemicals'),
]

# -- §10 customers, by channel ----------------------------------------------
CUSTOMERS = [
    ('CUS-PANDA',  'Panda Retail Company',      'modern',      'c2'),
    ('CUS-OTHAIM', 'Abdullah Al Othaim Markets', 'modern',     'c2'),
    ('CUS-DANUBE', 'Danube',                    'modern',      'c2'),
    ('CUS-CARR',   'Carrefour KSA',             'modern',      'c2'),
    ('CUS-LULU',   'LuLu Hypermarket',          'modern',      'c2'),
    ('CUS-BIND',   'Bin Dawood',                'modern',      'c2'),
    ('CUS-WHJZN',  'Jazan Wholesale Trading',   'traditional', 'c2'),
    ('CUS-WHASR',  'Asir Wholesale Est.',       'traditional', 'c2'),
    ('CUS-WHNJR',  'Najran Distribution',       'traditional', 'c2'),
    ('CUS-HOTEL',  'Southern Hotels Group',     'horeca',      'c2'),
    ('CUS-CATER',  'Jazan Catering Co.',        'horeca',      'c2'),
    ('CUS-HEALTH', 'Jazan Health Cluster',      'institutional', 'c2'),
    ('CUS-SCHOOL', 'Jazan School Districts',    'institutional', 'c2'),
    ('CUS-WAQF',   'Endowment Water Platform (سقيا)', 'charity', 'c2'),
]

# -- §11 seasonality ---------------------------------------------------------
MONTHLY_INDEX = [72, 78, 96, 104, 128, 141, 158, 152, 118, 92, 80, 74]

#: §11. The Hijri calendar drifts ~11 days a year against the Gregorian, so the
#: same month carries a different seasonal load in consecutive years. This is
#: the forecasting trap, and it is deliberate.
RAMADAN = {2025: ('2025-03-01', '2025-03-30'), 2026: ('2026-02-18', '2026-03-19')}
HAJJ = {2025: ('2025-06-04', '2025-06-09'), 2026: ('2026-05-25', '2026-05-30')}

FREIGHT_SAR_PER_PALLET = {
    'Jazan': 18, 'Abha': 46, 'Khamis Mushait': 46, 'Jeddah': 165, 'Riyadh': 240,
}

# -- §12 people --------------------------------------------------------------
#   login, name, company, groups, purpose
USERS = [
    ('ahmed.q',  'Ahmed Al-Qahtani',  'c1',
     ['purchase.group_purchase_manager', 'stock.group_stock_user'],
     'Procurement Manager — full-privilege baseline'),
    ('fahad.p',  'Fahad Al-Otaibi',   'c1', ['READONLY_PURCHASE'],
     'Purchase Officer, READ ONLY — agent allows draft write, user does not, must DENY'),
    ('noura.p',  'Noura Al-Harbi',    'c1',
     ['purchase.group_purchase_user', 'stock.group_stock_user'],
     'Purchase Officer — normal draft-write PASS'),
    ('salem.i',  'Salem Al-Zahrani',  'c1', ['stock.group_stock_manager'],
     'Warehouse Manager'),
    ('mansour.i', 'Mansour Al-Ghamdi', 'c1', ['stock.group_stock_user'],
     'Warehouse Clerk'),
    ('khalid.m', 'Khalid Al-Shehri',  'c1',
     ['mrp.group_mrp_manager', 'stock.group_stock_user'], 'Production Manager'),
    ('yousef.m', 'Yousef Al-Amri',    'c1', ['mrp.group_mrp_user'], 'Line Supervisor'),
    ('huda.q',   'Huda Al-Faifi',     'c1',
     ['quality.group_quality_manager', 'mrp.group_mrp_user'], 'QA Manager'),
    ('rania.q',  'Rania Al-Malki',    'c1', ['quality.group_quality_user'], 'QC Analyst'),
    ('omar.f',   'Omar Al-Dosari',    'c1', ['account.group_account_manager'],
     'Financial Controller — finance no Phase 1 agent may reach'),
    ('layla.f',  'Layla Al-Subaie',   'c2', ['account.group_account_user'],
     'Accountant — multi-company finance boundary'),
    ('tariq.s',  'Tariq Al-Mutairi',  'c2', ['sales_team.group_sale_manager'],
     'Sales Manager — C2 user must not reach C1 production cost'),
    ('bandar.s', 'Bandar Al-Juhani',  'c2',
     ['sales_team.group_sale_salesman', 'stock.group_stock_user', 'WAREHOUSE_SCOPED'],
     'Branch Manager, Jeddah — warehouse-scoped record domain test'),
    ('hr.admin', 'Hessa Al-Anzi',     'c1', ['hr.group_hr_user'],
     'HR Officer — HR data no Phase 1 agent may reach'),
]

#: §12. Four service users, one per agent. None administrators, none able to
#: log in, none holding Accounting, HR or Sales groups.
SERVICE_USERS = [
    ('ai.procurement', 'AI / Procurement', 'procurement', ['c1'],
     ['purchase.group_purchase_user', 'stock.group_stock_user']),
    ('ai.inventory', 'AI / Inventory', 'inventory', ['c1', 'c2'],
     ['stock.group_stock_user']),
    ('ai.manufacturing', 'AI / Manufacturing', 'manufacturing', ['c1'],
     ['mrp.group_mrp_user', 'stock.group_stock_user']),
    ('ai.quality', 'AI / Quality', 'quality', ['c1'],
     ['quality.group_quality_user', 'mrp.group_mrp_user', 'stock.group_stock_user']),
]

# -- §13 the seeded conditions ------------------------------------------------
#: Shortfall for S-01, in units of PK-BTL-330.
S01_SHORTAGE_UNITS = 486_000
#: S-09: the treatment batch that fails QCP-03.
S09_LOT = 'WT-260819-02'
S09_BROMATE_PPB = 13
