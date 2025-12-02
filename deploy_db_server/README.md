# 🖥️ Servidor de Base de Datos (Tu PC)

Esta carpeta contiene **solo** lo necesario para ejecutar el servidor PseudoDB.

## Instalación rápida

```bash
pip install -r requirements.txt
```

## Configuración

Edita `setups/config_db.json` con tu IP:
```json
{
  "db_ip": "0.0.0.0",
  "db_socket": "9017",
  ...
}
```

## Uso

```bash
# 1. Resetear estado (opcional, para federación nueva)
./scripts/reset_federation.sh

# 2. Iniciar servidor
python -m fl_main.pseudodb.pseudo_db

# 3. Monitorear (en otra terminal)
python scripts/check_federation_status.py
```
