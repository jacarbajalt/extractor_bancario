# client.py
import requests
import base64
import json

# --- CONFIGURACIÓN ---
# La URL donde se está ejecutando tu API.
# Si ejecutas el cliente en la misma máquina que el servidor, usa 'localhost'.
API_URL = "http://localhost:5000/extract"
# El archivo PDF que quieres enviar para procesar.
PDF_TO_TEST = "/home/desarrollo8/Descargas/BBVAEDOS/BBVA_AGOS.pdf"
# --- FIN DE CONFIGURACIÓN ---

def test_api():
    """
    Lee un archivo PDF, lo codifica en Base64 y lo envía al endpoint de la API.
    """
    try:
        # 1. Leer el archivo PDF en modo binario
        with open(PDF_TO_TEST, "rb") as pdf_file:
            pdf_bytes = pdf_file.read()
        
        # 2. Codificar los bytes a Base64 y luego a una cadena de texto UTF-8
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # 3. Crear el payload JSON
        payload = {"pdf_base64": pdf_base64}
        
        print(f"Enviando '{PDF_TO_TEST}' a la API en {API_URL}...")
        
        # 4. Enviar la petición POST a la API
        response = requests.post(API_URL, json=payload)
        
        # 5. Procesar la respuesta
        if response.status_code == 200:
            print("¡Éxito! La API respondió correctamente.")
            transactions = response.json()
            print(f"Se encontraron {len(transactions)} transacciones:")
            
            # Imprimir las primeras 5 transacciones como ejemplo
            for i, trx in enumerate(transactions[:5]):
                print(f"  {i+1}: {trx['Fecha']} - {trx['Descripción'][:50]}... | Retiro: {trx['Retiro']} | Deposito: {trx['Deposito']}")
            
            # Opcional: Guardar el resultado en un archivo JSON
            with open("resultado_api.json", "w") as f:
                json.dump(transactions, f, indent=2)
            print("\nResultado completo guardado en 'resultado_api.json'")

        else:
            print(f"Error: La API respondió con el código de estado {response.status_code}")
            print("Respuesta del servidor:")
            print(response.json())

    except FileNotFoundError:
        print(f"Error: El archivo de prueba '{PDF_TO_TEST}' no fue encontrado.")
    except requests.exceptions.ConnectionError:
        print(f"Error de conexión: No se pudo conectar a la API en {API_URL}.")
        print("Asegúrate de que el servidor 'api.py' se esté ejecutando.")
    except Exception as e:
        print(f"Ocurrió un error inesperado en el cliente: {e}")

if __name__ == "__main__":
    test_api()