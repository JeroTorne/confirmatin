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
        "whatsapp_token_secret": "whatsapp-token-corpus",
        "whatsapp_phone_id_secret": "phone-id-corpus",
        "verify_token_secret": "token-cliente-corpus",
        "nombre_empresa": "Verónica Di Giannantonio Kinesiología",
        "review_link": "https://g.page/r/CdBheRUiFHb_EBM/review"
    },
    "corpuskinesiologia2@gmail.com": {
        "google_credentials_secret": "google-credentials-corpus-guido",
        "whatsapp_token_secret": "whatsapp-token-corpus",
        "whatsapp_phone_id_secret": "phone-id-corpus",
        "verify_token_secret": "token-cliente-corpus",
        "nombre_empresa": "Guido Bazzana (R.P.G)",
        "review_link": "https://g.page/r/CdBheRUiFHb_EBM/review"
    },
    # "podologiafisherton@gmail.com": {
    #     "google_credentials_secret": "google-credentials-podologia",
    #     "whatsapp_token_secret": "whatsapp-token-corpus",
    #     "whatsapp_phone_id_secret": "phone-id-corpus",
    #     "verify_token_secret": "token-cliente-corpus",
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
                            if "interactive" in message:
                                try:
                                    interactive_type = message["interactive"]["type"]
                                    if interactive_type == "button_reply":
                                        button_reply = message["interactive"].get("button_reply", {}).get("id")
                                        if not button_reply:
                                            print("Error: No se encontró 'button_reply' en el mensaje.")
                                            return jsonify({'status': 'Error en el mensaje recibido'}), 400

                                        print(f"button_reply recibido: {button_reply}")

                                        # Iterar sobre todos los calendarios configurados
                                        for calendar_id, config in CALENDAR_SECRET_CONFIG.items():
                                            service = get_service_from_keyvault(config["google_credentials_secret"])
                                            events_result = service.events().list(calendarId=calendar_id, maxResults=500).execute()
                                            events = events_result.get('items', [])
                                            print(f"Eventos obtenidos de {calendar_id}: {len(events)}")

                                            for event in events:
                                                event_description = event.get('description', '')

                                                # Normalizar el número de teléfono
                                                normalized_from_number = f"+{from_number}" if not from_number.startswith("+") else from_number

                                                if "<b>Reservada por</b>" in event_description and normalized_from_number in event_description:
                                                    if button_reply == 'si':
                                                        color_id = '2'  # Verde (confirmado)
                                                        status = 'confirmed'
                                                    elif button_reply == 'no':
                                                        color_id = '11'  # Rojo (cancelado)
                                                        status = 'confirmed' #Se puede poner 'cancelled' si se quiere eliminar el evento
                                                    else:
                                                        color_id = '5'  # Amarillo (respuesta no válida)
                                                        status = 'tentative'

                                                    print(f"Actualizando evento en {calendar_id} con color_id: {color_id} y status: {status}")
                                                    try:
                                                        service.events().patch(
                                                            calendarId=calendar_id,
                                                            eventId=event['id'],
                                                            body={
                                                                'colorId': color_id,
                                                                'status': status
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
                                    print(f"Error procesando el mensaje interactivo: {e}")
                                    return jsonify({'status': 'Error procesando el mensaje interactivo'}), 500

                return jsonify({'status': 'Número no encontrado en citas'}), 404


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
                    message = f'Hola, ¿confirmas tu cita con {nombre_empresa} para el día {start_date} a las {start_time}?'

                    # Enviar mensaje de WhatsApp
                    print(f"Enviando mensaje a {phone}: {message}")
                    whatsapp_token = get_secret_cached(config["whatsapp_token_secret"])
                    whatsapp_phone_id = get_secret_cached(config["whatsapp_phone_id_secret"])
                    send_whatsapp_message(phone, message, whatsapp_token, whatsapp_phone_id)

        return jsonify({'status': 'Mensajes enviados'})
    except Exception as e:
        print(f"Error en confirmar_citas: {e}")
        return jsonify({'status': 'Error al confirmar citas', 'error': str(e)}), 500

def extract_phone_number(description):
    import re
    # Busca cualquier número de al menos 8 dígitos seguidos
    match = re.search(r'(\d{8,15})', description)
    return match.group(1) if match else None



def send_whatsapp_message(phone, message, whatsapp_token, whatsapp_phone_id):
    url = f"https://graph.facebook.com/v17.0/{whatsapp_phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": message},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "si", "title": "Sí"}},
                    {"type": "reply", "reply": {"id": "no", "title": "No"}}
                ]
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Mensaje enviado a {phone}: {message}")
    except requests.exceptions.RequestException as e:
        print(f"Error al enviar mensaje a {phone}: {e}")
        if e.response is not None:
            print("Respuesta de la API:", e.response.text)

def job():
    with app.app_context():
        confirmar_citas()

def send_review_request(phone, whatsapp_token, whatsapp_phone_id, review_link):
    review_message = (
        "¡Gracias por tu visita! ¿Podrías dejarnos una reseña en Google Maps? "
        f"Tu opinión es muy importante para nosotros. {review_link}"
    )
    send_whatsapp_message(phone, review_message, whatsapp_token, whatsapp_phone_id)

def enviar_mensajes_resena():
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        one_hour_ago = now - datetime.timedelta(hours=1)
        time_min = one_hour_ago.strftime('%Y-%m-%dT%H:%M:%SZ')
        time_max = now.strftime('%Y-%m-%dT%H:%M:%SZ')

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
            for event in events:
                event_description = event.get('description', '')
                if "<b>Reservada por</b>" not in event_description:
                    continue
                phone = extract_phone_number(event_description)
                if phone:
                    whatsapp_token = get_secret_cached(config["whatsapp_token_secret"])
                    whatsapp_phone_id = get_secret_cached(config["whatsapp_phone_id_secret"])
                    review_link = config.get("review_link", "https://g.page/tu-negocio/review")
                    send_review_request(phone, whatsapp_token, whatsapp_phone_id, review_link)
    except Exception as e:
        print(f"Error al enviar mensajes de reseña: {e}")

def run_scheduler():
    schedule.every().hour.at(":34").do(job)  # Confirmaciones
    schedule.every().hour.at(":15").do(enviar_mensajes_resena)  # Mensajes de reseña
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
