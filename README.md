# Blocklist para Unbound y Otros Sistemas

Esta es una **lista de bloqueo** en formato texto diseñada para herramientas como [Unbound](https://www.unbound.net/), AdGuard Home, pfSense/OPNsense o cualquier sistema que use listas de dominios. Incluye bloqueo de páginas de juegos online, con reglas separadas para actualizaciones de Windows y Google que no afectan servicios como Hotmail, Office 365 o actualizaciones de navegadores.

## 📋 ¿Qué es esta lista?
- **Formato**: Texto plano, en sintaxis AdGuard Home (`||dominio^`) y también como hosts estándar (`0.0.0.0 dominio`).
- **Contenido**: Dominios de páginas de juegos online, servidores de Minecraft web (Eaglercraft, Opticraft, etc.) y bloqueadores de actualizaciones de Windows/Google.
- **Uso principal**: Bloqueo de tráfico no deseado en servidores DNS o firewalls.
- **Actualización**: La lista de juegos se actualiza automáticamente todos los días mediante GitHub Actions, y se depura de dominios muertos una vez al año.

## 🚀 Cómo usar la lista
1. Descarga el archivo de la lista o usa el link que corresponda en la tabla de abajo.
2. Configura tu herramienta para usar la lista:
   - **AdGuard Home / Unbound**: usa el archivo `GamesBlockList.txt` (sintaxis `||dominio^`).
   - **Hosts / OPNsense / sistemas sin soporte AdGuard**: usa `GamesBlockList_hosts.txt` (sintaxis `0.0.0.0 dominio`).

## Lists

| List | Link | Description |
|---|---|---|
| Games (AdGuard) | [GamesBlockList.txt](https://raw.githubusercontent.com/JosuhaSanhueza/BlockList/main/GamesBlockList.txt) | Páginas de juegos, formato AdGuard Home. |
| Games (Hosts) | [GamesBlockList_hosts.txt](https://raw.githubusercontent.com/JosuhaSanhueza/BlockList/main/GamesBlockList_hosts.txt) | Páginas de juegos, formato hosts estándar. |
| Windows Update | [WindowsUpdate.txt](https://raw.githubusercontent.com/JosuhaSanhueza/BlockList/main/WindowsUpdate.txt) | Bloqueo de actualizaciones de Windows. |
| Google Update | [GoogleUpdate.txt](https://raw.githubusercontent.com/JosuhaSanhueza/BlockList/main/GoogleUpdate.txt) | Bloqueo de actualizaciones de Google. |

## ⚙️ Mantenimiento automático

- **Diario** ([daily_blocklist.yml](.github/workflows/daily_blocklist.yml)): busca nuevos dominios de páginas de juegos a partir de `keywords.txt`, los valida y actualiza `GamesBlockList.txt` / `GamesBlockList_hosts.txt`.
- **Anual** ([yearly_cleanup.yml](.github/workflows/yearly_cleanup.yml)): revisa toda la lista y elimina dominios que ya no responden (ni HTTP/HTTPS ni DNS), dado que las páginas de juegos suelen tener vida útil larga.

## 📄 Licencia

Mantenido por **Josuha Sanhueza (EscolarApp)**.

- **Listas** (`GamesBlockList.txt`, `GamesBlockList_hosts.txt`, `WindowsUpdate.txt`,
  `GoogleUpdate.txt`, `keywords.txt`): [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.es)
  ([texto completo](LICENSE-LISTS)). Puedes usarlas y adaptarlas **citando este repositorio**,
  **sin fines comerciales** y compartiendo tus cambios con la misma licencia. Para uso comercial,
  escríbenos.
- **Código** (`scripts/`, `tests/`, `.github/`): [MIT](LICENSE).

