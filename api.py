# api.py
import base64
import io
import re
from typing import List, Dict, Optional

import pdfplumber
from flask import Flask, request, jsonify
from PyPDF2 import PdfReader, PdfWriter

from parsers import bbva_parser

app = Flask(__name__)

BANK_PARSERS = {
    "BBVA": bbva_parser,
}

def identify_bank_and_year(pdf: pdfplumber.PDF) -> (Optional[str], Optional[str]):
    """
    Identifica el banco y el año buscando en las primeras dos páginas del PDF.
    """
    bank, year = None, None
    
    # Itera sobre las dos primeras páginas para encontrar la información
    for page in pdf.pages[:2]:
        text = page.extract_text().upper()
        
        # Identificar banco
        if not bank:
            if "BBVA" in text:
                bank = "BBVA"
            else:
                bank = "Banco no soportado"
        
        # Extraer año
        if not year:
            match_bbva = re.search(r'DEL \d{2}/\d{2}/(\d{4})', text)
            
            if match_bbva:
                year = match_bbva.group(1)

        # Si ya encontramos ambos, salimos del bucle
        if bank and year:
            break
            
    # Si después del bucle no se encontró el año, se asigna el actual
    if not year:
        from datetime import datetime
        year = str(datetime.now().year)
        
    return bank, year

@app.route('/extraer_datos_pdf', methods=['POST'])
def extract_endpoint():
    """
    Endpoint multibancario para extraer transacciones de un PDF en Base64.
    """
    if not request.json or 'pdf_base64' not in request.json:
        return jsonify({"error": "Petición inválida. Se requiere JSON con 'pdf_base64'."}), 400

    base64_string = request.json['pdf_base64']
    
    try:
        pdf_bytes = base64.b64decode(base64_string)
        pdf_stream = io.BytesIO(pdf_bytes)
    except Exception as e:
        return jsonify({"error": f"Error de decodificación Base64: {e}"}), 400

    # Capa de reparación de PDF
    repaired_stream = io.BytesIO()
    try:
        reader = PdfReader(pdf_stream)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.write(repaired_stream)
        repaired_stream.seek(0)
    except Exception:
        pdf_stream.seek(0)
        repaired_stream = pdf_stream

    try:
        with pdfplumber.open(repaired_stream) as pdf:
            bank, year = identify_bank_and_year(pdf)
            
            if not bank or bank not in BANK_PARSERS:
                return jsonify({"error": "No se pudo identificar el banco del PDF o no hay un parser disponible."}), 400
            
            print(f"Banco identificado: {bank}, Año: {year}. Usando el parser correspondiente...")
            
            parser_module = BANK_PARSERS[bank]
            transactions = parser_module.parse(pdf, year)
            
            print(f"Extracción exitosa. Se encontraron {len(transactions)} transacciones.")
            return jsonify(transactions), 200
            
    except Exception as e:
        import traceback
        print(f"ERROR: Ocurrió un error interno durante el procesamiento del PDF: {traceback.format_exc()}")
        return jsonify({"error": "Error interno del servidor al procesar el archivo PDF.", "details": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)