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
import sys # Para comprobar el sistema operativo
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
# Importar la configuración de la base de datos desde el archivo centralizado
from database import SessionLocal, MemoryDB, DATABASE_URL

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

        # La memoria y el historial de conversación se cargan desde la DB o un archivo.
        self.memoria, self.conversation_history = self._cargar_memoria()
        self.logger.info(f"Cerebro Nexus para la sesión {self.session_id} inicializado y listo.")

    def _setup_logging(self):
        """Configura el logger para la IA."""
        self.logger = logging.getLogger(f"NexusIA.{self.session_id}")

        # El despachador de comandos se define una vez por instancia para mayor eficiencia.
        self.command_dispatcher = {
            self._handle_set_user_name: ["mi nombre es"],
            self._handle_get_user_name: ["¿cómo me llamo?", "cuál es mi nombre"],
            self._handle_remember_fact: ["recuerda que"],
            self._handle_recall_fact: ["qué sabes sobre", "recuérdame"],
            self._handle_open_website: ["abre", "inicia"],
            self._handle_google_search: ["busca en google"],
            self._handle_exit: ["adiós", "hasta luego", "apágate"],
        }

    def _cargar_memoria(self):
        """Carga la memoria y el historial desde la DB si está configurada, si no, usa archivos locales."""
        if DATABASE_URL and SessionLocal:
            # Usar 'with' para asegurar que la sesión de la DB se cierre correctamente
            with SessionLocal() as db:
                try:
                    db_memory = db.query(MemoryDB).filter(MemoryDB.session_id == self.session_id).first()
                    if db_memory:
                        self.logger.info(f"Memoria encontrada en la DB para la sesión {self.session_id}.")
                        memory = json.loads(db_memory.memory_json)
                        history = json.loads(db_memory.history_json) if db_memory.history_json else []
                        self.logger.info(f"Cargados {len(history)} turnos del historial de conversación.")
                        return memory, history
                    else:
                        self.logger.info(f"No se encontró memoria en la DB para la sesión {self.session_id}. Creando una nueva.")
                        return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}, []
                except Exception as e:
                    self.logger.error(f"Error al cargar memoria desde la DB: {e}. Usando estado en blanco.", exc_info=True)
                    return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}, []
        else:
            # Fallback to file-based memory for local development
            memoria_archivo = f"memoria_{self.session_id}.json"
            if os.path.exists(memoria_archivo):
                self.logger.info(f"DB no configurada. Usando archivo de memoria local: {memoria_archivo}")
                try:
                    with open(memoria_archivo, 'r', encoding='utf-8') as archivo:
                        data = json.load(archivo)
                        # El archivo local puede o no tener historial
                        memory = data.get("memoria", data) # Para compatibilidad con versiones antiguas
                        history = data.get("historial", [])
                        return memory, history
                except json.JSONDecodeError:
                    self.logger.error(f"Error al decodificar el archivo de memoria local '{memoria_archivo}'. Se creará una nueva memoria.")
                    return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}, []
            else:
                self.logger.info(f"DB no configurada y no se encontró archivo local. Creando memoria nueva.")
                return {"nombre": "", "nombre_usuario": "", "datos_aprendidos": {}}, []

    def _guardar_memoria(self):
        """Guarda la memoria y el historial en la DB si está configurada, si no, usa archivos locales."""
        if DATABASE_URL and SessionLocal:
            # Usar 'with' para asegurar que la sesión de la DB se cierre correctamente
            with SessionLocal() as db:
                try:
                    db_memory = db.query(MemoryDB).filter(MemoryDB.session_id == self.session_id).first()
                    memory_string = json.dumps(self.memoria, ensure_ascii=False, indent=4)
                    history_string = json.dumps(self.conversation_history, ensure_ascii=False, indent=4)

                    if db_memory:
                        db_memory.memory_json = memory_string
                        db_memory.history_json = history_string
                    else:
                        db_memory = MemoryDB(session_id=self.session_id, memory_json=memory_string, history_json=history_string)
                        db.add(db_memory)
                    db.commit()
                    self.logger.info(f"Memoria e historial para la sesión {self.session_id} guardados en la DB.")
                except Exception as e:
                    self.logger.error(f"Error al guardar memoria en la DB: {e}", exc_info=True)
                    db.rollback()
        else:
            # Fallback to file-based memory
            memoria_archivo = f"memoria_{self.session_id}.json"
            self.logger.info(f"DB no configurada. Guardando conocimiento e historial en archivo local: {memoria_archivo}")
            try:
                data_to_save = {"memoria": self.memoria, "historial": self.conversation_history}
                with open(memoria_archivo, 'w', encoding='utf-8') as archivo:
                    json.dump(data_to_save, archivo, ensure_ascii=False, indent=4)
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
            f"Basado en todo lo anterior, responde a la siguiente pregunta o comentario del usuario de forma natural y útil: \"{pregunta}\"\n"
            f"IMPORTANTE: Si tu respuesta incluye código, formátalo usando bloques de código de Markdown con triple comilla invertida (```)."
        )
        try:
            modelo = genai.GenerativeModel('gemini-1.5-flash-latest')
            respuesta = modelo.generate_content(prompt_completo.strip())
            self.logger.debug("Respuesta recibida del modelo Gemini.")
            return respuesta.text
        except Exception as e:
            self.logger.error(f"Error al contactar a Google Gemini: {e}", exc_info=True)
            return "Lo siento, parece que tengo problemas para contactar a Google Gemini en este momento."

    def pensar_con_gemini_stream(self, pregunta: str):
        """
        Envía una pregunta a Gemini y devuelve un generador que transmite la respuesta en trozos.
        """
        self.logger.debug("Consultando al cerebro externo Gemini en modo streaming...")
        historial_texto = "\n".join([f"{'Usuario' if i % 2 == 0 else 'IA'}: {turno}" for i, turno in enumerate(self.conversation_history[-6:])])
        prompt_completo = (
            f"Eres una IA servicial y amigable llamada {self.memoria.get('nombre', 'IA')}.\n"
            f"El nombre de tu usuario es {self.memoria.get('nombre_usuario', 'desconocido')}.\n"
            f"Estos son algunos datos que has aprendido sobre el usuario (en JSON): {json.dumps(self.memoria.get('datos_aprendidos', {}), ensure_ascii=False, indent=2)}.\n"
            f"Usa esta información para que tus respuestas suenen más personales, pero sin ser repetitivo.\n"
            f"Historial reciente:\n{historial_texto}\n"
            f"Responde a la siguiente pregunta del usuario de forma natural y útil: \"{pregunta}\""
            f"\nIMPORTANTE: Si tu respuesta incluye código, formátalo usando bloques de código de Markdown con triple comilla invertida (```)."
        )
        try:
            modelo = genai.GenerativeModel('gemini-1.5-flash-latest')
            # Itera sobre los chunks de la respuesta en streaming
            for chunk in modelo.generate_content(prompt_completo.strip(), stream=True):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            self.logger.error(f"Error al contactar a Google Gemini en modo stream: {e}", exc_info=True)
            yield "Lo siento, parece que tengo problemas para contactar a Google Gemini en este momento."

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
            return self._handle_set_ia_name(comando)

        # 2. Usar el despachador de comandos definido en la clase
        for handler, keywords in self.command_dispatcher.items():
            for keyword in keywords:
                if keyword in comando:
                    # Los handlers ahora devuelven un diccionario de acción
                    return handler(comando)
        
        # El comando 'ejecuta' es especial porque solo funciona en Windows.
        if "ejecuta" in comando:
            return self._handle_execute_app(comando)

        # 3. Si no es un comando conocido, se trata como una consulta general a Gemini.
        self.logger.debug(f"Comando no reconocido como función interna. Enviando a Gemini: '{comando}'")
        speech = self.pensar_con_gemini(comando)
        return {"speech": speech, "action": {"type": "none"}}

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
            # Buscar la primera aparición de " es " o " son " para más flexibilidad
            separador = " es " if " es " in dato_a_recordar else " son "
            clave, valor = dato_a_recordar.split(separador, 1)
            self.memoria["datos_aprendidos"][clave.strip()] = valor.strip()
            self._guardar_memoria()
            speech = f"Entendido. He guardado que '{clave.strip()}' es '{valor.strip()}'."
        except (ValueError, KeyError):
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
            # Pasamos solo el tema de la búsqueda a Gemini, no el comando completo.
            respuesta_inteligente = self.pensar_con_gemini(clave_a_buscar)
            speech += f" Según mi información, {respuesta_inteligente}"
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

        # ¡IMPORTANTE! Esta acción solo puede funcionar en el servidor donde corre el backend.
        # Añadimos una comprobación para evitar errores en entornos no-Windows (como Render).
        if not sys.platform.startswith('win'):
            return {
                "speech": f"Lo siento, la función de ejecutar aplicaciones como '{aplicacion}' solo está disponible cuando opero en un sistema Windows.",
                "action": {"type": "none"}
            }

        for app_name, executable in mapa_apps.items():
            if app_name in aplicacion:
                self.logger.info(f"Ejecutando '{executable}' en el servidor.")
                subprocess.Popen([executable])
                return {"speech": f"Ejecutando {app_name}.", "action": {"type": "none"}}
        
        # Si no se encuentra la app, se devuelve una respuesta sin acción.
        return {
            "speech": f"No sé cómo ejecutar '{aplicacion}'. Puedes enseñarme agregándolo al código.",
            "action": {"type": "none"}
        }

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
from flask import Flask, request, jsonify, Response, stream_with_context

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
            "interactuar": "/interact (POST)",
            "interactuar_stream": "/interact-stream (POST)"
        },
        "info": "Todas las peticiones a los endpoints de interacción requieren una cabecera 'X-Session-ID'."
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

        # Guardar la memoria y el historial al final de la interacción
        nexus_instance._guardar_memoria()

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

@app.route('/interact-stream', methods=['POST'])
def interactuar_stream():
    """Endpoint que transmite la respuesta de la IA usando Server-Sent Events (SSE)."""
    session_id = request.headers.get('X-Session-ID')
    if not session_id:
        return Response("La cabecera 'X-Session-ID' es requerida.", status=400)
    
    datos = request.json
    if not datos or 'comando' not in datos:
        return Response("El campo 'comando' es requerido.", status=400)

    def generate_events():
        nexus_instance = instance_manager.get_or_create_instance(session_id)
        comando = datos['comando'].lower()
        nexus_instance.logger.info(f"Comando de stream recibido de [{session_id}]: '{comando}'")
        nexus_instance.conversation_history.append(comando)

        # Comprobar si es un comando de acción específico
        matched_handler = None
        for handler, keywords in nexus_instance.command_dispatcher.items():
            if any(keyword in comando for keyword in keywords):
                matched_handler = handler
                break
        
        if "ejecuta" in comando:
            matched_handler = nexus_instance._handle_execute_app

        if matched_handler:
            # Si es un comando de acción, se ejecuta y se envía una única respuesta
            response_dict = matched_handler(comando)
            if response_dict.get("speech"):
                nexus_instance.conversation_history.append(response_dict.get("speech"))
            yield f"data: {json.dumps(response_dict)}\n\n"
            # Guardar la memoria y el historial al final de la interacción
            nexus_instance._guardar_memoria()
        else:
            # Si es una consulta general, se transmite la respuesta de Gemini
            full_response_text = ""
            for text_chunk in nexus_instance.pensar_con_gemini_stream(comando):
                full_response_text += text_chunk
                yield f"data: {json.dumps({'speech_chunk': text_chunk})}\n\n"
            if full_response_text:
                nexus_instance.conversation_history.append(full_response_text)
            # Guardar la memoria y el historial al final de la interacción
            nexus_instance._guardar_memoria()
        
        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(stream_with_context(generate_events()), mimetype='text/event-stream')

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
