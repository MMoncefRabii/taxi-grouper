import pandas as pd
from src.core.ml_model import load_historique_excel, prepare_historique_pairwise_examples
from src.data.training_data_manager import normalize_training_dataframe_for_historique

rows = []
for i in range(20):
    taxi = '2' if i % 2 == 0 else '1'
    rows.append({
        'Date': '2026-07-11',
        'Matricule': f'A{i+1}',
        'Nom - Prénom': f'Agent{i+1}',
        'Opération': 'Site client' if i % 2 == 0 else 'Visite client',
        'Site': 'Beb Souika' if i % 2 == 0 else 'Ariana',
        'Adresse': f'Address {i+1}, Tunis',
        "Heure d'arrivée": '09:00',
        'Groupe Taxi': taxi,
        'SourceSheet': 'TestSheet',
        'BlockID': 'B1',
    })

df = pd.DataFrame(rows)
print('columns', df.columns.tolist())
df = normalize_training_dataframe_for_historique(df)
print('normalized columns', df.columns.tolist())
print(df.head())

path = 'tmp_training_test.xlsx'
df.to_excel(path, index=False, engine='openpyxl')
print('wrote', path)

try:
    loaded = load_historique_excel(path)
    print('loaded rows', len(loaded))
    print(loaded.head())
    x, y = prepare_historique_pairwise_examples(loaded)
    print('pair examples', x.shape, y.shape)
    print('label counts', {int(v): int((y == v).sum()) for v in set(y)})
except Exception as e:
    print('error', type(e), e)
