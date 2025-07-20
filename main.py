"""
Fase 8: Conversión a API con Flask
La IA ahora funciona como un servidor backend, lista para recibir peticiones
de un cliente (como una app móvil). La lógica se ha separado de la salida.
"""

# --- MÓDULOS NECESARIOS ---
import json # Para leer y escribir la memoria en formato JSON
import os   # Para comprobar si el archivo de memoria ya existe
import google.generativeai as genai # El cerebro de Google
# Los módulos de voz (sr, pyttsx3) se eliminan del backend.
# El cliente (móvil) se encargará de la voz.
import webbrowser # Para abrir el navegador web
import subprocess # Para ejecutar comandos del sistema
from dotenv import load_dotenv # Para cargar nuestra clave de API secreta

# --- LOGGER GLOBAL ---
import logging

def setup_global_logger(name="NexusApp"):
    """Configura y devuelve un logger global."""
    logger = logging.getLogger(name)
    if not logger.hasHandlers():
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger

# --- DATABASE SETUP ---
from sqlalchemy import create_engine, Column, String, Text, inspect
from sqlalchemy.orm import sessionmaker, declarative_base

# Get the database URL from environment variables (provided by Render)
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # SQLAlchemy 1.4+ requires "postgresql://" instead of "postgres://"
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = None
SessionLocal = None
if DATABASE_URL:
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class MemoryDB(Base):
    __tablename__ = "memories"
    session_id = Column(String, primary_key=True, index=True)
    memory_json = Column(Text, nullable=False)

class Nexus:
    def __init__(self, session_id: str):
        """Inicializa la IA, carga la configuración y la memoria."""
        self.session_id = session_id
        self._setup_logging()
        self.logger.info(f"Inicializando sistemas para la sesión: {session_id}")
        # Cargar API Key
        load_dotenv()
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: # Fail fast if the key is missing
            raise ValueError("No se encontró la clave de API de Google. Por favor, configúrala en el archivo .env")
        genai.configure(api_key=api_key)

        # La memoria se carga desde la DB o un archivo, según la configuración.
        self.memoria = self._cargar_memoria()

        # Memoria a corto plazo para el contexto de la conversación
        self.conversation_history = []
        self.logger.info(f"Cerebro Nexus para la sesión {self.session_id} inicializado y listo.")

    def _setup_logging(self):
        """Configura el logger para la IA."""
        self.logger = logging.getLogger(f"NexusIA.{self.session_id}")

    def _cargar_memoria(self):
        """Carga la memoria desde la base de datos si está configurada, si no, usa archivos locales."""
        if DATABASE_URL and SessionLocal:
            db = SessionLocal()
            try:
                db_memory = db.query(MemoryDB).filter(MemoryDB.session_id == self.session_id).first()
                if db_memory:
                    self.logger.info(f"Memoria encontrada en la DB para la sesión {self.session_id}.")
                    return json.loads(db_memory.memory_json)
                else:
                    self.logger.info(f"No se encontró memoria en la DB para la sesión {self.session_id}. Creando una nueva.")
                    return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}
            except Exception as e:
                self.logger.error(f"Error al cargar memoria desde la DB: {e}. Usando memoria en blanco.", exc_info=True)
                return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}
            finally:
                db.close()
        else:
            # Fallback to file-based memory for local development
            memoria_archivo = f"memoria_{self.session_id}.json"
            if os.path.exists(memoria_archivo):
                self.logger.info(f"DB no configurada. Usando archivo de memoria local: {memoria_archivo}")
                try:
                    with open(memoria_archivo, 'r', encoding='utf-8') as archivo:
                        return json.load(archivo)
                except json.JSONDecodeError:
                    self.logger.error(f"Error al decodificar el archivo de memoria local '{memoria_archivo}'. Se creará una nueva memoria.")
                    return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}
            else:
                self.logger.info(f"DB no configurada y no se encontró archivo local. Creando memoria nueva.")
                return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}

    def _guardar_memoria(self):
        """Guarda la memoria en la base de datos si está configurada, si no, usa archivos locales."""
        if DATABASE_URL and SessionLocal:
            db = SessionLocal()
            try:
                db_memory = db.query(MemoryDB).filter(MemoryDB.session_id == self.session_id).first()
                memory_string = json.dumps(self.memoria, ensure_ascii=False, indent=4)
                if db_memory:
                    db_memory.memory_json = memory_string
                else:
                    db_memory = MemoryDB(session_id=self.session_id, memory_json=memory_string)
                    db.add(db_memory)
                db.commit()
                self.logger.info(f"Memoria para la sesión {self.session_id} guardada en la DB.")
            except Exception as e:
                self.logger.error(f"Error al guardar memoria en la DB: {e}", exc_info=True)
                db.rollback()
            finally:
                db.close()
        else:
            # Fallback to file-based memory
            memoria_archivo = f"memoria_{self.session_id}.json"
            self.logger.info(f"DB no configurada. Guardando conocimiento en archivo local: {memoria_archivo}")
            try:
                with open(memoria_archivo, 'w', encoding='utf-8') as archivo:
                    json.dump(self.memoria, archivo, ensure_ascii=False, indent=4)
            except Exception as e:
                self.logger.error(f"Error al guardar la memoria local: {e}")

    def pensar_con_gemini(self, pregunta: str) -> str:
        """
        Envía una pregunta al modelo de Gemini y devuelve la respuesta.
        Ahora incluye contexto de la memoria local y el historial de la conversación.
        """
        self.logger.debug("Consultando al cerebro externo Gemini...")

        # Construir el historial para el prompt
        historial_texto = "\n".join([f"{'Usuario' if i % 2 == 0 else 'IA'}: {turno}" for i, turno in enumerate(self.conversation_history[-6:])]) # Últimos 6 turnos

        prompt_completo = (
            f"Eres una IA servicial y amigable llamada {self.memoria.get('nombre', 'IA')}.\n"
            f"El nombre de tu usuario es {self.memoria.get('nombre_usuario', 'desconocido')}.\n"
            f"Estos son algunos datos que has aprendido sobre el usuario y sus preferencias (en formato JSON): "
            f"{json.dumps(self.memoria.get('datos_aprendidos', {}), ensure_ascii=False, indent=2)}.\n"
            f"Usa esta información para que tus respuestas suenen más personales, pero sin ser repetitivo.\n"
            f"A continuación se muestra el historial reciente de la conversación:\n"
            f"--- INICIO HISTORIAL ---\n"
            f"{historial_texto}\n"
            f"--- FIN HISTORIAL ---\n"
            f"Basado en todo lo anterior, responde a la siguiente pregunta o comentario del usuario de forma natural y útil: \"{pregunta}\""
        )
        try:
            modelo = genai.GenerativeModel('gemini-1.5-flash-latest')
            respuesta = modelo.generate_content(prompt_completo.strip())
            self.logger.debug("Respuesta recibida del modelo Gemini.")
            return respuesta.text
        except Exception as e:
            self.logger.error(f"Error al contactar a Google Gemini: {e}", exc_info=True)
            return "Lo siento, parece que tengo problemas para contactar a Google Gemini en este momento."

    def pensar_y_responder(self, comando: str) -> dict:
        """
        Esta es la función principal del "pensamiento".
        Recibe un comando y devuelve un diccionario con la respuesta y la acción.
        """
        if not comando:
            return {"speech": "", "action": {"type": "none"}}

        # --- Lógica de Comandos ---
        # 1. Comandos de configuración inicial (tienen prioridad)
        if not self.memoria.get("nombre"):
            return {"speech": self._handle_set_ia_name(comando), "action": {"type": "none"}}

        # 2. Despachador de comandos basado en palabras clave
        #    Este diccionario mapea una función (handler) a una lista de palabras clave.
        command_dispatcher = {
            self._handle_set_user_name: ["mi nombre es"],
            self._handle_get_user_name: ["¿cómo me llamo?", "cuál es mi nombre"],
            self._handle_remember_fact: ["recuerda que"],
            self._handle_recall_fact: ["qué sabes sobre", "recuérdame"],
            self._handle_open_website: ["abre", "inicia"],
            self._handle_google_search: ["busca en google"],
            self._handle_execute_app: ["ejecuta"],
            self._handle_exit: ["adiós", "hasta luego", "apágate"],
        }

        for handler, keywords in command_dispatcher.items():
            for keyword in keywords:
                if comando.startswith(keyword):
                    # Los handlers ahora devuelven un diccionario de acción
                    return handler(comando)

        # 3. Activación por nombre y consulta a Gemini
        nombre_ia = self.memoria.get("nombre", "").lower()
        if nombre_ia and comando.startswith(nombre_ia):
            return self._handle_gemini_query(comando)

        # 4. Si no es un comando conocido ni empieza con el nombre, no hace nada.
        self.logger.debug(f"Comando ignorado por no ser un comando directo ni empezar con el nombre de la IA: '{comando}'")
        return {"speech": "", "action": {"type": "none"}}

    # --- Métodos manejadores de comandos (Handlers) ---
    # AHORA DEVUELVEN TEXTO O DICCIONARIOS, NO LLAMAN A self.hablar()

    def _handle_set_ia_name(self, comando):
        nombre_elegido = comando.strip().capitalize()
        self.memoria["nombre"] = nombre_elegido
        self._guardar_memoria()
        return {
            "speech": f"¡Entendido! A partir de ahora mi nombre es {nombre_elegido}. ¿En qué puedo ayudarte?",
            "action": {"type": "none"}
        }

    def _handle_set_user_name(self, comando):
        nombre_nuevo = comando.split("mi nombre es")[-1].strip().capitalize()
        self.memoria["nombre_usuario"] = nombre_nuevo
        self._guardar_memoria()
        return {"speech": f"¡Hola, {nombre_nuevo}! Un placer conocerte. He guardado tu nombre.", "action": {"type": "none"}}

    def _handle_get_user_name(self, comando):
        nombre_usuario = self.memoria.get("nombre_usuario")
        if nombre_usuario:
            speech = f"Te llamas {nombre_usuario}, ¿verdad?"
        else:
            speech = "Aún no me has dicho tu nombre. Puedes decir 'mi nombre es...' para que lo recuerde."
        return {"speech": speech, "action": {"type": "none"}}

    def _handle_remember_fact(self, comando):
        dato_a_recordar = comando.replace("recuerda que", "", 1).strip()
        try:
            clave, valor = dato_a_recordar.split(" es ", 1)
            self.memoria["datos_aprendidos"][clave.strip()] = valor.strip()
            self._guardar_memoria()
            speech = f"Entendido. He guardado que '{clave.strip()}' es '{valor.strip()}'."
        except ValueError:
            speech = "Para que recuerde algo, por favor usa el formato: 'recuerda que [dato] es [valor]'."
        return {"speech": speech, "action": {"type": "none"}}

    def _handle_recall_fact(self, comando):
        # Normalizar el comando para extraer la clave
        clave_a_buscar = comando.replace("qué sabes sobre", "").replace("recuérdame", "").strip()
        respuesta_memoria = self.memoria["datos_aprendidos"].get(clave_a_buscar)
        if respuesta_memoria:
            speech = f"Recuerdo que {clave_a_buscar} es {respuesta_memoria}."
        else:
            speech = f"No tengo información específica sobre '{clave_a_buscar}'. Le preguntaré a mi cerebro externo."
            respuesta_inteligente = self.pensar_con_gemini(comando)
            speech += f" {respuesta_inteligente}" # Se puede concatenar o manejar diferente
        return {"speech": speech, "action": {"type": "none"}}

    def _handle_open_website(self, comando):
        sitio_web = comando.replace("abre", "").replace("inicia", "").strip()
        if not sitio_web.startswith("http"):
            sitio_web = "https://" + sitio_web
        return {
            "speech": f"Claro, abriendo {sitio_web}.",
            "action": {"type": "open_url", "payload": {"url": sitio_web}}
        }

    def _handle_google_search(self, comando):
        termino_busqueda = comando.replace("busca en google", "").strip()
        url_busqueda = f"https://www.google.com/search?q={termino_busqueda.replace(' ', '+')}"
        return {
            "speech": f"Buscando '{termino_busqueda}' en Google.",
            "action": {"type": "open_url", "payload": {"url": url_busqueda}}
        }

    def _handle_execute_app(self, comando):
        aplicacion = comando.replace("ejecuta", "").strip().lower()
        mapa_apps = {
            "calculadora": "calc.exe",
            "bloc de notas": "notepad.exe",
            "explorador de archivos": "explorer.exe"
        }
        for app_name, executable in mapa_apps.items():
            if app_name in aplicacion:
                # Esta acción sigue siendo específica del servidor, pero la estructuramos para el futuro.
                # Un cliente móvil podría interpretar "execute_app" para abrir una app de Android/iOS.
                # Por ahora, la ejecutamos en el servidor para mantener la funcionalidad.
                self.logger.info(f"Ejecutando '{executable}' en el servidor.")
                subprocess.Popen([executable])
                return {
                    "speech": f"Ejecutando {app_name} en el dispositivo servidor.",
                    "action": {"type": "execute_app", "payload": {"app_name": app_name}}
                }
        
        # Si no se encuentra la app, se devuelve una respuesta sin acción.
        return {
            "speech": f"No sé cómo ejecutar '{aplicacion}'. Puedes enseñarme agregándolo al código.",
            "action": {"type": "none"}
        }

    def _handle_gemini_query(self, comando):
        nombre_ia = self.memoria.get("nombre", "").lower()
        comando_real = comando[len(nombre_ia):].strip()
        if not comando_real:
            speech = f"¡Hola! Soy {self.memoria.get('nombre')}. ¿Qué necesitas?"
        else:
            speech = self.pensar_con_gemini(comando_real)
        return {"speech": speech, "action": {"type": "none"}}

    def _handle_exit(self, comando):
        nombre_usuario = self.memoria.get("nombre_usuario", "tú")
        if nombre_usuario == "tú":
            speech = "¡Hasta pronto!"
        else:
            speech = f"¡Hasta pronto, {nombre_usuario}!"
        return {"speech": speech, "action": {"type": "exit"}}

    def saludar(self):
        """Genera el saludo inicial de la IA."""
        nombre_recordado = self.memoria.get("nombre")
        nombre_usuario_recordado = self.memoria.get("nombre_usuario")
        if nombre_recordado:
            if nombre_usuario_recordado:
                return f"¡Hola de nuevo, {nombre_usuario_recordado}! Soy {nombre_recordado} y estoy lista para ayudarte."
            else:
                return f"¡Hola de nuevo! Soy {nombre_recordado}. Estoy lista para ayudarte."
        else:
            return "Hola, soy tu nueva IA. Aún no tengo un nombre. Por favor, dime cómo quieres llamarme."

# --- INICIO DE LA API CON FLASK ---
from flask import Flask, request, jsonify

# Para permitir peticiones desde el navegador (necesario para la app web)
from flask_cors import CORS # type: ignore

class NexusInstanceManager:
    """Gestiona múltiples instancias de la IA, una por sesión."""
    def __init__(self):
        self._instances = {}

    def get_or_create_instance(self, session_id: str) -> Nexus:
        """Obtiene una instancia existente o crea una nueva si no existe."""
        if session_id not in self._instances:
            print(f"Creando nueva instancia de Nexus para la sesión: {session_id}")
            self._instances[session_id] = Nexus(session_id=session_id)
        return self._instances[session_id]

app = Flask(__name__)

# Habilitar CORS para permitir que la app web se comunique con el backend
CORS(app)

# Creamos un administrador global para todas las instancias de Nexus.
instance_manager = NexusInstanceManager()

# Logger para la aplicación Flask en sí.
app_logger = setup_global_logger()

@app.route('/', methods=['GET'])
def health_check():
    """Endpoint de bienvenida o 'health check'."""
    # Este endpoint no necesita una sesión, es solo para verificar que el servidor está vivo.
    return jsonify({
        "status": "online",
        "message": "Bienvenido al servidor de Nexus IA. El cerebro está activo.",
        "endpoints_disponibles": {
            "saludo": "/saludo (GET)",
            "interactuar": "/interact (POST)"
        },
        "info": "Todas las peticiones a /saludo e /interact requieren una cabecera 'X-Session-ID'."
    })

@app.route('/interact', methods=['POST'])
def interactuar():
    """Endpoint principal para interactuar con la IA."""
    session_id = request.headers.get('X-Session-ID')
    try:

        if not session_id:
            return jsonify({"error": "La cabecera 'X-Session-ID' es requerida."}), 400
        
        datos = request.json
        if not datos or 'comando' not in datos:
            return jsonify({"error": "El campo 'comando' es requerido."}), 400
        
        nexus_instance = instance_manager.get_or_create_instance(session_id)
        comando = datos['comando'].lower()
        nexus_instance.logger.info(f"Comando recibido de [{session_id}]: '{comando}'")

        # Añadimos el comando del usuario al historial ANTES de pensar la respuesta
        nexus_instance.conversation_history.append(comando)
        
        respuesta = nexus_instance.pensar_y_responder(comando)
        
        # Añadimos la respuesta de la IA al historial de conversación
        if respuesta.get("speech"):
            nexus_instance.conversation_history.append(respuesta.get("speech"))

        nexus_instance.logger.info(f"Respuesta generada: {respuesta}")
        return jsonify(respuesta)

    except Exception as e:
        # Usamos el logger global para garantizar que el error se registre siempre.
        log_message = f"Error en el endpoint /interact: {e}"
        if session_id:
            log_message += f" (Session: {session_id})"
        app_logger.error(log_message, exc_info=True)
        return jsonify({"error": "Ha ocurrido un error interno en el servidor."}), 500

@app.route('/saludo', methods=['GET'])
def saludo_inicial():
    """Endpoint para obtener el saludo inicial."""
    session_id = request.headers.get('X-Session-ID')
    if not session_id:
        return jsonify({"error": "La cabecera 'X-Session-ID' es requerida."}), 400
    
    nexus_instance = instance_manager.get_or_create_instance(session_id)
    saludo = nexus_instance.saludar()
    return jsonify({"speech": saludo, "action": {"type": "none"}})

@app.route('/admin/sessions', methods=['GET'])
def get_active_sessions():
    """Endpoint de administración para ver las sesiones activas."""
    active_sessions = list(instance_manager._instances.keys())
    return jsonify({"active_sessions": active_sessions, "count": len(active_sessions)})

if __name__ == '__main__':
    # Este bloque es para ejecutar el servidor localmente para pruebas.
    # Usa el servidor de desarrollo de Flask, que es ideal para depurar.
    # El comando 'gunicorn main:app' se usará en producción (Render).
    print("Iniciando servidor de desarrollo de Flask en http://127.0.0.1:5000")
    print("NOTA: Este modo es para pruebas. En producción, se usará Gunicorn.")
    app.run(host="0.0.0.0", port=5000, debug=True)


# Inicializa la aplicación (por ejemplo, crea las tablas de la base de datos si es necesario)
def init_app():
    if DATABASE_URL and engine:
        app_logger.info("Configuración de base de datos detectada.")
        Base.metadata.create_all(bind=engine, checkfirst=True)
        app_logger.info("Tablas de la base de datos verificadas/creadas.")

init_app()
