const apiBaseInput = document.getElementById('apiBase') as HTMLInputElement
const apiKeyInput = document.getElementById('apiKey') as HTMLInputElement
const reportTextInput = document.getElementById('reportText') as HTMLTextAreaElement
const reportTypeInput = document.getElementById('reportType') as HTMLSelectElement
const locationInput = document.getElementById('location') as HTMLInputElement
const output = document.getElementById('output') as HTMLPreElement

const btnAnalyze = document.getElementById('btnAnalyze') as HTMLButtonElement
const btnSearch = document.getElementById('btnSearch') as HTMLButtonElement
const btnAlerts = document.getElementById('btnAlerts') as HTMLButtonElement
const btnWsUpdates = document.getElementById('btnWsUpdates') as HTMLButtonElement
const btnWsAlerts = document.getElementById('btnWsAlerts') as HTMLButtonElement
const btnWsClose = document.getElementById('btnWsClose') as HTMLButtonElement

let socket: WebSocket | null = null

function log(data: unknown): void {
  const pretty = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  output.textContent = `${pretty}\n\n${output.textContent}`
}

function headers(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-API-Key': apiKeyInput.value.trim(),
  }
}

async function callApi(path: string, init?: RequestInit): Promise<void> {
  const res = await fetch(`${apiBaseInput.value.trim()}${path}`, {
    ...init,
    headers: {
      ...headers(),
      ...(init?.headers ?? {}),
    },
  })

  let body: unknown
  try {
    body = await res.json()
  } catch {
    body = await res.text()
  }

  log({
    path,
    status: res.status,
    requestId: res.headers.get('X-Request-ID'),
    rateLimit: {
      limit: res.headers.get('X-RateLimit-Limit'),
      remaining: res.headers.get('X-RateLimit-Remaining'),
      reset: res.headers.get('X-RateLimit-Reset'),
      role: res.headers.get('X-RateLimit-Role'),
    },
    body,
  })
}

btnAnalyze.addEventListener('click', async () => {
  await callApi('/reports/analyze', {
    method: 'POST',
    body: JSON.stringify({
      report: reportTextInput.value,
      report_type: reportTypeInput.value,
      location: locationInput.value,
    }),
  })
})

btnSearch.addEventListener('click', async () => {
  const query = encodeURIComponent(reportTextInput.value.split(' ')[0] || 'attack')
  await callApi(`/reports/search?q=${query}&location=${encodeURIComponent(locationInput.value)}`)
})

btnAlerts.addEventListener('click', async () => {
  await callApi('/alerts')
})

function connectWs(path: '/ws/updates' | '/ws/alerts'): void {
  if (socket) socket.close()

  const requestId = crypto.randomUUID()
  const base = apiBaseInput.value.trim().replace('http://', 'ws://').replace('https://', 'wss://')
  const url = `${base}${path}?api_key=${encodeURIComponent(apiKeyInput.value.trim())}&request_id=${encodeURIComponent(requestId)}`

  socket = new WebSocket(url)

  socket.onopen = () => {
    log({ ws: 'open', path, requestId })
    if (path === '/ws/updates') {
      socket?.send(reportTextInput.value)
    }
  }

  socket.onmessage = (event) => {
    try {
      log({ ws: 'message', payload: JSON.parse(event.data) })
    } catch {
      log({ ws: 'message', payload: event.data })
    }
  }

  socket.onerror = () => log({ ws: 'error', path })
  socket.onclose = (event) => log({ ws: 'closed', code: event.code, reason: event.reason })
}

btnWsUpdates.addEventListener('click', () => connectWs('/ws/updates'))
btnWsAlerts.addEventListener('click', () => connectWs('/ws/alerts'))
btnWsClose.addEventListener('click', () => {
  socket?.close()
  socket = null
})

log('Janam frontend connected. Configure API URL/key and start testing.')
