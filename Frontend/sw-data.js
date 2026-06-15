/**
 * ============================================================
 * Frontend/sw-data.js
 * ============================================================
 * RÔLE : Client API partagé (objet global SW) pour toutes les
 *        pages du Frontend — auth, données, toasts.
 *
 * DESCRIPTION :
 *   Centralise l'accès à l'API Node (/api/*) : gestion du token
 *   de session (localStorage), authentification (register,
 *   login, logout, checkAuth, requireAuth,
 *   redirectIfLoggedIn), CRUD sur les données utilisateur
 *   (garde-robe, profils, préférences, cartes, abonnement) et
 *   affichage de notifications toast. Toutes les requêtes
 *   passent par _get/_post/_put/_del qui ajoutent automatiquement
 *   le header Authorization: Bearer et gèrent les 401 (redirection
 *   vers la page de connexion).
 *
 *   Inclure dans chaque page : <script src="sw-data.js"></script>
 *
 * FONCTIONS PRINCIPALES :
 *   - SW.register/login/logout/checkAuth/requireAuth/redirectIfLoggedIn : cycle de vie de la session
 *   - SW.getData/getWardrobe/getCategory/getProfiles/...                : lecture des données utilisateur
 *   - SW.addCloth/updateCloth/deleteCloth/addCard/...                    : CRUD garde-robe, profils, cartes
 *   - SW.showToast(msg, isError)                                          : affiche une notification toast
 *   - _headers()/_get()/_post()/_put()/_del()                             : helpers fetch internes avec Bearer token
 *
 * DÉPENDANCES :
 *   - localStorage (sw_token, sw_user)
 *
 * APPELS ENTRANTS :
 *   - Chargé via <script src="sw-data.js"> sur toutes les pages applicatives
 *
 * APPELS SORTANTS :
 *   - server.js (toutes les routes /api/*)
 * ============================================================
 */

// ══════════════════════════════════════════════
//   Smart Wear — Client API partagé
//   Inclure dans chaque page : <script src="sw-data.js"></script>
// ══════════════════════════════════════════════

const SW = {

  // ── Token de session ──
  getToken()  { return localStorage.getItem('sw_token'); },
  setToken(t) { localStorage.setItem('sw_token', t); },
  clearToken(){ localStorage.removeItem('sw_token'); localStorage.removeItem('sw_user'); },
  getUser()   { try { return JSON.parse(localStorage.getItem('sw_user')); } catch { return null; } },
  setUser(u)  { localStorage.setItem('sw_user', JSON.stringify(u)); },

  // ── Auth ──
  async register(prenom, nom, email, password) {
    const r = await _post('/api/auth/register', { prenom, nom, email, password });
    if (r.token) { SW.setToken(r.token); SW.setUser(r.user); }
    return r;
  },

  async login(email, password) {
    const r = await _post('/api/auth/login', { email, password });
    if (r.token) { SW.setToken(r.token); SW.setUser(r.user); }
    return r;
  },

  async logout() {
    try { await _post('/api/auth/logout', {}); } catch {}
    SW.clearToken();
    window.location.href = 'page_connexion_inscription.html';
  },

  async checkAuth() {
    const token = SW.getToken();
    if (!token) return null;
    try {
      const r = await _get('/api/auth/me');
      SW.setUser(r.user);
      return r.user;
    } catch {
      SW.clearToken();
      return null;
    }
  },

  // Redirige vers connexion si pas connecté
  async requireAuth() {
    const user = await SW.checkAuth();
    if (!user) {
      window.location.href = 'page_connexion_inscription.html';
      return null;
    }
    return user;
  },

  // Redirige vers dashboard si déjà connecté
  async redirectIfLoggedIn() {
    const user = await SW.checkAuth();
    if (user) {
      window.location.href = 'page_apres_connection.html';
    }
  },

  // ── Données ──
  async getData()               { return _get('/api/data'); },
  async getWardrobe()           { return _get('/api/wardrobe'); },
  async getCategory(cat)        { return _get('/api/wardrobe/' + cat); },
  async getProfiles()           { return _get('/api/profiles'); },
  async saveUser(data)          { return _put('/api/user', data); },
  async addProfile(data)        { return _post('/api/profiles', data); },
  async updateProfile(id, data) { return _put('/api/profiles/' + id, data); },
  async deleteProfile(id)       { return _del('/api/profiles/' + id); },
  async addCloth(cat, data)         { return _post('/api/wardrobe/' + cat, data); },
  async updateCloth(cat, id, data)  { return _put('/api/wardrobe/' + cat + '/' + id, data); },
  async deleteCloth(cat, id)        { return _del('/api/wardrobe/' + cat + '/' + id); },
  async savePreferences(data)   { return _put('/api/preferences', data); },
  async addCard(data)           { return _post('/api/paiement/cartes', data); },
  async updateCard(id, data)    { return _put('/api/paiement/cartes/' + id, data); },
  async deleteCard(id)          { return _del('/api/paiement/cartes/' + id); },
  async setAbonnement(plan)     { return _put('/api/abonnement', { plan }); },

  // ── Toast ──
  showToast(msg, isError) {
    let t = document.getElementById('sw-toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'sw-toast';
      t.style.cssText = 'position:fixed;bottom:28px;right:28px;z-index:9999;padding:13px 20px;border-radius:10px;font-family:Jost,sans-serif;font-size:13px;transform:translateY(80px);opacity:0;transition:all 0.35s cubic-bezier(0.34,1.56,0.64,1);pointer-events:none;';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.background = isError ? '#A32D2D' : '#1B3A6B';
    t.style.color = '#FAFAF8';
    t.style.transform = 'translateY(0)'; t.style.opacity = '1';
    clearTimeout(t._timer);
    t._timer = setTimeout(() => { t.style.transform = 'translateY(80px)'; t.style.opacity = '0'; }, 3000);
  }
};

// ── Fonctions internes avec token ──
// Construit les en-têtes de requête (Content-Type + Authorization: Bearer si connecté).
function _headers() {
  const h = { 'Content-Type': 'application/json' };
  const tok = SW.getToken();
  if (tok) h['Authorization'] = 'Bearer ' + tok;
  return h;
}

// Requête GET authentifiée ; déconnecte et redirige vers la connexion en cas de 401.
async function _get(url) {
  const r = await fetch(url, { headers: _headers() });
  if (r.status === 401) { SW.clearToken(); window.location.href = 'page_connexion_inscription.html'; throw new Error('Non connecté'); }
  if (!r.ok) throw new Error('Erreur ' + r.status);
  return r.json();
}
// Requête POST authentifiée (JSON) ; lève une erreur avec le message renvoyé par l'API si non-OK.
async function _post(url, data) {
  const r = await fetch(url, { method:'POST', headers:_headers(), body:JSON.stringify(data) });
  if (!r.ok) { const e = await r.json().catch(()=>({error:'Erreur'})); throw new Error(e.error || 'Erreur ' + r.status); }
  return r.json();
}
// Requête PUT authentifiée (JSON) ; déconnecte et redirige vers la connexion en cas de 401.
async function _put(url, data) {
  const r = await fetch(url, { method:'PUT', headers:_headers(), body:JSON.stringify(data) });
  if (r.status === 401) { SW.clearToken(); window.location.href = 'page_connexion_inscription.html'; throw new Error('Non connecté'); }
  if (!r.ok) throw new Error('Erreur ' + r.status);
  return r.json();
}
// Requête DELETE authentifiée ; déconnecte et redirige vers la connexion en cas de 401.
async function _del(url) {
  const r = await fetch(url, { method:'DELETE', headers:_headers() });
  if (r.status === 401) { SW.clearToken(); window.location.href = 'page_connexion_inscription.html'; throw new Error('Non connecté'); }
  if (!r.ok) throw new Error('Erreur ' + r.status);
  return r.json();
}