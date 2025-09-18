# parsers/banamex_parser.py
import pdfplumber
import re
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from typing import List, Dict, Any, Optional

# --- MAPAS DE DATOS ---

MONTH_MAP = {
    'ENE': '01', 'FEB': '02', 'MAR': '03', 'ABR': '04', 'MAY': '05', 'JUN': '06',
    'JUL': '07', 'AGO': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DIC': '12',
    'ENERO': '01', 'FEBRERO': '02', 'MARZO': '03', 'ABRIL': '04', 'MAYO': '05', 'JUNIO': '06',
    'JULIO': '07', 'AGOSTO': '08', 'SEPTIEMBRE': '09', 'OCTUBRE': '10', 'NOVIEMBRE': '11', 'DICIEMBRE': '12'
}

# Mapa auxiliar de abreviaturas a mes numérico (usa mayúsculas)
def _map_month_abbr(mon_abbr: str) -> int:
    mapping = {
        "ENE":1,"FEB":2,"MAR":3,"ABR":4,"MAY":5,"JUN":6,
        "JUL":7,"AGO":8,"SEP":9,"OCT":10,"NOV":11,"DIC":12,
        "JAN":1,"APR":4,"AUG":8,"DEC":12
    }
    mon_abbr = (mon_abbr or "").upper()[:3]
    return mapping.get(mon_abbr, 1)

# --- FUNCIONES AUXILIARES ---

_amount_regex = re.compile(r'(\d{1,3}(?:,\d{3})*\.\d{2}-?)')

def _parse_amount_token(tok: str) -> float:
    """Normaliza un token tipo '1,600.00' o '62.18-' a float (negativos si tienen '-')"""
    tok = tok.strip()
    neg = tok.endswith('-')
    tok = tok.rstrip('-').replace(',', '')
    try:
        v = float(tok)
    except:
        v = 0.0
    return -v if neg else v

def _extract_amounts_from_text(text: str) -> List[float]:
    """Devuelve lista de importes (float) encontrados en el texto (en orden de aparición)."""
    toks = _amount_regex.findall(text)
    return [_parse_amount_token(t) for t in toks]

def _format_date_banamex(date_str: str, year: str) -> Optional[str]:
    if not date_str: return None
    clean_str = date_str.upper().replace(' DE ', ' ')
    
    for month_es, month_num in MONTH_MAP.items():
        if month_es in clean_str:
            clean_str = clean_str.replace(month_es, month_num)
            break
            
    parts = clean_str.split()
    try:
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            day, month = parts[0], parts[1]
            effective_year = parts[2] if len(parts) > 2 and parts[2].isdigit() else year
            return f"{effective_year}-{month.zfill(2)}-{day.zfill(2)}"
    except (ValueError, IndexError):
        pass
    return None

def _clean_amount(text: Optional[str]) -> float:
    if text is None or not isinstance(text, str) or text.strip() == '': return 0.0
    try:
        return float(text.replace('$', '').replace(',', '').strip())
    except ValueError:
        return 0.0

def _format_flexible_date_banamex(date_str: str, year: str) -> Optional[str]:
    if not date_str: return None
    clean_str = date_str.upper().replace(' DE ', ' ')
    
    for month_es, month_num in MONTH_MAP.items():
        if month_es in clean_str:
            clean_str = clean_str.replace(month_es, month_num)
            break
            
    for fmt in ("%d %m %Y", "%d/%m/%Y"):
        try:
            formatted_str = ' '.join(clean_str.split())
            dt = datetime.strptime(formatted_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    try:
        parts = clean_str.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            day, month = parts
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    except Exception:
        pass
        
    return None

def find_column_boundaries(page: pdfplumber.page.Page) -> Optional[Dict[str, Tuple[float, float]]]:
    words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
    boundaries = {}
    header_candidates = [w for w in words if w['top'] < page.height * 0.5]

    for word in header_candidates:
        text = word["text"].upper()
        if text.startswith("RETIRO"):
            boundaries["retiro"] = (word["x0"], word["x1"])
        # --- FIX: Aceptar "DEPOSITO" y "DEPÓSITO" (con tilde) ---
        elif text.startswith("DEPOSITO") or text.startswith("DEPÓSITO"):
            boundaries["deposito"] = (word["x0"], word["x1"])
        elif text.startswith("SALDO"):
            boundaries["saldo"] = (word["x0"], word["x1"])
    
    return boundaries if 'retiro' in boundaries and 'deposito' in boundaries else None

def group_words_into_lines(words: List[Dict], tolerance: int = 3) -> List[List[Dict]]:
    if not words: return []
    lines, current_line = [], [words[0]]
    for word in words[1:]:
        if abs(word["top"] - current_line[-1]["top"]) <= tolerance:
            current_line.append(word)
        else:
            lines.append(sorted(current_line, key=lambda w: w["x0"]))
            current_line = [word]
    lines.append(sorted(current_line, key=lambda w: w["x0"]))
    return lines

# --- FUNCIONES DE PARSEO DE METADATOS (CORREGIDAS) ---

def _parse_clabe(text: str) -> Optional[str]:
    match = re.search(r'CLABE Interbancaria\s+([0-9]{18})', text, re.IGNORECASE)
    return match.group(1) if match else None

def _parse_rfc(text: str) -> Optional[str]:
    """
    Extrae el RFC (12 o 13 caracteres), manejando las dos etiquetas posibles:
    - "Registro Federal de Contribuyentes:"
    - "RFC"
    """
    # Patrón unificado que busca cualquiera de las dos etiquetas.
    match = re.search(r'(?:Registro Federal de Contribuyentes|RFC)\s*:?\s*([A-Z0-9]{12,13})', text, re.IGNORECASE)
    return match.group(1) if match else None


def _parse_client_name(text: str) -> Optional[str]:
    # --- Método 1: Nombre del Receptor en CFDI (si viene en la sección fiscal) ---
    match = re.search(r'Nombre del Receptor\s+([^\n]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # --- Método 2: Formato empresarial / digital (con CLIENTE:) ---
    match = re.search(r'CLIENTE:\s*([^\n]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # --- Método 3: Razón social hardcoded (si aplica en tu caso) ---
    match = re.search(r'(CPA CONTROL DE COMPROBANTES DIGITALES S DE RL DE C)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # --- Método 4: Formato personal (línea en mayúsculas tipo "JUAN ANTONIO...") ---
    lines = text.split("\n")
    for line in lines:
        clean = line.strip()
        if re.fullmatch(r"[A-ZÁÉÍÓÚÑ\s]{10,}", clean):
            if not any(word in clean for word in ["BANAMEX", "ESTADO DE CUENTA", "CLIENTE", "RFC", "C.R."]):
                return clean

    return None

def _parse_account_number(text: str) -> Optional[str]:
    match = re.search(r'Número de cuenta de cheques\s+([0-9]+)', text)
    if match: return match.group(1)

    match = re.search(r'CONTRATO\s+([0-9]{10})', text)
    if match: return match.group(1)
    return None

# Función auxiliar para convertir a yyyy-mm-dd
def _format_flexible_date_banamex(date_str: str, default_year: Optional[str] = None) -> Optional[str]:
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
    }

    # Formato tipo "13 de abril del 2025" o "13 de abril 2025"
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)\s+(\d{4})', date_str, re.IGNORECASE)
    if m:
        d, mes, y = m.groups()
        mes = meses.get(mes.lower())
        if mes:
            return f"{y}-{mes:02d}-{int(d):02d}"

    # Formato tipo "01/FEB/2025"
    m = re.search(r'(\d{2})/([A-Z]{3})/(\d{4})', date_str, re.IGNORECASE)
    if m:
        d, mes_abbr, y = m.groups()
        try:
            dt = datetime.strptime(f"{d}/{mes_abbr}/{y}", "%d/%b/%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Si solo trae día y mes, agregamos año por defecto
    m = re.search(r'(\d{1,2})\s+de\s+(\w+)', date_str, re.IGNORECASE)
    if m and default_year:
        d, mes = m.groups()
        mes = meses.get(mes.lower())
        if mes:
            return f"{default_year}-{mes:02d}-{int(d):02d}"

    return None

def _parse_period(text: str) -> Tuple[Optional[str], Optional[str]]:
    # --- MÉTODO 1: MiCuenta (ej: "Período del 13 de abril al 12 de mayo del 2025") ---
    match = re.search(
        r'Per[ií]odo\s+del\s+(\d{1,2}\s+de\s+\w+)(?:\s+del)?\s+al\s+(\d{1,2}\s+de\s+\w+)(?:\s+del)?\s+(\d{4})',
        text,
        re.IGNORECASE
    )
    if match:
        year = match.group(3)
        start_str = f"{match.group(1)} {year}"
        end_str = f"{match.group(2)} {year}"
        start_date = _format_flexible_date_banamex(start_str, year)
        end_date = _format_flexible_date_banamex(end_str, year)
        return start_date, end_date

    # --- MÉTODO 2: Digital (ej: "RESUMEN DEL: 01/FEB/2025 AL 28/FEB/2025") ---
    match = re.search(
        r'RESUMEN DEL:\s*(\d{2}/[A-Z]{3}/\d{4})\s+AL\s+(\d{2}/[A-Z]{3}/\d{4})',
        text,
        re.IGNORECASE
    )
    if match:
        start_date = _format_flexible_date_banamex(match.group(1))
        end_date = _format_flexible_date_banamex(match.group(2))
        return start_date, end_date

    return None, None

def _parse_balances(text: str) -> Tuple[float, float]:
    initial_balance, final_balance = 0.0, 0.0
    match_ini = re.search(r'Saldo anterior\s+\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
    if match_ini: initial_balance = _clean_amount(match_ini.group(1))

    match_fin = re.search(r'(?:SALDO AL CORTE|SALDO AL \d{1,2} DE \w+ DE \d{4})\s+\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
    if match_fin: final_balance = _clean_amount(match_fin.group(1))
    
    return initial_balance, final_balance

def _parse_totals(text: str) -> Tuple[float, int, float, int]:
    imp_c, mov_c, imp_a, mov_a = 0.0, 0, 0.0, 0
    
    match_a = re.search(r'\(?\+\)?\s*(\d+)\s*Depósitos\s+\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
    if not match_a:
        match_a = re.search(r'Depósitos\s+([\d,]+\.\d{2})', text, re.IGNORECASE) # Formato sin conteo de mov.
        if match_a: imp_a = _clean_amount(match_a.group(1))
    else:
        mov_a = int(match_a.group(1))
        imp_a = _clean_amount(match_a.group(2))

    match_c = re.search(r'\(?\-\)?\s*(\d+)\s*Retiros(?:/Otros cargos)?\s+\$?([\d,]+\.\d{2})', text, re.IGNORECASE)
    if not match_c:
        match_c = re.search(r'Retiros/Otros cargos\s+([\d,]+\.\d{2})', text, re.IGNORECASE) # Formato sin conteo de mov.
        if match_c: imp_c = _clean_amount(match_c.group(1))
    else:
        mov_c = int(match_c.group(1))
        imp_c = _clean_amount(match_c.group(2))
        
    return imp_c, mov_c, imp_a, mov_a

# --- PARSER DE MOVIMIENTOS ---

# --- PARSER DE MOVIMIENTOS ---
def parse_transactions(pages: List[pdfplumber.page.Page], year: str) -> List[Dict[str, any]]:
    all_transactions = []
    column_boundaries = None

    transaction_blocks = []
    current_block = []
    in_tx_section = False
    
    for page in pages:
        if not column_boundaries:
            column_boundaries = find_column_boundaries(page)
        
        lines = group_words_into_lines(page.extract_words(x_tolerance=2, y_tolerance=3))
        
        for line_words in lines:
            line_text = " ".join(w['text'] for w in line_words)
            if "DETALLE DE OPERACIONES" in line_text.upper(): in_tx_section = True
            if not in_tx_section: continue
            if any(marker in line_text.upper() for marker in ["SALDO MINIMO REQUERIDO", "RESUMEN OPERACIONES TARJETA", "GLOSARIO"]):
                in_tx_section = False
                break
                
            if re.match(r"^\d{1,2}\s+[A-Z]{3}", line_text.upper()):
                if current_block: transaction_blocks.append(current_block)
                current_block = [line_words]
            elif current_block:
                current_block.append(line_words)
    
    if current_block: transaction_blocks.append(current_block)

    if not column_boundaries: return []

    for block in transaction_blocks:
        first_line_text = " ".join(w['text'] for w in block[0])
        date_match = re.match(r"(\d{1,2})\s+([A-Z]{3})", first_line_text.upper())
        if not date_match: continue
        
        day, month_str = date_match.groups()
        date = _format_date_banamex(f"{day} {month_str}", year)
        
        retiro, deposito, saldo = 0.0, 0.0, 0.0
        description_parts = []
        
        all_words_in_block = [word for line in block for word in line]

        for word in all_words_in_block:
            cx = (word["x0"] + word["x1"]) / 2
            word_text = word['text']
            
            try:
                # Check if the word is a number before cleaning
                float(word_text.replace(',', ''))
                is_numeric = True
            except ValueError:
                is_numeric = False

            if is_numeric:
                if column_boundaries['retiro'][0] - 20 <= cx <= column_boundaries['retiro'][1] + 20:
                    retiro += _clean_amount(word_text)
                elif column_boundaries['deposito'][0] - 20 <= cx <= column_boundaries['deposito'][1] + 20:
                    deposito += _clean_amount(word_text)
                elif 'saldo' in column_boundaries and column_boundaries['saldo'][0] - 20 <= cx <= column_boundaries['saldo'][1] + 20:
                    # Saldo no se suma, se sobrescribe con el último encontrado
                    saldo = _clean_amount(word_text)
                else:
                    description_parts.append(word_text)
            else:
                 description_parts.append(word_text)
        
        clean_desc = re.sub(r"^\d{1,2}\s+[A-Z]{3}\s+", "", " ".join(description_parts)).strip()
        
        if clean_desc or (retiro > 0 or deposito > 0):
            all_transactions.append({"Fecha": date, "Descripción": clean_desc, "Retiro": retiro, "Deposito": deposito, "Saldo": saldo})

    return all_transactions

# --- FUNCIÓN ORQUESTADORA PRINCIPAL ---

def parse(pdf: pdfplumber.PDF, year: str) -> Dict[str, any]:
    """
    Parsea un estado de cuenta de Banamex y extrae metadatos y transacciones.
    """
    full_text = "\n".join(page.extract_text(x_tolerance=2, y_tolerance=0) or "" for page in pdf.pages)
    
    periodo_inicial, periodo_final = _parse_period(full_text)
    effective_year = datetime.strptime(periodo_final, "%Y-%m-%d").year if periodo_final else year

    clabe = _parse_clabe(full_text)
    rfc = _parse_rfc(full_text)
    client_name = _parse_client_name(full_text)
    account_number = _parse_account_number(full_text)
    saldo_inicial, saldo_final = _parse_balances(full_text)
    imp_c, mov_c, imp_a, mov_a = _parse_totals(full_text)
    
    transactions = parse_transactions(pdf.pages, str(effective_year))
    
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