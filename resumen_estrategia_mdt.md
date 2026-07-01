# Resumen de la Estrategia Institucional (MDT - Joaquín Vega)

Este documento es una recopilación de todas las reglas matemáticas y conceptuales extraídas de los videos del curso de Joaquín Vega, para ser programadas en el algoritmo `el_monstruo`.

## 1. Filosofía de Gestión (Gestión Monetaria)
- **Límite Operativo Diario:** Máximo 4 operaciones al día.
- **Ratio Riesgo/Beneficio:** Mínimo estricto de **1:4**.
- **Movimientos Secundarios (Volumen):** Operar a favor de la dirección que dicta el Primer Ciclo Macro es el "Movimiento Prioritario". Cualquier operación en contra de esta dirección es un "Movimiento Secundario" y **debe operarse con menor volumen/riesgo**.

## 2. El Mapeo del Gráfico (Orígenes y Temporalidades)
- **Punto de Inicio (Multi-Timeframe):** NUNCA mapear el ciclo macro en temporalidades menores a 4 Horas (H4). El Origen Absoluto debe buscarse en Mensual, Semanal, Diario o H4.
- **El Método de las Muñecas Rusas:** Se busca el Impulso Mayor absoluto. Su retroceso es el impulso del siguiente fractal menor. Se itera sobre los retrocesos hasta llegar a la temporalidad deseada, garantizando un anclaje macro.
- **Desgrane del Ruido:** Si un retroceso nuevo es **MAYOR** en pips que los retrocesos anteriores, los Puntos de Control anteriores **MUEREN**. 

## 3. El Primer Ciclo (Macro) y sus 3 Escenarios Actuales
El **Primer Ciclo (Macro)** es el que manda (Ciclos 2 al 5 solo añaden información). Al trazar el Fibo sobre el origen del Primer Ciclo, habrá 3 escenarios:
1. **Caso 1 (Listo para operar):** El precio tocó el 38.2% Y actualmente está dentro de una de las 3 Zonas de Trabajo. Se busca patrón de entrada inmediatamente. (El ciclo macro dicta las 4 informaciones).
2. **Caso 2 (Búsqueda de Sub-ciclos):** El precio tocó el 38.2% (ciclo activo y zonas dibujadas), PERO el precio está flotando en medio del gráfico sin tocar ninguna zona. Como el ciclo macro no nos da información operativa actual, **el algoritmo debe bajar a buscar un Segundo Ciclo (Sub-ciclo)** dentro de la estructura actual que sí esté tocando una de sus propias zonas.
3. **Caso 3 (Ciclo Inactivo):** El retroceso macro nunca llegó al 38.2%. El ciclo macro no existe operativamente.

## 4. Las Zonas de Trabajo (Manipulación Institucional)
- **Tamaño exacto:** Cada zona de trabajo mide exactamente **19.1%** del tamaño del impulso (la mitad de la distancia hasta la extensión de anulación 38.2%).
- **Ubicación de las Cajas (Estructura Matemática Exacta):**
  - **Zona Alta (Ventas):** Comienza exactamente en el nivel **0%** y se extiende hacia afuera hasta el **-19.1%**.
  - **Zona Media (A favor de tendencia):** Comienza exactamente en el **61.8%** y se extiende hacia abajo hasta el **80.9%** (61.8 + 19.1).
  - **Zona Baja (Compras):** Comienza exactamente en el nivel **100%** (el origen) y se extiende hacia afuera hasta el **119.1%** (100 + 19.1).
- **Muerte de Zona:** Si el precio supera el límite exterior de la caja y toca el siguiente nivel (ej: el -38.2% para la Zona Alta), la zona muere definitivamente.
## 5. Gatillo de Entrada (La Regla del 1/3)
- **Falsa Rotura (Entrada):** Si el precio entra en una zona, rompe el límite, pero la distancia de rotura es **menor a 1/3 del ciclo** y es rechazado, entramos.

## 6. Invalidación de Zonas y Ciclos (Cuándo NO operar)
- **Muerte de una Zona:** Si el precio alcanza el siguiente nivel Fibo, la zona **muere para siempre**.
- **Muerte del Ciclo Completo:** Todo el ciclo muere si el precio toca cualquiera de las dos extensiones extremas: **-38.2% o 138.2%**.

## 7. Gestión Dinámica y Stop Loss (Protección en Gráfico)
- **Las 4 Informaciones que nunca deben faltar:** Hacia dónde (dirección), Hasta dónde (Take Profit macro), Dónde te anulan (Stop Loss), Qué te permite (Fibo Seguimiento).
- **Stop Loss (Dónde te anulan):** Al entrar en el 61.8%, el SL inicial va al origen. Si el precio avanza y toca el 38.2%, el SL se mueve al borde de la caja del 61.8%. (En Partes Altas/Bajas, el SL siempre se queda en el origen).
- **Fibo de Seguimiento (Cierre del 50%):** Se traza un Fibo dinámico a favor del trade. Si el retroceso cruza el 61.8% de seguimiento, se cierra el 50%.
- **Acotar la Zona de Seguimiento:** Si la zona del 61.8% del Fibo de Seguimiento se superpone con un nivel de anulación estricto (Stop Loss), la zona de seguimiento se "acota" (recorta) para no permitir que el precio toque la anulación.

## 8. Protocolo de Trabajo en Partes Altas / Bajas (Evolución a Ciclo Mayor)
- **Anulación Inmediata:** Al tocar la Parte Alta/Baja, se borran las demás zonas internas.
- **Fibo de Alerta y Objetivo:** El bot traza un NUEVO Fibo Mayor absoluto. El Take Profit apunta a la **Zona de 61.8% de Alerta** de este nuevo ciclo.
- **Activación del Ciclo Mayor:** Si el precio toca el **38.2% de Alerta**, el Ciclo Mayor se activa. El ciclo menor muere y pasamos a operar el nuevo gran ciclo.

## 9. Patrones de Giro en Zonas de Decisión
Cuando el precio llega a una zona de decisión trazada por nuestros ciclos, solo existen **4 formas posibles en las que el precio puede girar**. Todas las figuras chartistas o patrones de velas nacen de estas cuatro estructuras básicas.

### El Proceso de 3 Pautas
Para que un giro sea operable y objetivo, debe constar de un proceso de al menos **3 pautas (movimientos)**. Todas las estructuras válidas de giro comparten las primeras dos pautas, y se diferencian en la tercera:
1. **Pauta 1 (Llegada):** El precio llega a la zona de decisión.
2. **Pauta 2 (Rechazo):** El precio hace un retroceso inicial (rechazo de la zona).
3. **Pauta 3 (Definición):** El precio vuelve a testear la zona y define el tipo de giro.

### Las 4 Formas de Giro
1. **Vuelta en V (Descartada):** El precio llega a la zona y se da la vuelta inmediatamente. Es un movimiento muy rápido que **solo consta de 2 pautas**. Al no tener Pauta 3, no ofrece información objetiva para operarla, por lo que **se descarta** algorítmicamente.
2. **Falla (Fallo de Máximos / Mínimos):** En la Pauta 3, el precio intenta volver al extremo de la zona pero **falla y no logra alcanzar el máximo/mínimo anterior**. 
3. **Doble Techo / Doble Suelo:** En la Pauta 3, el precio vuelve a re-testear **exactamente** el mismo nivel del máximo/mínimo dejado en la Pauta 1.
4. **El Engaño (Trampa):** En la Pauta 3, el precio supera levemente el máximo/mínimo anterior (hace un falso quiebre) para atrapar a la masa, y luego gira. Es el patrón **más común e importante** ("Patrón de Primer Engaño").

## 10. Anatomía del Patrón de Engaño y Fibo de Entrada
Los patrones de giro tienen la misma estructura sin importar si se dan en una zona de compras o de ventas. A partir del patrón de engaño, se introducen nuevas reglas matemáticas y de temporalidad para su ejecución:

### Temporalidad del Patrón y Confirmación
- **Bajar una Temporalidad:** Para observar las "tripas" del patrón (el desarrollo de las 3 pautas), el algoritmo siempre debe bajar **una temporalidad por debajo** del tamaño del ciclo que se está trabajando (Ej: Si el ciclo es H1, el patrón se busca en M30).
- **Confirmación de la Pauta 2:** Para confirmar que la Pauta 2 (el rechazo) se está formando, el precio debe dejar un extremo definido (máximo o mínimo). Esto se confirma matemáticamente al tener **2 velas cerradas a la izquierda y 2 velas cerradas a la derecha** en la temporalidad inferior.

### Proporcionalidad de la Zona
- Un patrón válido debería alcanzar (profundizar) al menos **la mitad de la zona** de decisión. A esto se le llama "proporcionalidad de la zona" (buscar el trabajo en la zona media del ciclo).

### El Fibo de Entrada y la Zona de Engaños
Se introduce un nuevo tipo de Fibo exclusivo para operar patrones: **El Fibo de Entrada**.
- **Nuevo Nivel (161.8%):** Al Fibo de Entrada se le añade de forma permanente la extensión **161.8%**. Esta extensión sirve ÚNICA Y EXCLUSIVAMENTE para trabajar patrones.
- **Zona de Engaños:** El espacio comprendido entre los niveles de extensión **138.2% y 161.8%** del Fibo de Entrada se denomina "Zona de Engaños". Es la medida objetiva a donde el precio debería llegar en la Pauta 3.
- **Fibo Dinámico (Siguiendo a la Pauta 2):** Una vez detectado el origen de la Pauta 2, se traza el Fibo de Entrada. Si el precio sigue retrocediendo y haciendo nuevos extremos a favor del rechazo, **el Fibo de Entrada debe actualizarse (seguirlo)**. Como consecuencia, la Zona de Engaños se va moviendo dinámicamente.
- **Fin de la Pauta 2 e Inicio de la Pauta 3:** La Pauta 2 se considera FINALIZADA **únicamente** cuando el precio retorna y vuelve a tocar exactamente el nivel extremo (Punto de engaño original) dejado por la Pauta 1. Sin importar cuánto tiempo tarde, mientras no retestee ese nivel, el mercado sigue en Pauta 2. Al tocarlo, inicia la Pauta 3, y en ese instante **la Zona de Engaños queda confirmada, fija y lista para operar**.

## 11. Ejecución del Patrón: La Entrada Agresiva
Una vez que el precio ha llegado a la Zona de Engaños (y asumiendo que es un engaño proporcional que no se ha salido de la zona macro), la Pauta 3 empieza a definirse. Si el precio **respeta el nivel 161.8%** (es decir, se detiene y entra volumen en su contra), estamos listos para operar. La primera forma de atacar este patrón es la **Entrada Agresiva**.

### Reglas de la Entrada Agresiva
- **Gatillo de Entrada:** Se entra a mercado en el instante exacto en que el precio, tras haber hecho el engaño, **cruza de regreso por el Punto de Engaño Original** (se mete de vuelta por debajo o por encima del nivel que rompió para engañar).
- **Sin Esperar Cierres:** Para la entrada agresiva **NO se esperan cierres de vela**. En el momento en que el precio cruza la línea por 1 pip, se ejecuta la operación a mercado.
- **Stop Loss Inicial:** El Stop Loss estructural se coloca justo por encima (en ventas) o por debajo (en compras) del nivel extremo absoluto (la mecha) que dejó el engaño.

### Fibo de Seguimiento y Gestión del Riesgo Inmediato
En el preciso instante en que la orden entra a mercado, el Fibo de Entrada pierde su utilidad. Inmediatamente se debe trazar el **Fibo de Seguimiento**.
- **Trazado:** Se traza desde el origen del movimiento (inicio de la Pauta 2) hasta el extremo absoluto que acaba de dejar el engaño.
- **La Regla del 61.8% de Seguimiento:** Al estar dentro del mercado, es normal (y fractal) que el precio haga retrocesos. Se le permite al precio retroceder hasta la zona del 61.8% de seguimiento.
- **Cierre del 50% por Seguridad:** Si el precio retrocede y **supera por un solo milímetro (1 pip)** el límite exterior de la zona del 61.8% del Fibo de Seguimiento, **se cierra automáticamente el 50% de la posición**. Nunca se permite que el mercado consuma un Stop Loss completo si el precio amenazó la zona de seguimiento.
- **Anulación Total:** Si el precio sigue en contra y vuelve al origen del engaño, la posición (o la mitad restante) se cierra completamente.

### Ventajas y Desventajas
- **Ventaja:** Si el engaño es genuino, el desarrollo del precio a favor será sumamente rápido y potente, permitiendo capturar todo el recorrido desde el origen hacia los objetivos finales.
- **Desventaja:** Tiene un porcentaje de aciertos más bajo, ya que al no esperar cierres, es susceptible a falsos quiebres por volatilidad en el punto de entrada.

## 12. La Entrada Calmada y Filtro de Carencia
Existe una segunda forma de operar el patrón de Primer Engaño, que puede utilizarse por sí sola (por preferencia de riesgo) o como "Plan B" en caso de haber perdido la Entrada Agresiva.

### La Entrada Calmada
El operador calmado no entra a mercado cuando el precio cruza el punto de engaño. En su lugar, espera a que el gatillo agresivo se active primero.
- **Gatillo de Entrada (El Retroceso):** Una vez que el precio activa la entrada agresiva, el operador calmado traza el **Fibo de Seguimiento** (desde el origen de la Pauta 2 hasta el extremo absoluto del engaño) y **espera pacientemente a que el precio haga un retroceso y toque la zona del 61.8% de seguimiento**. En el instante en que toca esa zona, entra a mercado.
- **Stop Loss:** Se coloca exactamente en el mismo sitio que el del agresivo (en el extremo absoluto del engaño). Al entrar desde el 61.8%, el riesgo asumido (tamaño del Stop) es mucho menor.
- **Gestión Inmediata (Idéntica):** La regla de protección es la misma. Si el precio retrocede un solo milímetro (1 pip) por fuera del límite de la zona del 61.8% de seguimiento, se cierra el 50% de la posición.
- **Ventaja / Desventaja:** La gran ventaja es que se trabaja con Stop Loss más reducidos (mejor Ratio R:B) y entradas estadísticamente más fiables. La desventaja es que, si el movimiento institucional es muy violento y el precio se va sin hacer jamás el retroceso al 61.8%, el operador calmado se queda sin operar.

### Filtro Algorítmico: Entradas con Carencia (Requisito del 161.8%)
Para que un patrón de engaño sea de alta calidad, el precio DEBE llegar y consumir (tocar) el nivel **161.8%** de la Zona de Engaños.
- **Entrada con Carencia (NO Operar):** Si el precio llega a la Zona de Engaños (ej. supera el 138.2%) pero **NO alcanza el 161.8%**, y se devuelve dando el gatillo agresivo, es una entrada con carencia. **Algorítmicamente, ESTAS ENTRADAS SE FILTRAN Y SE DESCARTAN**.
- **La trampa del engaño fraccionado:** La razón para no operarlas es que es altamente probable que el mercado esté haciendo un engaño fraccionado, y termine regresando más tarde a re-testear y consumir el 161.8%, lo cual barrería los Stop Loss de los operadores prematuros.
- **Excepción de Validación Posterior:** Solo se puede dar por válido un engaño que no tocó el 161.8% si, al devolverse, el precio desarrolla tanta fuerza que logra **romper con claridad el origen de la Pauta 2** (el máximo o mínimo donde inició el rechazo). Si eso ocurre, el engaño se valida retroactivamente y solo entonces se podría buscar una **Entrada Calmada** utilizando el Fibo de Seguimiento de ese impulso ya confirmado.

## 13. Rotura y Muerte del Patrón de Engaño
Saber cuándo un patrón deja de ser válido es de vital importancia para el algoritmo, evitando que opere figuras rotas. El nivel clave que dicta la validez del patrón de Primer Engaño es el pico (extremo) dejado en el nivel **161.8%**.

### Regla de Invalidez: El Doble Retesteo
Una vez que el precio ha llegado al 161.8% de la Zona de Engaños, lo ha respetado y ha dejado un extremo claro (confirmado por 2 velas cerradas a la izquierda y 2 a la derecha), **ese nivel extremo se vuelve intocable**.
- **La Muerte del Patrón:** Si el precio, ya sea antes o después de dar el gatillo de entrada, se devuelve y **vuelve a retestear (tocar por segunda vez) la línea del extremo dejado en el 161.8%**, el patrón SE ROMPE Y SE MUERE automáticamente.
- Un patrón de Primer Engaño **jamás permite un doble retesteo de su nivel de engaño absoluto**. Si esto ocurre, todo lo analizado para ese patrón queda invalidado y el algoritmo debe pasar a buscar otro tipo de estructura (lo que se conoce como "Segundo Patrón").

### Resumen de Condiciones del Primer Engaño
Para que el bot procese un Primer Engaño perfecto, debe validar el siguiente checklist:
1. **Contexto:** El precio está operando dentro de una Zona de Decisión activa.
2. **Proporcionalidad:** El patrón entra hasta la zona media pero NUNCA se escapa de los límites de la zona macro del ciclo.
3. **Temporalidad:** El análisis de las pautas se ejecuta en una temporalidad inmediatamente inferior a la del ciclo.
4. **Estructura (3 Pautas):** Existe Pauta 1 (Llegada), Pauta 2 (Rechazo) y Pauta 3 (Definición).
5. **Carencia (Requisito 161.8%):** La Pauta 3 alcanza y consume obligatoriamente el nivel 161.8% del Fibo de Entrada.
6. **Muerte (Cero Retesteos):** El pico absoluto dejado en el 161.8% nunca vuelve a ser retesteado.
7. **Gatillo:** Se ejecuta la entrada al cruzar agresivamente el engaño original, o al presentarse el retroceso calmado a la zona del 61.8% del Fibo de Seguimiento.

## 14. Evolución de Patrones: El Segundo Engaño
El mercado institucional no solo presenta las formas básicas de giro, sino que constantemente hace *combinaciones* o iteraciones de las mismas. Una de las evoluciones más comunes se da cuando un Patrón de Primer Engaño fracasa, dando origen al **Patrón de Segundo Engaño**.

### La Trampa de la Falta de Proporcionalidad
Es frecuente que el mercado forme un Patrón de Primer Engaño cuya estructura sea "perfecta" (cumple las 3 pautas, llega y respeta el 161.8%, y da el gatillo de entrada). Sin embargo, puede tener un defecto crítico: **No es proporcional**.
- **El Problema:** Su Zona de Engaños (161.8%) se queda muy corta y no logra alcanzar la mitad de la zona macro de decisión. Es un patrón "pequeño" arrinconado en el borde de la caja.
- **Regla Algorítmica (Filtro Estricto):** NUNCA se debe tomar una entrada si el patrón no es proporcional. Es altísimamente probable que ese patrón prematuro falle, rompa su nivel de 161.8% y barra con los Stop Loss de los operadores que entraron muy temprano.

### La Mecánica del Segundo Engaño
Cuando ese primer engaño pequeño se rompe (el precio se devuelve y retestea su pico del 161.8%), el patrón de Primer Engaño muere, pero evoluciona inmediatamente al **Segundo Engaño**. Esto no es más que el mismo patrón repetido por segunda vez, pero más profundo en la zona.
- **Cambio de Medición (El Segundo Rechazo):** El Fibo de Entrada original del primer engaño se descarta. Ahora, se debe medir **el segundo rechazo** que tuvo el precio en la zona (el retroceso que ocasionó el fallo del primer intento).
- **Nueva Zona de Engaños:** Al proyectar el nuevo Fibo de Entrada sobre este segundo rechazo, la nueva Zona de Engaños (138.2% a 161.8%) quedará ubicada mucho más profunda dentro de la zona de decisión. **Ahora sí, este Segundo Engaño será proporcional a la zona.**
- **Mismas Reglas Operativas:** Una vez identificada la nueva Zona de Engaños proporcional, el algoritmo aplica **exactamente las mismas reglas** que en el Primer Engaño:
  1. Esperar a que el precio llegue y respete el nuevo nivel de 161.8%.
  2. El nuevo "Punto de Engaño Original" (el nivel a romper para el gatillo) será el extremo dejado por el segundo rechazo.
  3. Ejecutar Entrada Agresiva (al quiebre) o Calmada (al retroceso).
  4. Mismas reglas de gestión con el Fibo de Seguimiento y protección del 50% ante retrocesos al 61.8%.

## 15. El Límite de la Manipulación: El Tercer Engaño
En algunas ocasiones, la manipulación institucional es aún más profunda y enrevesada con el objetivo de acumular mayor cantidad de contratos antes de liberar el precio. Esto da lugar a la repetición del patrón de engaño hasta una tercera vez dentro de la misma zona.

### Evolución al Tercer Engaño
Si el Patrón de Segundo Engaño (que ya era proporcional y válido) fracasa y el precio rompe su extremo de 161.8%, el patrón muere y evoluciona al **Tercer Engaño**.
- **Mecánica de Medición:** Se debe medir el **tercer rechazo** (el retroceso que ocasionó la rotura del segundo engaño). Al trazar el Fibo de Entrada sobre este tercer rechazo, obtenemos la nueva Zona de Engaños (más profunda).
- **Mismas Reglas Operativas:** El comportamiento esperado y las reglas de gatillo, Stop Loss y Fibo de Seguimiento son exactamente las mismas que en las versiones anteriores.

### La Regla del Volumen (Gestión de Riesgo)
- Si el algoritmo ejecutó una pérdida válida en el Segundo Engaño (recordando que el Primero no se debió operar si le faltaba proporcionalidad), al presentarse el Tercer Engaño la entrada es válida, PERO se debe entrar con **menor volumen (menor riesgo/lotaje)**. El contexto ya ha hecho fallar al sistema una vez en esa zona, por lo que la exposición monetaria debe reducirse.

### El Límite Absoluto (La Regla del 3)
- **Máximo 3 Engaños:** El algoritmo NUNCA debe procesar ni buscar más de tres iteraciones de este patrón. Si el Tercer Engaño se rompe, la secuencia de engaños finaliza.
- Matemáticamente, un "cuarto engaño" es inviable porque obligaría al precio a salirse por completo de los límites de la Zona de Decisión (anulando el ciclo macro), por lo que la estrategia descarta cualquier manipulación más allá del tercer nivel.

## 16. El Patrón de Entrada Profunda (Pauta 3 Corta)
Habrá escenarios donde el precio entra de una forma tan agresiva a la zona de trabajo que imposibilita matemáticamente la formación de un patrón de engaño válido.

### Invalidación del Engaño por Límite de Zona
Cuando el precio entra muy profundo en la caja y hace una Pauta 2 (rechazo), el bot traza el Fibo de Entrada para buscar el patrón de Primer Engaño. 
- **La Regla de Exclusión:** Si al proyectar la Zona de Engaños, **al menos UNO de los niveles (ej. el 161.8%) se proyecta FUERA de los límites de la Zona de Decisión** (o queda exactamente al ras del límite macro), ese nivel de engaño NO SIRVE.
- Bastaría con que solo el 161.8% quede fuera del límite de la zona para que el engaño se descarte por completo. Automáticamente, el algoritmo cambia de estrategia operativa.

### Mecánica de la Entrada Profunda (Pauta 3 Corta)
Al descartar el engaño, pasamos a operar lo que se conoce como **Patrón de Entrada Profunda en Zona**.
- **Cambio de Foco:** Ya no nos interesan los niveles de extensión 138.2/161.8. En su lugar, el mismo Fibo con el que estábamos midiendo la Pauta 2 se utilizará exclusivamente para buscar un retroceso interno.
- **Gatillo de Entrada (La Pauta 3 Corta):** El algoritmo ahora solo espera a que el precio haga un retroceso (Pauta 3 Corta) hacia la **Zona del 61.8%** de ese mismo Fibo. En el instante en que el precio toca el 61.8%, se ejecuta la entrada a mercado. (No existe opción de entrada agresiva en este patrón, siempre se espera al retroceso).
- **Stop Loss:** El Stop Loss estructural se coloca inmediatamente por encima (ventas) o por debajo (compras) del punto extremo más profundo que haya dejado el precio en la zona antes de iniciar el retroceso.

### Gestión Inmediata (La Regla del Milímetro)
La misma zona del 61.8% utilizada para entrar, servirá simultáneamente para gestionar el riesgo de la operación.
- Si una vez ejecutada la orden, el precio sigue en contra y **se escapa por un solo milímetro (1 pip)** del límite exterior de la zona del 61.8%, el algoritmo ejecuta un **cierre del 50% de la posición**. Esta regla protege el capital ante la posibilidad de que el mercado decida continuar en contra y anular la entrada profunda.

## 17. El Patrón de Engaño Extremo (La Última Oportunidad)
El Engaño Extremo ocurre cuando el precio rompe los límites de la Zona de Decisión pero sin llegar a tocar el nivel de anulación (el siguiente nivel Fibo que mataría la zona por completo). Esta es la última oportunidad que tiene el mercado para darse la vuelta en esa zona de trabajo.

### La Zona de Indecisión
- El espacio que existe entre el límite exterior de nuestra zona de trabajo y el nivel de anulación definitivo se denomina **Zona de Indecisión**.
- Cuando el precio entra en esta área, **es inoperable**. El algoritmo debe pausar su operativa y no tomar ninguna decisión mientras el precio esté flotando por fuera de los límites de la zona. 

### El Filtro de Calidad (La Regla del 25%)
No todo escape de zona califica como un Engaño Extremo operable. Para que este patrón sea algorítmicamente válido, el precio debe demostrar que su objetivo era buscar liquidez profunda (barrer stops fuertemente).
- **Regla Estricta:** Un engaño extremo SOLO ES VÁLIDO si el precio logra adentrarse **al menos un 25% de la longitud total de la Zona de Indecisión**.
- Si el precio sale de la zona pero recorre menos del 25% (un escape muy tímido/pequeño), **el patrón se descarta y no se opera**. Es altamente probable que sea una trampa y termine haciendo una sacudida mucho más potente después.

### Operativa y Gatillos
La salida (escape de zona) suele darse con mucha velocidad (velas grandes o mechazos profundos), y el retorno debe ser igual de contundente.
- **Entrada Agresiva:** El bot ejecuta la orden a mercado en el instante exacto en que el precio, tras haber cumplido la regla del >25%, **vuelve a meterse (cruza la línea) hacia el interior de nuestra Zona de Decisión original**. No se esperan cierres de vela.
- **Stop Loss:** El SL estructural se ubica inmediatamente por encima (ventas) o por debajo (compras) del punto máximo absoluto que dejó el engaño extremo en la zona de indecisión.
- **Fibo de Seguimiento y Entrada Calmada:** Una vez ejecutada la orden agresiva (o si se prefiere entrar calmado), se traza inmediatamente el Fibo de Seguimiento desde el origen absoluto del movimiento y se ubica la zona del 61.8%.
- **Gestión Inmediata (50%):** De la misma manera, si el retroceso posterior quiebra la zona del 61.8% de seguimiento por 1 solo pip, se ejecuta el cierre de seguridad del 50% de la posición.

## 18. Evolución: Doble Suelo / Doble Techo con Impulso
Este patrón surge como una evolución o "cambio de plan" cuando el precio, estando en pleno desarrollo de la Pauta 3, no logra alcanzar los niveles de engaño previstos.

### El Gatillo de Transición (La Regla del Tercio)
- **La Situación Inicial:** El bot está midiendo un patrón de engaño normal (proporcional). El precio ha confirmado que entramos en la Pauta 3, y estamos esperando que llegue a la zona de engaños (mínimo al 138.2%). 
- **La Ruptura Temprana:** Si el precio no llega a los niveles de engaño y, por el contrario, se devuelve con fuerza en contra de nuestra expectativa y **rompe el extremo de la Pauta 2 (el máximo/mínimo donde inició el rechazo)**, el bot debe activar una validación matemática.
- **Regla del 1/3 (El Filtro):** Si esa ruptura supera el extremo de la Pauta 2 por una distancia **igual o mayor a UN TERCIO (1/3) de la altura total de esa Pauta 2**, el patrón cambia inmediatamente. Ya no buscamos engaños; la estructura ha evolucionado a un **Doble Suelo (o Doble Techo) con Impulso**.

### Mecánica Operativa del Patrón
Una vez que el precio confirma la ruptura con la regla del tercio, el análisis de engaño se descarta y el bot debe ajustarse al nuevo escenario:
- **Cambio de Fibo:** El Fibo de Entrada antiguo se elimina. Se debe trazar un **Fibo de Seguimiento** a TODO el nuevo gran impulso que acaba de generar el precio (desde la máxima dilatación en la base de la Pauta 3, hasta el extremo final de la rotura que superó el tercio).
- **Gatillo (Sin Entrada Agresiva):** En este patrón no existe entrada agresiva. El algoritmo simplemente debe esperar el retroceso natural del precio hacia la **zona del 61.8%** de este nuevo Fibo de seguimiento. En el instante en que el precio toca el 61.8%, se ejecuta la entrada a mercado.
- **Stop Loss Estructural:** El SL se coloca inmediatamente por encima (en ventas) o por debajo (en compras) de la **máxima dilatación (la mecha absoluta del inicio del impulso)**. 
- **La Muerte del Patrón:** El precio tiene estrictamente prohibido volver a tocar esa máxima dilatación original. Si el mercado retrocede tan profundo que vuelve a testear esa mecha base, el patrón de Doble Suelo/Techo se considera roto y se debe buscar un nuevo análisis.

## 19. Concurrencia de Zonas (Superposición de Ciclos)
Al trabajar con más de un ciclo (ej. un Ciclo Mayor Macro y un Ciclo Menor o Sub-ciclo), es muy común que sus zonas operativas se superpongan. A esto se le llama **Concurrencia**. Las reglas de concurrencia **solo aplican a zonas de la misma dirección** (ej. Compras con Compras, o Ventas con Ventas). La regla de oro es: **La Zona Mayor siempre manda**. Existen 3 tipos de concurrencias:

### Caso 1: Inmersión Total (La más simple)
- **Escenario:** La Zona Menor (del sub-ciclo) está **completamente inmersa** (metida por completo) dentro de la Zona Mayor (del ciclo macro).
- **Regla:** La Zona Menor desaparece y se elimina automáticamente. NO se buscan patrones basándose en la medida de la Zona Menor. Todo patrón y gestión se trabaja usando exclusivamente los límites de la Zona Mayor.

### Caso 2: Ataque Frontal a Zona Menor (Zona Libre)
- **Escenario:** El precio se acerca a la concurrencia y **primero ataca a la Zona Menor**, la cual se superpone parcialmente con la Zona Mayor que está más atrás.
- **La Regla de la Mitad Libre:** La Zona Menor es útil y válida **SOLO SI** tiene "claramente" al menos **la mitad (50%) de su tamaño libre** antes de solaparse con la Zona Mayor.
- **Acción:** Si tiene la mitad libre, se deja la Zona Menor como válida, **pero se acota (recorta)** exactamente en el límite donde empieza la Zona Mayor. Se buscan patrones en ese espacio libre. Si NO tiene al menos la mitad de su tamaño libre, la Zona Menor se elimina y solo queda la Zona Mayor.

### Caso 3: El Sándwich (Ataque a Zona Mayor)
- **Escenario:** El precio se acerca a la concurrencia y **primero ataca a la Zona Mayor**. La Zona Menor está escondida o solapada en la parte de atrás de la Zona Mayor (como un sándwich).
- **Regla Estricta:** La Zona Menor **JAMÁS SIRVE** en este escenario. Directamente se elimina del gráfico y toda la operativa se centra exclusivamente en la Zona Mayor.
