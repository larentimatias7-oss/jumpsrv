---
name: modern-component-patterns
description: Genera y refina interfaces web modernas, componentes desacoplados y sistemas visuales corporativos siguiendo la paleta de marca y diseño de Milicic (naranja constructora, gris pizarra, blanco y grises neutros). Úsalo cuando diseñes UI, dashboards, formularios o maquetas web.
---

# Skill: Modern Component Patterns (Milicic Design System)

## 1. Identidad Visual y Paleta de Colores (Milicic Brand)
El diseño debe reflejar solidez ingenieril, industria de gran escala y claridad corporativa:

- **Color Primario / Acento:** `#F39200` (Naranja Milicic).
  - *Uso:* Botones principales (CTA), bordes de métricas activas, badges destacados, barras de progreso y acentos en títulos.
  - *Hover:* `#D98200`
- **Color Secundario / Cabeceras:** `#2A343D` (Gris Pizarra Oscuro).
  - *Uso:* Barras de navegación superiores, texto de títulos de alta jerarquía y footers.
- **Fondo Principal:** `#FFFFFF` (Blanco puro) y fondos de tarjetas en `#F8F9FA` / `#F1F3F5`.
- **Modo Oscuro (Dark Mode):**
  - *Fondo de página:* `#0F141A` (Carbón profundo).
  - *Superficies / Tarjetas / Modales:* `#1A222B` (Pizarra oscuro refinado).
  - *Cabecera en Modo Oscuro:* `#141A20`.
  - *Bordes y separadores:* `#2D3742` / `#242D36`.
  - *Texto principal en modo oscuro:* `#F1F5F9` (alto contraste).
  - *Texto secundario:* `#CBD5E1` y `#94A3B8`.
  - *Acentos y Badges:* Naranja Milicic `#F39200` con fondos suaves translúcidos `rgba(243, 146, 0, 0.16)`.
- **Tipografía y Textos:**
  - Títulos: `#1A2026` o `#2A343D` (modo claro) / `#F1F5F9` (modo oscuro).
  - Texto base / Párrafos: `#4A5568` (modo claro) / `#CBD5E1` (modo oscuro).
  - Acentos tipográficos: Se permite naranja en subtítulos destacados o métricas numéricas.

---

## 2. Reglas de Composición y Componentes

### A. Tarjetas de Métricas / Stats (Estilo Milicic)
Inspiradas en los círculos y badges de logros de la web institucional:
- Contenedores limpios con bordes sutiles o aros en color naranja (`border-2 border-[#F39200]`).
- Cifras en gran formato tipográfico (`text-3xl` o `text-4xl`, `font-bold`, color `#F39200` o `#2A343D`).
- Etiquetas descriptivas inferiores en gris neutro (`text-sm text-[#4A5568]`).

### B. Botones y Elementos Interactivos
- **Primario:** Fondo `#F39200`, texto `#FFFFFF` (o `#1A2026` si se requiere máximo contraste), esquinas suaves (`rounded-md` o `rounded-lg`), sin bordes gruesos agresivos.
- **Secundario / Outline:** Fondo transparente o blanco, borde `border-2 border-[#2A343D]`, texto `#2A343D`.
- **Efectos:** Transición sutil (`transition-all duration-200 hover:shadow-md`).

### C. Navegación y Encabezados
- Barra de navegación sólida en tono oscuro `#2A343D` con texto blanco/gris claro (`#E2E8F0`) o barra blanca limpia con acentos y logo naranja.
- Separadores sutiles usando tonos grises fríos (`#E5E7EB`).

---

## 3. Principios de Código y Arquitectura UI
1. **Espaciado Matemático:** Trabajar sobre una cuadrícula base de 8px (Tailwind: `gap-2`, `gap-4`, `p-6`, etc.).
2. **Jerarquía Visual:** Ningún elemento compite con el botón de acción principal o el indicador de estado.
3. **Accesibilidad:** Mantener un ratio de contraste mínimo de 4.5:1 para todo texto legible. Evitar colocar texto blanco sobre naranja claro sin verificar contraste; preferir texto oscuro o usar el naranja como borde/icono.
4. **Verificación en Antigravity:** Cuando se genere código HTML/React/Tailwind, levantar o validar la vista con el visor integrado para garantizar fidelidad cromática y adaptabilidad responsive.
