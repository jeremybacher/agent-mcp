"use strict";

// Todo lo que viene del agente o del padrón se inserta como texto (textContent),
// nunca como HTML: la página no arma marcado a partir de datos.

const VERIFICAR = "verificar-proveedores";
const PREGUNTAR = "consultar-datos";

const MODOS = {
  [PREGUNTAR]: {
    titulo: "Preguntar",
    ayuda: "Responde con lo ya verificado. No consulta ARCA.",
    placeholder: "Preguntá sobre los proveedores ya verificados…",
  },
  [VERIFICAR]: {
    titulo: "Verificar CUITs",
    etiqueta: "ARCA",
    ayuda: "Consulta el Padrón de ARCA.",
    placeholder: "Pegá uno o más CUITs, uno por línea o separados por coma…",
  },
};

const SUGERENCIAS = [
  { texto: "¿Qué proveedores tenemos?", modo: PREGUNTAR, enviar: true },
  { texto: "¿Cuáles están inactivos?", modo: PREGUNTAR, enviar: true },
  { texto: "Verificar un CUIT", modo: VERIFICAR, enviar: false },
];

// Mismos topes que aplica el servidor: así la petición no se pasa de tamaño.
const MAX_TURNOS = 6;
const MAX_CHARS_TURNO = 2000;
const MAX_CHARS_INFORME = 8000;
const MAX_BYTES_ARCHIVO = 64 * 1024;
const CLAVE_TEMPERATURE = "arca-agent.temperature";
const REINTENTOS_DE_CONEXION = 3;

const recortar = (texto, max) => (texto.length > max ? texto.slice(0, max) : texto);
const esperar = (ms) => new Promise((resolver) => setTimeout(resolver, ms));
const $ = (id) => document.getElementById(id);

let modo = PREGUNTAR;
let corriendo = false;
let mensajes = []; // { tipo: "usuario" | "agente" | "sistema", ... }
let corte = 0; // el agente solo "ve" los mensajes desde este índice
let temperatureDelAgente = 0;
let modoElegidoAMano = false;
let consultas = [];

function el(etiqueta, atributos = {}, texto = "") {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) nodo.setAttribute(clave, valor);
  if (texto) nodo.textContent = texto;
  return nodo;
}

async function api(metodo, ruta, cuerpo) {
  const opciones = { method: metodo, cache: "no-store" };
  // Todo lo que no es lectura viaja como JSON: es lo que el servidor exige contra CSRF.
  if (metodo !== "GET") {
    opciones.headers = { "Content-Type": "application/json" };
    opciones.body = JSON.stringify(cuerpo ?? {});
  }
  const res = await fetch(ruta, opciones);
  let datos = {};
  try {
    datos = await res.json();
  } catch (_) {
    // respuesta sin cuerpo JSON
  }
  if (!res.ok) throw new Error(datos.error || `Error ${res.status}`);
  return datos;
}

const formatearCuit = (cuit) =>
  /^\d{11}$/.test(cuit ?? "")
    ? `${cuit.slice(0, 2)}-${cuit.slice(2, 10)}-${cuit.slice(10)}`
    : (cuit ?? "");

// ---------- Markdown (subconjunto seguro) ----------

function inline(texto, padre) {
  for (const parte of texto.split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
    if (!parte) continue;
    if (parte.length > 4 && parte.startsWith("**") && parte.endsWith("**")) {
      padre.append(el("strong", {}, parte.slice(2, -2)));
    } else if (parte.length > 2 && parte.startsWith("`") && parte.endsWith("`")) {
      padre.append(el("code", {}, parte.slice(1, -1)));
    } else {
      padre.append(document.createTextNode(parte));
    }
  }
}

function celdas(linea) {
  return linea.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function esSeparadorDeTabla(linea) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(linea || "");
}

function desenvolver(md) {
  // El modelo a veces envuelve todo el informe en un bloque ```markdown.
  const m = /^\s*```(?:markdown|md)?\s*\n([\s\S]*?)\n```\s*$/.exec(md);
  return m ? m[1] : md;
}

function renderMarkdown(md) {
  const fragmento = document.createDocumentFragment();
  const lineas = desenvolver(md).replace(/\r\n/g, "\n").split("\n");
  let i = 0;

  while (i < lineas.length) {
    const linea = lineas[i];
    if (!linea.trim()) {
      i++;
      continue;
    }

    const titulo = /^(#{1,3})\s+(.*)$/.exec(linea);
    if (titulo) {
      const h = el("h" + (titulo[1].length + 2));
      inline(titulo[2], h);
      fragmento.append(h);
      i++;
      continue;
    }

    if (linea.trim().startsWith("```")) {
      const codigo = [];
      i++;
      while (i < lineas.length && !lineas[i].trim().startsWith("```")) codigo.push(lineas[i++]);
      i++;
      fragmento.append(el("pre", {}, codigo.join("\n")));
      continue;
    }

    if (linea.trim().startsWith("|") && esSeparadorDeTabla(lineas[i + 1])) {
      const tabla = el("table");
      const cabecera = el("tr");
      for (const c of celdas(linea)) {
        const th = el("th");
        inline(c, th);
        cabecera.append(th);
      }
      const encabezado = el("thead");
      encabezado.append(cabecera);
      tabla.append(encabezado);
      const cuerpo = el("tbody");
      i += 2;
      while (i < lineas.length && lineas[i].trim().startsWith("|")) {
        const fila = el("tr");
        for (const c of celdas(lineas[i])) {
          const td = el("td");
          inline(c, td);
          fila.append(td);
        }
        cuerpo.append(fila);
        i++;
      }
      tabla.append(cuerpo);
      const envoltorio = el("div", { class: "tabla-scroll" });
      envoltorio.append(tabla);
      fragmento.append(envoltorio);
      continue;
    }

    if (/^\s*[-*]\s+/.test(linea)) {
      const lista = el("ul");
      while (i < lineas.length && /^\s*[-*]\s+/.test(lineas[i])) {
        const item = el("li");
        inline(lineas[i].replace(/^\s*[-*]\s+/, ""), item);
        lista.append(item);
        i++;
      }
      fragmento.append(lista);
      continue;
    }

    const parrafo = el("p");
    const texto = [];
    while (
      i < lineas.length &&
      lineas[i].trim() &&
      !/^(#{1,3}\s|\s*[-*]\s|\s*\||\s*```)/.test(lineas[i])
    ) {
      texto.push(lineas[i++].trim());
    }
    if (!texto.length) texto.push(lineas[i++].trim());
    inline(texto.join(" "), parrafo);
    fragmento.append(parrafo);
  }
  return fragmento;
}

// ---------- Temperatura editable ----------

function normalizarTemperature(valor) {
  const n = Number(valor);
  if (valor === null || valor === "" || !Number.isFinite(n) || n < 0 || n > 2) return null;
  return Math.round(n * 10) / 10;
}

function temperatureGuardada() {
  try {
    return normalizarTemperature(localStorage.getItem(CLAVE_TEMPERATURE));
  } catch (_) {
    return null; // almacenamiento bloqueado: se usa el valor del agente
  }
}

function guardarTemperature(valor) {
  try {
    localStorage.setItem(CLAVE_TEMPERATURE, String(valor));
  } catch (_) {
    // sin almacenamiento: el valor vale solo para esta sesión
  }
}

const temperatureActual = () => Number($("temperature").value);

function mostrarTemperature() {
  const valor = temperatureActual();
  $("temperature-valor").textContent = String(valor);
  $("resumen-ajustes").textContent = `temp ${valor}`;
  $("temperature-reset").hidden = valor === temperatureDelAgente;
  $("temperature-reset").textContent = `Restablecer (${temperatureDelAgente})`;
}

function iniciarTemperature(delAgente) {
  temperatureDelAgente = delAgente;
  $("temperature").value = String(temperatureGuardada() ?? delAgente);
  mostrarTemperature();
}

// ---------- Herramientas (pastillas) ----------

function resumirArgumentos(argumentos) {
  const pares = Object.entries(argumentos || {}).map(([clave, valor]) => {
    let texto = typeof valor === "string" ? valor : String(JSON.stringify(valor) ?? "");
    if (texto.length > 28) texto = texto.slice(0, 28) + "…";
    return `${clave}=${texto}`;
  });
  return recortar(pares.join(", "), 90);
}

function textoDeResultado(h) {
  if (h.estado === "ejecutando") return "ejecutando…";
  if (h.estado === "ok") return `✓ ${h.ms} ms`;
  return `✗ falló${h.error ? ": " + recortar(String(h.error), 60) : ""}`;
}

function pintarPastilla(nodo, h) {
  nodo.className = "herramienta " + h.estado;
  nodo.title = h.estado === "error" && h.error ? String(h.error) : "";
  nodo.replaceChildren(
    el("span", { class: "punto" }),
    el("code", { class: "nombre" }, h.nombre),
    el("span", { class: "args" }, `(${resumirArgumentos(h.argumentos)})`),
    el("span", { class: "resultado" }, textoDeResultado(h)),
  );
}

function crearPastilla(h) {
  const nodo = el("div");
  pintarPastilla(nodo, h);
  return nodo;
}

// ---------- Streaming de eventos ----------

function nuevaSesion(destinos) {
  return { texto: "", herramientas: [], pastillas: new Map(), pendiente: false, destinos };
}

function programarRender(sesion) {
  if (sesion.pendiente) return;
  sesion.pendiente = true;
  requestAnimationFrame(() => {
    sesion.pendiente = false;
    sesion.destinos.contenido.replaceChildren(renderMarkdown(sesion.texto));
    sesion.destinos.alRenderizar?.();
  });
}

function actualizarEscribiendo(sesion) {
  const nodo = sesion.destinos.escribiendo;
  if (!nodo) return;
  const hayHerramientaCorriendo = [...sesion.pastillas.values()].some(
    ({ h }) => h.estado === "ejecutando",
  );
  nodo.hidden = sesion.texto.length > 0 || hayHerramientaCorriendo;
}

const esLineaDeHerramienta = (linea) => /^\[\d+\]/.test(linea);

function aplicarEvento(evento, sesion) {
  const d = sesion.destinos;
  if (evento.tipo === "traza") {
    // Las llamadas a herramientas se muestran como pastillas, no como líneas de texto.
    if (!esLineaDeHerramienta(evento.linea)) d.traza?.(evento.linea);
  } else if (evento.tipo === "herramienta") {
    // Lo que el modelo haya dicho antes de llamar a la herramienta no es la respuesta.
    sesion.texto = "";
    d.contenido.replaceChildren();
    const h = {
      nombre: evento.nombre,
      argumentos: evento.argumentos,
      estado: "ejecutando",
      ms: 0,
      error: null,
    };
    const nodo = crearPastilla(h);
    sesion.herramientas.push(h);
    sesion.pastillas.set(evento.id, { h, nodo });
    d.pastillas.append(nodo);
  } else if (evento.tipo === "herramienta_fin") {
    const par = sesion.pastillas.get(evento.id);
    if (par) {
      par.h.estado = evento.ok ? "ok" : "error";
      par.h.ms = evento.ms;
      par.h.error = evento.error;
      pintarPastilla(par.nodo, par.h);
    }
  } else if (evento.tipo === "texto") {
    sesion.texto += evento.delta;
    programarRender(sesion);
  }
  actualizarEscribiendo(sesion);
  d.alRenderizar?.();
}

async function crearTrabajo(cuerpo) {
  return (await api("POST", "/api/trabajos", cuerpo)).id;
}

// Abre el stream SSE del trabajo y resuelve con el evento final.
// La reconexión la controlamos nosotros (no la automática de EventSource, que se espacia
// sin límite): ante un corte se confirma que el servidor y el trabajo siguen ahí y se
// retoma desde el último evento recibido; si no responde, se rinde en pocos segundos.
function transmitir(id, alEvento) {
  return new Promise((resolver, rechazar) => {
    const ruta = `/api/trabajos/${encodeURIComponent(id)}`;
    let recibidos = 0;
    let fallos = 0;
    let cerrado = false;

    const terminar = (accion, valor) => {
      if (cerrado) return;
      cerrado = true;
      accion(valor);
    };

    async function recuperar() {
      while (!cerrado) {
        fallos += 1;
        if (fallos > REINTENTOS_DE_CONEXION) {
          terminar(rechazar, new Error("Se perdió la conexión con el servidor."));
          return;
        }
        await esperar(1000);
        try {
          await api("GET", ruta); // falla si el servidor cayó o el trabajo ya no existe
        } catch (_) {
          continue;
        }
        abrir();
        return;
      }
    }

    function abrir() {
      const fuente = new EventSource(`${ruta}/eventos?desde=${recibidos}`);
      fuente.onmessage = (mensaje) => {
        let evento;
        try {
          evento = JSON.parse(mensaje.data);
        } catch (_) {
          return;
        }
        fallos = 0;
        recibidos += 1;
        alEvento(evento);
        if (evento.tipo === "fin") {
          fuente.close();
          terminar(resolver, evento);
        }
      };
      fuente.onerror = () => {
        fuente.close(); // sin reintento automático del navegador
        if (!cerrado) recuperar();
      };
    }

    abrir();
  });
}

// ---------- Hilo de mensajes ----------

const hilo = $("hilo");
let pegadoAlFinal = true;

function bajarSiPegado(forzar = false) {
  if (forzar || pegadoAlFinal) hilo.scrollTop = hilo.scrollHeight;
}

hilo.addEventListener("scroll", () => {
  pegadoAlFinal = hilo.scrollHeight - hilo.scrollTop - hilo.clientHeight < 80;
  $("bajar").hidden = pegadoAlFinal;
});

$("bajar").addEventListener("click", () => {
  pegadoAlFinal = true;
  bajarSiPegado(true);
});

function actualizarBienvenida() {
  $("bienvenida").hidden = mensajes.length > 0;
}

function agregar(mensaje, nodo) {
  mensajes.push(mensaje);
  $("mensajes").append(nodo);
  actualizarBienvenida();
}

function crearMensajeUsuario(m) {
  const fila = el("div", { class: "mensaje usuario" });
  const burbuja = el("div", { class: "burbuja" });
  if (m.modo === VERIFICAR) burbuja.append(el("div", { class: "etiqueta-modo" }, "VERIFICAR"));
  burbuja.append(el("div", { class: "texto" }, m.texto));
  fila.append(burbuja);
  return fila;
}

function crearMensajeAgente(m) {
  const fila = el("div", { class: "mensaje agente" });
  const cuerpo = el("div", { class: "cuerpo" });
  const meta = el("div", { class: "meta" });
  const pastillas = el("div", { class: "actividad" });
  const contenido = el("div", { class: "contenido" });
  const escribiendo = el("div", { class: "escribiendo" }, "Pensando ");
  const puntos = el("span", { class: "puntos" });
  for (let i = 0; i < 3; i++) puntos.append(el("span"));
  escribiendo.append(puntos);
  const acciones = el("div", { class: "acciones-mensaje" });
  acciones.hidden = true;
  cuerpo.append(meta, pastillas, contenido, escribiendo, acciones);
  fila.append(el("div", { class: "avatar", "aria-hidden": "true" }, "A"), cuerpo);
  m.dom = { fila, meta, pastillas, contenido, escribiendo, acciones };
  return fila;
}

function crearMensajeSistema(texto) {
  const fila = el("div", { class: "mensaje sistema" });
  fila.append(el("span", {}, texto));
  return fila;
}

function agregarNotaDeSistema(texto) {
  agregar({ tipo: "sistema", texto }, crearMensajeSistema(texto));
  // El agente deja de ver lo anterior: no debe responder con datos que ya no existen.
  corte = mensajes.length;
}

function botonDeAccion(texto, alClick) {
  const boton = el("button", { type: "button" }, texto);
  boton.addEventListener("click", () => alClick(boton));
  return boton;
}

function descargar(texto) {
  const enlace = el("a", {
    href: URL.createObjectURL(new Blob([texto], { type: "text/markdown" })),
    download: "informe.md",
  });
  enlace.click();
  setTimeout(() => URL.revokeObjectURL(enlace.href), 1000);
}

function mostrarAcciones(m) {
  const { acciones } = m.dom;
  acciones.replaceChildren();
  if (m.estado === "listo") {
    acciones.append(
      botonDeAccion("Copiar", async (boton) => {
        try {
          await navigator.clipboard.writeText(m.respuesta);
          boton.textContent = "¡Copiado!";
        } catch (_) {
          boton.textContent = "No se pudo copiar";
        }
        setTimeout(() => (boton.textContent = "Copiar"), 1500);
      }),
    );
    if (m.modo === VERIFICAR) {
      acciones.append(botonDeAccion("Descargar .md", () => descargar(m.respuesta)));
    }
  } else {
    acciones.append(
      botonDeAccion("Reintentar", (boton) => {
        if (corriendo) return;
        boton.disabled = true;
        enviarMensaje(m.pregunta, m.modo);
      }),
    );
  }
  acciones.hidden = false;
}

// El agente ve, desde el último corte, los turnos de preguntas y el último informe.
function contextoParaElAgente() {
  const visibles = mensajes
    .slice(corte)
    .filter((m) => m.tipo === "agente" && m.estado === "listo");
  const turnos = visibles
    .filter((m) => m.modo === PREGUNTAR)
    .slice(-MAX_TURNOS)
    .map((m) => ({
      pregunta: recortar(m.pregunta, MAX_CHARS_TURNO),
      respuesta: recortar(m.respuesta, MAX_CHARS_TURNO),
    }));
  const informes = visibles.filter((m) => m.modo === VERIFICAR);
  const ultimo = informes.length ? informes[informes.length - 1].respuesta : "";
  return { conversacion: turnos, informe: recortar(ultimo, MAX_CHARS_INFORME) };
}

function fijarCorriendo(valor) {
  corriendo = valor;
  for (const id of ["enviar", "nueva", "temperature", "temperature-reset"]) $(id).disabled = valor;
  hilo.setAttribute("aria-busy", String(valor));
}

async function enviarMensaje(texto, modoDelMensaje) {
  const limpio = texto.trim();
  if (corriendo || !limpio) return;
  fijarCorriendo(true);

  const usuario = { tipo: "usuario", texto: limpio, modo: modoDelMensaje };
  const agente = {
    tipo: "agente",
    modo: modoDelMensaje,
    pregunta: limpio,
    estado: "en_curso",
    respuesta: "",
    herramientas: [],
    error: null,
  };
  agregar(usuario, crearMensajeUsuario(usuario));
  agregar(agente, crearMensajeAgente(agente));
  pegadoAlFinal = true;
  bajarSiPegado(true);

  const sesion = nuevaSesion({
    pastillas: agente.dom.pastillas,
    contenido: agente.dom.contenido,
    escribiendo: agente.dom.escribiendo,
    traza: (linea) => agente.dom.meta.append(el("div", {}, linea)),
    alRenderizar: () => bajarSiPegado(),
  });

  let fin;
  try {
    const cuerpo = { skill: modoDelMensaje, texto: limpio, temperature: temperatureActual() };
    // La conversación y el último informe viajan como contexto: el servidor no guarda estado.
    if (modoDelMensaje === PREGUNTAR) Object.assign(cuerpo, contextoParaElAgente());
    const id = await crearTrabajo(cuerpo);
    fin = await transmitir(id, (evento) => aplicarEvento(evento, sesion));
  } catch (err) {
    fin = { estado: "error", error: err.message };
  }

  agente.herramientas = sesion.herramientas;
  agente.dom.escribiendo.hidden = true;
  if (fin.estado === "listo") {
    agente.estado = "listo";
    agente.respuesta = fin.informe;
    agente.dom.contenido.replaceChildren(renderMarkdown(fin.informe));
  } else {
    agente.estado = "error";
    agente.error = fin.error || "La ejecución falló.";
    agente.dom.contenido.append(el("p", { class: "error" }, agente.error));
  }
  mostrarAcciones(agente);
  bajarSiPegado();
  fijarCorriendo(false);
  cargarHistorial();
  $("entrada").focus();
}

// ---------- Compositor ----------

const esSoloCuits = (texto) => {
  const tokens = texto.split(/[\s,;]+/).filter(Boolean);
  return tokens.length > 0 && tokens.every((t) => /^[\d-]{8,}$/.test(t));
};

function mostrarAviso(texto) {
  $("aviso").textContent = texto || "";
  $("aviso").hidden = !texto;
}

function crecer() {
  const campo = $("entrada");
  campo.style.height = "auto";
  campo.style.height = Math.min(campo.scrollHeight, 200) + "px";
}

function fijarModo(nuevo, { aMano = false } = {}) {
  modo = nuevo;
  if (aMano) modoElegidoAMano = true;
  for (const boton of $("modos").children) {
    boton.setAttribute("aria-pressed", String(boton.dataset.modo === modo));
  }
  $("entrada").placeholder = MODOS[modo].placeholder;
  $("grupo-archivo").hidden = modo !== VERIFICAR;
  if (aMano) mostrarAviso("");
}

function armarModos() {
  for (const [clave, cfg] of Object.entries(MODOS)) {
    const boton = el("button", { type: "button", "aria-pressed": "false", title: cfg.ayuda });
    boton.dataset.modo = clave;
    boton.append(document.createTextNode(cfg.titulo));
    if (cfg.etiqueta) boton.append(el("span", { class: "etiqueta-arca" }, cfg.etiqueta));
    boton.addEventListener("click", () => {
      fijarModo(clave, { aMano: true });
      $("entrada").focus();
    });
    $("modos").append(boton);
  }
}

function armarSugerencias() {
  for (const sugerencia of SUGERENCIAS) {
    const boton = el("button", { type: "button" }, sugerencia.texto);
    boton.addEventListener("click", () => {
      if (corriendo) return;
      fijarModo(sugerencia.modo, { aMano: true });
      if (sugerencia.enviar) enviarMensaje(sugerencia.texto, sugerencia.modo);
      else $("entrada").focus();
    });
    $("sugerencias").append(boton);
  }
}

function enviarDesdeElCampo() {
  if (corriendo) return;
  const texto = $("entrada").value;
  if (!texto.trim()) return;
  const modoDelMensaje = modo;
  $("entrada").value = "";
  crecer();
  mostrarAviso("");
  modoElegidoAMano = false;
  // Verificar es una acción puntual: lo siguiente que se escriba suele ser una pregunta,
  // y mandarla como lista de CUITs fallaría.
  if (modoDelMensaje === VERIFICAR) fijarModo(PREGUNTAR);
  enviarMensaje(texto, modoDelMensaje);
}

$("formulario").addEventListener("submit", (evento) => {
  evento.preventDefault();
  enviarDesdeElCampo();
});

$("entrada").addEventListener("keydown", (evento) => {
  // Enter envía; Shift+Enter agrega una línea. No se interfiere con la composición (IME).
  if (evento.key === "Enter" && !evento.shiftKey && !evento.isComposing) {
    evento.preventDefault();
    enviarDesdeElCampo();
  }
});

$("entrada").addEventListener("input", () => {
  crecer();
  // Si lo pegado son solo CUITs, lo más probable es que se quiera verificar: se avisa antes de enviar.
  if (modo === PREGUNTAR && !modoElegidoAMano && esSoloCuits($("entrada").value)) {
    fijarModo(VERIFICAR);
    mostrarAviso(
      "Detecté CUITs: se van a verificar contra ARCA. Si querés preguntar, cambiá a «Preguntar».",
    );
  }
});

$("archivo").addEventListener("change", async (evento) => {
  const archivo = evento.target.files[0];
  evento.target.value = "";
  if (!archivo) return;
  if (archivo.size > MAX_BYTES_ARCHIVO) {
    mostrarAviso("El archivo supera los 64 KB.");
    return;
  }
  $("entrada").value = await archivo.text();
  fijarModo(VERIFICAR, { aMano: true });
  crecer();
  $("entrada").focus();
});

$("nueva").addEventListener("click", () => {
  if (corriendo) return;
  mensajes = [];
  corte = 0;
  $("mensajes").replaceChildren();
  mostrarAviso("");
  actualizarBienvenida();
  $("entrada").focus();
});

// ---------- Ventanas (ajustes, historial, confirmación) ----------

function confirmar(titulo, texto, textoBoton) {
  return new Promise((resolver) => {
    const dialogo = $("confirmacion");
    $("confirmacion-titulo").textContent = titulo;
    $("confirmacion-texto").textContent = texto;
    $("confirmacion-aceptar").textContent = textoBoton;
    dialogo.returnValue = "";
    dialogo.addEventListener("close", () => resolver(dialogo.returnValue === "si"), {
      once: true,
    });
    $("confirmacion-aceptar").onclick = () => dialogo.close("si");
    $("confirmacion-cancelar").onclick = () => dialogo.close("no");
    dialogo.showModal();
  });
}

function chip(nombre, valor) {
  const nodo = el("span", { class: "chip" });
  nodo.append(document.createTextNode(nombre + ": "), el("strong", {}, String(valor)));
  return nodo;
}

async function cargarConfig() {
  try {
    const cfg = await api("GET", "/api/config");
    $("config").append(
      chip("Modelo", cfg.modelo),
      chip("máx. tokens", cfg.max_output_tokens),
      chip("máx. iteraciones", cfg.max_tool_iterations),
      chip("skills", cfg.skills.map((s) => s.nombre).join(", ")),
    );
    iniciarTemperature(cfg.temperature);
  } catch (err) {
    mostrarAviso("No se pudo leer la configuración del agente: " + err.message);
  }
}

function mostrarErrorDelHistorial(texto) {
  $("historial-mensaje").textContent = texto || "";
  $("historial-mensaje").hidden = !texto;
}

function abrirDetalle(consulta) {
  $("detalle-contenido").textContent = JSON.stringify(consulta.resultado ?? consulta, null, 2);
  $("detalle").showModal();
}

function preguntarPor(consulta) {
  $("historial-dialogo").close();
  fijarModo(PREGUNTAR, { aMano: true });
  $("entrada").value = `Contame sobre ${formatearCuit(consulta.cuit)}`;
  crecer();
  $("entrada").focus();
}

async function borrarConsulta(consulta) {
  const nombre = consulta.razon_social ? ` (${consulta.razon_social})` : "";
  const cuit = formatearCuit(consulta.cuit);
  const acepto = await confirmar(
    "¿Borrar este CUIT del historial?",
    `${cuit}${nombre}. Se eliminan todas sus consultas guardadas. No se puede deshacer.`,
    "Borrar",
  );
  if (!acepto) return;
  mostrarErrorDelHistorial("");
  try {
    await api("DELETE", `/api/historial/${encodeURIComponent(consulta.cuit)}`);
  } catch (err) {
    mostrarErrorDelHistorial(err.message);
    return;
  }
  agregarNotaDeSistema(`Se borró ${cuit} del historial. El agente ya no ve lo anterior.`);
  await cargarHistorial();
}

async function limpiarHistorial() {
  const acepto = await confirmar(
    "¿Borrar todo el historial?",
    "Se eliminan todas las consultas guardadas y se compacta la base de datos. No se puede deshacer.",
    "Borrar todo",
  );
  if (!acepto) return;
  mostrarErrorDelHistorial("");
  try {
    const { eliminadas } = await api("DELETE", "/api/historial", { confirmar: true });
    agregarNotaDeSistema(
      `Historial borrado (${eliminadas} consultas). El agente ya no ve lo anterior.`,
    );
  } catch (err) {
    mostrarErrorDelHistorial(err.message);
    return;
  }
  await cargarHistorial();
}

function filaVacia(texto) {
  const fila = el("tr");
  fila.append(el("td", { colspan: "5", class: "vacio" }, texto));
  return fila;
}

function filaDeConsulta(consulta) {
  const fila = el("tr");
  const fecha = new Date(consulta.fecha);
  for (const valor of [
    formatearCuit(consulta.cuit),
    consulta.razon_social ?? "",
    consulta.estado ?? "",
    Number.isNaN(fecha.getTime()) ? "" : fecha.toLocaleString("es-AR"),
  ]) {
    fila.append(el("td", {}, valor));
  }
  const acciones = el("td", { class: "acciones" });
  for (const [texto, alClick] of [
    ["Ver", () => abrirDetalle(consulta)],
    ["Preguntar", () => preguntarPor(consulta)],
    ["Borrar", () => borrarConsulta(consulta)],
  ]) {
    const boton = el("button", { type: "button", class: "chico" }, texto);
    boton.addEventListener("click", alClick);
    acciones.append(boton);
  }
  fila.append(acciones);
  return fila;
}

async function cargarHistorial() {
  let total = 0;
  try {
    const datos = await api("GET", "/api/historial");
    consultas = datos.consultas || [];
    total = datos.total ?? consultas.length;
  } catch (err) {
    $("historial").replaceChildren(filaVacia("No se pudo cargar el historial: " + err.message));
    return;
  }
  $("contador-historial").textContent = String(total);
  $("contador-historial").hidden = total === 0;
  $("historial-limpiar").disabled = total === 0;
  $("historial-resumen").textContent = total
    ? `Mostrando ${consultas.length} de ${total} consultas guardadas, las más recientes primero.`
    : "";
  $("historial").replaceChildren(
    ...(consultas.length ? consultas.map(filaDeConsulta) : [filaVacia("Sin consultas todavía...")]),
  );
}

$("abrir-historial").addEventListener("click", async () => {
  mostrarErrorDelHistorial("");
  await cargarHistorial();
  $("historial-dialogo").showModal();
});
$("historial-limpiar").addEventListener("click", limpiarHistorial);
$("historial-cerrar").addEventListener("click", () => $("historial-dialogo").close());
$("detalle-cerrar").addEventListener("click", () => $("detalle").close());
$("abrir-ayuda").addEventListener("click", () => $("ayuda").showModal());
$("ver-funciones").addEventListener("click", () => $("ayuda").showModal());
$("ayuda-cerrar").addEventListener("click", () => $("ayuda").close());
$("abrir-ajustes").addEventListener("click", () => $("ajustes").showModal());
$("ajustes-cerrar").addEventListener("click", () => $("ajustes").close());

$("temperature").addEventListener("input", () => {
  guardarTemperature(temperatureActual());
  mostrarTemperature();
});
$("temperature-reset").addEventListener("click", () => {
  $("temperature").value = String(temperatureDelAgente);
  guardarTemperature(temperatureDelAgente);
  mostrarTemperature();
});

// ---------- Inicio ----------

armarModos();
armarSugerencias();
fijarModo(PREGUNTAR);
mostrarTemperature();
actualizarBienvenida();
cargarConfig();
cargarHistorial();
$("entrada").focus();
