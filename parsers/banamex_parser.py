# parsers/banamex_parser.py
import pdfplumber
import re
from typing import List, Dict, Optional, Any
from datetime import datetime

# Se definen constantes para el procesamiento
MONTH_MAP = {
    'ENE': '01', 'FEB': '02', 'MAR': '03', 'ABR': '04', 'MAY': '05', 'JUN': '06',
    'JUL': '07', 'AGO': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DIC': '12'
}

# Palabras clave para ignorar en la sección de movimientos
IGNORE_PATTERNS = [
    r"FECHA\s+CONCEPTO\s+RETIROS\s+DEPOSITOS\s+SALDO",
    r"SALDO ANTERIOR",
    r"RESUMEN POR MEDIOS DE ACCESO",
    r"Cheques\s+\d+\s+\d+",
]

def _clean_amount(text: Optional[str]) -> float:
    """Limpia una cadena de texto para convertirla en un flotante."""
    if not text or not isinstance(text, str):
        return 0.0
    try:
        # Remueve el signo de pesos, comas y espacios en blanco
        return float(text.replace('$', '').replace(',', '').strip())
    except (ValueError, AttributeError):
        return 0.0

def find_header_and_boundaries(page: pdfplumber.page.Page) -> Optional[tuple]:
    """
    Encuentra la cabecera de la tabla, su límite vertical inferior
    y las coordenadas X de las columnas.
    """
    # Usa "CONCEPTO" como ancla para encontrar la fila de la cabecera
    header_words = [word for word in page.extract_words() if "CONCEPTO" in word['text'].upper()]
    if not header_words:
        return None

    header_top = header_words[0]['top']
    words_in_header = [word for word in page.extract_words(keep_blank_chars=True) if abs(word['top'] - header_top) < 5]
    
    # **CAMBIO 1: Calcular el límite vertical**
    # Todo lo que esté por encima de este punto será ignorado.
    header_bottom = max(w['bottom'] for w in words_in_header) if words_in_header else 0

    boundaries = {}
    col_names = ["RETIROS", "DEPOSITOS", "SALDO"]
    for name in col_names:
        for word in words_in_header:
            if name in word['text'].upper():
                boundaries[name.lower()] = (word['x0'], word['x1'])
                break
    
    if 'retiros' in boundaries and 'depositos' in boundaries:
        # **CAMBIO 2: Devolver el límite vertical junto con las coordenadas**
        return header_bottom, boundaries
    
    return None

def group_words_by_line(words: List[Dict], tolerance: int = 7) -> List[List[Dict]]:
    """Agrupa palabras extraídas con pdfplumber en líneas cohesivas."""
    if not words:
        return []
    lines = []
    current_line = [words[0]]
    for word in words[1:]:
        # Si la palabra está verticalmente cerca de la última, es parte de la misma línea
        if abs(word['top'] - current_line[-1]['top']) <= tolerance:
            current_line.append(word)
        else:
            lines.append(sorted(current_line, key=lambda w: w['x0']))
            current_line = [word]
    lines.append(sorted(current_line, key=lambda w: w['x0']))
    return lines

def is_line_to_ignore(line_text: str) -> bool:
    """Verifica si una línea debe ser ignorada basado en patrones."""
    return any(re.search(pat, line_text, re.IGNORECASE) for pat in IGNORE_PATTERNS)

def parse(pdf: pdfplumber.PDF, year: str) -> Dict[str, Any]:
    """
    Función principal para parsear un estado de cuenta de Banamex.
    Extrae metadatos, saldos, totales y una lista detallada de movimientos.
    """
    full_text = ""
    first_page_text = pdf.pages[0].extract_text() or ""
    full_text = first_page_text + "\n" + "".join([p.extract_text() or "" for p in pdf.pages[1:]])
    
    # 1. Extracción de Metadatos y Totales del Resumen (más robusto)
    metadata = {
        "clabe": None,
        "numero_cuenta": None,
        "rfc": None,
        "nombre_cliente": None,
        "saldo_inicial": 0.0,
        "saldo_final": 0.0,
        "total_cargos": 0.0,
        "total_abonos": 0.0,
        "periodo": None,
        "fecha_corte": None
    }
    
    # Usa expresiones regulares en el texto de la primera página para mayor eficiencia
    metadata["nombre_cliente"] = (re.search(r'^(CPA CONTROL DE COMPROBANTES DIGITALES S DE RL DE C)', first_page_text, re.MULTILINE).group(1) or "").strip()
    metadata["rfc"] = (re.search(r'Registro Federal de Contribuyentes:\s*([A-Z0-9]{12,13})', first_page_text).group(1) or "").strip()
    metadata["clabe"] = (re.search(r'CLABE Interbancaria\s*([\d\s]+)', first_page_text).group(1) or "").replace(" ", "")
    metadata["numero_cuenta"] = (re.search(r'Nacional\s+(\d{10})', first_page_text).group(1) or "").strip()
    metadata["periodo"] = (re.search(r'RESUMEN DEL:\s*(.+)', first_page_text).group(1) or "").strip()
    metadata["fecha_corte"] = (re.search(r'ESTADO DE CUENTA AL\s+(.+)', first_page_text).group(1) or "").strip()

    # Extracción de saldos y totales del resumen
    resumen_match = re.search(r'Saldo Anterior\s+\$?([\d,.]+)[\s\S]+?Depósitos\s+\$?([\d,.]+)[\s\S]+?Retiros\s+\$?([\d,.]+)[\s\S]+?SALDO AL.+?\$?([\d,.]+)', first_page_text)
    if resumen_match:
        metadata["saldo_inicial"] = _clean_amount(resumen_match.group(1))
        metadata["total_abonos"] = _clean_amount(resumen_match.group(2))
        metadata["total_cargos"] = _clean_amount(resumen_match.group(3))
        metadata["saldo_final"] = _clean_amount(resumen_match.group(4))
        
    year = re.search(r'(\d{4})', metadata["fecha_corte"]).group(1) if metadata["fecha_corte"] else ""

    # 2. Extracción de Movimientos usando coordenadas
    movimientos = []
    in_transaction_section = False

    for page in pdf.pages:
        page_text = page.extract_text()
        if "DETALLE DE OPERACIONES" in page_text:
            in_transaction_section = True
        if "SALDO MINIMO REQUERIDO" in page_text:
            in_transaction_section = False
        
        if not in_transaction_section:
            continue
            
        header_info = find_header_and_boundaries(page)
        if not header_info:
            continue

        header_bottom, boundaries = header_info
        words = [word for word in page.extract_words() if word['top'] > header_bottom]
        retiros_x0, retiros_x1 = boundaries['retiros']
        depositos_x0, depositos_x1 = boundaries['depositos']
        saldo_x0, saldo_x1 = boundaries['saldo']

        lines_of_words = group_words_by_line(words)

        for line_words in lines_of_words:
            line_text = " ".join([w['text'] for w in line_words])
            
            if is_line_to_ignore(line_text):
                continue

            date_match = re.match(r'^(\d{2})\s+([A-Z]{3})', line_text)
            
            # Asigna palabras a las columnas correctas
            description_words, retiro_words, deposito_words, saldo_words = [], [], [], []
            for word in line_words:
                if retiros_x0 <= word['x0'] < retiros_x1 + 20:
                    retiro_words.append(word['text'])
                elif depositos_x0 <= word['x0'] < depositos_x1 + 10:
                    deposito_words.append(word['text'])
                elif saldo_x0 <= word['x0'] < saldo_x1 + 20:
                    saldo_words.append(word['text'])
                else:
                    description_words.append(word['text'])
            
            retiro = _clean_amount(" ".join(retiro_words))
            deposito = _clean_amount(" ".join(deposito_words))
            saldo = _clean_amount(" ".join(saldo_words))
            descripcion = " ".join(description_words)

            if date_match:
                day, month_abbr = date_match.groups()
                month = MONTH_MAP.get(month_abbr, "00")
                fecha = f"{year}-{month}-{day}"
                
                # Limpia la fecha de la descripción
                descripcion = re.sub(r'^(\d{2})\s+([A-Z]{3})\s*', '', descripcion).strip()
                
                if descripcion or retiro or deposito:
                    movimientos.append({
                        "Fecha": fecha,
                        "Descripción": descripcion,
                        "Retiro": retiro,
                        "Deposito": deposito,
                        "Saldo": saldo,
                        "Banco": "Banamex"
                    })
            elif (descripcion or retiro or deposito) and movimientos:
                # Es una línea de continuación para la descripción
                movimientos[-1]["Descripción"] += " " + descripcion.strip()
                # Si hay montos "huérfanos", los asigna al movimiento anterior
                if retiro > 0: movimientos[-1]["Retiro"] += retiro
                if deposito > 0: movimientos[-1]["Deposito"] += deposito
                if saldo > 0: movimientos[-1]["Saldo"] = saldo # Sobrescribe el saldo con el último valor válido

    return {"metadata": metadata, "movimientos": movimientos}