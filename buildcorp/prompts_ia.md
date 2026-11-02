# Registro de apoyo de inteligencia artificial

Este archivo registra las consultas hechas a herramientas de IA durante el desarrollo, como pide la Evaluación 3 de Desarrollo Backend.

**Herramienta utilizada:** Claude (Anthropic), modelo Claude Opus 5.5.

## Consulta 1: construcción del proyecto

**Fecha:** 1 de noviembre de 2026.

**Prompt.** Se entregó el enunciado de la evaluación completo, con esta instrucción inicial:

> necesito hacer esto [información general, ponderación, aprendizajes esperados y criterios de evaluación]
> este es el proyecto asignado en el cual te tienes que basar: Proyecto 4: Sistema de Alquiler y Control de Herramientas (BuildCorp) [problema y requerimientos 1 a 4]
> estos son los requirimientos tecnicos que tienes que tener en cuenta [Django/DRF, Django Admin, PostgreSQL, frontend responsivo, despliegue en EC2, apoyo de IA, entregables]

**Apoyo recibido.** La IA generó una primera versión de:

| Área | Qué generó |
|---|---|
| Modelos y migraciones | Herramientas, trazabilidad, préstamos, firmas, planes, órdenes y alertas, con restricciones en la base de datos |
| Reglas de negocio | `services.py`: estados permitidos, cobros, firma, bloqueo de morosos y mantenciones |
| Administración | Django Admin personalizado y roles con permisos |
| API | Endpoints de Django REST Framework, autenticación por sesión y token |
| Interfaz | Templates, CSS, JavaScript y captura de firma en canvas |
| Pruebas | Pruebas automatizadas de reglas, permisos, web y API |
| Despliegue | Script de instalación, servicios systemd, Gunicorn y Nginx |
| Documentación | `README.md` y este archivo |

**Verificación hecha por la IA durante el desarrollo.** Ejecutó las pruebas sobre PostgreSQL, recorrió las pantallas en un navegador automatizado con cada rol, en tamaño de escritorio y de teléfono, y ensayó el script de instalación en un entorno Ubuntu 24.04 de pruebas, sin AWS. Esas verificaciones encontraron errores que se corrigieron, entre ellos:

- Un rechazo de entrega deshacía también el bloqueo automático del contratista, porque ambos iban en la misma transacción.
- Los planes con intervalos cortos quedaban siempre como "próximos a vencer".
- Una página fallaba cuando una orden de trabajo no tenía técnico asignado.
- Los técnicos podían ver datos de contratistas en alertas y en la trazabilidad.


```

## Revisión del estudiante


- Revisión del código: Se verefica que esta funcionando y cambios realizados en secciones que faltaba colocar el AWS
- Cambios realizados: ninguno 
- Despliegue en AWS Academy: Se hace mediante consola de comandos y se crea una instancia en ubuntu, donde queda la pagina funcionando
