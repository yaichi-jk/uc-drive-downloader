# Política de seguridad

## Reportar vulnerabilidades

**No abras issues públicos** para fallos de seguridad. Reporta de forma
privada:

- Si eres colaborador del repo: usa *Settings → Security → Security
  advisories → New draft security advisory*.
- Si eres externo: escribe por el canal que el mantenedor indique en su perfil
  de GitHub, describiendo el fallo sin exponer datos sensibles.

En tu reporte incluye:

1. Descripción breve del fallo y su impacto.
2. Pasos para reproducirlo (sin credenciales reales).
3. Versión/commit afectado.

Responderemos lo antes posible y, tras arreglar, publicaremos un aviso que
acredite tu reporte si así lo deseas.

## Privacidad de credenciales

- Este proyecto **nunca** debe contener tokens, contraseñas ni cookies.
- Si crees que una credencial (p. ej. un token de GitHub) se filtró en un
  commit, **revócala de inmediato** en GitHub Settings → Developer settings →
  Fine-grained/Classic tokens y luego avísanos.
- Los binarios compilados (Releases) deben descargarse de los Releases
  oficiales del repositorio, no de enlaces de terceros.

## Versiones soportadas

| Versión | Soporte          |
|---------|------------------|
| 1.x     | Activo           |

## Responsible disclosure

Damos 90 días de cortesía antes de divulgar públicamente cualquier fallo,
salvo que el mantenedor pacte otra cosa.