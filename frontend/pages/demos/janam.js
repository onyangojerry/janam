const apiBaseInput = document.getElementById('apiBase')
const apiKeyInput = document.getElementById('apiKey')
const requestIdInput = document.getElementById('requestId')
const defaultLimitInput = document.getElementById('defaultLimit')

const reportTextInput = document.getElementById('reportText')
const reportTypeInput = document.getElementById('reportType')
const locationInput = document.getElementById('location')
const latitudeInput = document.getElementById('latitude')
const longitudeInput = document.getElementById('longitude')
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
const caseMapEl = document.getElementById('caseMap')
const filterHighInput = document.getElementById('filterHigh')
const filterMediumInput = document.getElementById('filterMedium')
const filterLowInput = document.getElementById('filterLow')
const btnMapFit = document.getElementById('btnMapFit')
const btnMapCenterHigh = document.getElementById('btnMapCenterHigh')
const enableGeofenceInput = document.getElementById('enableGeofence')
const enableAudibleAlarmInput = document.getElementById('enableAudibleAlarm')
const geofenceRadiusMetersInput = document.getElementById('geofenceRadiusMeters')
const geofenceCooldownHighSecondsInput = document.getElementById('geofenceCooldownHighSeconds')
const geofenceCooldownMediumSecondsInput = document.getElementById('geofenceCooldownMediumSeconds')
const geofenceCooldownLowSecondsInput = document.getElementById('geofenceCooldownLowSeconds')
const btnGeofenceCheck = document.getElementById('btnGeofenceCheck')
const geofenceStatusEl = document.getElementById('geofenceStatus')

const btnHealth = document.getElementById('btnHealth')
const btnFormats = document.getElementById('btnFormats')
const btnListReports = document.getElementById('btnListReports')
const btnGetAlerts = document.getElementById('btnGetAlerts')
const btnLocationAnalytics = document.getElementById('btnLocationAnalytics')

const btnAnalyze = document.getElementById('btnAnalyze')
const btnAnalyzeText = document.getElementById('btnAnalyzeText')
const btnAnalyzeAudio = document.getElementById('btnAnalyzeAudio')
const btnAnalyzeImage = document.getElementById('btnAnalyzeImage')
const btnAnalyzeVideo = document.getElementById('btnAnalyzeVideo')
const btnUseGps = document.getElementById('btnUseGps')

const btnSearch = document.getElementById('btnSearch')
const btnGetReport = document.getElementById('btnGetReport')
const btnClearOutput = document.getElementById('btnClearOutput')
const btnRefreshIntel = document.getElementById('btnRefreshIntel')

const btnWsUpdates = document.getElementById('btnWsUpdates')
const btnWsAlerts = document.getElementById('btnWsAlerts')
const btnWsCases = document.getElementById('btnWsCases')
const btnWsInit = document.getElementById('btnWsInit')
const btnWsSendPayload = document.getElementById('btnWsSendPayload')
const btnWsClose = document.getElementById('btnWsClose')

let socket = null
const alertEvents = []
const caseMarkers = new Map()
const caseMeta = new Map()

let caseMap = null
let userMarker = null
let geofenceCircle = null
let userLocation = null
const geofenceLastTriggeredAt = new Map()
let alarmAudioContext = null
const leafletGlobal = typeof window !== 'undefined' ? window.L : null

function initCaseMap() {
  if (!leafletGlobal || !caseMapEl || caseMap) return
  caseMap = leafletGlobal.map(caseMapEl).setView([6.5244, 3.3792], 11)
  leafletGlobal
    .tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    })
    .addTo(caseMap)
}

function isSeverityVisible(severity) {
  const normalized = `${severity || ''}`.toLowerCase()
  if (normalized === 'high') return Boolean(filterHighInput?.checked)
  if (normalized === 'medium') return Boolean(filterMediumInput?.checked)
  return Boolean(filterLowInput?.checked)
}

function applyMarkerFilters() {
  if (!caseMap) return
  for (const [reportId, marker] of caseMarkers.entries()) {
    const metadata = caseMeta.get(reportId)
    const visible = isSeverityVisible(metadata?.severity)
    const hasLayer = caseMap.hasLayer(marker)
    if (visible && !hasLayer) marker.addTo(caseMap)
    if (!visible && hasLayer) caseMap.removeLayer(marker)
  }
}

function fitVisibleCases() {
  if (!caseMap) return
  const visiblePoints = []
  for (const [reportId, marker] of caseMarkers.entries()) {
    if (!caseMap.hasLayer(marker)) continue
    const metadata = caseMeta.get(reportId)
    if (!metadata) continue
    visiblePoints.push([metadata.latitude, metadata.longitude])
  }

  if (visiblePoints.length === 0) {
    log('No visible map markers for current severity filters.')
    return
  }

  caseMap.fitBounds(visiblePoints, { padding: [24, 24], maxZoom: 15 })
}

function getGeofenceRadiusMeters() {
  const parsed = Number.parseInt(geofenceRadiusMetersInput?.value || '1000', 10)
  if (Number.isNaN(parsed)) return 1000
  return Math.max(50, parsed)
}

function severityPriority(severity) {
  const normalized = `${severity || ''}`.toLowerCase()
  if (normalized === 'high') return 3
  if (normalized === 'medium') return 2
  return 1
}

function getGeofenceCooldownMsForSeverity(severity) {
  const normalized = `${severity || ''}`.toLowerCase()
  const source = normalized === 'high'
    ? geofenceCooldownHighSecondsInput
    : normalized === 'medium'
      ? geofenceCooldownMediumSecondsInput
      : geofenceCooldownLowSecondsInput
  const fallbackSeconds = normalized === 'high' ? 30 : normalized === 'medium' ? 90 : 180
  const parsed = Number.parseInt(source?.value || `${fallbackSeconds}`, 10)
  if (Number.isNaN(parsed)) return fallbackSeconds * 1000
  return Math.max(5, parsed) * 1000
}

function setGeofenceStatus(text) {
  if (geofenceStatusEl) {
    geofenceStatusEl.textContent = `Geofence: ${text}`
  }
}

function haversineDistanceMeters(lat1, lon1, lat2, lon2) {
  const earthRadiusMeters = 6371000
  const toRadians = (value) => (value * Math.PI) / 180
  const deltaLat = toRadians(lat2 - lat1)
  const deltaLon = toRadians(lon2 - lon1)
  const latitude1 = toRadians(lat1)
  const latitude2 = toRadians(lat2)

  const a =
    Math.sin(deltaLat / 2) * Math.sin(deltaLat / 2) +
    Math.sin(deltaLon / 2) * Math.sin(deltaLon / 2) * Math.cos(latitude1) * Math.cos(latitude2)
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  return earthRadiusMeters * c
}

function upsertUserLocationOnMap(latitude, longitude) {
  initCaseMap()
  if (!caseMap || !leafletGlobal) return

  if (userMarker) {
    userMarker.setLatLng([latitude, longitude])
  } else {
    const icon = leafletGlobal.divIcon({
      className: 'janam-user-marker',
      html: '<div style="width:12px;height:12px;border-radius:999px;background:#2f7df6;border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,0.25);"></div>',
      iconSize: [12, 12],
      iconAnchor: [6, 6],
    })
    userMarker = leafletGlobal.marker([latitude, longitude], { icon }).addTo(caseMap)
    userMarker.bindPopup('Your current location')
  }

  const radius = getGeofenceRadiusMeters()
  if (geofenceCircle) {
    geofenceCircle.setLatLng([latitude, longitude])
    geofenceCircle.setRadius(radius)
  } else {
    geofenceCircle = leafletGlobal.circle([latitude, longitude], {
      radius,
      color: '#2f7df6',
      fillColor: '#2f7df6',
      fillOpacity: 0.12,
      weight: 1,
    }).addTo(caseMap)
  }
}

function notifyGeofence(message) {
  if (typeof Notification === 'undefined') {
    return
  }
  if (Notification.permission === 'granted') {
    new Notification('Janam Safety Alert', { body: message })
  }
}

function getAlarmAudioContext() {
  if (typeof window === 'undefined') {
    return null
  }

  if (!alarmAudioContext) {
    const Context = window.AudioContext || window.webkitAudioContext
    if (!Context) {
      return null
    }
    alarmAudioContext = new Context()
  }

  return alarmAudioContext
}

function playAudibleAlarm() {
  if (!enableAudibleAlarmInput?.checked) {
    return
  }

  const context = getAlarmAudioContext()
  if (!context) {
    log({ geofence: 'audio_unavailable', detail: 'Web Audio API is not supported in this browser.' })
    return
  }

  if (context.state === 'suspended') {
    void context.resume()
  }

  const now = context.currentTime
  for (let index = 0; index < 3; index += 1) {
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.type = 'square'
    oscillator.frequency.value = 880
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(0.18, now + (index * 0.3) + 0.01)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + (index * 0.3) + 0.22)
    oscillator.connect(gain)
    gain.connect(context.destination)
    oscillator.start(now + (index * 0.3))
    oscillator.stop(now + (index * 0.3) + 0.24)
  }
}

function evaluateGeofence() {
  if (!enableGeofenceInput?.checked) {
    setGeofenceStatus('disabled')
    return
  }

  if (!userLocation) {
    setGeofenceStatus('enabled, waiting for GPS location')
    return
  }

  const radius = getGeofenceRadiusMeters()
  let nearestAny = null
  let nearestInside = null

  for (const [reportId, metadata] of caseMeta.entries()) {
    const severity = `${metadata.severity || ''}`.toLowerCase()
    const distance = haversineDistanceMeters(userLocation.latitude, userLocation.longitude, metadata.latitude, metadata.longitude)
    const candidate = { reportId, metadata, distance, severity }

    if (!nearestAny || distance < nearestAny.distance) {
      nearestAny = candidate
    }

    if (distance > radius) {
      continue
    }

    if (
      !nearestInside ||
      severityPriority(candidate.severity) > severityPriority(nearestInside.severity) ||
      (
        severityPriority(candidate.severity) === severityPriority(nearestInside.severity) &&
        candidate.distance < nearestInside.distance
      )
    ) {
      nearestInside = candidate
    }
  }

  if (!nearestAny) {
    setGeofenceStatus('enabled, no cases available')
    return
  }

  if (nearestInside) {
    const meters = Math.round(nearestInside.distance)
    const severity = nearestInside.severity || 'low'
    const message = `You are ${meters}m from ${severity}-risk case #${nearestInside.reportId}.`
    const cooldownMs = getGeofenceCooldownMsForSeverity(severity)
    const lastTriggeredAt = geofenceLastTriggeredAt.get(nearestInside.reportId) || 0
    const now = Date.now()
    const nextAllowedAt = lastTriggeredAt + cooldownMs
    if (now >= nextAllowedAt) {
      geofenceLastTriggeredAt.set(nearestInside.reportId, now)
      log({
        geofence: 'triggered',
        reportId: nearestInside.reportId,
        severity,
        distance_meters: meters,
        radius_meters: radius,
        cooldown_ms: cooldownMs,
      })
      notifyGeofence(message)
      playAudibleAlarm()
      setGeofenceStatus(`inside alert radius (${message})`)
    } else {
      const secondsLeft = Math.ceil((nextAllowedAt - now) / 1000)
      setGeofenceStatus(`inside ${severity}-risk radius, cooldown active (${secondsLeft}s remaining)`)
    }
    return
  }

  const meters = Math.round(nearestAny.distance)
  const nearestSeverity = nearestAny.severity || 'low'
  setGeofenceStatus(`enabled, nearest ${nearestSeverity}-risk case is ${meters}m away`)
}

function centerHighRisk() {
  if (!caseMap) return
  let latestHigh = null
  for (const metadata of caseMeta.values()) {
    if (`${metadata.severity}`.toLowerCase() !== 'high') continue
    if (!latestHigh || metadata.createdAt > latestHigh.createdAt) {
      latestHigh = metadata
    }
  }

  if (!latestHigh) {
    log('No high-risk incidents available to center.')
    return
  }

  caseMap.setView([latestHigh.latitude, latestHigh.longitude], 14)
}

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

function parseCoordinate(value, min, max) {
  const parsed = Number.parseFloat(value)
  if (Number.isNaN(parsed)) return null
  if (parsed < min || parsed > max) return null
  return parsed
}

function geolocationPromise() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error('Geolocation is not supported by this browser.'))
      return
    }

    navigator.geolocation.getCurrentPosition(resolve, reject, {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 0,
    })
  })
}

async function reverseGeocodeOpenStreetMap(latitude, longitude) {
  const params = new URLSearchParams({
    format: 'jsonv2',
    lat: `${latitude}`,
    lon: `${longitude}`,
    zoom: '16',
  })

  const response = await fetch(`https://nominatim.openstreetmap.org/reverse?${params.toString()}`)
  if (!response.ok) {
    throw new Error(`OpenStreetMap reverse geocoding failed: ${response.status}`)
  }

  const body = await response.json()
  if (typeof body?.display_name === 'string' && body.display_name.trim()) {
    return body.display_name.trim()
  }

  return `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`
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

  if (event?.report_id) {
    updateCaseMarker({
      id: event.report_id,
      location: event.location,
      latitude: event.latitude,
      longitude: event.longitude,
      severity: event.severity,
      summary: event.summary,
      created_at: event.created_at,
    })
  }
}

function markerColorBySeverity(severity) {
  const normalized = `${severity || ''}`.toLowerCase()
  if (normalized === 'high') return '#d62d20'
  if (normalized === 'medium') return '#f4b400'
  return '#2ea043'
}

function updateCaseMarker(report) {
  initCaseMap()
  if (!caseMap || !report) return

  const latitude = Number(report.latitude)
  const longitude = Number(report.longitude)
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return

  const reportId = String(report.id ?? report.report_id ?? crypto.randomUUID())
  const severity = report.severity || report.analysis?.severity || 'low'
  const summary = report.summary || report.analysis?.summary || report.report || 'Case update'
  const location = report.location || 'Unknown location'
  const createdAt = report.created_at || ''

  const popupHtml = `
    <strong>Case #${reportId}</strong><br>
    <span>Severity: ${severity}</span><br>
    <span>Location: ${location}</span><br>
    <span>${summary}</span><br>
    <small>${createdAt}</small>
  `

  const color = markerColorBySeverity(severity)
  const icon = leafletGlobal.divIcon({
    className: 'janam-marker',
    html: `<div style="width:14px;height:14px;border-radius:999px;background:${color};border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,0.25);"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  })

  const existing = caseMarkers.get(reportId)
  if (existing) {
    existing.setLatLng([latitude, longitude])
    existing.setPopupContent(popupHtml)
    caseMeta.set(reportId, {
      severity,
      latitude,
      longitude,
      createdAt: createdAt,
    })
    applyMarkerFilters()
    return
  }

  const marker = leafletGlobal.marker([latitude, longitude], { icon }).addTo(caseMap)
  marker.bindPopup(popupHtml)
  caseMarkers.set(reportId, marker)
  caseMeta.set(reportId, {
    severity,
    latitude,
    longitude,
    createdAt: createdAt,
  })
  applyMarkerFilters()
  evaluateGeofence()
}

async function refreshIntel() {
  const limit = getLimit()
  const body = await callApi(`/alerts?limit=${limit}`)
  if (Array.isArray(body)) {
    for (const event of body) captureAlert(event)
  }
}

async function refreshCaseMap() {
  const limit = getLimit()
  const body = await callApi(`/reports?limit=${limit}`, { method: 'GET' })
  if (!Array.isArray(body)) return
  for (const report of body) {
    updateCaseMarker(report)
  }
}

async function analyzeViaPath(path, reportType) {
  const latitude = parseCoordinate(latitudeInput.value, -90, 90)
  const longitude = parseCoordinate(longitudeInput.value, -180, 180)
  await callApi(path, {
    method: 'POST',
    body: JSON.stringify({
      report: reportTextInput.value,
      report_type: reportType,
      source: sourceInput.value,
      location: locationInput.value,
      latitude,
      longitude,
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

btnLocationAnalytics.addEventListener('click', async () => {
  await callApi('/analytics/locations', { method: 'GET' })
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

btnAnalyzeImage.addEventListener('click', async () => {
  await analyzeViaPath('/reports/image', 'image')
})

btnAnalyzeVideo.addEventListener('click', async () => {
  await analyzeViaPath('/reports/video', 'video')
})

btnUseGps.addEventListener('click', async () => {
  try {
    log('Requesting device GPS location...')
    const position = await geolocationPromise()
    const latitude = position.coords.latitude
    const longitude = position.coords.longitude

    latitudeInput.value = latitude.toFixed(6)
    longitudeInput.value = longitude.toFixed(6)
    userLocation = { latitude, longitude }
    upsertUserLocationOnMap(latitude, longitude)

    const resolvedLocation = await reverseGeocodeOpenStreetMap(latitude, longitude)
    locationInput.value = resolvedLocation
    evaluateGeofence()

    log({
      gps: 'updated',
      latitude,
      longitude,
      resolvedLocation,
      provider: 'OpenStreetMap Nominatim',
    })
  } catch (error) {
    log({
      gps: 'error',
      detail: error instanceof Error ? error.message : String(error),
    })
  }
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
  await refreshCaseMap()
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
      if (payload?.event === 'case' && payload?.report) updateCaseMarker(payload.report)
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
btnWsCases.addEventListener('click', () => connectWs('/ws/cases'))
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

for (const filterInput of [filterHighInput, filterMediumInput, filterLowInput]) {
  filterInput?.addEventListener('change', () => {
    applyMarkerFilters()
  })
}

btnMapFit?.addEventListener('click', () => {
  fitVisibleCases()
})

btnMapCenterHigh?.addEventListener('click', () => {
  centerHighRisk()
})

enableGeofenceInput?.addEventListener('change', async () => {
  if (enableGeofenceInput.checked && typeof Notification !== 'undefined' && Notification.permission === 'default') {
    try {
      await Notification.requestPermission()
    } catch {
      // ignore permission prompt errors and keep geofence available in log-only mode
    }
  }
  evaluateGeofence()
})

geofenceRadiusMetersInput?.addEventListener('change', () => {
  if (userLocation) {
    upsertUserLocationOnMap(userLocation.latitude, userLocation.longitude)
  }
  evaluateGeofence()
})

for (const input of [
  geofenceCooldownHighSecondsInput,
  geofenceCooldownMediumSecondsInput,
  geofenceCooldownLowSecondsInput,
]) {
  input?.addEventListener('change', () => {
    evaluateGeofence()
  })
  input?.addEventListener('input', () => {
    evaluateGeofence()
  })
}

btnGeofenceCheck?.addEventListener('click', async () => {
  if (!userLocation) {
    try {
      const position = await geolocationPromise()
      userLocation = { latitude: position.coords.latitude, longitude: position.coords.longitude }
      upsertUserLocationOnMap(userLocation.latitude, userLocation.longitude)
    } catch (error) {
      log({ geofence: 'gps_error', detail: error instanceof Error ? error.message : String(error) })
      setGeofenceStatus('unable to read GPS location')
      return
    }
  }

  evaluateGeofence()
})

initCaseMap()
void refreshCaseMap()

log('Janam operations console ready. Start with Health/Formats, then ingest incident reports and monitor live alerts.')
