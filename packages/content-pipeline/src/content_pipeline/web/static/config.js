/**
 * Salk Content Studio — Configuracao
 *
 * Auto-detecta API URL baseado no ambiente:
 * - docker-compose: frontend na porta 3000, API na porta 8080
 * - Render/producao: same-origin (ambos servidos pelo mesmo dominio)
 */
window.STUDIO_CONFIG = {
  API_URL: window.location.port === '3000'
    ? 'http://localhost:8080'   // docker-compose (frontend on 3000, api on 8080)
    : window.location.origin,   // same-origin (Render serves both)
  VERSION: '2.0.0',
};
