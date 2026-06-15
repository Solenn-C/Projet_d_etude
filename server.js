/**
 * server.js
 * ============================================================
 * RÔLE : Serveur HTTP principal SmartWear (Node.js, port 3000).
 *        Sert le Frontend statique et expose l'API JSON
 *        (auth, garde-robe, profils, préférences, paiement,
 *        analyse IA, conseil de tenue).
 *
 * DESCRIPTION :
 *   Serveur http natif (sans framework) avec routeur manuel par
 *   pathname/méthode. Stocke toutes les données dans
 *   Frontend/db.json (users, sessions, wardrobe, profiles,
 *   preferences, cartes, propositions/tenue du jour).
 *   L'authentification repose sur un token Bearer associé à un
 *   userId dans db.sessions — userId n'est jamais lu depuis
 *   req.body. Délègue l'analyse d'image et le conseil de tenue à
 *   des scripts Python (scripts/predict.py, scripts/analyse_couleur.py,
 *   scripts/conseil_tenue.py) via execFile, et proxy les requêtes
 *   /api/remove-bg vers le Backend FastAPI (port 8000).
 *
 * FONCTIONS PRINCIPALES :
 *   - loadDB() / saveDB(data)               : lecture/écriture de Frontend/db.json
 *   - generateToken() / getTokenFromHeaders(req) / getUserFromToken(token, db) : gestion des sessions
 *   - safeUser(user)                        : retire le hash du mot de passe avant envoi
 *   - sendJSON(res, status, data) / readBody(req) : helpers HTTP (réponse JSON, lecture du body)
 *   - serveFile(res, filePath)              : sert un fichier statique du Frontend
 *   - callGroq(payload)                     : proxy vers l'API Groq (chat)
 *   - runOnnxClassifier(base64Image)        : classification catégorie via scripts/predict.py (ONNX)
 *   - callGroqVision(base64Image, mediaType, typeDetecte) : analyse couleur/marque/saisons via scripts/analyse_couleur.py (Groq Vision)
 *   - analyzeClothingImage(base64Image, mediaType) : combine ONNX + Groq Vision pour /api/analyze-image
 *   - getOutfitAdvice(userId, demande, recentItems) : appelle scripts/conseil_tenue.py pour /api/agent/conseil
 *   - Routes : /api/auth/*, /api/data, /api/user, /api/wardrobe/*,
 *     /api/profiles/*, /api/preferences, /api/paiement/cartes/*,
 *     /api/abonnement, /api/analyze-image, /api/agent/conseil,
 *     /api/agent/valider-tenue, /api/agent/tenue-du-jour,
 *     /api/chat, /api/upload, /api/remove-bg
 *
 * DÉPENDANCES :
 *   - dotenv (.env -> GROQ_API_KEY), bcryptjs, multer,
 *     http/https/fs/path/os/crypto, child_process (execFile)
 *   - Frontend/db.json (base de données partagée)
 *   - scripts/predict.py, scripts/analyse_couleur.py, scripts/conseil_tenue.py (sous-processus Python)
 *   - Backend FastAPI sur 127.0.0.1:8000 (proxy /api/remove-bg)
 *
 * APPELS ENTRANTS :
 *   - Toutes les pages Frontend/*.html via Frontend/sw-data.js (fetch sur /api/...)
 *
 * APPELS SORTANTS :
 *   - api.groq.com (chat + vision), Backend FastAPI :8000, scripts Python (execFile)
 * ============================================================
 */

require('dotenv').config();
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const bcrypt = require('bcryptjs');
const crypto = require('crypto');
const https = require('https');
const multer = require('multer');
const { execFile } = require('child_process');

const PORT = 3000;
const FRONTEND_DIR = path.join(__dirname, 'Frontend');
const DB_FILE = path.join(FRONTEND_DIR, 'db.json');
const UPLOADS_DIR = path.join(FRONTEND_DIR, 'uploads');

if (!fs.existsSync(UPLOADS_DIR)) fs.mkdirSync(UPLOADS_DIR, { recursive: true });

// Configuration de l'upload de photos (Frontend/uploads/) : nom de fichier unique horodaté, 10 Mo max.
const _multerStorage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, UPLOADS_DIR),
  filename: (_req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase() || '.png';
    cb(null, Date.now() + '_' + crypto.randomBytes(4).toString('hex') + ext);
  },
});
const _upload = multer({ storage: _multerStorage, limits: { fileSize: 10 * 1024 * 1024 } });

const GROQ_API_KEY    = process.env.GROQ_API_KEY || '';
const GROQ_MODEL      = 'llama-3.3-70b-versatile';

// ──────────────────────────────────────────────
// BASE DE DONNÉES
// ──────────────────────────────────────────────
// Charge Frontend/db.json ; le crée avec une structure vide s'il n'existe pas encore.
function loadDB() {
  if (!fs.existsSync(DB_FILE)) {
    const initial = { users: [], sessions: {}, wardrobe: {}, profiles: [], preferences: {}, cartes: [] };
    fs.writeFileSync(DB_FILE, JSON.stringify(initial, null, 2));
    return initial;
  }
  return JSON.parse(fs.readFileSync(DB_FILE, 'utf8'));
}

// Écrit l'objet db dans Frontend/db.json (formaté, UTF-8).
function saveDB(data) {
  fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2), 'utf8');
}

// Renvoie la date du jour au format AAAA-MM-JJ (utilisé pour les propositions/tenue du jour).
function todayStr() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

// ──────────────────────────────────────────────
// UTILITAIRES AUTH
// ──────────────────────────────────────────────
// Génère un token de session aléatoire (hex, 32 octets).
function generateToken() {
  return crypto.randomBytes(32).toString('hex');
}

// Extrait le token Bearer de l'en-tête Authorization, ou null si absent.
function getTokenFromHeaders(req) {
  const auth = req.headers['authorization'];
  if (auth && auth.startsWith('Bearer ')) return auth.slice(7);
  return null;
}

// Résout le token de session en utilisateur via db.sessions (source unique de vérité pour l'identité).
function getUserFromToken(token, db) {
  if (!token) return null;
  const userId = (db.sessions || {})[token];
  if (!userId) return null;
  return db.users.find(u => u.id === userId) || null;
}

// Retourne une copie de l'utilisateur sans son hash de mot de passe, pour les réponses JSON.
function safeUser(user) {
  const { password, ...u } = user;
  return u;
}

// ──────────────────────────────────────────────
// UTILITAIRES HTTP
// ──────────────────────────────────────────────
// Envoie une réponse JSON avec les en-têtes CORS communs à toute l'API.
function sendJSON(res, status, data) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS'
  });
  res.end(JSON.stringify(data));
}

// Lit le corps de la requête et le parse en JSON (objet vide si invalide ou absent).
function readBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try { resolve(JSON.parse(body)); }
      catch { resolve({}); }
    });
  });
}

// ──────────────────────────────────────────────
// FICHIERS STATIQUES
// ──────────────────────────────────────────────
const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
  '.webp': 'image/webp'
};

// Sert un fichier statique avec le bon Content-Type (déduit de son extension), ou 404 s'il est introuvable.
function serveFile(res, filePath) {
  const ext = path.extname(filePath);
  const contentType = MIME[ext] || 'text/plain';
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('404 Not Found'); return; }
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
}

// ──────────────────────────────────────────────
// PROXY GROQ
// ──────────────────────────────────────────────
// Envoie un payload de chat à l'API Groq (api.groq.com) et renvoie la réponse JSON brute.
function callGroq(payload) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload);
    const options = {
      hostname: 'api.groq.com',
      path: '/openai/v1/chat/completions',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Authorization': `Bearer ${GROQ_API_KEY}`,
        'Content-Length': Buffer.byteLength(body),
      },
    };
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

// ─── ANALYSE IA ───────────────────────────────────────────────
// Catégorie : modèle ONNX custom SmartWear (scripts/predict.py)
// Couleur / Marque / Saisons : Groq Vision (agent/analyse_image.py, exécuté
//   en sous-processus via scripts/analyse_couleur.py). Le type détecté par
//   l'ONNX (top1) est transmis en paramètre pour guider l'analyse.
// ──────────────────────────────────────────────────────────────

// Écrit l'image dans un fichier temporaire et la classe via scripts/predict.py (modèle ONNX, top 3).
function runOnnxClassifier(base64Image) {
  return new Promise((resolve, reject) => {
    const tempPath = path.join(os.tmpdir(), 'smartwear_' + Date.now() + '.jpg');
    fs.writeFile(tempPath, Buffer.from(base64Image, 'base64'), (writeErr) => {
      if (writeErr) return reject(writeErr);
      execFile('py', ['scripts/predict.py', tempPath, '--top', '3'],
        { cwd: __dirname, timeout: 30000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } },
        (err, stdout) => {
          fs.unlink(tempPath, () => {});
          if (err) return reject(err);
          const results = [];
          for (const line of stdout.split('\n')) {
            const m = line.match(/^\s+(\d+)\.\s+(.+?)\s+([\d.]+)%/);
            if (m) results.push({ classe: m[2].trim(), score: parseFloat(m[3]) / 100 });
          }
          if (results.length === 0) return reject(new Error('Aucune classification extraite du script ONNX'));
          resolve({ top1: results[0] || null, top2: results[1] || null, top3: results[2] || null });
        }
      );
    });
  });
}

// Écrit l'image dans un fichier temporaire et lance scripts/analyse_couleur.py (Groq Vision) pour couleur/marque/saisons.
function callGroqVision(base64Image, mediaType, typeDetecte) {
  return new Promise((resolve, reject) => {
    const EXT_BY_MEDIA_TYPE = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp' };
    const ext = EXT_BY_MEDIA_TYPE[mediaType] || '.jpg';
    const tempPath = path.join(os.tmpdir(), 'smartwear_groq_' + Date.now() + ext);
    fs.writeFile(tempPath, Buffer.from(base64Image, 'base64'), (writeErr) => {
      if (writeErr) return reject(writeErr);
      const args = ['scripts/analyse_couleur.py', tempPath];
      if (typeDetecte) args.push('--type', typeDetecte);
      execFile('py', args,
        { cwd: __dirname, timeout: 30000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } },
        (err, stdout) => {
          fs.unlink(tempPath, () => {});
          if (err) return reject(err);
          try {
            resolve(JSON.parse(stdout.trim()));
          } catch (e) {
            reject(new Error('Réponse analyse Groq invalide : ' + stdout.slice(0, 200)));
          }
        }
      );
    });
  });
}

// Combine la classification ONNX (catégorie) et l'analyse Groq Vision (couleur/marque/saisons) pour /api/analyze-image.
async function analyzeClothingImage(base64Image, mediaType) {
  let onnx = null;
  try {
    onnx = await runOnnxClassifier(base64Image);
  } catch (e) {
    console.error('[SmartWear] ONNX classifier indisponible :', e.message);
  }

  const typeDetecte = onnx?.top1?.classe || null;

  let vision = {};
  try {
    vision = await callGroqVision(base64Image, mediaType, typeDetecte);
  } catch (e) {
    console.error('[SmartWear] Analyse Groq Vision indisponible :', e.message);
  }

  if (onnx) {
    return {
      top1: onnx.top1,
      top2: onnx.top2,
      top3: onnx.top3,
      couleur: vision.couleur || '',
      marque: vision.marque || 'Inconnue',
      saisons: vision.saisons || [],
    };
  }

  if (Object.keys(vision).length) {
    return {
      nom: '',
      couleur: vision.couleur || '',
      marque: vision.marque || 'Inconnue',
      saisons: vision.saisons || [],
    };
  }
  throw new Error('Analyse IA indisponible (ONNX + Groq Vision en erreur).');
}

// Envoie {userId, demande, recent} sur stdin à scripts/conseil_tenue.py et renvoie la tenue proposée (JSON sur stdout).
function getOutfitAdvice(userId, demande, recentItems) {
  return new Promise((resolve, reject) => {
    const child = execFile('py', ['scripts/conseil_tenue.py'],
      { cwd: __dirname, timeout: 30000, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } },
      (err, stdout) => {
        if (err) return reject(err);
        let result;
        try {
          result = JSON.parse(stdout.trim());
        } catch (e) {
          return reject(new Error('Réponse agent conseil invalide : ' + stdout.slice(0, 200)));
        }
        if (result.error) {
          const notFound = result.code === 'WARDROBE_NOT_FOUND';
          const agentErr = new Error(result.error);
          agentErr.notFound = notFound;
          return reject(agentErr);
        }
        resolve(result);
      }
    );
    const payload = { userId, demande };
    if (Array.isArray(recentItems) && recentItems.length > 0) {
      payload.recent = recentItems;
    }
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

// ──────────────────────────────────────────────
// SERVEUR
// ──────────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;
  const method = req.method;

  // CORS preflight
  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS'
    });
    res.end();
    return;
  }

  // ── FICHIERS STATIQUES ──
  if (!pathname.startsWith('/api/')) {
    // Racine → page d'accueil
    if (pathname === '/') {
      return serveFile(res, path.join(FRONTEND_DIR, 'page_accueil_site.html'));
    }
    // Cherche le fichier dans Frontend/
    const filePath = path.join(FRONTEND_DIR, pathname);
    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      return serveFile(res, filePath);
    }
    // Cherche aussi à la racine du projet (ex: node_modules assets)
    const rootPath = path.join(__dirname, pathname);
    if (fs.existsSync(rootPath) && fs.statSync(rootPath).isFile()) {
      return serveFile(res, rootPath);
    }
    return serveFile(res, path.join(FRONTEND_DIR, 'page_accueil_site.html'));
  }

  const db = loadDB();
  const token = getTokenFromHeaders(req);

  // Résout l'utilisateur courant depuis le token ; répond 401 et renvoie null si non authentifié.
  function requireUser() {
    const user = getUserFromToken(token, db);
    if (!user) { sendJSON(res, 401, { error: 'Non authentifié.' }); return null; }
    return user;
  }

  // ════════════════════════════════
  // GROQ PROXY
  // ════════════════════════════════
  if (pathname === '/api/chat' && method === 'POST') {
    const body = await readBody(req);
    try {
      const response = await callGroq({
        model: GROQ_MODEL,
        messages: body.messages || [],
        temperature: body.temperature ?? 0.7,
        max_tokens: body.max_tokens ?? 800,
      });
      return sendJSON(res, 200, response);
    } catch (err) {
      return sendJSON(res, 502, { error: 'Erreur Groq : ' + err.message });
    }
  }

  // ════════════════════════════════
  // UPLOAD PHOTO
  // ════════════════════════════════
  if (pathname === '/api/upload' && method === 'POST') {
    const user = requireUser(); if (!user) return;
    _upload.single('photo')(req, res, (err) => {
      if (err) return sendJSON(res, 400, { error: err.message });
      if (!req.file) return sendJSON(res, 400, { error: 'Aucun fichier reçu.' });
      sendJSON(res, 200, { url: '/uploads/' + req.file.filename });
    });
    return;
  }

  // ════════════════════════════════
  // PROXY REMOVE-BG → FastAPI :8000
  // ════════════════════════════════
  if (pathname === '/api/remove-bg' && method === 'POST') {
    // Lire le body multipart brut et le retransmettre à FastAPI
    const chunks = [];
    req.on('data', c => chunks.push(c));
    req.on('end', () => {
      const bodyBuf = Buffer.concat(chunks);
      const contentType = req.headers['content-type'] || '';
      const options = {
        hostname: '127.0.0.1',
        port: 8000,
        path: '/image/remove-bg',
        method: 'POST',
        headers: {
          'Content-Type': contentType,
          'Content-Length': bodyBuf.length,
        },
      };
      const proxy = require('http').request(options, (apiRes) => {
        if (apiRes.statusCode !== 200) {
          return sendJSON(res, 502, { error: 'FastAPI remove-bg erreur ' + apiRes.statusCode });
        }
        const parts = [];
        apiRes.on('data', c => parts.push(c));
        apiRes.on('end', () => {
          const img = Buffer.concat(parts);
          res.writeHead(200, {
            'Content-Type': 'image/png',
            'Content-Length': img.length,
            'Access-Control-Allow-Origin': '*',
          });
          res.end(img);
        });
      });
      proxy.on('error', () => {
        sendJSON(res, 503, { error: 'FastAPI inaccessible — lance : cd Backend && py -m uvicorn main:app --port 8000' });
      });
      proxy.write(bodyBuf);
      proxy.end();
    });
    return;
  }

  // ════════════════════════════════
  // AUTH
  // ════════════════════════════════

  // POST /api/auth/register
  if (pathname === '/api/auth/register' && method === 'POST') {
    const { prenom, nom, email, password } = await readBody(req);
    if (!prenom || !email || !password)
      return sendJSON(res, 400, { error: 'Prénom, email et mot de passe requis.' });
    if (db.users.find(u => u.email === email))
      return sendJSON(res, 409, { error: 'Un compte existe déjà avec cet email.' });

    const hash = await bcrypt.hash(password, 10);
    const user = {
      id: crypto.randomUUID(),
      prenom, nom: nom || '', email, password: hash,
      createdAt: new Date().toISOString()
    };
    db.users.push(user);
    const tok = generateToken();
    if (!db.sessions) db.sessions = {};
    db.sessions[tok] = user.id;
    saveDB(db);
    return sendJSON(res, 201, { message: 'Compte créé !', token: tok, user: safeUser(user) });
  }

  // POST /api/auth/login
  if (pathname === '/api/auth/login' && method === 'POST') {
    const { email, password } = await readBody(req);
    const user = db.users.find(u => u.email === email);
    if (!user) return sendJSON(res, 401, { error: 'Email ou mot de passe incorrect.' });
    const valid = await bcrypt.compare(password, user.password);
    if (!valid) return sendJSON(res, 401, { error: 'Email ou mot de passe incorrect.' });

    const tok = generateToken();
    if (!db.sessions) db.sessions = {};
    db.sessions[tok] = user.id;
    saveDB(db);
    return sendJSON(res, 200, { message: 'Connecté !', token: tok, user: safeUser(user) });
  }

  // GET /api/auth/me
  if (pathname === '/api/auth/me' && method === 'GET') {
    const user = getUserFromToken(token, db);
    if (!user) return sendJSON(res, 401, { error: 'Non authentifié.' });
    return sendJSON(res, 200, { user: safeUser(user) });
  }

  // POST /api/auth/logout
  if (pathname === '/api/auth/logout' && method === 'POST') {
    if (token && db.sessions) {
      delete db.sessions[token];
      saveDB(db);
    }
    return sendJSON(res, 200, { message: 'Déconnecté.' });
  }

  // ════════════════════════════════
  // DONNÉES GÉNÉRALES
  // ════════════════════════════════

  // GET /api/data
  if (pathname === '/api/data' && method === 'GET') {
    const user = requireUser(); if (!user) return;
    return sendJSON(res, 200, {
      user: safeUser(user),
      wardrobe: (db.wardrobe || {})[user.id] || {},
      profiles: (db.profiles || []).filter(p => p.userId === user.id),
      preferences: (db.preferences || {})[user.id] || {}
    });
  }

  // ════════════════════════════════
  // UTILISATEUR
  // ════════════════════════════════

  // PUT /api/user
  if (pathname === '/api/user' && method === 'PUT') {
    const user = requireUser(); if (!user) return;
    const updates = await readBody(req);
    delete updates.password; delete updates.id; delete updates.email;
    const idx = db.users.findIndex(u => u.id === user.id);
    db.users[idx] = { ...db.users[idx], ...updates };
    saveDB(db);
    return sendJSON(res, 200, safeUser(db.users[idx]));
  }

  // ════════════════════════════════
  // GARDE-ROBE
  // ════════════════════════════════
  const wardrobeAll  = pathname === '/api/wardrobe';
  const wardrobeCat  = pathname.match(/^\/api\/wardrobe\/([^/]+)$/);
  const wardrobeItem = pathname.match(/^\/api\/wardrobe\/([^/]+)\/([^/]+)$/);

  if (wardrobeAll && method === 'GET') {
    const user = requireUser(); if (!user) return;
    return sendJSON(res, 200, (db.wardrobe || {})[user.id] || {});
  }

  if (wardrobeCat && method === 'GET') {
    const user = requireUser(); if (!user) return;
    return sendJSON(res, 200, ((db.wardrobe || {})[user.id] || {})[wardrobeCat[1]] || []);
  }

  if (wardrobeCat && method === 'POST') {
    const user = requireUser(); if (!user) return;
    const cat = wardrobeCat[1];
    const body = await readBody(req);
    if (!db.wardrobe) db.wardrobe = {};
    if (!db.wardrobe[user.id]) db.wardrobe[user.id] = {};
    if (!db.wardrobe[user.id][cat]) db.wardrobe[user.id][cat] = [];
    // L'id vient toujours du serveur (string) — ignore l'id éventuel du client
    const item = { ...body, id: Date.now().toString(), createdAt: new Date().toISOString() };
    db.wardrobe[user.id][cat].push(item);
    saveDB(db);
    return sendJSON(res, 201, item);
  }

  if (wardrobeItem && method === 'PUT') {
    const user = requireUser(); if (!user) return;
    const [, cat, id] = wardrobeItem;
    const body = await readBody(req);
    const items = ((db.wardrobe || {})[user.id] || {})[cat] || [];
    const idx = items.findIndex(i => i.id === id);
    if (idx === -1) return sendJSON(res, 404, { error: 'Vêtement introuvable.' });
    items[idx] = { ...items[idx], ...body };
    db.wardrobe[user.id][cat] = items;
    saveDB(db);
    return sendJSON(res, 200, items[idx]);
  }

  if (wardrobeItem && method === 'DELETE') {
    const user = requireUser(); if (!user) return;
    const [, cat, id] = wardrobeItem;
    if (!db.wardrobe?.[user.id]?.[cat])
      return sendJSON(res, 404, { error: 'Catégorie introuvable.' });
    db.wardrobe[user.id][cat] = db.wardrobe[user.id][cat].filter(i => String(i.id) !== String(id));
    saveDB(db);
    return sendJSON(res, 200, { message: 'Supprimé.' });
  }

  // ════════════════════════════════
  // PROFILS
  // ════════════════════════════════
  const profilesBase = pathname === '/api/profiles';
  const profilesItem = pathname.match(/^\/api\/profiles\/([^/]+)$/);

  if (profilesBase && method === 'GET') {
    const user = requireUser(); if (!user) return;
    return sendJSON(res, 200, (db.profiles || []).filter(p => p.userId === user.id));
  }

  if (profilesBase && method === 'POST') {
    const user = requireUser(); if (!user) return;
    const body = await readBody(req);
    if (!db.profiles) db.profiles = [];
    const profile = { id: Date.now().toString(), userId: user.id, ...body };
    db.profiles.push(profile);
    saveDB(db);
    return sendJSON(res, 201, profile);
  }

  if (profilesItem && method === 'PUT') {
    const user = requireUser(); if (!user) return;
    const id = profilesItem[1];
    const body = await readBody(req);
    const idx = (db.profiles || []).findIndex(p => p.id === id && p.userId === user.id);
    if (idx === -1) return sendJSON(res, 404, { error: 'Profil introuvable.' });
    db.profiles[idx] = { ...db.profiles[idx], ...body };
    saveDB(db);
    return sendJSON(res, 200, db.profiles[idx]);
  }

  if (profilesItem && method === 'DELETE') {
    const user = requireUser(); if (!user) return;
    const id = profilesItem[1];
    db.profiles = (db.profiles || []).filter(p => !(p.id === id && p.userId === user.id));
    saveDB(db);
    return sendJSON(res, 200, { message: 'Profil supprimé.' });
  }

  // ════════════════════════════════
  // PRÉFÉRENCES
  // ════════════════════════════════
  if (pathname === '/api/preferences' && method === 'PUT') {
    const user = requireUser(); if (!user) return;
    const body = await readBody(req);
    if (!db.preferences) db.preferences = {};
    db.preferences[user.id] = { ...(db.preferences[user.id] || {}), ...body };
    saveDB(db);
    return sendJSON(res, 200, db.preferences[user.id]);
  }

  // ════════════════════════════════
  // PAIEMENT / CARTES
  // ════════════════════════════════
  const cartesBase = pathname === '/api/paiement/cartes';
  const cartesItem = pathname.match(/^\/api\/paiement\/cartes\/([^/]+)$/);

  if (cartesBase && method === 'POST') {
    const user = requireUser(); if (!user) return;
    const body = await readBody(req);
    if (!db.cartes) db.cartes = [];
    const carte = { id: Date.now().toString(), userId: user.id, ...body };
    db.cartes.push(carte);
    saveDB(db);
    return sendJSON(res, 201, carte);
  }

  if (cartesItem && method === 'PUT') {
    const user = requireUser(); if (!user) return;
    const id = cartesItem[1];
    const body = await readBody(req);
    const idx = (db.cartes || []).findIndex(c => c.id === id && c.userId === user.id);
    if (idx === -1) return sendJSON(res, 404, { error: 'Carte introuvable.' });
    db.cartes[idx] = { ...db.cartes[idx], ...body };
    saveDB(db);
    return sendJSON(res, 200, db.cartes[idx]);
  }

  if (cartesItem && method === 'DELETE') {
    const user = requireUser(); if (!user) return;
    const id = cartesItem[1];
    db.cartes = (db.cartes || []).filter(c => !(c.id === id && c.userId === user.id));
    saveDB(db);
    return sendJSON(res, 200, { message: 'Carte supprimée.' });
  }

  // ════════════════════════════════
  // ABONNEMENT
  // ════════════════════════════════
  if (pathname === '/api/abonnement' && method === 'PUT') {
    const user = requireUser(); if (!user) return;
    const { plan } = await readBody(req);
    const idx = db.users.findIndex(u => u.id === user.id);
    db.users[idx].abonnement = plan;
    saveDB(db);
    return sendJSON(res, 200, { plan });
  }

  // ════════════════════════════════
  // ANALYSE IA (VISION)
  // ════════════════════════════════
  if (pathname === '/api/analyze-image' && method === 'POST') {
    const user = requireUser(); if (!user) return;
    const body = await readBody(req);
    const { base64, mediaType } = body;
    if (!base64) return sendJSON(res, 400, { error: 'Image base64 requise.' });
    try {
      const result = await analyzeClothingImage(base64, mediaType || 'image/jpeg');
      return sendJSON(res, 200, result);
    } catch (e) {
      console.error('Erreur analyse IA :', e.message);
      return sendJSON(res, 500, { error: e.message || 'Analyse IA indisponible.' });
    }
  }

  // ════════════════════════════════
  // CONSEIL DE TENUE (AGENT IA)
  // ════════════════════════════════
  if (pathname === '/api/agent/conseil' && method === 'POST') {
    const user = requireUser(); if (!user) return;
    const { demande } = await readBody(req);
    if (!demande) return sendJSON(res, 400, { error: 'Demande requise.' });

    const today = todayStr();
    let recentHauts = [];
    try {
      if (!db.propositionsDuJour) db.propositionsDuJour = {};
      let entry = db.propositionsDuJour[user.id];
      if (!entry || entry.date !== today) {
        entry = { date: today, hauts: [] };
        db.propositionsDuJour[user.id] = entry;
      }
      recentHauts = entry.hauts;
    } catch (e) {
      console.error('Erreur lecture propositionsDuJour :', e.message);
    }

    try {
      const result = await getOutfitAdvice(user.id, demande, recentHauts);

      try {
        const hautNom = result?.tenue?.haut?.nom;
        if (hautNom) {
          if (!db.propositionsDuJour) db.propositionsDuJour = {};
          let entry = db.propositionsDuJour[user.id];
          if (!entry || entry.date !== today) {
            entry = { date: today, hauts: [] };
          }
          if (!entry.hauts.includes(hautNom)) entry.hauts.push(hautNom);
          db.propositionsDuJour[user.id] = entry;
          saveDB(db);
        }
      } catch (e) {
        console.error('Erreur écriture propositionsDuJour :', e.message);
      }

      try {
        if (!db.propositionDuJour) db.propositionDuJour = {};
        db.propositionDuJour[user.id] = { date: today, tenue: result };
        saveDB(db);
      } catch (e) {
        console.error('Erreur écriture propositionDuJour :', e.message);
      }

      return sendJSON(res, 200, result);
    } catch (e) {
      console.error('Erreur conseil de tenue :', e.message);
      if (e.notFound) return sendJSON(res, 404, { error: e.message });
      return sendJSON(res, 500, { error: e.message || 'Conseil de tenue indisponible.' });
    }
  }

  // ════════════════════════════════
  // VALIDATION DE LA TENUE DU JOUR
  // ════════════════════════════════
  if (pathname === '/api/agent/valider-tenue' && method === 'POST') {
    const user = requireUser(); if (!user) return;
    const { tenue } = await readBody(req);
    if (!tenue) return sendJSON(res, 400, { error: 'Tenue requise.' });

    try {
      if (!db.tenueDuJour) db.tenueDuJour = {};
      db.tenueDuJour[user.id] = { date: todayStr(), tenue };
      saveDB(db);
    } catch (e) {
      console.error('Erreur écriture tenueDuJour :', e.message);
    }

    return sendJSON(res, 200, { ok: true });
  }

  if (pathname === '/api/agent/tenue-du-jour' && method === 'GET') {
    const user = requireUser(); if (!user) return;

    const today = todayStr();
    try {
      const validee = (db.tenueDuJour || {})[user.id];
      if (validee && validee.date === today) {
        return sendJSON(res, 200, { etat: 'validee', figee: true, tenue: validee.tenue });
      }

      const proposee = (db.propositionDuJour || {})[user.id];
      if (proposee && proposee.date === today) {
        return sendJSON(res, 200, { etat: 'proposee', figee: false, tenue: proposee.tenue });
      }
    } catch (e) {
      console.error('Erreur lecture tenueDuJour :', e.message);
    }

    return sendJSON(res, 200, { etat: 'vide', figee: false });
  }

  // ════════════════════════════════
  // 404
  // ════════════════════════════════
  sendJSON(res, 404, { error: 'Route introuvable.' });
});

server.listen(PORT, () => {
  console.log(`\n✅  SmartWear server lancé sur http://localhost:${PORT}`);
  console.log(`📁  Base de données : ${DB_FILE}`);
  console.log(`🔐  Authentification bcrypt activée\n`);
  console.log('Routes disponibles :');
  console.log('  POST /api/auth/register   — inscription');
  console.log('  POST /api/auth/login      — connexion');
  console.log('  GET  /api/auth/me         — utilisateur connecté');
  console.log('  POST /api/auth/logout     — déconnexion');
  console.log('  POST /api/chat            — proxy Groq (tenues IA)');
  console.log('  GET  /api/data            — toutes les données');
  console.log('  PUT  /api/user            — modifier le profil');
  console.log('  GET/POST /api/wardrobe/:cat');
  console.log('  PUT/DELETE /api/wardrobe/:cat/:id');
  console.log('  POST /api/analyze-image    — analyse IA (ONNX + Groq Vision)');
  console.log('  POST /api/agent/conseil    — conseil de tenue (agent IA)');
  console.log('  GET/POST /api/profiles');
  console.log('  PUT/DELETE /api/profiles/:id');
  console.log('  PUT  /api/preferences');
  console.log('  POST /api/paiement/cartes');
  console.log('  PUT/DELETE /api/paiement/cartes/:id');
  console.log('  PUT  /api/abonnement\n');
});
