const body = document.body;
const clinicSlug = body.dataset.clinicSlug;
const storageKey = `senha_facil_device_${clinicSlug}`;
let memoryDeviceToken = null;
let deviceToken = readStoredToken();
let ticket = null;
let eventSource = null;
let wakeLock = null;
let audioContext = null;
let lastAlertedTicketId = null;

const categoryPanel = document.querySelector("#categoryPanel");
const ticketPanel = document.querySelector("#ticketPanel");
const ticketCode = document.querySelector("#ticketCode");
const ticketStatus = document.querySelector("#ticketStatus");
const queuePosition = document.querySelector("#queuePosition");
const roomLabel = document.querySelector("#roomLabel");
const connectionStatus = document.querySelector("#connectionStatus");

function readStoredToken() {
  try {
    return localStorage.getItem(storageKey);
  } catch {
    return memoryDeviceToken;
  }
}

function storeToken(token) {
  memoryDeviceToken = token;
  try {
    localStorage.setItem(storageKey, token);
  } catch {
    // The in-memory token keeps the current session working when storage is blocked.
  }
}

function ensureToken() {
  if (!deviceToken) {
    deviceToken = globalThis.crypto?.randomUUID?.() || `device-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    storeToken(deviceToken);
  }
}

async function requestWakeLock() {
  if ("wakeLock" in navigator) {
    try {
      wakeLock = await navigator.wakeLock.request("screen");
    } catch {
      wakeLock = null;
    }
  }
}

function unlockCallAudio() {
  const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
  if (!AudioContextClass) return;
  if (!audioContext) audioContext = new AudioContextClass();
  audioContext.resume?.();
}

function playCallSound() {
  unlockCallAudio();
  if (!audioContext) return;

  const startAt = audioContext.currentTime + 0.05;
  [0, 0.32, 0.64].forEach((offset) => {
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(880, startAt + offset);
    gain.gain.setValueAtTime(0.0001, startAt + offset);
    gain.gain.exponentialRampToValueAtTime(0.22, startAt + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, startAt + offset + 0.18);

    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start(startAt + offset);
    oscillator.stop(startAt + offset + 0.2);
  });
}

function flashCalledTicket() {
  ticketCode.classList.remove("flash-called");
  void ticketCode.offsetWidth;
  ticketCode.classList.add("flash-called");
}

function alertCalledTicket() {
  if (ticket.status !== "chamado" || lastAlertedTicketId === ticket.id) return;
  lastAlertedTicketId = ticket.id;
  flashCalledTicket();
  playCallSound();
  navigator.vibrate?.([250, 100, 250]);
}

function renderTicket(nextTicket) {
  ticket = nextTicket;
  categoryPanel.classList.add("hidden");
  ticketPanel.classList.remove("hidden");
  ticketCode.textContent = ticket.ticket_code;
  ticketStatus.textContent = ticket.status === "chamado" ? "Sua vez!" : "Aguardando";
  queuePosition.textContent = ticket.status === "chamado"
    ? "DIRIJA-SE AO LOCAL"
    : ticket.position > 0
    ? `Existem ${ticket.position} pessoa(s) na sua frente.`
    : "Voce e o proximo da fila.";
  roomLabel.textContent = ticket.room ? `Dirija-se a ${ticket.room}.` : "";
  ticketPanel.classList.toggle("called", ticket.status === "chamado");
  alertCalledTicket();
}

function connectTicketEvents() {
  if (!ticket || eventSource) return;
  if (typeof EventSource === "undefined") {
    connectionStatus.textContent = "Sem tempo real";
    return;
  }
  eventSource = new EventSource(`/api/eventos/ticket/${ticket.id}`);
  eventSource.addEventListener("connected", () => {
    connectionStatus.textContent = "Online";
  });
  eventSource.addEventListener("ticket_called", (event) => {
    renderTicket(JSON.parse(event.data).ticket);
  });
  eventSource.addEventListener("ticket_removed", () => {
    ticket = null;
    eventSource.close();
    eventSource = null;
    ticketPanel.classList.add("hidden");
    ticketPanel.classList.remove("called");
    categoryPanel.classList.remove("hidden");
    connectionStatus.textContent = "Senha removida";
  });
  eventSource.onerror = () => {
    connectionStatus.textContent = "Reconectando";
  };
}

async function recoverTicket() {
  ensureToken();
  try {
    const response = await fetch(`/api/senhas/recuperar?clinic_slug=${clinicSlug}&device_token=${deviceToken}`);
    const data = await response.json();
    if (data.ticket) {
      renderTicket(data.ticket);
      connectTicketEvents();
      requestWakeLock();
    }
  } catch {
    connectionStatus.textContent = "Offline";
  }
}

async function generateTicket(category) {
  ensureToken();
  unlockCallAudio();
  try {
    const response = await fetch("/api/senhas/gerar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clinic_slug: clinicSlug, category, device_token: deviceToken }),
    });
    const data = await response.json();
    if (!response.ok) {
      alert(data.error || "Nao foi possivel emitir sua senha.");
      return;
    }
    storeToken(data.device_token);
    renderTicket(data.ticket);
    connectTicketEvents();
    requestWakeLock();
  } catch {
    alert("Nao foi possivel conectar ao servidor. Verifique se o Flask esta rodando.");
  }
}

document.querySelectorAll(".category-button").forEach((button) => {
  button.addEventListener("click", () => generateTicket(button.dataset.category));
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && ticket && !wakeLock) requestWakeLock();
});

recoverTicket();
