"""Datos de ejemplo para la demo: usuarios, plantillas de tickets y artículos."""

from __future__ import annotations

from dataclasses import dataclass

DEMO_PASSWORD = "Demo1234!"

# (email, nombre, rol, especialidades)
DEMO_USERS: list[tuple[str, str, str, list[str]]] = [
    ("supervisor@example.com", "Laura Giménez", "supervisor", []),
    ("n1.martin@example.com", "Martín Sosa", "agente_n1", ["windows", "aplicaciones"]),
    ("n1.carla@example.com", "Carla Benítez", "agente_n1", ["redes", "windows"]),
    ("n1.diego@example.com", "Diego Ferreyra", "agente_n1", ["aplicaciones", "linux"]),
    ("n2.sofia@example.com", "Sofía Ledesma", "agente_n2", ["redes"]),
    ("n2.pablo@example.com", "Pablo Quiroga", "agente_n2", ["linux", "bases_de_datos"]),
    ("n2.valeria@example.com", "Valeria Ríos", "agente_n2", ["windows", "aplicaciones"]),
    ("n3.javier@example.com", "Javier Acosta", "agente_n3", ["redes", "linux"]),
    (
        "n3.lucia@example.com",
        "Lucía Paz",
        "agente_n3",
        ["bases_de_datos", "aplicaciones", "windows"],
    ),
    ("ana.perez@example.com", "Ana Pérez", "solicitante", []),
    ("jorge.lopez@example.com", "Jorge López", "solicitante", []),
    ("marta.diaz@example.com", "Marta Díaz", "solicitante", []),
    ("ricardo.vega@example.com", "Ricardo Vega", "solicitante", []),
    ("paula.molina@example.com", "Paula Molina", "solicitante", []),
    ("tomas.herrera@example.com", "Tomás Herrera", "solicitante", []),
]


@dataclass(frozen=True)
class TicketTemplate:
    title: str
    description: str
    impact: str
    urgency: str
    # Nivel donde típicamente se termina resolviendo (para simular escalamientos)
    resolves_at: str
    resolution: str


TICKET_TEMPLATES: list[TicketTemplate] = [
    TicketTemplate(
        "No puedo ingresar, me dice usuario bloqueado",
        "Intenté varias veces con mi contraseña y ahora Windows me dice que la cuenta está bloqueada.",
        "bajo",
        "alta",
        "N1",
        "Se desbloqueó la cuenta en Active Directory y se forzó el cambio de contraseña.",
    ),
    TicketTemplate(
        "Olvidé mi contraseña del dominio",
        "Volví de vacaciones y no recuerdo la clave. Necesito blanqueo para entrar a la PC.",
        "bajo",
        "media",
        "N1",
        "Blanqueo de contraseña con validación de identidad por legajo.",
    ),
    TicketTemplate(
        "Contraseña vencida en el correo del celular",
        "El celular me pide la contraseña del mail todo el tiempo desde que la cambié.",
        "bajo",
        "baja",
        "N1",
        "Se reconfiguró la cuenta en el cliente de correo móvil con la nueva clave.",
    ),
    TicketTemplate(
        "La VPN no conecta desde mi casa",
        "FortiClient queda en 98% y después da error de credenciales. Ayer funcionaba.",
        "medio",
        "alta",
        "N1",
        "Certificado del cliente vencido. Se reinstaló FortiClient con el perfil actualizado.",
    ),
    TicketTemplate(
        "VPN se desconecta cada 10 minutos",
        "Trabajo remoto y la VPN se corta seguido, pierdo las sesiones del ERP.",
        "medio",
        "media",
        "N2",
        "Se ajustó el MTU del túnel y el timeout de DPD en el concentrador.",
    ),
    TicketTemplate(
        "No resuelve nombres internos",
        "Desde la sucursal Rosario no resuelve intranet.empresa.local, nslookup da timeout.",
        "alto",
        "media",
        "N2",
        "El reenviador DNS de la sucursal apuntaba a un servidor dado de baja. Se corrigió.",
    ),
    TicketTemplate(
        "Sin internet en todo el piso 3",
        "Ninguna PC del piso 3 tiene red desde las 10. Los teléfonos IP tampoco andan.",
        "alto",
        "alta",
        "N2",
        "Se reemplazó la fuente del switch de acceso del piso 3 y se verificó el uplink.",
    ),
    TicketTemplate(
        "WiFi de la sala de reuniones muy lento",
        "En la sala grande el wifi anda muy lento, las videollamadas se cortan.",
        "medio",
        "media",
        "N1",
        "Se cambió el canal del access point por interferencia y se actualizó el firmware.",
    ),
    TicketTemplate(
        "Latencia alta hacia el datacenter",
        "Desde las sucursales hay latencia de 300 ms hacia los servidores del datacenter.",
        "alto",
        "media",
        "N3",
        "Ruta asimétrica por cambio del proveedor. Se ajustó BGP local preference.",
    ),
    TicketTemplate(
        "IP duplicada en la red de administración",
        "Aparece un aviso de conflicto de IP en varias PCs de administración.",
        "medio",
        "media",
        "N2",
        "Se amplió el scope DHCP y se reservaron las IPs de impresoras fuera del rango.",
    ),
    TicketTemplate(
        "Base de datos de facturación muy lenta",
        "Las consultas del sistema de facturación tardan más de un minuto desde esta mañana.",
        "alto",
        "alta",
        "N3",
        "Se identificó un plan de ejecución degradado en PostgreSQL; se actualizaron estadísticas y se creó un índice.",
    ),
    TicketTemplate(
        "Deadlocks en SQL Server del ERP",
        "El ERP muestra errores de deadlock al cerrar pedidos en horario pico.",
        "alto",
        "media",
        "N3",
        "Se ajustó el nivel de aislamiento y el orden de actualización en el procedimiento almacenado.",
    ),
    TicketTemplate(
        "Falló el backup nocturno de la base de datos",
        "El reporte de backups indica que el job de la base de clientes falló anoche.",
        "medio",
        "alta",
        "N2",
        "Disco de destino lleno. Se depuraron backups viejos y se ajustó la retención.",
    ),
    TicketTemplate(
        "Pedido de acceso de lectura a la base de reportes",
        "Necesito usuario de solo lectura en la base de reportes para armar tableros.",
        "bajo",
        "baja",
        "N2",
        "Se creó el rol de solo lectura y se entregaron credenciales por canal seguro.",
    ),
    TicketTemplate(
        "Servidor Linux de aplicaciones con disco lleno",
        "El servidor app-02 (Ubuntu) avisa disco lleno en /var y la aplicación no levanta.",
        "alto",
        "alta",
        "N2",
        "Se rotaron logs de nginx, se configuró logrotate y se amplió el volumen.",
    ),
    TicketTemplate(
        "Servicio nginx no levanta después del reinicio",
        "Tras el reinicio programado, systemd muestra nginx en estado failed.",
        "alto",
        "media",
        "N2",
        "Error de sintaxis en un virtual host agregado. Se corrigió y se validó con nginx -t.",
    ),
    TicketTemplate(
        "No puedo entrar por SSH al servidor de integración",
        "Al conectar por ssh me rechaza la clave pública, antes funcionaba.",
        "medio",
        "media",
        "N2",
        "Permisos incorrectos en authorized_keys tras un deploy. Se restauraron.",
    ),
    TicketTemplate(
        "Tarea cron de exportación no se ejecuta",
        "La exportación diaria de pedidos que corre por cron no generó el archivo hoy.",
        "medio",
        "media",
        "N3",
        "El script dependía de una variable de entorno no disponible en cron. Se definió en el crontab.",
    ),
    TicketTemplate(
        "Escritorio remoto al servidor de contabilidad no responde",
        "No puedo conectarme por RDP al servidor Windows Server de contabilidad.",
        "medio",
        "alta",
        "N2",
        "El servicio de escritorio remoto estaba detenido por una actualización. Se reinició y se programó la ventana.",
    ),
    TicketTemplate(
        "Outlook no sincroniza el correo",
        "Outlook queda en 'desconectado' y no recibo correos desde ayer.",
        "bajo",
        "alta",
        "N1",
        "Se recreó el perfil de Outlook y se reparó el archivo OST.",
    ),
    TicketTemplate(
        "Buzón de correo lleno",
        "Me llegó un aviso de que el buzón está lleno y no puedo enviar correos.",
        "bajo",
        "media",
        "N1",
        "Se habilitó el archivo en línea y se depuraron adjuntos grandes con el usuario.",
    ),
    TicketTemplate(
        "No llegan correos externos a ventas",
        "Los clientes dicen que los mails a ventas@ rebotan desde hoy.",
        "alto",
        "alta",
        "N3",
        "Registro MX mal modificado en el proveedor DNS. Se restauró y se verificó la propagación.",
    ),
    TicketTemplate(
        "Impresora de recepción no imprime",
        "La impresora de recepción tiene trabajos en cola pero no imprime nada.",
        "bajo",
        "media",
        "N1",
        "Se reinició la cola de impresión y se reinstaló el driver.",
    ),
    TicketTemplate(
        "Escáner no envía a la carpeta compartida",
        "El escáner del piso 2 da error al escanear a carpeta.",
        "bajo",
        "baja",
        "N1",
        "Se actualizó la contraseña de la cuenta de servicio del escáner.",
    ),
    TicketTemplate(
        "Notebook no enciende",
        "Mi notebook no prende, la luz de carga no se enciende.",
        "bajo",
        "alta",
        "N1",
        "Cargador defectuoso. Se reemplazó por uno de stock.",
    ),
    TicketTemplate(
        "Pantalla azul al iniciar Windows",
        "Desde la actualización de ayer la PC muestra pantalla azul al iniciar.",
        "bajo",
        "alta",
        "N2",
        "Driver de video incompatible. Se revirtió el driver desde modo seguro.",
    ),
    TicketTemplate(
        "Pedido de segundo monitor",
        "Solicito un segundo monitor para el puesto de análisis de datos.",
        "bajo",
        "baja",
        "N1",
        "Se entregó y configuró un monitor de 24 pulgadas.",
    ),
    TicketTemplate(
        "Error 500 en el portal de clientes",
        "El portal de clientes muestra error 500 al querer descargar facturas.",
        "alto",
        "alta",
        "N3",
        "Excepción no controlada tras el último deploy. Se aplicó hotfix y se agregó monitoreo.",
    ),
    TicketTemplate(
        "No puedo instalar el software de diseño",
        "Necesito instalar la aplicación de diseño pero me pide permisos de administrador.",
        "bajo",
        "baja",
        "N1",
        "Se instaló desde el portal de software corporativo con licencia asignada.",
    ),
    TicketTemplate(
        "Licencia de Office vencida",
        "Word dice que el producto no tiene licencia y no me deja editar.",
        "bajo",
        "media",
        "N1",
        "Se reasignó la licencia en la consola y se reactivó Office.",
    ),
    TicketTemplate(
        "El CRM no guarda los cambios de contactos",
        "Al editar un contacto en el CRM aparece un mensaje de error y no guarda.",
        "medio",
        "media",
        "N2",
        "Campo obligatorio nuevo sin valor por defecto. Se corrigió la validación.",
    ),
    TicketTemplate(
        "Sistema de facturación no emite comprobantes",
        "El sistema de facturación da error al autorizar comprobantes electrónicos.",
        "alto",
        "alta",
        "N2",
        "Certificado del web service fiscal vencido. Se renovó e instaló.",
    ),
    TicketTemplate(
        "Pedido de acceso a carpeta compartida de RRHH",
        "Necesito permiso de lectura en la carpeta compartida de Recursos Humanos.",
        "bajo",
        "baja",
        "N1",
        "Se agregó al usuario al grupo de AD correspondiente con aprobación del responsable.",
    ),
    TicketTemplate(
        "Acceso denegado a la unidad de red de proyectos",
        "Desde hoy me da acceso denegado al abrir la unidad P: de proyectos.",
        "medio",
        "media",
        "N1",
        "La GPO de mapeo cambió de grupo. Se actualizó la membresía del usuario.",
    ),
    TicketTemplate(
        "Firewall bloquea la aplicación del proveedor",
        "La aplicación del proveedor logístico no conecta, creemos que el firewall la bloquea.",
        "medio",
        "media",
        "N2",
        "Se agregó la regla de salida para el rango de IPs del proveedor.",
    ),
    TicketTemplate(
        "Consulta lenta en el reporte mensual",
        "El reporte mensual de ventas tarda 20 minutos en generarse.",
        "medio",
        "baja",
        "N3",
        "Se reescribió la query con CTE y se agregaron índices compuestos.",
    ),
    TicketTemplate(
        "Teclado y mouse inalámbricos no responden",
        "El teclado y el mouse inalámbricos dejaron de funcionar.",
        "bajo",
        "media",
        "N1",
        "Se reemplazaron las baterías y se re-emparejó el receptor USB.",
    ),
    TicketTemplate(
        "Calendario compartido no muestra reuniones",
        "No veo las reuniones del calendario compartido del equipo comercial.",
        "bajo",
        "baja",
        "N1",
        "Se volvieron a otorgar permisos de revisor sobre el calendario.",
    ),
    TicketTemplate(
        "Controlador de dominio con replicación fallida",
        "El monitoreo marca errores de replicación entre los controladores de dominio.",
        "alto",
        "media",
        "N3",
        "Se corrigió la sincronización horaria (NTP) y se forzó la replicación.",
    ),
    TicketTemplate(
        "Consulta sobre cómo compartir pantalla en videollamada",
        "No sé cómo compartir una sola ventana en la herramienta de videollamadas.",
        "bajo",
        "baja",
        "N1",
        "Se explicó el procedimiento y se envió el instructivo.",
    ),
]

KB_ARTICLES: list[dict[str, object]] = [
    {
        "title": "Desbloqueo de cuenta y blanqueo de contraseña",
        "body": "1. Validar identidad del usuario (legajo + pregunta de seguridad).\n"
        "2. En Active Directory: Usuarios y equipos > cuenta > Desbloquear.\n"
        "3. Si pidió blanqueo, asignar clave temporal y marcar 'cambiar en el próximo inicio'.\n"
        "4. Verificar que no haya sesiones con la clave vieja (celular, VPN) que vuelvan a bloquear.",
        "keywords": ["contraseña", "bloqueado", "blanqueo", "active directory", "clave"],
        "category": "acceso_cuentas",
        "specialty": "windows",
    },
    {
        "title": "VPN FortiClient: errores frecuentes y solución",
        "body": "Error en 98%: certificado vencido o perfil desactualizado; reinstalar con el perfil "
        "corporativo. Desconexiones frecuentes: revisar MTU (1400) y estabilidad del wifi del "
        "hogar. Error de credenciales: verificar que la cuenta no esté bloqueada.",
        "keywords": ["vpn", "forticlient", "desconecta", "certificado", "remoto"],
        "category": "red_conectividad",
        "specialty": "redes",
    },
    {
        "title": "Diagnóstico básico de DNS en sucursales",
        "body": "Ejecutar nslookup contra el DNS local y contra el central. Si el local falla, "
        "revisar los reenviadores condicionales y la conectividad del enlace. Limpiar caché con "
        "ipconfig /flushdns en el cliente.",
        "keywords": ["dns", "nslookup", "resuelve", "sucursal"],
        "category": "red_conectividad",
        "specialty": "redes",
    },
    {
        "title": "Outlook desconectado o sin sincronizar",
        "body": "Verificar conectividad y estado del servicio. Crear un perfil nuevo desde Panel de "
        "control > Correo. Si el OST está dañado, renombrarlo y dejar que se regenere.",
        "keywords": ["outlook", "correo", "sincroniza", "desconectado", "ost"],
        "category": "correo",
        "specialty": "aplicaciones",
    },
    {
        "title": "Disco lleno en servidores Linux",
        "body": "Identificar con df -h y du -sh /var/* | sort -h. Rotar logs (logrotate -f), "
        "limpiar journal (journalctl --vacuum-size=500M) y evaluar ampliar el volumen LVM.",
        "keywords": ["linux", "disco lleno", "logrotate", "var", "ubuntu"],
        "category": "servidores",
        "specialty": "linux",
    },
    {
        "title": "Consultas lentas en PostgreSQL: checklist",
        "body": "Revisar pg_stat_activity y bloqueos. Correr EXPLAIN ANALYZE de la consulta. "
        "Actualizar estadísticas con ANALYZE y evaluar índices faltantes. Verificar autovacuum.",
        "keywords": ["base de datos", "postgres", "lenta", "consulta", "indice"],
        "category": "base_de_datos",
        "specialty": "bases_de_datos",
    },
    {
        "title": "Impresora con trabajos trabados en cola",
        "body": "Detener el servicio Cola de impresión, borrar C:\\Windows\\System32\\spool\\PRINTERS, "
        "iniciar el servicio y reenviar. Si persiste, reinstalar el driver.",
        "keywords": ["impresora", "imprime", "cola", "spooler"],
        "category": "impresion",
        "specialty": "windows",
    },
]
