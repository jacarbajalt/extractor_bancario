# parsers/banamex_parser.py

import pdfplumber
import re
from typing import List, Dict
import logging

# Configuración del Logger para ver el proceso en la terminal
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def clean_value(value: str) -> float:
    """Limpia y convierte un string monetario a un valor flotante."""
    if not isinstance(value, str):
        return 0.0
    
    cleaned_value = value.replace('\n', ' ').replace('$', '').replace(',', '').strip()
    if not cleaned_value:
        return 0.0
    try:
        if '(' in cleaned_value and ')' in cleaned_value:
            cleaned_value = '-' + cleaned_value.replace('(', '').replace(')', '')
        return float(cleaned_value)
    except (ValueError, TypeError):
        logging.warning(f"No se pudo convertir el valor a float: '{value}'")
        return 0.0

def is_valid_transaction_row(row: List[str]) -> bool:
    """Verifica si una fila tiene las características de una transacción."""
    if not row or len(row) < 5:
        return False
    
    # Debe tener un concepto que no sea un encabezado o un saldo anterior
    concepto = row[1]
    if not concepto or "CONCEPTO" in concepto.upper() or "SALDO ANTERIOR" in concepto.upper():
        return False
        
    # Debe tener al menos un valor numérico en las columnas de dinero
    has_monetary_value = any(clean_value(cell) != 0.0 for cell in [row[2], row[3]])
    return has_monetary_value

def parse(pdf: pdfplumber.PDF, year: str) -> List[Dict]:
    """
    Parsea un objeto PDF de Banamex. Esta versión utiliza una configuración de tabla
    explícita para manejar PDFs con tablas sin bordes visibles.
    """
    logging.info("--- INICIANDO PARSEO DE BANAMEX (VERSIÓN ROBUSTA) ---")
    logging.info(f"Procesando PDF del año: {year} con {len(pdf.pages)} páginas.")
    
    transactions = []
    parsing_active = False
    last_valid_date = None

    # --- CONFIGURACIÓN PARA DETECCIÓN DE TABLAS ---
    # Esta es la clave: le decimos a pdfplumber cómo encontrar las tablas
    # basándose en la alineación del texto y no en las líneas.
    table_settings = {
        "vertical_strategy": "text",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
    }

    for i, page in enumerate(pdf.pages):
        page_num = i + 1
        logging.info(f"--- Procesando página {page_num} ---")
        
        page_text = page.extract_text()
        
        if not parsing_active and re.search(r'Detalle de Operaciones', page_text, re.IGNORECASE):
            parsing_active = True
            logging.info(f"¡Activado! Se encontró 'Detalle de Operaciones' en la página {page_num}.")
        
        if not parsing_active:
            logging.info(f"Página {page_num}: Aún no se encuentra el inicio de las operaciones. Saltando.")
            continue

        # Usamos la configuración explícita para extraer tablas
        tables = page.extract_tables(table_settings)
        logging.info(f"Página {page_num}: Se encontraron {len(tables)} tablas con la nueva configuración.")

        for table_idx, table in enumerate(tables):
            logging.info(f"Página {page_num}, Tabla {table_idx + 1}: Analizando {len(table)} filas.")
            
            for row_idx, row in enumerate(table):
                logging.debug(f"  - Fila {row_idx + 1}: {row}")
                
                if is_valid_transaction_row(row):
                    fecha_str, concepto, retiros, depositos, saldo = row[:5]
                    
                    if fecha_str and fecha_str.strip():
                        last_valid_date = f"{fecha_str.strip().replace(' ', '-')} {year}"

                    if not last_valid_date:
                        logging.warning("    -> Saltando fila porque no se ha establecido una fecha válida.")
                        continue
                    
                    transaction_data = {
                        "Fecha": last_valid_date,
                        "Descripcion": concepto.strip().replace('\n', ' '),
                        "Depositos": clean_value(depositos),
                        "Retiros": clean_value(retiros),
                        "Saldo": clean_value(saldo),
                        "Banco": "Banamex"
                    }
                    transactions.append(transaction_data)
                    logging.info(f"    -> TRANSACCIÓN AGREGADA: {transaction_data}")
                else:
                    # Lógica mejorada para descripciones multi-línea
                    if transactions and row and len(row) > 1 and row[1] and row[1].strip() and not row[0]:
                        extra_desc = row[1].strip().replace('\n', ' ')
                        transactions[-1]['Descripcion'] += f" {extra_desc}"
                        logging.info(f"    -> Descripción extendida para la última transacción: '{extra_desc}'")
                    else:
                        logging.debug("    -> Fila no es una transacción o es encabezado.")

    logging.info(f"--- PARSEO FINALIZADO --- Se encontraron {len(transactions)} transacciones en total.")
    return transactions