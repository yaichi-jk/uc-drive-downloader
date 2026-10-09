# Contribuyendo a uc-drive-downloader

¡Gracias por querer colaborar! Cualquier aporte es bienvenido: reportes de
errores, mejoras de UI, nuevos formatos, documentación o binarios para más
plataformas.

## Cómo empezar

1. Fork del repositorio y clon local:
   ```bash
   git clone https://github.com/yaichi-jk/uc-drive-downloader.git
   cd uc-drive-downloader
   ```
2. El proyecto usa **solo la biblioteca estándar de Python** (no externa).
   Asegúrate de tener Python ≥ 3.10.
3. Crea una rama para tu cambio:
   ```bash
   git checkout -b feat/mi-mejora
   ```

## Convenciones de código

- Sigue el estilo existente (PEP 8).
- No añadas dependencias de terceros si se puede resolver con `stdlib`.
- No añadas comentarios innecesarios.
- Respeta la taxonomía de errores de `uc_drive/errors.py`.
- Formatea mensajes de progreso con los helpers de `uc_drive/ui.py`.
- Documenta las subfunciones añadidas en `README.md`.

## Verificación

Antes del `git commit`, valida que todo compile:

```bash
python3 -m py_compile uc_drive/*.py main.py tools/*.py
```

Si tu cambio toca la API/descarga, haz un smoke test real:

```bash
python3 -u main.py view <share_id> --file "<nombre_archivo>"
python3 -u main.py test <share_id>
```

No es necesario romper la red: usa tamaños pequeños para pruebas de descarga.

## Pull request

- Mensaje de commit claro y conciso (gitmoji opcional).
- Describe en la PR qué cambia y cómo lo verificaste.
- Mantén cambios pequeños y enfocados; una cosa por PR.
- Asegúrate de que el CI del repo (release) siga compilando.

## Dudas

Abre un issue con la etiqueta `question` antes de implementar cambios grandes
o ambiciosos: a veces hay una forma más simple de hacer lo mismo.

## Aviso legal

Este proyecto es educativo. Si envías una PR que facilite evadir
sistemas de pago, DRM o violaciones de copyright, será rechazada.