import os
import urllib.parse
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
raw_uri = os.environ.get('MONGODB_URI')
parsed = urllib.parse.urlparse(raw_uri)
mongo_user = os.environ.get('MONGODB_WRITER_USER')
mongo_pass = os.environ.get('MONGODB_WRITER_PASSWD')
mongo_db = os.environ.get('MONGODB_DB_NAME')

uri = f'mongodb://{mongo_user}:{mongo_pass}@{parsed.hostname}:{parsed.port}/'
client = MongoClient(uri)
db = client[mongo_db]

print('========================================================')
print('📊 AUDITORÍA DE PERIODOS EN MONGODB (PlatformEventsDB)')
print('========================================================')

coll_m = db['monthly_performance_summaries']
platforms = coll_m.distinct('_id.platform')
print(f'Plataformas encontradas en monthly_performance_summaries: {platforms}\n')

def generate_expected_months(start_ym, end_ym):
    sy, sm = map(int, start_ym.split('-'))
    ey, em = map(int, end_ym.split('-'))
    cur_y, cur_m = sy, sm
    res = []
    while (cur_y < ey) or (cur_y == ey and cur_m <= em):
        res.append(f'{cur_y:04d}-{cur_m:02d}')
        cur_m += 1
        if cur_m > 12:
            cur_m = 1
            cur_y += 1
    return res

for p in platforms:
    distinct_months = sorted(coll_m.distinct('_id.month', {'_id.platform': p}))
    if not distinct_months:
        print(f'Plataforma: {p} -> SIN MESES')
        continue
    
    min_m = distinct_months[0]
    max_m = distinct_months[-1]
    expected = generate_expected_months(min_m, max_m)
    missing = sorted(list(set(expected) - set(distinct_months)))
    
    print(f'🔹 Plataforma: {p.upper()}')
    print(f'   - Rango total:       {min_m}  hasta  {max_m}')
    print(f'   - Total meses:       {len(distinct_months)}')
    print(f'   - Huecos detectados: {len(missing)} meses faltantes')
    if missing:
        print(f'     ⚠️ MESES FALTANTES: {missing}')
    else:
        print(f'     ✅ Serie continua sin ningún hueco entre {min_m} y {max_m}')
    
    # Desglose por años
    years_breakdown = {}
    for m in distinct_months:
        y = m[:4]
        years_breakdown.setdefault(y, []).append(m)
    print('   - Desglose por año:')
    for y in sorted(years_breakdown.keys()):
        months_in_y = years_breakdown[y]
        print(f'       * {y}: {len(months_in_y)} meses ({months_in_y[0]} a {months_in_y[-1]})')
    print()

print('========================================================')
print('📅 AUDITORÍA EN RESÚMENES ANUALES (yearly_performance_summaries)')
print('========================================================')
coll_y = db['yearly_performance_summaries']
platforms_y = coll_y.distinct('_id.platform')
for p in platforms_y:
    years = sorted(coll_y.distinct('_id.year', {'_id.platform': p}))
    print(f'🔹 Plataforma: {p.upper()} -> Años en BD: {years}')
print()
