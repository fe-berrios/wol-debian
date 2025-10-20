#!/bin/bash

# monitor.sh
# Monitorea jugadores conectados y suspende el servidor si est� inactivo

# Configuraci�n
SERVER_DIR="/home/paip/minecraft/server"
RCON_HOST="localhost"
RCON_PORT="25575"
RCON_PASSWORD="minecraft"
IDLE_TIMEOUT=600  # 10 minutos en segundos
GRACE_PERIOD=300  # 5 minutos de gracia despu�s de despertar
CHECK_INTERVAL=60  # Verificar cada 60 segundos

# Archivo para trackear el �ltimo estado de suspensi�n
SUSPEND_TRACKER="/tmp/minecraft_suspend_time"

# Funci�n para verificar si el servidor est� ejecut�ndose
is_server_running() {
    netstat -tlnp 2>/dev/null | grep :25565 > /dev/null
}

# Funci�n para obtener jugadores conectados
get_online_players() {
    /usr/local/bin/mcrcon -H $RCON_HOST -P $RCON_PORT -p $RCON_PASSWORD "list" 2>/dev/null | grep -o '[0-9]\+ of' | grep -o '[0-9]\+'
}

# Funci�n para verificar si estamos en per�odo de gracia
is_grace_period() {
    if [ -f "$SUSPEND_TRACKER" ]; then
        local last_suspend_time=$(cat "$SUSPEND_TRACKER")
        local current_time=$(date +%s)
        local time_since_resume=$((current_time - last_suspend_time))
        
        if [ $time_since_resume -lt $GRACE_PERIOD ]; then
            local remaining=$((GRACE_PERIOD - time_since_resume))
            echo "$(date): En per�odo de gracia. Tiempo restante: $remaining segundos"
            return 0
        else
            # Per�odo de gracia terminado, eliminar el archivo
            rm -f "$SUSPEND_TRACKER"
        fi
    fi
    return 1
}

# Funci�n para marcar el tiempo de suspensi�n
mark_suspend_time() {
    date +%s > "$SUSPEND_TRACKER"
    echo "$(date): Marcando tiempo de suspensi�n para per�odo de gracia"
}

# Funci�n principal de monitoreo
monitor_players() {
    local idle_counter=0
    
    # Verificar si acabamos de despertar de una suspensi�n
    if [ -f "$SUSPEND_TRACKER" ]; then
        echo "$(date): Detectado despertar reciente. Iniciando per�odo de gracia de 5 minutos"
    else
        echo "$(date): Iniciando monitoreo normal"
    fi
    
    while true; do
        if is_server_running; then
            # Si estamos en per�odo de gracia, no contar inactividad
            if is_grace_period; then
                idle_counter=0
                players=$(get_online_players)
                if [ -n "$players" ] && [ "$players" -gt 0 ]; then
                    echo "$(date): Jugadores conectados durante gracia: $players - Eliminando per�odo de gracia"
                    rm -f "$SUSPEND_TRACKER"
                fi
            else
                players=$(get_online_players)
                
                if [ -n "$players" ] && [ "$players" -gt 0 ]; then
                    echo "$(date): Jugadores conectados: $players - Reiniciando contador de inactividad"
                    idle_counter=0
                else
                    if [ "$players" -eq "0" ]; then
                        idle_counter=$((idle_counter + CHECK_INTERVAL))
                        echo "$(date): Servidor vac�o. Tiempo inactivo: $idle_counter segundos"
                        
                        if [ $idle_counter -ge $IDLE_TIMEOUT ]; then
                            echo "$(date): Sin jugadores por $IDLE_TIMEOUT segundos. Suspender servidor..."
                            
                            # Marcar el tiempo antes de suspender
                            mark_suspend_time
                            
                            # Enviar mensaje a los jugadores (por si acaso)
                            /usr/local/bin/mcrcon -H $RCON_HOST -P $RCON_PORT -p $RCON_PASSWORD "say El servidor se suspender� por inactividad en 30 segundos"
                            sleep 30
                            
                            # Detener servidor de Minecraft correctamente
                            /usr/local/bin/mcrcon -H $RCON_HOST -P $RCON_PORT -p $RCON_PASSWORD "stop"
                            
                            # Esperar a que el servidor se cierre completamente
                            sleep 30
                            
                            # Suspender el sistema
                            sudo systemctl suspend
                            break
                        fi
                    else
                        echo "$(date): No se pudo obtener el estado de jugadores"
                    fi
                fi
            fi
        else
            echo "$(date): Servidor no est� ejecut�ndose"
            idle_counter=0
        fi
        
        sleep $CHECK_INTERVAL
    done
}

# Ejecutar monitoreo
echo "Iniciando monitoreo de jugadores..."
monitor_players