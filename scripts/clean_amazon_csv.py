"""Cleans an Amazon Content Performance report CSV.

Removes physical duplicate rows by verifying composite keys (Title, ASIN, Region, Territory, Period, Consumption Type)
or identical rows. When --unique-titles is passed, keeps only the first occurrence of each title for matching purposes.
"""

import sys
import csv
import time
from pathlib import Path

from core.ingestion.amazon_csv import find_csv_file

def main():
    start_time = time.time()
    
    unique_titles_mode = "--unique-titles" in sys.argv
    cli_args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # Setup paths
    project_root = Path(__file__).resolve().parent.parent
    amazon_dir = project_root / "data" / "amazon"
    
    if len(cli_args) > 0:
        raw_csv_path = Path(cli_args[0])
        print(f"Usando CSV original proporcionado: {raw_csv_path.name}")
    else:
        print("Buscando CSV original de Amazon...")
        raw_csv_path = find_csv_file(amazon_dir)
        print(f"Encontrado: {raw_csv_path.name}")
        
    if len(cli_args) > 1:
        output_path = Path(cli_args[1])
    else:
        output_dir = project_root / "data" / "output" / "cleaned_data"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "cleaned_amazon.csv"
    
    seen_keys = set()
    total_rows = 0
    kept_rows = 0
    
    mode_desc = "título único (--unique-titles)" if unique_titles_mode else "clave compuesta (Title, ASIN, Geo, Periodo, Oferta)"
    print(f"Limpiando duplicados físicos por {mode_desc} y guardando en {output_path.name}...")
    
    with raw_csv_path.open("r", encoding="utf-8-sig") as fin:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames
        
        with output_path.open("w", newline="", encoding="utf-8-sig") as fout:
            writer = csv.DictWriter(fout, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                total_rows += 1
                title = row.get("Title Name")
                if not title:
                    continue
                    
                if unique_titles_mode:
                    key = title.strip()
                else:
                    key = (
                        title.strip(),
                        (row.get("ASIN") or "").strip(),
                        (row.get("Region") or "").strip(),
                        (row.get("Territory") or "").strip(),
                        (row.get("Period Start") or "").strip(),
                        (row.get("Period End") or "").strip(),
                        (row.get("Consumption Type") or "").strip(),
                    )

                if key not in seen_keys:
                    seen_keys.add(key)
                    writer.writerow(row)
                    kept_rows += 1
                    
                if total_rows % 100000 == 0:
                    print(f"  ... Procesadas {total_rows} filas.")
                    
    elapsed = time.time() - start_time
    print("\n=== Resumen de Limpieza ===")
    print(f"Filas originales procesadas: {total_rows}")
    print(f"Filas únicas guardadas:      {kept_rows}")
    print(f"Duplicados eliminados:       {total_rows - kept_rows}")
    print(f"Tiempo de ejecución:         {elapsed:.2f} segundos")
    print(f"Archivo limpio:              {output_path}")

if __name__ == "__main__":
    main()
