from datetime import datetime, timedelta
import pytz

tz = pytz.timezone("America/Bogota")

def iniciar():
    return {
        "inicio": datetime.now(tz),
        "en_curso": True,
        "distancia_km": 0.0,
        "ruta": []
    }

def tiempo_transcurrido(evento):
    segundos = int((datetime.now(tz) - evento["inicio"]).total_seconds())
    return segundos, str(timedelta(seconds=segundos))

def detener(evento):
    evento["fin"] = datetime.now(tz)
    evento["en_curso"] = False
    return evento
