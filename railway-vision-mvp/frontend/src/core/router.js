export function createRouter({ routes, onRoute }) {
  function parseHash() {
    const raw = (window.location.hash || '#/login').replace(/^#\/?/, '');
    const path = raw || 'login';
    return routes.find((r) => r.path === path) || routes.find((r) => r.path === '404');
  }

  function navigate(path) {
    const next = `#/${path}`;
    if (window.location.hash !== next) {
      window.location.hash = next;
      return;
    }
    onRoute(parseHash());
  }

  function handle() {
    onRoute(parseHash());
  }

  window.addEventListener('hashchange', handle);

  return {
    start() {
      handle();
    },
    navigate,
  };
}
