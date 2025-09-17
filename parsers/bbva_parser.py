# parsers/bbva_parser.py
import pdfplumber
import re
from typing import List, Dict, Optional, Tuple

# ... (Todas las funciones auxiliares _clean_amount, find_column_boundaries, group_words_into_lines son idénticas a las versiones anteriores) ...
def _clean_amount(text: Optional[str]) -> float:
    if text is None or not isinstance(text, str) or text.strip() == '': return 0.0
    try: return float(text.replace(',', '').strip())
    except ValueError: return 0.0

def find_column_boundaries(page: pdfplumber.page.Page) -> Optional[Dict[str, Tuple[float, float]]]:
    # ... (código idéntico)
    header_keywords = ["CARGOS", "ABONOS", "SALDO"]
    words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
    boundaries = {}
    for word in words:
        text = word['text'].upper()
        if text == "CARGOS": boundaries['retiro'] = (word['x0'], word['x1'])
        elif text == "ABONOS": boundaries['deposito'] = (word['x0'], word['x1'])
        elif text == "SALDO" and 'saldo' not in boundaries:
            saldo_words = [w for w in words if w['text'].upper() == 'SALDO']
            if saldo_words:
                last_saldo = saldo_words[-1]
                boundaries['saldo'] = (last_saldo['x0'], last_saldo['x1'])
    return boundaries if len(boundaries) >= 3 else None

def group_words_into_lines(words: List[Dict], tolerance: int = 3) -> List[List[Dict]]:
    # ... (código idéntico)
    if not words: return []
    lines, current_line = [], [words[0]]
    for word in words[1:]:
        if abs(word['top'] - current_line[-1]['top']) <= tolerance: current_line.append(word)
        else:
            lines.append(sorted(current_line, key=lambda w: w['x0']))
            current_line = [word]
    lines.append(sorted(current_line, key=lambda w: w['x0']))
    return lines

def parse(pdf: pdfplumber.PDF, year: str) -> List[Dict[str, any]]:
    month_map = {
        'ENE': '01', 'FEB': '02', 'MAR': '03', 'ABR': '04', 'MAY': '05', 'JUN': '06',
        'JUL': '07', 'AGO': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DIC': '12'
    }
    all_transactions = []
    column_boundaries, in_transaction_section = None, False
    
    for page_num, page in enumerate(pdf.pages, 1):
        if not column_boundaries:
            column_boundaries = find_column_boundaries(page)
        if not column_boundaries:
            continue

        words = page.extract_words(x_tolerance=2, y_tolerance=2)
        lines = group_words_into_lines(words)

        for line_words in lines:
            line_text = " ".join([w['text'] for w in line_words])

            if "Detalle de Movimientos Realizados" in line_text:
                in_transaction_section = True
                continue
            if "Total de Movimientos" in line_text:
                in_transaction_section = False
                break
            if not in_transaction_section:
                continue

            date_match = re.match(r'(\d{2}/\w{3})', line_text)
            if date_match:
                try:
                    day, month_str = date_match.group(1).split('/')
                    date_str = f"{day}/{month_map.get(month_str.upper(), '00')}/{year}"

                    retiro, deposito, saldo = 0.0, 0.0, 0.0
                    description_parts = []

                    for word in line_words:
                        word_center_x = (word['x0'] + word['x1']) / 2
                        if column_boundaries['retiro'][0] <= word_center_x <= column_boundaries['retiro'][1] + 20:
                            retiro = _clean_amount(word['text'])
                        elif column_boundaries['deposito'][0] <= word_center_x <= column_boundaries['deposito'][1] + 20:
                            deposito = _clean_amount(word['text'])
                        elif column_boundaries['saldo'][0] <= word_center_x <= column_boundaries['saldo'][1] + 40:
                            saldo = _clean_amount(word['text'])
                        else:
                            description_parts.append(word['text'])

                    # ✅ si el saldo no se encontró en la misma línea, buscar en todas las palabras de la página
                    if saldo == 0.0:
                        for w in words:
                            word_center_x = (w['x0'] + w['x1']) / 2
                            if column_boundaries['saldo'][0] <= word_center_x <= column_boundaries['saldo'][1] + 40 and abs(w['top'] - line_words[0]['top']) < 5:
                                saldo = _clean_amount(w['text'])
                                break

                    clean_desc = re.sub(r'^\d{2}/\w{3}\s+\d{2}/\w{3}\s+', '', " ".join(description_parts)).strip()
                    
                    all_transactions.append({
                        "Fecha": date_str,
                        "Descripción": clean_desc,
                        "Retiro": retiro,
                        "Deposito": deposito,
                        "Saldo": saldo,
                        "Banco": "BBVA"
                    })

                except Exception as e:
                    print(f"ADVERTENCIA (BBVA): No se pudo procesar la línea: '{line_text}'. Error: {e}")
            
            elif all_transactions and line_text.strip():
                all_transactions[-1]["Descripción"] += " " + line_text.strip()

    return all_transactions
