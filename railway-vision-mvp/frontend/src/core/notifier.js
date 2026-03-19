let notifier = (message, type = 'info') => {
  console[type === 'error' ? 'error' : 'log'](message);
};

export function setNotifier(fn) {
  notifier = typeof fn === 'function' ? fn : notifier;
}

export function notify(message, type = 'info') {
  notifier(String(message || '').trim(), type);
}
