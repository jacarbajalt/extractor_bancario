import sys
import logging

# La siguiente línea ya no es estrictamente necesaria si usaste la 
# configuración de Apache con 'python-path', pero no hace daño dejarla.
sys.path.insert(0, '/var/www/html/proyectos/extractor_bancario/')

logging.basicConfig(stream=sys.stderr)

from api import app as application