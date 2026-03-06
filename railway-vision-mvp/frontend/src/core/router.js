function compilePattern(pattern) {
  const cleaned = (pattern || '').replace(/^\/+|\/+$/g, '');
  const chunks = cleaned ? cleaned.split('/') : [];
  const keys = [];
  const regexBody = chunks
    .map((chunk) => {
      if (chunk.startsWith(':')) {
        keys.push(chunk.slice(1));
        return '([^/]+)';
      }
      return chunk.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    })
    .join('/');
  const regex = new RegExp(`^${regexBody}$`);
  return { regex, keys };
}

function parsePath(rawHash) {
  const raw = String(rawHash || '#/login').replace(/^#\/?/, '');
  const [pathPart] = raw.split('?');
  const trimmed = pathPart.replace(/^\/+|\/+$/g, '');
  return trimmed || 'login';
}

export function createRouter({ routes, onRoute }) {
  const compiled = routes.map((route) => ({
    ...route,
    _matcher: compilePattern(route.pattern || route.path || ''),
  }));
  const fallback404 = compiled.find((route) => route.name === '404') || { name: '404', path: '404', pattern: '404', _matcher: compilePattern('404') };

  function match(path) {
    for (const route of compiled) {
      const found = route._matcher.regex.exec(path);
      if (!found) continue;
      const params = {};
      route._matcher.keys.forEach((key, idx) => {
        params[key] = decodeURIComponent(found[idx + 1]);
      });
      return { ...route, params, currentPath: path };
    }
    return { ...fallback404, params: {}, currentPath: path };
  }

  function current() {
    return match(parsePath(window.location.hash));
  }

  function navigate(path) {
    const normalized = String(path || '').replace(/^#\/?/, '').replace(/^\/+|\/+$/g, '');
    const next = `#/${normalized || 'login'}`;
    if (window.location.hash !== next) {
      window.location.hash = next;
      return;
    }
    onRoute(current());
  }

  function back(fallbackPath = 'dashboard') {
    const before = window.location.hash;
    if (window.history.length > 1) {
      window.history.back();
      window.setTimeout(() => {
        if (window.location.hash === before) navigate(fallbackPath);
      }, 120);
      return;
    }
    navigate(fallbackPath);
  }

  function handle() {
    onRoute(current());
  }

  window.addEventListener('hashchange', handle);

  return {
    start() {
      handle();
    },
    navigate,
    back,
    current,
  };
}
