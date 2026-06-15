/**
 * ============================================================
 * Frontend/js/ui-nav.js
 * ============================================================
 * RÔLE : Comportements d'interface purement visuels de la barre
 *        de navigation (sidebar mobile + effet "scrolled").
 *
 * DESCRIPTION :
 *   Script indépendant du JS applicatif (SW.*) chargé séparément
 *   par chaque page. Ne contient aucune logique métier ni appel
 *   réseau : il gère uniquement l'ouverture/fermeture du tiroir
 *   sidebar sur mobile (burger, backdrop, Échap, clic sur un
 *   lien) et l'ajout de la classe CSS "scrolled" sur la nav
 *   lorsque la page est défilée.
 *
 * FONCTIONS PRINCIPALES :
 *   - setOpen(open)  : ouvre/ferme la sidebar mobile et synchronise burger/backdrop
 *   - onScroll()     : bascule la classe "scrolled" sur la nav selon le scroll
 *
 * DÉPENDANCES :
 *   - (aucune — DOM natif)
 *
 * APPELS ENTRANTS :
 *   - Chargé via <script src="js/ui-nav.js"> sur les pages possédant
 *     une .sidebar / .nav-burger / .app-nav / .site-nav
 *
 * APPELS SORTANTS :
 *   - (aucun)
 * ============================================================
 */
(function () {
  const burger = document.querySelector('.nav-burger');
  const sidebar = document.querySelector('.sidebar');
  const backdrop = document.querySelector('.sidebar-backdrop');

  if (burger && sidebar) {
    // Ouvre/ferme la sidebar mobile et met à jour le backdrop + aria-expanded.
    const setOpen = (open) => {
      sidebar.classList.toggle('open', open);
      backdrop && backdrop.classList.toggle('show', open);
      burger.setAttribute('aria-expanded', String(open));
    };
    burger.addEventListener('click', () => setOpen(!sidebar.classList.contains('open')));
    backdrop && backdrop.addEventListener('click', () => setOpen(false));
    sidebar.querySelectorAll('a').forEach((link) => link.addEventListener('click', () => setOpen(false)));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') setOpen(false); });
  }

  const nav = document.querySelector('.app-nav, .site-nav');
  if (nav) {
    // Ajoute la classe "scrolled" à la nav dès que la page est défilée de plus de 8px.
    const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }
})();
