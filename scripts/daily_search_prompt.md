# Tarea diaria: buscar y agregar nuevos sitios de juegos

Este es el repo `BlockList` (lista de bloqueo de páginas de juegos para AdGuard/Unbound).
Ya estás parado en el directorio del repo. Hacé lo siguiente, en orden:

1. `git pull --ff-only origin main` para partir del estado más reciente.

2. Buscá sitios nuevos de juegos usando esta metodología (la que mejor rindió):
   - Preferí **artículos "top X páginas de juegos"** ("mejores webs de juegos online 2026",
     "lista de páginas de juegos gratis", "alternativas a friv", "juegos de [categoría] sitios
     recomendados 2026") y extraé TODOS los dominios que mencionan con WebFetch — rinde muchísimo
     más que buscar juego por juego.
   - Complementá con 3-5 búsquedas web dirigidas a categorías de juegos que la lista actual
     no cubra bien (revisá `keywords.txt` para ver qué ya está cubierto).
   - Opcional: la API de GitHub (`https://api.github.com/search/repositories?q=topic:X`) para
     topics como `unblocked-games`, `eaglercraft`, `friv-games` — sacá el campo `homepage` de
     cada repo.

3. Para cada dominio candidato nuevo (que no esté ya en `GamesBlockList.txt`), verificalo con
   la función real del proyecto, NUNCA lo agregues sin verificar:
   ```python
   from scripts.update_blocklist import is_game_website
   is_game_website("dominio.com")  # True/False
   ```
   Solo se agregan los que dan `True`.

4. **Antes de agregar un dominio que parezca infraestructura amplia** (CDN compartido, plataforma
   de crowdfunding, gran institución con contenido no relacionado a juegos — ej. lo que pasó con
   Fastly y Kickstarter), usá criterio: si bloquearlo de raíz afectaría un montón de sitios sin
   relación a juegos, excluilo a mano aunque haya pasado la verificación automática, y considerá
   agregarlo a `WHITELIST` en `scripts/update_blocklist.py` con un comentario explicando por qué.

   **Nunca bloquees un hosting, CDN o dominio compartido completo** (`github.io`, `vercel.app`,
   `pages.dev`, `netlify.app`, `cloudfront.net`, `it.com`, `us.com`...): bloqueá el subdominio del
   juego (`juego.github.io`). La lista está en `SHARED_SUFFIXES` (`scripts/validate_blocklist.py`) y
   el validador la hace cumplir, igual que rechaza los sitios del top 10.000 de Tranco que no estén
   en `POPULAR_APPROVED`. Si el validador rechaza un dominio, no lo fuerces: dejalo para revisión.

5. Agregá los dominios confirmados a `GamesBlockList.txt` (formato `||dominio^`, sin `www.`,
   sin duplicados — dedupeá contra lo que ya existe).

6. Extraé keywords nuevas de los dominios agregados hoy (fragmentos de nombre distintivos,
   no palabras genéricas en inglés/español que puedan traer ruido — ver el problema que causó
   la keyword "arch" antes de ahora) y agregalas a `keywords.txt` con un comentario de fecha.

7. Corré: `python3 scripts/validate_blocklist.py`, `python3 -m pytest tests/ -q`, y
   `python3 scripts/generate_hosts_format.py`. Todo debe pasar antes de comitear.

8. Si hay cambios: `git add -A`, comiteá con un mensaje descriptivo (cuántos dominios, de qué
   fuente), `git pull --rebase origin main`, `git push`.

9. Si no encontrás nada nuevo hoy, no hagas commit vacío — está bien, no todos los días hay
   resultados.

Roblox ya está en la lista (desde el 2026-10-20, para que el docente lo controle con "Permitir
juegos"); no hace falta buscar sus dominios principales. No uses fuentes que sean
explícitamente "herramientas de evasión/bypass" (ej. listas tipo ByePassHub) si la herramienta
de fetch las rechaza por ese motivo — no lo intentes rodear con curl u otro método.

**No bloquees contenido 100% educativo** (juegos de matemáticas, geografía, mecanografía,
ortografía, dibujo infantil, entrenamiento cognitivo/atención, etc.), aunque `is_game_website()`
lo marque como `True` — el objetivo del proyecto es bloquear distracción, no aprendizaje. Si un
sitio es inequívocamente curricular/educativo, no lo agregues (y si lo agregaste sin darte cuenta,
sacalo y agregalo a `WHITELIST` con un comentario). Si una página mezcla contenido educativo con
juegos de puro entretenimiento, se revisa a mano — no la agregues ni la excluyas por tu cuenta,
dejala para revisión del usuario.
