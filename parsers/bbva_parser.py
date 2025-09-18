# parsers/bbva_parser.py
import pdfplumber
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime

IGNORE_PATTERNS = [
    # Encabezados generales
    r"Estado de Cuenta",
    r"Libret[oó]n Básico",
    r"Cuenta Digital",
    r"No\. de Cuenta",
    r"No\. de Cliente",
    r"PAGINA \d+ / \d+",
    r"BBVA MEXICO, S\.A\., INSTITUCION DE BANCA MULTIPLE",
    r"Estimado Cliente",
    r"su Contrato ha sido modificado",
    r"Con BBVA adelante",
    r"MAESTRA PYME BBVA",
    r"MAESTRA DOLARES PYME BBVA",
    r"MAESTRA PERSONAL BBVA",
    r"MAESTRA EMPRESARIAL BBVA",
    r"MAESTRA PYME DIGITAL BBVA",
    r"MAESTRA PERSONAL DIGITAL BBVA",
    r"MAESTRA EMPRESARIAL DIGITAL BBVA",
    r"BBVA Contigo",
    r"BBVA Contigo Empresarial",
    r"BBVA Contigo Pyme",
    
    # Columnas de tabla
    r"FECHA\s+OPER",
    r"SALDO\s+OPER",
    r"COD\. DESCRIPCIÓN",
    r"REFERENCIA",
    r"CARGOS",
    r"ABONOS",
    r"SALDO",
    
    # Pies de página
    r"LINEA BBVA",
    r"Av\. Paseo de la Reforma",
    r"COMISION NACIONAL PARA",
    r"Este documento es una representación impresa de un CFDI",
    r"Ponemos a su disposición",
    r"UNIDAD ESPECIALIZADA DE ATENCION",
    r"ACLARACIONES",
    r"LEYENDAS DE ADVERTENCIA",
    r"La GAT Real es el rendimiento",
    r"el cual puede consultarlo en cualquier sucursal o www.bbva.mx La GAT Real es el rendimiento que obtendría después de descontar la inflación estimada",
    r"GAT Real",
    r"el cual puede consultarlo en cualquier sucursal",
    r"No\. Cuenta \d+",
    r"No\. Cliente \d+"
]

MONTH_MAP = {
    'ENE': '01', 'FEB': '02', 'MAR': '03', 'ABR': '04', 'MAY': '05', 'JUN': '06',
    'JUL': '07', 'AGO': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DIC': '12'
}

def _parse_totals(text: str, is_credit: bool) -> Tuple[float, int, float, int]:
    imp_c, mov_c, imp_a, mov_a = 0.0, 0, 0.0, 0
    if is_credit:
        match = re.search(r'TOTAL IMPORTES:\s+\$\s*([\d,]+\.\d{2})\s+-\$\s*([\d,]+\.\d{2})', text, re.IGNORECASE)
        if match:
            imp_c = _clean_amount(match.group(1))
            imp_a = _clean_amount(match.group(2))
    else:
        match_c = re.search(r'TOTAL IMPORTE CARGOS\s+([\d,]+\.\d{2})\s+TOTAL MOVIMIENTOS CARGOS\s+(\d+)', text, re.IGNORECASE)
        match_a = re.search(r'TOTAL IMPORTE ABONOS\s+([\d,]+\.\d{2})\s+TOTAL MOVIMIENTOS ABONOS\s+(\d+)', text, re.IGNORECASE)
        if match_c:
            imp_c = _clean_amount(match_c.group(1))
            mov_c = int(match_c.group(2))
        if match_a:
            imp_a = _clean_amount(match_a.group(1))
            mov_a = int(match_a.group(2))
            
    return imp_c, mov_c, imp_a, mov_a

def is_ignore_line(text: str) -> bool:
    """True si es encabezado/pie de página en BBVA"""
    return any(re.search(pat, text, re.IGNORECASE) for pat in IGNORE_PATTERNS)

def _format_flexible_date(date_str: str) -> Optional[str]:
    """Convierte varios formatos de fecha de BBVA a YYYY-MM-DD."""
    if not date_str: return None
    
    date_str = date_str.upper().replace('/', '-')
    
    for es, en in MONTH_MAP.items():
        date_str = date_str.replace(es, en)
        
    for fmt in ("%d-%m-%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

# ... (Todas las funciones auxiliares _clean_amount, find_column_boundaries, group_words_into_lines son idénticas a las versiones anteriores) ...
def _clean_amount(text: Optional[str]) -> float:
    if text is None or not isinstance(text, str) or text.strip() == '': return 0.0
    try: return float(text.replace(',', '').strip())
    except ValueError: return 0.0

def _parse_clabe(text: str) -> Optional[str]:
    """Extrae la CLABE interbancaria de 18 dígitos."""
    match = re.search(r'(?:No\.?\s+(?:de\s+)?)?Cuenta\s+CLABE\s+([\d\s]+)', text, re.IGNORECASE)
    if match:
        cleaned_clabe = re.sub(r'\D', '', match.group(1))
        if len(cleaned_clabe) == 18:
            return cleaned_clabe
    return None

def _parse_account_number(text: str) -> Optional[str]:
    """Extrae el número de cuenta o de tarjeta."""
    # Prioridad para tarjeta de crédito
    match = re.search(r'No\.\s+de\s+Tarjeta\s+([\d\s]+)', text, re.IGNORECASE)
    if match:
        return re.sub(r'\s+', '', match.group(1))
    
    # Fallback para cuenta de débito
    match = re.search(r'No\.?\s+(?:de\s+)?Cuenta\s+(\d+)', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

def _parse_client_name(text: str) -> Optional[str]:
    """Extrae el nombre del titular usando varios métodos de fallback."""
    # Método 1: Búsqueda por "Nombre del Receptor"
    match = re.search(r'Nombre\s+del\s+Receptor\s*:\s*(.+)', text, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if 'código postal' not in name.lower():
            return name

    # Método 2: Búsqueda por línea debajo de "BBVA"
    match = re.search(r'BBVA\s*\n\s*([A-ZÁÉÍÓÚÑ\s]{10,}\b(?:SA\s+DE\s+CV|S\s+DE\s+RL\s+DE\s+CV|SA\s+PI\s+DE\s+CV)?)', text)
    if match:
        name = match.group(1).strip()
        if 'estado de cuenta' not in name.lower():
            return name
            
    # Método 3: Búsqueda relativa al RFC (último recurso)
    lines = text.splitlines()
    rfc_line_index = -1
    for i, line in enumerate(lines):
        if re.search(r'^R\.F\.C\s+[A-Z0-9]+', line.strip(), re.IGNORECASE):
            rfc_line_index = i
            break
    
    if rfc_line_index != -1:
        for i in range(rfc_line_index - 1, -1, -1):
            line = lines[i].strip()
            if len(line) > 10 and not re.search(r'^(No\.|Fecha|Periodo)', line, re.IGNORECASE):
                return line
    
    return None

def _parse_period(text: str, is_credit: bool) -> Tuple[Optional[str], Optional[str]]:
    """Extrae las fechas de inicio y fin del periodo."""
    regex = ''
    if is_credit:
        regex = r'Periodo\s.*?Del\s+([\d\/]{8,10})\s+al\s+([\d\/]{8,10})'
    else:
        regex = r'Periodo\s+(?:DEL\s+)?([\d]{2}\/(?:\w{3}|\d{2})\/\d{2,4})\s+AL\s+([\d]{2}\/(?:\w{3}|\d{2})\/\d{2,4})'
    
    match = re.search(regex, text, re.IGNORECASE | re.DOTALL)
    if match:
        start_date_str = match.group(1)
        end_date_str = match.group(2)
        return _format_flexible_date(start_date_str), _format_flexible_date(end_date_str)
        
    return None, None

def _parse_balances(text: str, is_credit: bool) -> Tuple[float, float]:
    """Extrae los saldos inicial y final."""
    initial_balance, final_balance = 0.0, 0.0
    if is_credit:
        match_ini = re.search(r'Saldo Inicial del Periodo\s*\+?\s*\$?\s*([\d,]+\.\d{2})', text, re.IGNORECASE | re.DOTALL)
        match_fin = re.search(r'Saldo al Corte\s*\$?\s*([\d,]+\.\d{2})', text, re.IGNORECASE | re.DOTALL)
        if match_ini: initial_balance = _clean_amount(match_ini.group(1))
        if match_fin: final_balance = _clean_amount(match_fin.group(1))
    else:
        match_ini = re.search(r'(?:Saldo\s+(?:de\s+)?Liquidación\s+Inicial|Saldo\s+Inicial)\s*\+?\s*\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
        match_fin = re.search(r'(?:Saldo\s+(?:de\s+Operación\s+)?Final)\s*(?:\(\+\))?\s*\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
        if match_ini: initial_balance = _clean_amount(match_ini.group(1))
        if match_fin: final_balance = _clean_amount(match_fin.group(1))
    return initial_balance, final_balance

def _parse_rfc(text: str) -> Optional[str]:
    """
    Extrae el RFC del titular (12 o 13 caracteres), tolerando variaciones
    como "RFC", "R.F.C" y la presencia de un ":" después.
    """
    match = re.search(r'R\.?F\.?C\.?\s*[:]?\s*([A-Z0-9]{12,13})', text, re.IGNORECASE)
    if match:
        return match.group(1)
    return None

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

def parse_debito(pdf: pdfplumber.PDF, year: str) -> List[Dict[str, any]]:
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

            if is_ignore_line(line_text):
                continue

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
                    date_str = f"{year}-{MONTH_MAP.get(month_str.upper(), '00')}-{day}"

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

def parse_credit_card(pdf: pdfplumber.PDF, year: str) -> List[Dict[str, any]]:
    all_transactions = []
    in_transaction_section = False
    
    for page_num, page in enumerate(pdf.pages, 1):
        text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
        lines = text.split("\n")

        for line in lines:
            if "Movimientos Efectuados Tarjeta Titular" in line:
                in_transaction_section = True
                continue
            if "TOTAL IMPORTES" in line:
                in_transaction_section = False
                break
            if not in_transaction_section:
                continue

            # detectar línea con fechas tipo dd/mm/yy
            match = re.match(r'(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})\s+(.*)', line)
            if match:
                fecha_aut, fecha_apli, rest = match.groups()

                # normalizar a yyyy-mm-dd
                def to_iso(date_str: str) -> str:
                    try:
                        # convierte dd/mm/yy → yyyy-mm-dd
                        return datetime.strptime(date_str, "%d/%m/%y").strftime("%Y-%m-%d")
                    except:
                        return date_str  # fallback

                fecha_aut_iso = to_iso(fecha_aut)
                fecha_apli_iso = to_iso(fecha_apli)

                # separar importe final
                importe_match = re.search(r'(\$ ?-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)$', rest)
                importe = 0.0
                descripcion = rest
                retiro, deposito = 0.0, 0.0

                if importe_match:
                    importe_txt = importe_match.group(1).replace("$", "").strip()
                    try:
                        importe = float(importe_txt.replace(",", ""))
                    except:
                        importe = 0.0
                    descripcion = rest[:rest.rfind(importe_match.group(1))].strip()

                if importe > 0:
                    retiro = importe
                elif importe < 0:
                    deposito = abs(importe)

                all_transactions.append({
                    "Fecha": fecha_apli_iso,   # usamos la fecha de aplicación en ISO
                    "Descripción": descripcion,
                    "Retiro": retiro,
                    "Deposito": deposito,
                    "Banco": "BBVA TC",
                    "Saldo": 0.0  # saldo no disponible en tarjetas de crédito
                })

    return all_transactions

def parse(pdf: pdfplumber.PDF, year: str) -> List[Dict[str, any]]:
    """
    Parsea un estado de cuenta de BBVA (débito o crédito) y extrae metadatos y transacciones.
    """
    full_text = "\n".join(page.extract_text(x_tolerance=2) or "" for page in pdf.pages)
    is_credit = "Saldo al Corte" in full_text and "No. de Tarjeta" in full_text
    clabe = _parse_clabe(full_text)
    client_name = _parse_client_name(full_text)
    account_number = _parse_account_number(full_text)
    periodo_inicial, periodo_final = _parse_period(full_text, is_credit)
    saldo_inicial, saldo_final = _parse_balances(full_text, is_credit)
    rfc = _parse_rfc(full_text)

    imp_c, mov_c, imp_a, mov_a = _parse_totals(full_text, is_credit)

    # 2. Parsear transacciones
    if is_credit:
        transactions = parse_credit_card(pdf, year)
    else:
        transactions = parse_debito(pdf, year)

    # 3. Post-procesamiento para totales de TC (se calculan, no se leen)
    if is_credit:
        mov_c = sum(1 for t in transactions if t.get('Retiro', 0) > 0)
        mov_a = sum(1 for t in transactions if t.get('Deposito', 0) > 0)

    # 4. Construir el diccionario final
    result = {
        "clabe_interbancaria": clabe,
        "rfc": rfc,
        "nom_cliente": client_name,
        "num_cuenta": account_number,
        "periodo_inicial": periodo_inicial,
        "periodo_final": periodo_final,
        "saldo_inicial": saldo_inicial,
        "saldo_final": saldo_final,
        "total_importe_cargos": imp_c,
        "total_movimientos_cargo": mov_c,
        "total_importe_abonos": imp_a,
        "total_movimientos_abono": mov_a,
        "movimientos": transactions
    }
    
    return result