import paho.mqtt.client as mqtt
import threading
import math

from flask import Flask, render_template, jsonify

app = Flask(__name__)

current_tank_level_percentage = 50
current_pir_state = 0

level_lock = threading.Lock()
pir_lock = threading.Lock()

MQTT_BROKER_HOST = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC = "streelet"

TANK_RADIUS_CM = 5.5
TANK_RADIUS_MM = TANK_RADIUS_CM * 10

# --- CONFIGURACIÓN DE ALTURAS DEL TANQUE ---
# Altura física total del recipiente en milímetros (desde el fondo hasta el borde superior)
TANK_PHYSICAL_HEIGHT_MM = 140 # 14 cm

# Margen en la parte superior donde el sensor puede ser errático (4 cm)
SENSOR_MARGIN_MM = 40 # 4 cm

# Altura desde el fondo que consideramos el 100% de llenado (tu objetivo de 10 cm)
# Esto corresponde a la altura física menos el margen si el 100% es justo al borde del margen
FULL_LEVEL_HEIGHT_MM = TANK_PHYSICAL_HEIGHT_MM - SENSOR_MARGIN_MM # Esto calcula 140 - 40 = 100 mm

# Validaciones básicas de configuración
if FULL_LEVEL_HEIGHT_MM > TANK_PHYSICAL_HEIGHT_MM:
     print("Advertencia de Configuración: La altura del 100% es mayor que la altura física del tanque.")

if FULL_LEVEL_HEIGHT_MM <= 0:
    print("Error de Configuración: La altura del 100% debe ser un valor positivo.")



mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)



def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("¡Conectado al Broker MQTT!")
        # La suscripción ahora se maneja en on_connect usando el cliente V2
        # También puedes suscribirte en connect_mqtt() antes de loop_start()
        client.subscribe(MQTT_TOPIC)
        print(f"Suscrito al tópico: {MQTT_TOPIC}")
    else:
        print(f"Fallo al conectar con código {rc}")
        # Puedes añadir lógica aquí para intentar reconectar si rc indica un error recuperable

# Callback para cuando el cliente se desconecta del broker (API V2 signature)
def on_disconnect(client, userdata, rc, properties=None):
    if rc != 0:
        print(f"¡Desconexión inesperada del Broker MQTT con código {rc}!")
        # Aquí podrías añadir lógica para intentar reconectar automáticamente


# Callback principal para recibir mensajes 
def on_message_streelet(client, userdata, msg):
    # Decodificar la carga del mensaje (payload)
    payload_str = msg.payload.decode('utf-8').strip()
    # print(f"Mensaje recibido en el tópico {msg.topic}: {payload_str}") # Descomentar para ver todos los mensajes crudos

    # Asegurarse de que el mensaje es del tópico que esperamos (aunque ya estamos suscritos a uno)
    if msg.topic != MQTT_TOPIC:
        print(f"Tópico ignorado: {msg.topic}")
        return

    try:
        # --- Procesar mensaje de Nivel de Tanque (sult_) ---
        if payload_str.startswith("sult_"):
            print(f"Mensaje sult_ recibido en {msg.topic}: {payload_str}")
            parts = payload_str.split("_")
            if len(parts) == 2:
                distance_mm_str = parts[1]
                try:
                    distance_mm = float(distance_mm_str)
                    print(f"Distancia medida por sensor (desde arriba, mm): {distance_mm}")

                    # Calcular la altura del líquido desde el fondo físico del tanque
                    liquid_height_from_bottom_mm = TANK_PHYSICAL_HEIGHT_MM - distance_mm

                    # Clampear la altura del líquido dentro del rango físico posible (0 hasta altura física)
                    if liquid_height_from_bottom_mm < 0:
                        liquid_height_from_bottom_mm = 0
                    elif liquid_height_from_bottom_mm > TANK_PHYSICAL_HEIGHT_MM:
                         liquid_height_from_bottom_mm = TANK_PHYSICAL_HEIGHT_MM

                    # Calcular el porcentaje de llenado, relativo a la altura definida como 100% (FULL_LEVEL_HEIGHT_MM)
                    tank_level_percentage = 0

                    # Evitar división por cero si FULL_LEVEL_HEIGHT_MM fuera 0 o negativo
                    if FULL_LEVEL_HEIGHT_MM > 0:
                         tank_level_percentage = (liquid_height_from_bottom_mm / FULL_LEVEL_HEIGHT_MM) * 100
                    else:
                         print("Error de Configuración: FULL_LEVEL_HEIGHT_MM no es un valor válido para el cálculo del porcentaje.")


                    # Clampear el porcentaje final entre 0 y 100.
                    if tank_level_percentage < 0:
                         tank_level_percentage = 0
                    elif tank_level_percentage > 100:
                         tank_level_percentage = 100

                    global current_tank_level_percentage
                    with level_lock:
                        current_tank_level_percentage = tank_level_percentage

                    print(f"Altura líquida desde el fondo físico (mm): {liquid_height_from_bottom_mm:.2f}, Nivel del tanque calculado (% de {FULL_LEVEL_HEIGHT_MM}mm): {current_tank_level_percentage:.2f}%")

                except ValueError:
                    print(f"Error sult_: No se pudo convertir '{distance_mm_str}' a número.")
                except Exception as e:
                    print(f"Ocurrió un error inesperado al procesar sult_ mensaje: {e}")

            else:
                print(f"Formato 'sult_' incorrecto. Se esperaba 'sult_numero', recibido: {payload_str}")

        # --- Procesar mensaje de Sensor PIR (spir_) ---
        elif payload_str.startswith("spir_"):
            print(f"Mensaje spir_ recibido en {msg.topic}: {payload_str}")
            parts = payload_str.split("_")
            if len(parts) == 2:
                pir_state_str = parts[1]
                try:
                    pir_state = int(pir_state_str)

                    if pir_state in [0, 1]:
                        global current_pir_state
                        with pir_lock:
                            current_pir_state = pir_state
                        print(f"Estado de PIR recibido: {pir_state}")
                    else:
                        print(f"Advertencia spir_: Estado PIR inesperado: {pir_state_str}. Se esperaba 0 o 1.")

                except ValueError:
                    print(f"Error spir_: No se pudo convertir '{pir_state_str}' a número entero.")
                except Exception as e:
                    print(f"Ocurrió un error inesperado al procesar spir_ mensaje: {e}")
            else:
                 print(f"Formato 'spir_' incorrecto. Se esperaba 'spir_0' o 'spir_1', recibido: {payload_str}")

        # --- Mensaje no reconocido ---
        else:
             print(f"Formato de mensaje no reconocido en tópico {MQTT_TOPIC}: {payload_str}")


    except Exception as e:
        print(f"Ocurrió un error general al procesar mensaje MQTT: {e}")


# Asignar las funciones de callback
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message_streelet
mqtt_client.on_disconnect = on_disconnect # Asignamos el callback de desconexión


def connect_mqtt():
    try:
        # connect_async es a menudo preferible para no bloquear,
        # y on_connect manejará el resultado de la conexión.
        # Usando connect síncrono y loop_start:
        mqtt_client.connect(MQTT_BROKER_HOST, MQTT_PORT, keepalive=60) # keepalive=60 es común
        mqtt_client.loop_start()
        print("Ciclo del cliente MQTT iniciado en hilo de fondo.")
    except Exception as e:
        # Este except solo captura errores síncronos al iniciar la conexión
        print(f"Error inicial al intentar conectar con el broker MQTT: {e}")


@app.route('/')
def index():
    with level_lock:
         level_to_render = current_tank_level_percentage
    with pir_lock:
         pir_state_to_render = current_pir_state

    return render_template('index.html',
                           initial_level=level_to_render,
                           initial_pir_state=pir_state_to_render)

# Ruta API para devolver ambos datos
@app.route('/api/sensor_data')
def get_sensor_data():
    with level_lock:
         level_to_return = current_tank_level_percentage
    with pir_lock:
         pir_state_to_return = current_pir_state

    return jsonify({
        'level': level_to_return,
        'pir_state': pir_state_to_return
        })

if __name__ == '__main__':
    # Conectar a MQTT antes de iniciar la aplicación Flask
    connect_mqtt()

    # Ejecutar la aplicación Flask
    # use_reloader=False recomendado con hilos en segundo plano
    app.run(debug=True, use_reloader=False)