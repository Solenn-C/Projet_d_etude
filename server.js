const http   = require('http');
const https  = require('https');
const fs     = require('fs');
const path   = require('path');
const bcrypt = require('bcryptjs');
const crypto = require('crypto');

const GROQ_API_KEY = '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';
const PORT        = 3000;
const DB_FILE     = path.join(__dirname, 'db.json');
const ENTRY       = 'page_accueil_site.html';
const SALT_ROUNDS = 10;

// ── Base de données principale (comptes + sessions) ──
function loadDB() {
  if (!fs.existsSync(DB_FILE)) { const d = { users:[], sessions:{} }; saveDB(d); return d; }
  try { return JSON.parse(fs.readFileSync(DB_FILE, 'utf-8')); }
  catch { return { users:[], sessions:{} }; }
}
function saveDB(db) { fs.writeFileSync(DB_FILE, JSON.stringify(db, null, 2), 'utf-8'); }

// ── Données personnelles par utilisateur (dossier users/) ──
function getUserData(userId) {
  const p = path.join(__dirname, 'users', userId + '.json');
  if (!fs.existsSync(p)) return defaultUserData();
  try { return JSON.parse(fs.readFileSync(p, 'utf-8')); }
  catch { return defaultUserData(); }
}
function saveUserData(userId, data) {
  const dir = path.join(__dirname, 'users');
  if (!fs.existsSync(dir)) fs.mkdirSync(dir);
  fs.writeFileSync(path.join(dir, userId + '.json'), JSON.stringify(data, null, 2), 'utf-8');
}
function defaultUserData() {
  return {
    user: { prenom:'', nom:'', email:'', telephone:'', dateNaissance:'', genre:'', ville:'Paris', pays:'France', langue:'Français', heureNotif:'08:00', unite:'Celsius', abonnement:'gratuit', tailleHaut:'', tailleBas:'', tailleChaussures:'', styles:[], contextes:['quotidien'], onboardingDone:false },
    profiles: [],
    wardrobe: { manteau:[], haut:[], bas:[], ensemble:[], chaussures:[], accessoires:[] },
    preferences: { villes:['Paris'], notifications:{ tenueDuJour:true, meteo:true, tendances:false, piecesManquantes:true, emails:false } },
    paiement: { cartes:[], factures:[] }
  };
}

// ── Helpers ──
const MIME = { '.html':'text/html; charset=utf-8','.css':'text/css','.js':'application/javascript','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.svg':'image/svg+xml','.ico':'image/x-icon','.webp':'image/webp' };

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => { try { resolve(body ? JSON.parse(body) : {}); } catch { reject(new Error('Invalid JSON')); } });
  });
}
function send(res, status, data) { res.writeHead(status, { 'Content-Type':'application/json' }); res.end(JSON.stringify(data)); }
function token() { return crypto.randomBytes(32).toString('hex'); }

function getAuthUser(req) {
  const db  = loadDB();
  const auth = (req.headers['authorization'] || '').replace('Bearer ', '').trim();
  if (!auth) return null;
  const userId = db.sessions[auth];
  if (!userId) return null;
  const user = db.users.find(u => u.id === userId);
  return user ? { ...user, token: auth } : null;
}

// ── Serveur ──
const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type,Authorization');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  const url    = req.url.split('?')[0];
  const method = req.method;

  // ── INSCRIPTION ──
  if (method === 'POST' && url === '/api/auth/register') {
    try {
      const { email, password, prenom, nom } = await readBody(req);
      if (!email || !password || !prenom || !nom) { send(res, 400, { error:'Tous les champs sont requis' }); return; }
      if (!email.includes('@'))  { send(res, 400, { error:'Email invalide' }); return; }
      if (password.length < 8)   { send(res, 400, { error:'Mot de passe trop court (8 caractères minimum)' }); return; }
      const db = loadDB();
      if (db.users.find(u => u.email === email.toLowerCase())) { send(res, 409, { error:'Cet email est déjà utilisé' }); return; }
      const hash   = await bcrypt.hash(password, SALT_ROUNDS);
      const userId = crypto.randomUUID();
      db.users.push({ id:userId, email:email.toLowerCase(), password:hash, prenom, nom, createdAt:new Date().toISOString() });
      const tok = token();
      db.sessions[tok] = userId;
      saveDB(db);
      const ud = defaultUserData();
      ud.user.email = email.toLowerCase(); ud.user.prenom = prenom; ud.user.nom = nom;
      saveUserData(userId, ud);
      console.log('✓ Inscription :', email);
      send(res, 201, { ok:true, token:tok, user:{ id:userId, email:email.toLowerCase(), prenom, nom } });
    } catch(e) { console.error(e); send(res, 500, { error:'Erreur serveur' }); }
    return;
  }

  // ── CONNEXION ──
  if (method === 'POST' && url === '/api/auth/login') {
    try {
      const { email, password } = await readBody(req);
      if (!email || !password) { send(res, 400, { error:'Email et mot de passe requis' }); return; }
      const db   = loadDB();
      const user = db.users.find(u => u.email === email.toLowerCase());
      if (!user) { send(res, 401, { error:'Email ou mot de passe incorrect' }); return; }
      const valid = await bcrypt.compare(password, user.password);
      if (!valid) { send(res, 401, { error:'Email ou mot de passe incorrect' }); return; }
      const tok = token();
      db.sessions[tok] = user.id;
      saveDB(db);
      console.log('✓ Connexion :', email);
      send(res, 200, { ok:true, token:tok, user:{ id:user.id, email:user.email, prenom:user.prenom, nom:user.nom } });
    } catch(e) { console.error(e); send(res, 500, { error:'Erreur serveur' }); }
    return;
  }

  // ── DÉCONNEXION ──
  if (method === 'POST' && url === '/api/auth/logout') {
    const au = getAuthUser(req);
    if (au) { const db = loadDB(); delete db.sessions[au.token]; saveDB(db); }
    send(res, 200, { ok:true }); return;
  }

  // ── VÉRIFIER SESSION ──
  if (method === 'GET' && url === '/api/auth/me') {
    const au = getAuthUser(req);
    if (!au) { send(res, 401, { error:'Non connecté' }); return; }
    send(res, 200, { user:{ id:au.id, email:au.email, prenom:au.prenom, nom:au.nom } }); return;
  }

  // ── API IA (Groq) ──
  if (method === 'POST' && url === '/api/chat') {
    const au = getAuthUser(req);
    if (!au) { send(res, 401, { error:'Non connecté' }); return; }
    let body = '';
    req.on('data', c => body += c);
    req.on('end', () => {
      let p; try { p = JSON.parse(body); } catch { res.writeHead(400); res.end('Invalid JSON'); return; }

      // Format Groq (OpenAI-compatible) : system prompt en premier message
      const messages = [];
      if (p.system) messages.push({ role: 'system', content: p.system });
      (p.messages || []).forEach(m => messages.push({ role: m.role, content: m.content }));

      const payload = JSON.stringify({
        model: 'llama-3.3-70b-versatile',
        messages,
        max_tokens: p.max_tokens || 1000,
        temperature: 0.7
      });

      const opts = {
        hostname: 'api.groq.com',
        path: '/openai/v1/chat/completions',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + GROQ_API_KEY,
          'Content-Length': Buffer.byteLength(payload)
        }
      };

      const ar = https.request(opts, r => {
        let d = '';
        r.on('data', c => d += c);
        r.on('end', () => {
          try {
            const groqRes = JSON.parse(d);
            if (groqRes.error) {
              res.writeHead(400, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ error: { message: groqRes.error.message } }));
              return;
            }
            // Conversion réponse Groq → format attendu par le client
            const text = groqRes.choices?.[0]?.message?.content || '';
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ content: [{ type: 'text', text }] }));
          } catch(e) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: { message: 'Erreur parsing réponse Groq' } }));
          }
        });
      });
      ar.on('error', e => { res.writeHead(500); res.end(JSON.stringify({ error: { message: e.message } })); });
      ar.write(payload);
      ar.end();
    });
    return;
  }

  // ── API DATA (routes protégées) ──
  if (url.startsWith('/api/')) {
    const au = getAuthUser(req);
    if (!au) { send(res, 401, { error:'Non connecté — veuillez vous connecter' }); return; }
    const uid = au.id;
    const d   = getUserData(uid);

    if (method==='GET'  && url==='/api/data')              { send(res,200,d); return; }

    if (method==='PUT'  && url==='/api/user') {
      const b=await readBody(req); d.user={...d.user,...b};
      const mdb=loadDB(); const i=mdb.users.findIndex(u=>u.id===uid);
      if(i!==-1){ if(b.prenom)mdb.users[i].prenom=b.prenom; if(b.nom)mdb.users[i].nom=b.nom; saveDB(mdb); }
      saveUserData(uid,d); send(res,200,{ok:true,user:d.user}); return;
    }

    if (method==='GET'  && url==='/api/profiles')          { send(res,200,d.profiles); return; }
    if (method==='POST' && url==='/api/profiles') {
      const b=await readBody(req); const p={id:Date.now(),...b,createdAt:new Date().toISOString()};
      d.profiles.push(p); saveUserData(uid,d); send(res,201,p); return;
    }
    if (method==='PUT'  && url.startsWith('/api/profiles/')) {
      const id=parseInt(url.split('/')[3]); const b=await readBody(req);
      const i=d.profiles.findIndex(p=>p.id===id); if(i===-1){send(res,404,{error:'Introuvable'});return;}
      d.profiles[i]={...d.profiles[i],...b}; saveUserData(uid,d); send(res,200,d.profiles[i]); return;
    }
    if (method==='DELETE'&& url.startsWith('/api/profiles/')) {
      const id=parseInt(url.split('/')[3]); d.profiles=d.profiles.filter(p=>p.id!==id);
      saveUserData(uid,d); send(res,200,{ok:true}); return;
    }

    if (method==='GET'  && url==='/api/wardrobe')          { send(res,200,d.wardrobe); return; }
    if (method==='GET'  && url.startsWith('/api/wardrobe/') && url.split('/').length===4) {
      const cat=url.split('/')[3]; send(res,200,d.wardrobe[cat]||[]); return;
    }
    if (method==='POST' && url.startsWith('/api/wardrobe/')) {
      const cat=url.split('/')[3]; const b=await readBody(req);
      if(!d.wardrobe[cat])d.wardrobe[cat]=[];
      const item={id:Date.now(),...b,createdAt:new Date().toISOString()};
      d.wardrobe[cat].push(item); saveUserData(uid,d); send(res,201,item); return;
    }
    if (method==='PUT'  && url.startsWith('/api/wardrobe/') && url.split('/').length===5) {
      const pts=url.split('/'); const cat=pts[3]; const id=parseInt(pts[4]); const b=await readBody(req);
      if(!d.wardrobe[cat]){send(res,404,{error:'Catégorie introuvable'});return;}
      const i=d.wardrobe[cat].findIndex(x=>x.id===id); if(i===-1){send(res,404,{error:'Vêtement introuvable'});return;}
      d.wardrobe[cat][i]={...d.wardrobe[cat][i],...b}; saveUserData(uid,d); send(res,200,d.wardrobe[cat][i]); return;
    }
    if (method==='DELETE'&& url.startsWith('/api/wardrobe/')) {
      const pts=url.split('/'); const cat=pts[3]; const id=parseInt(pts[4]);
      if(!d.wardrobe[cat]){send(res,404,{error:'Catégorie introuvable'});return;}
      d.wardrobe[cat]=d.wardrobe[cat].filter(x=>x.id!==id); saveUserData(uid,d); send(res,200,{ok:true}); return;
    }

    if (method==='PUT'  && url==='/api/preferences') {
      const b=await readBody(req); d.preferences={...d.preferences,...b};
      saveUserData(uid,d); send(res,200,{ok:true}); return;
    }

    if (method==='POST' && url==='/api/paiement/cartes') {
      const b=await readBody(req); const card={id:Date.now(),...b,active:true};
      d.paiement.cartes.push(card); saveUserData(uid,d); send(res,201,card); return;
    }
    if (method==='PUT'  && url.startsWith('/api/paiement/cartes/')) {
      const id=parseInt(url.split('/')[4]); const b=await readBody(req);
      const i=d.paiement.cartes.findIndex(c=>c.id===id); if(i===-1){send(res,404,{error:'Carte introuvable'});return;}
      d.paiement.cartes[i]={...d.paiement.cartes[i],...b}; saveUserData(uid,d); send(res,200,d.paiement.cartes[i]); return;
    }
    if (method==='DELETE'&& url.startsWith('/api/paiement/cartes/')) {
      const id=parseInt(url.split('/')[4]);
      d.paiement.cartes=d.paiement.cartes.filter(c=>c.id!==id); saveUserData(uid,d); send(res,200,{ok:true}); return;
    }

    if (method==='PUT'  && url==='/api/abonnement') {
      const b=await readBody(req); d.user.abonnement=b.plan;
      saveUserData(uid,d); send(res,200,{ok:true,plan:b.plan}); return;
    }

    send(res,404,{error:'Route inconnue'}); return;
  }

  // ── Fichiers statiques ──
  let urlPath = url === '/' ? '/'+ENTRY : url;
  const filePath = path.join(__dirname, urlPath);
  if (!filePath.startsWith(__dirname)) { res.writeHead(403); res.end('Interdit'); return; }
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Page non trouvée : '+urlPath); return; }
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, { 'Content-Type': MIME[ext]||'application/octet-stream' });
    res.end(data);
  });
});

server.listen(PORT, () => {
  console.log('\n  ╔══════════════════════════════════════════════╗');
  console.log('  ║         Smart Wear — App démarrée           ║');
  console.log('  ╠══════════════════════════════════════════════╣');
  console.log('  ║   http://localhost:'+PORT+'                      ║');
  console.log('  ║   Auth : bcryptjs ✓  Sessions : token ✓     ║');
  console.log('  ╚══════════════════════════════════════════════╝\n');
});