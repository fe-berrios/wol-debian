# -*- coding: utf-8 -*-
import socket
import threading
import os
import time
import json
import struct
import base64
import signal

# --- CONFIGURACION ---
PROXY_HOST = '0.0.0.0'
PROXY_PORT = 25565

SERVER_HOST = '192.168.100.36'
SERVER_PORT = 25565
SERVER_MAC = '40:A8:F0:67:CA:21'

# Ruta al icono del servidor (PNG 64x64)
SERVER_ICON_PATH = '/home/paip/minecraft-proxy/server-icon.png'

# Ruta al archivo de whitelist
WHITELIST_PATH = '/home/paip/minecraft-proxy/whitelist.json'

# Mensaje cuando un jugador no esta en la whitelist
MENSAJE_NO_WHITELIST = "No estas en la whitelist de este servidor."

# --- MENSAJES PERSONALIZADOS ---
FAKE_SERVER_STATUS_OFFLINE = {
    "version": {
        "name": "1.21.4",
        "protocol": 767
    },
    "players": {
        "max": 20,
        "online": 0,
        "sample": []
    },
    "description": {
        "text": "\u00a7cSuspendido. \u00a77Conectate para encender el servidor! "
    }
}

FAKE_SERVER_STATUS_ONLINE = {
    "version": {
        "name": "1.21.4",
        "protocol": 767
    },
    "players": {
        "max": 20,
        "online": 0,
        "sample": []
    },
    "description": {
        "text": "\u00a7aActivo. \u00a77Ingresa para jugar!"
    }
}

MENSAJE_DESPERTANDO = "Despertando el servidor! Espera unos 30 segundos y vuelve a recargar la lista de servidores."

# --- FIN DE LA CONFIGURACION ---

is_waking_up = False
server_icon_base64 = None
whitelist = []
whitelist_enabled = True

def load_whitelist():
    """Carga la whitelist desde el archivo JSON"""
    global whitelist, whitelist_enabled
    try:
        if os.path.exists(WHITELIST_PATH):
            with open(WHITELIST_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                whitelist_enabled = data.get('enabled', True)
                whitelist = data.get('players', [])
            print(f"[WHITELIST] Cargados {len(whitelist)} jugadores desde {WHITELIST_PATH}")
            print(f"[WHITELIST] Estado: {'ACTIVADA' if whitelist_enabled else 'DESACTIVADA'}")
        else:
            # Crear archivo de ejemplo si no existe
            example_whitelist = {
                "enabled": True,
                "players": [
                    "Notch",
                    "Jeb_",
                    "TuNombreAqui"
                ]
            }
            with open(WHITELIST_PATH, 'w', encoding='utf-8') as f:
                json.dump(example_whitelist, f, indent=2, ensure_ascii=False)
            whitelist = example_whitelist['players']
            whitelist_enabled = example_whitelist['enabled']
            print(f"[WHITELIST] Creado archivo de ejemplo en {WHITELIST_PATH}")
    except Exception as e:
        print(f"[WHITELIST] Error cargando whitelist: {e}")
        whitelist = []
        whitelist_enabled = False

def is_player_whitelisted(player_name):
    """Verifica si un jugador esta en la whitelist"""
    # Si la whitelist esta desactivada, permitir a todos
    if not whitelist_enabled:
        return True
    # Si la whitelist esta vacia, permitir a todos
    if not whitelist:
        return True
    return player_name in whitelist

def extract_player_name(login_packet_data):
    """Extrae el nombre del jugador del Login Start packet"""
    try:
        # En el Login Start packet (0x00 en login state), el formato es:
        # - String: nombre del jugador (VarInt length + UTF-8)
        # - UUID: UUID del jugador (16 bytes) - solo en versiones modernas
        
        # Leer longitud del nombre (VarInt)
        name_length, offset = read_varint_from_bytes(login_packet_data)
        if name_length is None:
            return None
        
        # Leer el nombre del jugador
        player_name = login_packet_data[offset:offset+name_length].decode('utf-8')
        return player_name
    except Exception as e:
        print(f"[ERROR] Error extrayendo nombre del jugador: {e}")
        return None

def load_server_icon():
    """Carga el icono del servidor y lo convierte a base64"""
    global server_icon_base64
    try:
        if os.path.exists(SERVER_ICON_PATH):
            with open(SERVER_ICON_PATH, 'rb') as f:
                icon_data = f.read()
                server_icon_base64 = "data:image/png;base64," + base64.b64encode(icon_data).decode('utf-8')
            print(f"[ICON] Icono del servidor cargado desde {SERVER_ICON_PATH}")
        else:
            print(f"[ICON] No se encontro icono en {SERVER_ICON_PATH}")
    except Exception as e:
        print(f"[ICON] Error cargando icono: {e}")

def get_real_server_status():
    """Obtiene el estado real del servidor incluyendo jugadores conectados"""
    try:
        # Crear conexion temporal al servidor real
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect((SERVER_HOST, SERVER_PORT))
        
        # Construir handshake packet (Status request)
        handshake_data = b''
        handshake_data += write_varint(0)  # Packet ID
        handshake_data += write_varint(767)  # Protocol version
        handshake_data += write_varint(len(SERVER_HOST)) + SERVER_HOST.encode('utf-8')
        handshake_data += struct.pack('>H', SERVER_PORT)
        handshake_data += write_varint(1)  # Next state (status)
        
        # Enviar handshake
        sock.sendall(write_varint(len(handshake_data)) + handshake_data)
        
        # Enviar status request
        status_request = write_varint(0)  # Packet ID 0x00
        sock.sendall(write_varint(len(status_request)) + status_request)
        
        # Leer respuesta
        packet_id, packet_data = read_packet(sock)
        if packet_id == 0x00:
            # Leer el JSON del status
            json_length, offset = read_varint_from_bytes(packet_data)
            json_data = packet_data[offset:offset+json_length].decode('utf-8')
            status = json.loads(json_data)
            
            sock.close()
            return status
        
        sock.close()
        return None
    except Exception as e:
        print(f"[DEBUG] Error obteniendo status real: {e}")
        return None

def read_varint(sock):
    """Lee un VarInt del socket"""
    value = 0
    for i in range(5):
        data = sock.recv(1)
        if not data:
            return None
        byte = ord(data)
        value |= (byte & 0x7F) << (7 * i)
        if not (byte & 0x80):
            return value
    return None

def write_varint(value):
    """Escribe un VarInt a bytes"""
    data = b''
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        data += bytes([byte])
        if value == 0:
            break
    return data

def read_packet(sock):
    """Lee un paquete completo del protocolo de Minecraft"""
    try:
        # Leer longitud del paquete (VarInt)
        length = read_varint(sock)
        if length is None:
            return None, None
        
        # Leer datos del paquete
        data = b''
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                return None, None
            data += chunk
        
        # Leer packet ID (VarInt)
        packet_id, offset = read_varint_from_bytes(data)
        packet_data = data[offset:]
        
        return packet_id, packet_data
    except:
        return None, None

def read_varint_from_bytes(data):
    """Lee un VarInt desde bytes"""
    value = 0
    offset = 0
    for i in range(5):
        if offset >= len(data):
            return None, offset
        byte = data[offset]
        value |= (byte & 0x7F) << (7 * i)
        offset += 1
        if not (byte & 0x80):
            return value, offset
    return None, offset

def send_packet(sock, packet_id, data=b''):
    """Envia un paquete segun el protocolo de Minecraft"""
    try:
        # Packet ID como VarInt
        packet_id_bytes = write_varint(packet_id)
        
        # Datos completos
        full_data = packet_id_bytes + data
        
        # Longitud como VarInt
        length_bytes = write_varint(len(full_data))
        
        # Enviar todo
        sock.sendall(length_bytes + full_data)
        return True
    except:
        return False

def send_status_response(sock, json_data):
    """Envia respuesta de status (packet 0x00)"""
    json_str = json.dumps(json_data)
    json_bytes = json_str.encode('utf-8')
    
    # Packet: 0x00 + String (JSON)
    data = write_varint(len(json_bytes)) + json_bytes
    return send_packet(sock, 0x00, data)

def send_ping_response(sock, ping_data):
    """Responde al ping (packet 0x01)"""
    # Simplemente devolvemos los mismos datos que recibimos
    return send_packet(sock, 0x01, ping_data)

def send_disconnect(sock, message):
    """Envia mensaje de desconexion (packet 0x00 en login state)"""
    # Formato JSON adecuado para Minecraft
    json_obj = {
        "text": message
    }
    json_str = json.dumps(json_obj, ensure_ascii=False)
    json_bytes = json_str.encode('utf-8')
    
    data = write_varint(len(json_bytes)) + json_bytes
    return send_packet(sock, 0x00, data)

def is_server_online():
    """Verifica si el servidor real esta en linea"""
    try:
        with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=2):
            return True
    except:
        return False

def handle_handshake(packet_data, client_socket):
    """Maneja el handshake inicial y determina la intencion del cliente"""
    try:
        # Leer protocol version (VarInt)
        protocol, offset = read_varint_from_bytes(packet_data)
        
        # Leer server address (String)
        addr_len, offset2 = read_varint_from_bytes(packet_data[offset:])
        offset += offset2
        server_addr = packet_data[offset:offset+addr_len].decode('utf-8')
        offset += addr_len
        
        # Leer server port (Unsigned Short)
        server_port = struct.unpack('>H', packet_data[offset:offset+2])[0]
        offset += 2
        
        # Leer next state (VarInt)
        next_state, _ = read_varint_from_bytes(packet_data[offset:])
        
        return next_state, protocol
    except Exception as e:
        print(f"Error parsing handshake: {e}")
        return None, None

def handle_status_request(client_socket, server_online, client_protocol):
    """Maneja solicitudes de status (lista de servidores)"""
    try:
        # Recibir el packet de status request (deberia estar vacio)
        packet_id, packet_data = read_packet(client_socket)
        if packet_id != 0x00 or packet_data is None:
            return False
        
        # Seleccionar el MOTD apropiado segun el estado del servidor
        if server_online:
            # Obtener estado real del servidor con jugadores conectados
            real_status = get_real_server_status()
            if real_status:
                status_response = real_status.copy()
                # Mantener nuestro MOTD personalizado pero usar los datos reales de jugadores
                status_response["description"] = FAKE_SERVER_STATUS_ONLINE["description"]
            else:
                status_response = FAKE_SERVER_STATUS_ONLINE.copy()
        else:
            status_response = FAKE_SERVER_STATUS_OFFLINE.copy()
        
        # Usar el protocol del cliente para evitar incompatibilidad
        status_response["version"]["protocol"] = client_protocol
        
        # Agregar icono si existe
        if server_icon_base64:
            status_response["favicon"] = server_icon_base64
        
        # Enviar respuesta de status
        if not send_status_response(client_socket, status_response):
            return False
        
        # Esperar y responder al ping
        packet_id, ping_data = read_packet(client_socket)
        if packet_id == 0x01:
            send_ping_response(client_socket, ping_data)
        
        return True
    except Exception as e:
        print(f"Error en handle_status_request: {e}")
        return False

def handle_client(client_socket):
    """Maneja a un cliente, diferenciando entre ping y login"""
    global is_waking_up
    
    try:
        # Leer el primer paquete (handshake)
        packet_id, packet_data = read_packet(client_socket)
        if packet_id is None:
            client_socket.close()
            return
        
        # El handshake siempre es packet 0x00
        if packet_id != 0x00:
            client_socket.close()
            return
        
        # Procesar handshake para determinar la intencion
        next_state, client_protocol = handle_handshake(packet_data, client_socket)
        
        if next_state is None:
            client_socket.close()
            return
        
        print(f"[DEBUG] Cliente usando protocol version: {client_protocol}")
        
        server_online = is_server_online()
        
        if next_state == 1:  # Status request (lista de servidores)
            print("[STATUS] Ping de lista de servidores detectado")
            if server_online:
                print("[STATUS] Servidor activo - mostrando MOTD de bienvenida")
            else:
                print("[STATUS] Servidor dormido - mostrando MOTD de suspension")
            handle_status_request(client_socket, server_online, client_protocol)
            client_socket.close()
                
        elif next_state == 2:  # Login request (conexion real)
            print("[LOGIN] Intento de conexion detectado")
            
            # Leer el Login Start packet del cliente
            login_packet_id, login_packet_data = read_packet(client_socket)
            
            if login_packet_id != 0x00:
                print("[LOGIN] Packet ID inesperado en login")
                client_socket.close()
                return
            
            # Extraer nombre del jugador
            player_name = extract_player_name(login_packet_data)
            
            if player_name is None:
                print("[LOGIN] No se pudo extraer el nombre del jugador")
                client_socket.close()
                return
            
            print(f"[LOGIN] Jugador: {player_name}")
            
            # Verificar whitelist
            if not is_player_whitelisted(player_name):
                print(f"[WHITELIST] Jugador {player_name} NO esta en la whitelist - RECHAZADO")
                send_disconnect(client_socket, MENSAJE_NO_WHITELIST)
                time.sleep(0.1)
                client_socket.close()
                return
            
            print(f"[WHITELIST] Jugador {player_name} esta en la whitelist - PERMITIDO")
            
            if server_online:
                print("[LOGIN] Servidor activo - conectando jugador")
                # Necesitamos reconstruir la conexion porque ya leimos el Login Start
                # Creamos una nueva conexion al servidor real
                try:
                    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    server_socket.settimeout(10)
                    server_socket.connect((SERVER_HOST, SERVER_PORT))
                    
                    # Reenviar handshake original
                    send_packet(server_socket, 0x00, packet_data)
                    
                    # Reenviar Login Start
                    send_packet(server_socket, 0x00, login_packet_data)
                    
                    # Crear tuneles bidireccionales
                    def forward(src, dst, name):
                        try:
                            while True:
                                data = src.recv(4096)
                                if not data:
                                    break
                                dst.sendall(data)
                        except:
                            pass
                        finally:
                            try:
                                src.close()
                            except:
                                pass
                    
                    threading.Thread(target=forward, args=(client_socket, server_socket, "client->server"), daemon=True).start()
                    threading.Thread(target=forward, args=(server_socket, client_socket, "server->client"), daemon=True).start()
                    
                except Exception as e:
                    print(f"[ERROR] Error conectando al servidor: {e}")
                    client_socket.close()
            else:
                if not is_waking_up:
                    is_waking_up = True
                    print(f"[WOL] Servidor dormido - enviando Wake-on-LAN (solicitado por {player_name})")
                    os.system(f'wakeonlan {SERVER_MAC}')
                    threading.Timer(60.0, reset_waking_up_flag).start()
                else:
                    print(f"[WOL] Servidor ya despertando (solicitado por {player_name})")
                
                print("[LOGIN] Informando al jugador - servidor despertando")
                
                mensaje_json = {
                    "text": "Despertando el servidor! Espera unos 30 segundos y vuelve a recargar la lista de servidores."
                }
                
                json_str = json.dumps(mensaje_json, ensure_ascii=False)
                json_bytes = json_str.encode('utf-8')
                data = write_varint(len(json_bytes)) + json_bytes
                send_packet(client_socket, 0x00, data)
                
                time.sleep(0.1)
                client_socket.close()
        else:
            client_socket.close()
            
    except Exception as e:
        print(f"[ERROR] Error en handle_client: {e}")
        client_socket.close()

def reset_waking_up_flag():
    """Reinicia el flag de 'despertando'"""
    global is_waking_up
    is_waking_up = False
    print("[WOL] Flag de 'despertando' reiniciado")

def proxy_connection(client_socket, initial_data, is_status):
    """Establece tunel entre cliente y servidor real"""
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.settimeout(10)
        server_socket.connect((SERVER_HOST, SERVER_PORT))
        
        # Reenviar handshake inicial
        send_packet(server_socket, 0x00, initial_data)
        
        def forward(src, dst, name):
            try:
                while True:
                    data = src.recv(4096)
                    if not data:
                        break
                    dst.sendall(data)
            except:
                pass
            finally:
                try:
                    src.close()
                except:
                    pass
        
        # Solo para status, no necesitamos mantener la conexion
        if is_status:
            # Reenviar los paquetes de status
            handle_status_request(client_socket, True, 767)
            client_socket.close()
            server_socket.close()
            return
        
        # Para login, mantener conexion activa
        threading.Thread(target=forward, args=(client_socket, server_socket, "client->server"), daemon=True).start()
        threading.Thread(target=forward, args=(server_socket, client_socket, "server->client"), daemon=True).start()
        
    except Exception as e:
        print(f"[ERROR] Error en proxy_connection: {e}")
        try:
            client_socket.close()
        except:
            pass

def main():
    # Cargar whitelist al iniciar
    load_whitelist()
    
    # Cargar icono al iniciar
    load_server_icon()
    
    proxy_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        proxy_server.bind((PROXY_HOST, PROXY_PORT))
        proxy_server.listen(10)
        print(f"[PROXY] Proxy de Minecraft escuchando en {PROXY_HOST}:{PROXY_PORT}")
        print(f"[PROXY] Servidor objetivo: {SERVER_HOST}:{SERVER_PORT}")
        print("[PROXY] Esperando conexiones...")
        
        while True:
            client_socket, addr = proxy_server.accept()
            print(f"\n[CONEXION] Nueva conexion de {addr}")
            handler = threading.Thread(target=handle_client, args=(client_socket,))
            handler.daemon = True
            handler.start()
            
    except KeyboardInterrupt:
        print("\n[PROXY] Cerrando proxy...")
    except Exception as e:
        print(f"[ERROR] Error en main: {e}")
    finally:
        proxy_server.close()

if __name__ == '__main__':
    main()