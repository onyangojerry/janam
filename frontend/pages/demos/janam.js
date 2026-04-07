const apiBaseInput = document.getElementById('apiBase')
const apiKeyInput = document.getElementById('apiKey')
const requestIdInput = document.getElementById('requestId')
const defaultLimitInput = document.getElementById('defaultLimit')

const reportTextInput = document.getElementById('reportText')
const reportTypeInput = document.getElementById('reportType')
const locationInput = document.getElementById('location')
const sourceInput = document.getElementById('source')

const searchQInput = document.getElementById('searchQ')
const searchSeverityInput = document.getElementById('searchSeverity')
const searchTypeInput = document.getElementById('searchType')
const reportIdInput = document.getElementById('reportId')

const wsPayloadInput = document.getElementById('wsPayload')

const countHighEl = document.getElementById('countHigh')
const countMediumEl = document.getElementById('countMedium')
const countLowEl = document.getElementById('countLow')
const dangerBannerEl = document.getElementById('dangerBanner')
const liveStatusEl = document.getElementById('liveStatus')

const output = document.getElementById('output')

const btnHealth = document.getElementById('btnHealth')
const btnFormats = document.getElementById('btnFormats')
const btnListReports = document.getElementById('btnListReports')
const btnGetAlerts = document.getElementById('btnGetAlerts')

const btnAnalyze = document.getElementById('btnAnalyze')
const btnAnalyzeText = document.getElementById('btnAnalyzeText')
const btnAnalyzeAudio = document.getElementById('btnAnalyzeAudio')
const btnAnalyzeVideo = document.getElementById('btnAnalyzeVideo')

const btnSearch = document.getElementById('btnSearch')
const btnGetReport = document.getElementById('btnGetReport')
const btnClearOutput = document.getElementById('btnClearOutput')
const btnRefreshIntel = document.getElementById('btnRefreshIntel')

const btnWsUpdates = document.getElementById('btnWsUpdates')
const btnWsAlerts = document.getElementById('btnWsAlerts')
const btnWsInit = document.getElementById('btnWsInit')
const btnWsSendPayload = document.getElementById('btnWsSendPayload')
const btnWsClose = document.getElementById('btnWsClose')

let socket = null
const alertEvents = []

function log(data) {
  const time = new Date().toISOString()
  const pretty = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  output.textContent = `[${time}] ${pretty}\n\n${output.textContent}`
}

function getRequestId() {
  return requestIdInput.value.trim() || crypto.randomUUID()
}

function getLimit() {
  const parsed = Number.parseInt(defaultLimitInput.value, 10)
  if (Number.isNaN(parsed)) return 25
  return Math.max(1, Math.min(parsed, 200))
}

function headers() {
  return {
    'Content-Type': 'application/json',
    'X-API-Key': apiKeyInput.value.trim(),
  }
}

async function callApi(path, init) {
  const requestId = getRequestId()
  const res = await fetch(`${apiBaseInput.value.trim()}${path}`, {
    ...init,
    headers: {
      ...headers(),
      'X-Request-ID': requestId,
      ...(init?.headers ?? {}),
    },
  })

  let body
  try {
    body = await res.json()
  } catch {
    body = await res.text()
  }

  log({
    path,
    status: res.status,
    sentRequestId: requestId,
    requestId: res.headers.get('X-Request-ID'),
    rateLimit: {
      limit: res.headers.get('X-RateLimit-Limit'),
      remaining: res.headers.get('X-RateLimit-Remaining'),
      reset: res.headers.get('X-RateLimit-Reset'),
      role: res.headers.get('X-RateLimit-Role'),
    },
    body,
  })

  return body
}

function updateDangerBoard() {
  const counts = { high: 0, medium: 0, low: 0 }
  for (const event of alertEvents) {
    const sev = `${event.severity || ''}`.toLowerCase()
    if (sev in counts) counts[sev] += 1
  }

  countHighEl.textContent = `${counts.high}`
  countMediumEl.textContent = `${counts.medium}`
  countLowEl.textContent = `${counts.low}`

  if (counts.high > 0) {
    dangerBannerEl.textContent = `Critical danger trend detected: ${counts.high} high-severity incidents require immediate response.`
    return
  }

  if (counts.medium > 0) {
    dangerBannerEl.textContent = `Elevated risk: ${counts.medium} medium-severity incidents under active monitoring.`
    return
  }

  if (counts.low > 0) {
    dangerBannerEl.textContent = `Low-risk activity observed: ${counts.low} incidents logged for situational awareness.`
    return
  }

  dangerBannerEl.textContent = 'No active danger trend yet.'
}

function captureAlert(event) {
  if (!event || typeof event !== 'object') return
  if (!event.severity || !event.event_id) return
  if (alertEvents.some((entry) => entry.event_id === event.event_id)) return
  alertEvents.unshift(event)
  if (alertEvents.length > 200) alertEvents.pop()
  updateDangerBoard()
}

async function refreshIntel() {
  const limit = getLimit()
  const body = await callApi(`/alerts?limit=${limit}`)
  if (Array.isArray(body)) {
    for (const event of body) captureAlert(event)
  }
}

async function analyzeViaPath(path, reportType) {
  await callApi(path, {
    method: 'POST',
    body: JSON.stringify({
      report: reportTextInput.value,
      report_type: reportType,
      source: sourceInput.value,
      location: locationInput.value,
    }),
  })
}

btnHealth.addEventListener('click', async () => {
  await callApi('/health', { method: 'GET' })
})

btnFormats.addEventListener('click', async () => {
  await callApi('/formats', { method: 'GET' })
})

btnListReports.addEventListener('click', async () => {
  await callApi(`/reports?limit=${getLimit()}`, { method: 'GET' })
})

btnGetAlerts.addEventListener('click', async () => {
  await refreshIntel()
})

btnAnalyze.addEventListener('click', async () => {
  await analyzeViaPath('/reports/analyze', reportTypeInput.value)
})

btnAnalyzeText.addEventListener('click', async () => {
  await analyzeViaPath('/reports/text', 'text')
})

btnAnalyzeAudio.addEventListener('click', async () => {
  await analyzeViaPath('/reports/audio', 'audio')
})

btnAnalyzeVideo.addEventListener('click', async () => {
  await analyzeViaPath('/reports/video', 'video')
})

btnSearch.addEventListener('click', async () => {
  const params = new URLSearchParams()
  const q = searchQInput.value.trim() || reportTextInput.value.split(' ')[0] || 'attack'
  params.set('q', q)
  params.set('limit', `${getLimit()}`)

  if (searchTypeInput.value) params.set('report_type', searchTypeInput.value)
  if (searchSeverityInput.value) params.set('severity', searchSeverityInput.value)
  if (sourceInput.value.trim()) params.set('source', sourceInput.value.trim())
  if (locationInput.value.trim()) params.set('location', locationInput.value.trim())

  await callApi(`/reports/search?${params.toString()}`, { method: 'GET' })
})

btnGetReport.addEventListener('click', async () => {
  const id = Number.parseInt(reportIdInput.value, 10)
  if (Number.isNaN(id) || id < 1) {
    log('Provide a valid report ID before fetching.')
    return
  }
  await callApi(`/reports/${id}`, { method: 'GET' })
})

btnClearOutput.addEventListener('click', () => {
  output.textContent = ''
})

btnRefreshIntel.addEventListener('click', async () => {
  await callApi(`/reports?limit=${getLimit()}`, { method: 'GET' })
  await refreshIntel()
})

function connectWs(path) {
  if (socket) socket.close()

  const requestId = getRequestId()
  const base = apiBaseInput.value.trim().replace('http://', 'ws://').replace('https://', 'wss://')
  const url = `${base}${path}?api_key=${encodeURIComponent(apiKeyInput.value.trim())}&request_id=${encodeURIComponent(requestId)}`

  socket = new WebSocket(url)
  liveStatusEl.textContent = `live: connecting ${path}`

  socket.onopen = () => {
    log({ ws: 'open', path, requestId })
    liveStatusEl.textContent = `live: connected ${path}`
    if (path === '/ws/updates') {
      socket?.send(reportTextInput.value)
    }
  }

  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      log({ ws: 'message', payload })
      if (payload?.severity) captureAlert(payload)
    } catch {
      log({ ws: 'message', payload: event.data })
    }
  }

  socket.onerror = () => log({ ws: 'error', path })
  socket.onclose = (event) => {
    liveStatusEl.textContent = 'live: idle'
    log({ ws: 'closed', code: event.code, reason: event.reason })
  }
}

btnWsUpdates.addEventListener('click', () => connectWs('/ws/updates'))
btnWsAlerts.addEventListener('click', () => connectWs('/ws/alerts'))
btnWsInit.addEventListener('click', () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    log('Connect a websocket first, then send init handshake.')
    return
  }
  const requestId = getRequestId()
  socket.send(JSON.stringify({ event: 'init', request_id: requestId }))
  log({ ws: 'sent_init', requestId })
})

btnWsSendPayload.addEventListener('click', () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    log('Connect to /ws/updates before sending payload.')
    return
  }
  socket.send(wsPayloadInput.value)
  log({ ws: 'sent_payload', text: wsPayloadInput.value })
})

btnWsClose.addEventListener('click', () => {
  socket?.close()
  socket = null
  liveStatusEl.textContent = 'live: idle'
})

log('Janam operations console ready. Start with Health/Formats, then ingest incident reports and monitor live alerts.')
