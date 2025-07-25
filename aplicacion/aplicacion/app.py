import os
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from flask import Flask, request, jsonify, render_template, redirect, url_for
from google.oauth2 import service_account
from googleapiclient.discovery import build
import datetime
import threading
import requests
import schedule
import time
import json
import tempfile

app = Flask(__name__)



# ---------------- CONFIGURACIÓN AZURE KEY VAULT ----------------
KEY_VAULT_NAME = "credencial"
KV_URI = f"https://{KEY_VAULT_NAME}.vault.azure.net"
credential = DefaultAzureCredential()
secret_client = SecretClient(vault_url=KV_URI, credential=credential)
# ---------------- FIN CONFIGURACIÓN AZURE KEY VAULT ----------------




# -----------   CACHÉ DE SECRETOS     ---------------
secret_cache = {}

def get_secret_cached(secret_name):
    if secret_name not in secret_cache:
        secret_cache[secret_name] = secret_client.get_secret(secret_name).value
    return secret_cache[secret_name]

# Función para obtener un secreto del Azure Key Vault
def get_secret(secret_name):
    return secret_client.get_secret(secret_name).value

# -----------  FIN CACHÉ DE SECRETOS    ---------------


# ----------- CARGAR DICCIONARIO CALENDARIOS CADA SECRETO --------------
CALENDAR_SECRET_CONFIG = {
    "corpuskinesiologiasl@gmail.com": {
        "google_credentials_secret": "google-credentials-corpus-vero",
        "whatsapp_token_secret": "token-confirmatin-meta",
        "whatsapp_phone_id_secret": "phone-id-CitaFy",
        "verify_token_secret": "token-cliente-confirmatin-developer",
        "nombre_empresa": "Verónica Di Giannantonio Kinesiología",
        "review_link": "https://g.page/r/CdBheRUiFHb_EBM/review"
    },
    "corpuskinesiologia2@gmail.com": {
        "google_credentials_secret": "google-credentials-corpus-guido",
        "whatsapp_token_secret": "token-confirmatin-meta",
        "whatsapp_phone_id_secret": "phone-id-CitaFy",
        "verify_token_secret": "token-cliente-confirmatin-developer",
        "nombre_empresa": "Guido Bazzana (R.P.G)",
        "review_link": "https://g.page/r/CdBheRUiFHb_EBM/review"
    },
    # "podologiafisherton@gmail.com": {
    #     "google_credentials_secret": "google-credentials-podologia",
    #     "whatsapp_token_secret": "token-confirmatin-meta",
    #     "whatsapp_phone_id_secret": "phone-id-CitaFy",
    #     "verify_token_secret": "token-cliente-confirmatin-developer",
    #     "nombre_empresa": "Veronica Weedon Podología Fisherton",
    #     "review_link": "https://g.page/r/CfHbMERrsfVXEBM/review"
    # }
}
# ----------- FIN CARGAR DICCIONARIO CALENDARIOS CADA SECRETO --------------

# Lista de calendar_id (puedes obtenerla de las claves del diccionario)
CALENDAR_IDS = list(CALENDAR_SECRET_CONFIG.keys())


# ---------------- CONFIGURACIÓN GOOGLE CALENDAR ----------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_service_from_keyvault(secret_name):
    secret = get_secret_cached(secret_name)
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json') as temp_file:
        temp_file.write(secret)
        temp_file_path = temp_file.name
    credentials = service_account.Credentials.from_service_account_file(
        temp_file_path, scopes=SCOPES
    )
    return build('calendar', 'v3', credentials=credentials)

# ---------------- CONFIGURACIÓN WHATSAPP API ----------------

# Diccionario en memoria para almacenar los IDs de mensajes procesados
processed_messages = set()

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        """ Verificación del webhook de Meta """
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        # Lista de tokens válidos (puedes cargarlos desde el .env)
        valid_tokens = [get_secret_cached(config["verify_token_secret"]) for config in CALENDAR_SECRET_CONFIG.values()]
        if mode == "subscribe" and token in valid_tokens:
            return challenge, 200
        return "Verificación fallida", 403

    elif request.method == 'POST':
        """ Recibir mensajes de WhatsApp y procesar respuestas """
        if request.content_type != 'application/json':
            return jsonify({'status': 'Content-Type no soportado'}), 415

        data = request.get_json()
        print("Datos recibidos en el webhook:", data)

        if not data:
            return jsonify({'status': 'No se recibió ningún dato'}), 200

        # Procesar los datos como antes
        if "entry" in data:
            for entry in data["entry"]:
                for change in entry["changes"]:
                    # Ignorar eventos de status (read, delivered, failed, etc.)
                    if "statuses" in change["value"]:
                        print("Evento de status ignorado:", change["value"]["statuses"])
                        return jsonify({'status': 'Status ignorado'}), 200

                    # Procesar mensajes
                    if "messages" in change["value"]:
                        for message in change["value"]["messages"]:
                            print("Mensaje recibido:", message)  # Registrar el mensaje recibido
                            message_id = message["id"]  # ID único del mensaje
                            from_number = message["from"]  # Número del remitente

                            # Verificar si el mensaje ya fue procesado
                            if message_id in processed_messages:
                                print(f"Mensaje con ID {message_id} ya procesado. Ignorando.")
                                return jsonify({'status': 'Mensaje ya procesado'}), 200

                            # Marcar el mensaje como procesado
                            processed_messages.add(message_id)

                            # Verificar el tipo de mensaje
                            button_reply = None
                            
                            # Manejar mensajes de tipo "interactive" (formato anterior)
                            if "interactive" in message:
                                try:
                                    interactive_type = message["interactive"]["type"]
                                    if interactive_type == "button_reply":
                                        button_reply = message["interactive"].get("button_reply", {}).get("id")
                                except Exception as e:
                                    print(f"Error procesando mensaje interactive: {e}")
                            
                            # Manejar mensajes de tipo "button" (formato actual)
                            elif "button" in message:
                                try:
                                    button_reply = message["button"].get("payload")
                                    print(f"Botón presionado (payload): {button_reply}")
                                except Exception as e:
                                    print(f"Error procesando mensaje button: {e}")

                            # Si tenemos una respuesta de botón, procesarla
                            if button_reply:
                                try:
                                    print(f"Procesando respuesta de botón: {button_reply}")
                                    print(f"Número de teléfono recibido: {from_number}")

                                    # Normalizar el número de teléfono antes del bucle
                                    normalized_from_number = f"+{from_number}" if not from_number.startswith("+") else from_number
                                    print(f"Número normalizado: {normalized_from_number}")

                                    # Iterar sobre todos los calendarios configurados
                                    for calendar_id, config in CALENDAR_SECRET_CONFIG.items():
                                        print(f"Buscando en calendario: {calendar_id}")
                                        service = get_service_from_keyvault(config["google_credentials_secret"])
                                        
                                        # Buscar eventos de las próximas 48 horas
                                        now = datetime.datetime.now(datetime.timezone.utc)
                                        two_days_later = now + datetime.timedelta(days=2)
                                        time_min = now.strftime('%Y-%m-%dT%H:%M:%SZ')
                                        time_max = two_days_later.strftime('%Y-%m-%dT%H:%M:%SZ')
                                        
                                        events_result = service.events().list(
                                            calendarId=calendar_id, 
                                            timeMin=time_min,
                                            timeMax=time_max,
                                            maxResults=500,
                                            singleEvents=True,
                                            orderBy='startTime'
                                        ).execute()
                                        events = events_result.get('items', [])
                                        print(f"Eventos obtenidos de {calendar_id}: {len(events)}")

                                        for event in events:
                                            event_description = event.get('description', '')
                                            print(f"Revisando evento: {event.get('summary', 'Sin título')}")
                                            print(f"Descripción del evento: {event_description[:100]}...")  # Primeros 100 caracteres

                                            # Verificar si contiene la marca de reserva y el número
                                            if "<b>Reservada por</b>" in event_description:
                                                print(f"Evento tiene reserva. Buscando número {normalized_from_number}")
                                                
                                                # También buscar sin el + para mayor compatibilidad
                                                number_without_plus = from_number
                                                
                                                if normalized_from_number in event_description or number_without_plus in event_description:
                                                    print(f"¡Número encontrado en evento! Actualizando...")
                                                    
                                                    if button_reply == 'si':
                                                        color_id = '2'  # Verde (confirmado)
                                                        status = 'confirmed'
                                                        icono = "✅"
                                                    elif button_reply == 'no':
                                                        color_id = '11'  # Rojo (cancelado)
                                                        status = 'confirmed'
                                                        icono = "❌"
                                                    else:
                                                        color_id = '5'  # Amarillo (respuesta no válida)
                                                        status = 'tentative'
                                                        icono = "⚠️"

                                                    nuevo_titulo = f"{icono} {event.get('summary', '')}"

                                                    print(f"Actualizando evento en {calendar_id} con color_id: {color_id}, status: {status}, título: {nuevo_titulo}")
                                                    try:
                                                        service.events().patch(
                                                            calendarId=calendar_id,
                                                            eventId=event['id'],
                                                            body={
                                                                'colorId': color_id,
                                                                'status': status,
                                                                'summary': nuevo_titulo
                                                            }
                                                        ).execute()
                                                        print("Evento actualizado correctamente.")
                                                        return jsonify({'status': 'Cita actualizada'}), 200
                                                    except Exception as e:
                                                        print(f"Error al actualizar el evento: {e}")
                                                        return jsonify({'status': 'Error al actualizar el evento'}), 500

                                    print("Número no encontrado en citas.")
                                    return jsonify({'status': 'Número no encontrado en citas'}), 404
                                except Exception as e:
                                    print(f"Error procesando el mensaje con botón: {e}")
                                    return jsonify({'status': 'Error procesando el mensaje con botón'}), 500
                            else:
                                print("Tipo de mensaje no soportado o sin botón")
                                return jsonify({'status': 'Tipo de mensaje no soportado'}), 200

        return jsonify({'status': 'Webhook procesado correctamente'}), 200


@app.route('/confirmar_citas', methods=['GET'])
def confirmar_citas():
    """Enviar confirmaciones de citas por WhatsApp"""
    try:
        now = datetime.datetime.now(datetime.timezone.utc) #Obtiene la fecha y hora actual en formato UTC
        tomorrow = now + datetime.timedelta(days=1) #Calcula la fecha y hora de exactamente 24 horas después de now (es decir, "mañana" a la misma hora).
        time_min = now.strftime('%Y-%m-%dT%H:%M:%SZ')  # Formato ISO 8601 con 'Z'
        time_max = tomorrow.strftime('%Y-%m-%dT%H:%M:%SZ')  # Formato ISO 8601 con 'Z' Estas variables (time_min y time_max) se usan después para pedirle a Google Calendar todos los eventos que ocurren entre "ahora" y "mañana a la misma hora".

        # Iterar sobre todos los calendarios configurados
        for calendar_id, config in CALENDAR_SECRET_CONFIG.items():
            service = get_service_from_keyvault(config["google_credentials_secret"])
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            print(f"Eventos encontrados en {calendar_id}: {len(events)}")

            for event in events:
                event_description = event.get('description', '')
                # Filtrar solo eventos con "<b>Reservada por</b>" en la descripción
                if "<b>Reservada por</b>" not in event_description:
                    continue

                phone = extract_phone_number(event_description)
                if phone:
                    start_datetime = event["start"]["dateTime"]
                    start_date = datetime.datetime.strptime(start_datetime[:10], '%Y-%m-%d').strftime('%d/%m/%Y')
                    start_time = start_datetime[11:16]
                    nombre_empresa = config.get("nombre_empresa", "la empresa")
                    
                    template_params = [
                        nombre_empresa,
                        start_date,
                        start_time
                    ]
                    
                    whatsapp_token = get_secret_cached(config["whatsapp_token_secret"])
                    whatsapp_phone_id = get_secret_cached(config["whatsapp_phone_id_secret"])
                    send_whatsapp_template(phone, whatsapp_token, whatsapp_phone_id, template_params)

        return jsonify({'status': 'Mensajes enviados'})
    except Exception as e:
        print(f"Error en confirmar_citas: {e}")
        return jsonify({'status': 'Error al confirmar citas', 'error': str(e)}), 500

def extract_phone_number(description):
    import re
    # Busca cualquier número de al menos 8 dígitos seguidos
    match = re.search(r'(\d{8,15})', description)
    return match.group(1) if match else None



def send_whatsapp_template(phone, whatsapp_token, whatsapp_phone_id, template_params):
    url = f"https://graph.facebook.com/v17.0/{whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "confirmarturno",
            "language": {
                "code": "es_AR"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": template_params[0]},  # nombre_empresa
                        {"type": "text", "text": template_params[1]},  # fecha
                        {"type": "text", "text": template_params[2]}   # hora
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Mensaje de plantilla enviado a {phone}")
    except requests.exceptions.RequestException as e:
        print(f"Error al enviar mensaje de plantilla: {e}")
        if e.response is not None:
            print("Respuesta de la API:", e.response.text)

def job():
    with app.app_context():
        confirmar_citas()

def send_whatsapp_message(phone, message, whatsapp_token, whatsapp_phone_id):
    """Envía un mensaje de texto simple por WhatsApp"""
    url = f"https://graph.facebook.com/v17.0/{whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Mensaje enviado a {phone}")
    except requests.exceptions.RequestException as e:
        print(f"Error al enviar mensaje: {e}")
        if e.response is not None:
            print("Respuesta de la API:", e.response.text)

def send_review_request(phone, whatsapp_token, whatsapp_phone_id, review_link):
    review_message = (
        "¡Gracias por tu visita! ¿Podrías dejarnos una reseña en Google Maps? "
        f"Tu opinión es muy importante para nosotros. {review_link}"
    )
    send_whatsapp_message(phone, review_message, whatsapp_token, whatsapp_phone_id)

def enviar_mensajes_resena():
    """
    Envía mensajes de reseña 5-10 minutos después de que termine cada cita.
    Aprovecha la ventana de 24 horas desde la confirmación para evitar usar templates.
    """
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        # Buscar citas que terminaron hace 5-15 minutos
        fifteen_minutes_ago = now - datetime.timedelta(minutes=15)
        five_minutes_ago = now - datetime.timedelta(minutes=5)
        time_min = fifteen_minutes_ago.strftime('%Y-%m-%dT%H:%M:%SZ')
        time_max = five_minutes_ago.strftime('%Y-%m-%dT%H:%M:%SZ')

        print(f"Buscando citas finalizadas entre {time_min} y {time_max}")

        for calendar_id, config in CALENDAR_SECRET_CONFIG.items():
            service = get_service_from_keyvault(config["google_credentials_secret"])
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=100,
                singleEvents=True,
                orderBy='startTime'
            ).execute()

            events = events_result.get('items', [])
            print(f"Eventos finalizados encontrados en {calendar_id}: {len(events)}")
            
            for event in events:
                event_description = event.get('description', '')
                event_summary = event.get('summary', '')
                
                # Solo procesar citas reservadas y confirmadas (con ✅)
                if "<b>Reservada por</b>" not in event_description:
                    continue
                    
                if "✅" not in event_summary:
                    print(f"Cita no confirmada, no enviando reseña: {event_summary}")
                    continue
                    
                # Verificar que la cita ya terminó
                end_time_str = event.get('end', {}).get('dateTime', '')
                if end_time_str:
                    end_time = datetime.datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                    if end_time > now:
                        print(f"Cita aún no terminó: {event_summary}")
                        continue
                
                phone = extract_phone_number(event_description)
                if phone:
                    whatsapp_token = get_secret_cached(config["whatsapp_token_secret"])
                    whatsapp_phone_id = get_secret_cached(config["whatsapp_phone_id_secret"])
                    review_link = config.get("review_link", "https://g.page/tu-negocio/review")
                    
                    if review_link and review_link != "https://g.page/tu-negocio/review":
                        print(f"Enviando solicitud de reseña a {phone} para {config['nombre_empresa']}")
                        send_review_request(phone, whatsapp_token, whatsapp_phone_id, review_link)
                    else:
                        print(f"No hay enlace de reseña configurado para {config['nombre_empresa']}")
                        
    except Exception as e:
        print(f"Error al enviar mensajes de reseña: {e}")

def run_scheduler():
    schedule.every().hour.at(":24").do(job)  # Confirmaciones
    schedule.every(10).minutes.do(enviar_mensajes_resena)  # Mensajes de reseña cada 10 minutos
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"Error en el planificador: {e}")
        time.sleep(1)

if __name__ == '__main__':
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    app.run(host='0.0.0.0', port=80)
